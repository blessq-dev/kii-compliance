"""Анализ влияния смены редакции нормативных документов.

1. diff_rules — что изменилось в правилах между двумя базами (редакциями):
   показатели и их диапазоны, состав мер и базовые наборы, требования № 235, сферы.
2. impact_on_objects — что это означает для конкретных объектов: меняется ли категория,
   какие меры становятся обязательными или перестают быть обязательными, какие новые
   несоответствия появляются при тех же реализованных мерах.

3. previous_edition, base_set_changes, requirement_changes — что нового в действующей
   редакции по сравнению с предыдущей (для пометок в интерфейсе).

Все функции работают с любыми пакетами правил: новая редакция подключается
добавлением файла в rules/, код не меняется.
"""

from dataclasses import dataclass, field

from engine.assessment import assess
from engine.rules_loader import Package, RuleBase
from engine.validation import InputError

ADDED, REMOVED, CHANGED = "добавлено", "исключено", "изменено"


@dataclass
class Change:
    area: str      # показатель | условие | мера | требование | сфера
    rule: str      # код правила
    what: str      # добавлено | исключено | изменено
    details: str = ""

    def __str__(self) -> str:
        return f"{self.area} {self.rule}: {self.what}" + (f" — {self.details}" if self.details else "")


def _index(items: list[dict], key: str) -> dict:
    return {str(it[key]): it for it in items}


def _compare(area: str, old: dict, new: dict, fields: dict) -> list[Change]:
    """Сравнение двух наборов правил {код: правило} по указанным полям {поле: подпись}."""
    out = [Change(area, k, ADDED, new[k].get("title") or new[k].get("text") or "") for k in new if k not in old]
    out += [Change(area, k, REMOVED) for k in old if k not in new]
    for k in old.keys() & new.keys():
        diffs = [label for f, label in fields.items() if old[k].get(f) != new[k].get(f)]
        if diffs:
            out.append(Change(area, k, CHANGED, ", ".join(diffs)))
    return sorted(out, key=lambda c: (c.what != ADDED, c.rule))


def _categories_change(old: dict, new: dict) -> str:
    a, b = set(old.get("categories", [])), set(new.get("categories", []))
    parts = [f"добавлена в набор {k} категории" for k in sorted(b - a)]
    parts += [f"исключена из набора {k} категории" for k in sorted(a - b)]
    return "; ".join(parts)


def diff_rules(old: RuleBase, new: RuleBase) -> list[Change]:
    """Изменения в правилах при переходе от базы old к базе new."""
    out = _compare("Показатель", _index(old.categorization["indicators"], "id"),
                   _index(new.categorization["indicators"], "id"),
                   {"values": "диапазоны значений", "options": "варианты значений",
                    "applies_if": "условие применимости", "title": "формулировка", "source": "источник"})
    out += _compare("Условие", _index(old.categorization.get("conditions", []), "id"),
                    _index(new.categorization.get("conditions", []), "id"), {"text": "формулировка"})
    m_old, m_new = _index(old.measures["measures"], "code"), _index(new.measures["measures"], "code")
    for c in _compare("Мера", m_old, m_new, {"title": "наименование", "categories": "базовые наборы"}):
        if c.what == CHANGED and "базовые наборы" in c.details:
            sets = _categories_change(m_old[c.rule], m_new[c.rule])
            c.details = c.details.replace("базовые наборы", sets)
        out.append(c)
    out += _compare("Требование", _index(old.security["requirements"], "id"),
                    _index(new.security["requirements"], "id"),
                    {"text": "формулировка", "condition": "условие", "source": "источник"})
    out += _compare("Сфера", _index(old.spheres["spheres"], "id"), _index(new.spheres["spheres"], "id"),
                    {"title": "наименование"})
    return out


@dataclass
class ObjectImpact:
    name: str
    category_old: int | None = None
    category_new: int | None = None
    became_required: list[str] = field(default_factory=list)    # меры, ставшие обязательными
    no_longer_required: list[str] = field(default_factory=list)  # меры, переставшие быть обязательными
    new_missing: list[str] = field(default_factory=list)         # новые несоответствия
    resolved: list[str] = field(default_factory=list)            # несоответствия, которые исчезли
    error: str | None = None                                     # оценка по новой редакции невозможна

    @property
    def changed(self) -> bool:
        return bool(self.error or self.category_old != self.category_new or self.became_required
                    or self.no_longer_required)


def _run(rules: RuleBase, state: dict):
    return assess(rules, state.get("object_name", ""), state["sphere"], state.get("indicators") or {},
                  state.get("implemented") or [], statuses=state.get("statuses"),
                  attributes=state.get("attributes"))


def impact_on_objects(old: RuleBase, new: RuleBase, states: list[dict]) -> list[ObjectImpact]:
    """Влияние смены редакции на объекты (состояния оценки в формате перечня объектов).

    Меры, которых нет в новой редакции, в отметках объекта не учитываются.
    """
    out = []
    for st in states:
        res = ObjectImpact(st.get("object_name", ""))
        try:
            before = _run(old, st)
        except (InputError, KeyError) as e:
            res.error = f"оценка по прежней редакции невозможна: {e}"
            out.append(res)
            continue
        new_codes = {m["code"] for m in new.measures["measures"]}
        st_new = dict(st, implemented=[c for c in st.get("implemented") or [] if c in new_codes],
                      statuses={c: s for c, s in (st.get("statuses") or {}).items() if c in new_codes})
        try:
            after = _run(new, st_new)
        except (InputError, KeyError) as e:
            res.category_old = before.categorization.category
            res.error = f"по новой редакции нужно уточнить исходные данные: {e}"
            out.append(res)
            continue
        req_old = {m["code"] for m in before.required}
        req_new = {m["code"] for m in after.required}
        res.category_old, res.category_new = before.categorization.category, after.categorization.category
        res.became_required = sorted(req_new - req_old)
        res.no_longer_required = sorted(req_old - req_new)
        res.new_missing = sorted(set(after.missing_codes) - set(before.missing_codes))
        res.resolved = sorted(set(before.missing_codes) - set(after.missing_codes))
        out.append(res)
    return out


# ---------------- изменения действующей редакции относительно предыдущей ----------------

def previous_edition(packages: list[Package], pkg: Package) -> Package | None:
    """Предыдущая редакция того же документа: пакет того же вида с ближайшей более ранней датой."""
    earlier = [p for p in packages if p.kind == pkg.kind and p.effective_from < pkg.effective_from]
    return max(earlier, key=lambda p: p.effective_from) if earlier else None


def base_set_changes(prev: Package, cur: Package, category: int) -> tuple[list[str], list[str]]:
    """Меры, которые в редакции cur стали обязательными для категории (по сравнению с prev)
    и которые перестали быть обязательными."""
    def base(pkg: Package) -> set[str]:
        return {m["code"] for m in pkg.data["measures"] if category in m.get("categories", [])}
    old, new = base(prev), base(cur)
    return sorted(new - old), sorted(old - new)


def requirement_changes(prev: Package, cur: Package) -> dict[str, str]:
    """Требования приказа № 235, добавленные или изменённые в редакции cur: {код: добавлено|изменено}."""
    old = {r["id"]: r for r in prev.data["requirements"]}
    return {r["id"]: ADDED if r["id"] not in old else CHANGED
            for r in cur.data["requirements"] if r["id"] not in old or old[r["id"]]["text"] != r["text"]}
