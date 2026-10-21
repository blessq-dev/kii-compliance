"""Автоматическая проверка пакетов правил (верификация базы правил).

Выполняется для любого пакета — текущего или новой редакции — без изменения кода.
Два уровня замечаний:
  - ошибка (error)     — пакет внутренне некорректен (повтор кода, правило без источника,
                         ссылка на несуществующее условие, категория вне 1–3). Такой пакет
                         нельзя использовать для оценки;
  - замечание (warning) — дефект самого нормативного текста, перенесённого дословно:
                         пересечение или разрыв диапазонов, нарушение монотонности шкалы,
                         непокрытый «тяжёлый» край шкалы, отсутствие порога значимости,
                         нарушение вложенности наборов мер, направление п. 22 без мер.
                         Оценка возможна, но замечание выводится эксперту и в отчёт.

Свойства формальной модели (см. ПЗ1, п. 3.4):
  - непротиворечивость: диапазоны разных категорий одного показателя не пересекаются;
  - связность шкалы: между диапазонами соседних категорий нет разрывов;
  - монотонность: категории идут по шкале по порядку (III → II → I или I → II → III);
  - покрытие тяжёлого края: самые тяжёлые последствия дают I категорию;
  - порог значимости: у III категории есть нижняя граница (нулевой ущерб не даёт категорию);
  - вложенность наборов мер: M(3) ⊆ M(2) ⊆ M(1);
  - согласованность направлений: каждое направление п. 22 приказа № 239 обеспечено
    группой мер приложения, и каждая группа соответствует направлению.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from engine.rules_loader import RULES_DIR, Package, RuleBase, RuleBaseError, check_package, find_packages

INF = float("inf")
CATEGORIES = (1, 2, 3)
ERROR, WARNING = "error", "warning"


@dataclass
class Finding:
    level: str     # error | warning
    package: str   # документ и редакция
    rule: str      # код правила (показатель, мера, требование) или «—» для пакета в целом
    text: str

    def __str__(self) -> str:
        kind = "Ошибка" if self.level == ERROR else "Замечание"
        return f"{kind} [{self.package}] {self.rule}: {self.text}"


# ---------------- диапазоны числовых показателей ----------------

def _fmt(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def bounds(rng: dict) -> tuple:
    """Диапазон → (нижняя, включена?, верхняя, включена?)."""
    return (rng.get("min", -INF), rng.get("min_incl", False),
            rng.get("max", INF), rng.get("max_incl", False))


def overlap(a: dict, b: dict) -> bool:
    """Пересекаются ли два диапазона (с учётом включения границ)."""
    lo1, li1, hi1, hi_i1 = bounds(a)
    lo2, li2, hi2, hi_i2 = bounds(b)
    lo, lo_incl = max((lo1, li1), (lo2, li2), key=lambda t: (t[0], not t[1]))
    hi, hi_incl = min((hi1, hi_i1), (hi2, hi_i2), key=lambda t: (t[0], t[1]))
    return lo < hi or (lo == hi and lo_incl and hi_incl)


def gap(lower: dict, upper: dict) -> str | None:
    """Разрыв между соседними диапазонами шкалы (lower лежит левее upper на числовой оси)."""
    _, _, hi, hi_incl = bounds(lower)
    lo, lo_incl, _, _ = bounds(upper)
    if hi == lo and not hi_incl and not lo_incl:
        return f"значение {_fmt(hi)} не входит ни в один диапазон"
    if hi < lo:
        return f"интервал ({_fmt(hi)}; {_fmt(lo)}) не входит ни в один диапазон"
    return None


def check_scale(ind: dict) -> list[str]:
    """Свойства шкалы одного числового показателя. Возвращает описания дефектов."""
    v = ind["values"]
    problems = []
    for i, a in enumerate(CATEGORIES):
        for b in CATEGORIES[i + 1:]:
            if overlap(v[a], v[b]):
                problems.append(f"пересекаются диапазоны {a} и {b} категорий")
    order = sorted(v, key=lambda k: (bounds(v[k])[0], bounds(v[k])[2]))
    for left, right in zip(order, order[1:]):
        g = gap(v[left], v[right])
        if g:
            problems.append(f"разрыв между {left} и {right} категориями: {g}")
    if order not in ([3, 2, 1], [1, 2, 3]):
        problems.append(f"нарушена монотонность: порядок категорий на числовой оси {order}")

    # Тяжёлый край шкалы. Направление определяем по III и II категориям: если II лежит
    # правее III — ущерб растёт с ростом значения (люди, проценты), иначе — убывает (допустимое время).
    growing = bounds(v[2])[0] >= bounds(v[3])[0]
    lo1, lo1_incl, hi1, _ = bounds(v[1])
    if growing and hi1 != INF:
        problems.append(f"значения больше {_fmt(hi1)} не дают I категорию")
    if not growing:
        limit = (ind.get("input") or {}).get("min", -INF)
        if lo1 > limit or (lo1 == limit and not lo1_incl and limit != -INF):
            edge = "включительно" if not lo1_incl else "не включая"
            problems.append(f"самые тяжёлые значения — от {_fmt(limit)} до {_fmt(lo1)} {edge} — "
                            "не дают никакой категории")

    # Порог значимости. Если у III категории нет нижней границы (для шкалы, где ущерб растёт
    # с ростом значения), то любое значение, в том числе нулевой ущерб, даёт категорию:
    # показатель не отделяет значимые объекты от незначимых.
    if growing and bounds(v[3])[0] == -INF:
        problems.append("у III категории нет нижней границы: любое значение, в том числе 0, "
                        "даёт категорию значимости (нет порога значимости)")
    return problems


# ---------------- проверки по видам правил ----------------

def _duplicates(items: list[dict], key: str) -> list[str]:
    seen, dup = set(), []
    for it in items:
        k = it.get(key)
        if k in seen:
            dup.append(k)
        seen.add(k)
    return dup


def _verify_categorization(pkg: Package) -> list[Finding]:
    title, out = pkg.title, []
    inds = pkg.data["indicators"]
    conditions = {c["id"] for c in pkg.data.get("conditions", [])}
    for d in _duplicates(inds, "id"):
        out.append(Finding(ERROR, title, str(d), "показатель с таким номером встречается дважды"))
    for ind in inds:
        rid = str(ind.get("id"))
        if not ind.get("source"):
            out.append(Finding(ERROR, title, rid, "нет ссылки на источник (документ и пункт)"))
        if ind.get("applies_if") and ind["applies_if"] not in conditions:
            out.append(Finding(ERROR, title, rid, f"условие применимости {ind['applies_if']!r} не описано "
                                                  "в разделе conditions"))
        if ind.get("type") == "number":
            values = ind.get("values") or {}
            if set(values) != set(CATEGORIES):
                out.append(Finding(ERROR, title, rid, "диапазоны должны быть заданы для категорий 1, 2 и 3"))
                continue
            for p in check_scale(ind):
                out.append(Finding(WARNING, title, rid, p))
        elif ind.get("type") == "choice":
            cats = [o.get("category") for o in ind.get("options") or []]
            bad = [c for c in cats if c is not None and c not in CATEGORIES]
            if bad:
                out.append(Finding(ERROR, title, rid, f"недопустимые категории вариантов: {bad}"))
            for d in _duplicates(ind.get("options") or [], "id"):
                out.append(Finding(ERROR, title, rid, f"вариант {d!r} встречается дважды"))
        else:
            out.append(Finding(ERROR, title, rid, f"неизвестный тип показателя {ind.get('type')!r}"))
    return out


def _verify_measures(pkg: Package) -> list[Finding]:
    title, out = pkg.title, []
    measures = pkg.data["measures"]
    groups = {g["code"] for g in pkg.data.get("groups", [])}
    for d in _duplicates(measures, "code"):
        out.append(Finding(ERROR, title, str(d), "мера с таким кодом встречается дважды"))
    for m in measures:
        code = str(m.get("code"))
        if not m.get("source"):
            out.append(Finding(ERROR, title, code, "нет ссылки на источник (документ и пункт)"))
        if groups and code.split(".")[0] not in groups:
            out.append(Finding(ERROR, title, code, "группа меры не описана в разделе groups"))
        bad = [c for c in m.get("categories", []) if c not in CATEGORIES]
        if bad:
            out.append(Finding(ERROR, title, code, f"недопустимые категории: {bad}"))
    sets = {k: {m["code"] for m in measures if k in m.get("categories", [])} for k in CATEGORIES}
    for lower, higher in ((3, 2), (2, 1)):
        for code in sorted(sets[lower] - sets[higher]):
            out.append(Finding(WARNING, title, code, f"входит в набор {lower} категории, но не в набор "
                                                     f"{higher} категории (нарушена вложенность M({lower}) ⊆ "
                                                     f"M({higher}))"))
    out += _verify_directions(pkg, groups, measures)
    return out


def _verify_directions(pkg: Package, groups: set, measures: list[dict]) -> list[Finding]:
    """Согласованность направлений п. 22 и групп мер приложения (если направления описаны).

    По п. 22 приказа № 239 каждое направление обеспечения безопасности осуществляется
    мерами, определяемыми по приложению. Направление без группы мер (или с группой,
    в которой нет мер) нельзя выполнить по приложению; группа, не названная ни в одном
    направлении, не опирается на п. 22.
    """
    title, out = pkg.title, []
    directions = pkg.data.get("directions")
    if not directions:
        return out
    with_measures = {m["code"].split(".")[0] for m in measures}
    for d in directions:
        name = f"п. 22 «{d['id']}»"
        if not d.get("group"):
            out.append(Finding(WARNING, title, name, f"направление «{d['title']}» должно осуществляться мерами "
                                                     "по приложению, но в приложении нет соответствующей группы мер"))
        elif d["group"] not in groups:
            out.append(Finding(ERROR, title, name, f"группа {d['group']!r} не описана в разделе groups"))
        elif d["group"] not in with_measures:
            out.append(Finding(WARNING, title, name, f"в группе {d['group']} нет ни одной меры"))
    named = {d.get("group") for d in directions}
    for g in sorted(groups - named):
        out.append(Finding(WARNING, title, g, "группа мер приложения не соответствует ни одному направлению п. 22"))
    return out


def _verify_checklist(pkg: Package, section: str, key: str) -> list[Finding]:
    title, out = pkg.title, []
    items = pkg.data[section]
    for d in _duplicates(items, key):
        out.append(Finding(ERROR, title, str(d), "код встречается дважды"))
    for it in items:
        if not it.get("source"):
            out.append(Finding(ERROR, title, str(it.get(key)), "нет ссылки на источник (документ и пункт)"))
    return out


def verify_package(pkg: Package) -> list[Finding]:
    """Проверка одного пакета правил (по его виду)."""
    if pkg.kind == "categorization":
        return _verify_categorization(pkg)
    if pkg.kind == "measures":
        return _verify_measures(pkg)
    if pkg.kind == "security_system":
        return _verify_checklist(pkg, "requirements", "id")
    return _verify_checklist(pkg, "spheres", "id")


def verify_rules(rules: RuleBase) -> list[Finding]:
    """Проверка всех пакетов, из которых собрана база правил."""
    return [f for pkg in rules.packages.values() for f in verify_package(pkg)]


def errors(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.level == ERROR]


# ---------------- добавление нового пакета в базу правил ----------------

def install_package(raw: bytes, rules_dir: Path | str = RULES_DIR) -> tuple[Path, list[Finding]]:
    """Проверяет пакет (структура и верификация) и сохраняет его в rules/<документ>/<дата>.yaml.

    Пакет с ошибками не сохраняется (RuleBaseError); замечания к тексту документа
    не мешают сохранению и возвращаются вызывающему. Папка документа — та же, где лежат
    другие редакции этого вида правил, иначе новая папка с именем вида правил.
    """
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as e:
        raise RuleBaseError(f"файл не является корректным YAML в кодировке UTF-8 ({e})") from e
    pkg = check_package(data)
    findings = verify_package(pkg)
    if errors(findings):
        raise RuleBaseError("пакет содержит ошибки:\n" + "\n".join(str(f) for f in errors(findings)))
    existing = [p for p in find_packages(rules_dir) if p.kind == pkg.kind]
    if any(p.effective_from == pkg.effective_from for p in existing):
        raise RuleBaseError(f"редакция правил вида {pkg.kind!r} с датой {pkg.effective_from:%d.%m.%Y} уже есть")
    folder = existing[-1].path.parent if existing else Path(rules_dir) / pkg.kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{pkg.effective_from:%Y-%m-%d}.yaml"
    path.write_bytes(raw)
    return path, findings
