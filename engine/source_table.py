"""Перечень показателей из текста документа (.docx): сверка с пакетом правил и черновик пакета.

Пометки об изменениях (engine/source_text.py) не находят изменений, если часть документа
изложена в новой редакции целиком: тогда у отдельных пунктов пометок нет (так было с Перечнем
показателей ПП № 127 в редакции постановления от 13.04.2019 № 452). Поэтому значения
показателей сверяются с пакетом напрямую — по таблице Перечня в тексте документа.

Что делает модуль (без ИИ, только разбор таблицы и формулировок границ):
  - indicator_rows   — строки таблицы Перечня: номер показателя, формулировка, значения III/II/I;
  - parse_range      — формулировка значения («более или равно 2, но менее 1000») → диапазон;
  - compare_package  — расхождения пакета правил с текстом: пороги, отсутствующие и лишние показатели;
  - draft_package    — черновик пакета новой редакции: правила прежнего пакета с новыми значениями
                       из текста; новые показатели помечаются для проверки экспертом (поле review).
"""

import copy
import re
from dataclasses import dataclass, field

import docx

CATEGORIES = (3, 2, 1)  # порядок колонок таблицы Перечня: III, II, I категория


@dataclass
class TableRow:
    id: str                   # номер показателя: «1», «2а», «10(1)»
    title: str                # формулировка показателя (для подпункта — с формулировкой пункта)
    texts: dict[int, str] = field(default_factory=dict)  # {категория: дословное значение}


def _clean(text: str) -> str:
    """Убирает ссылки на сноски «<1>» и лишние пробелы."""
    return re.sub(r"\s+", " ", re.sub(r"\s*<\d+>", "", text)).strip()


def read_tables(path) -> list[list[list[str]]]:
    """Таблицы документа верхнего уровня: [таблица][строка][ячейка] — текст ячейки.

    Объединённые ячейки повторяются (как в сетке таблицы); вложенные таблицы (примечания
    КонсультантПлюс внутри Перечня) в текст ячейки не входят.
    """
    doc = docx.Document(path)
    return [[[" ".join(c.text.split()) for c in row.cells] for row in t.rows] for t in doc.tables]


def indicator_rows(path) -> list[TableRow]:
    """Строки таблицы Перечня показателей (таблица с заголовком «Показатель»).

    Примечания КонсультантПлюс между строками разрезают таблицу на части — следующие за
    заголовочной таблицы со строками из 5 ячеек считаются её продолжением.
    """
    tables = read_tables(path)
    start = next((i for i, t in enumerate(tables) if t and t[0] and t[0][0].startswith("Показатель")), len(tables))
    table = []
    for t in tables[start:]:
        if t is not tables[start] and not any(len(r) == 5 for r in t):
            break
        table += t
    rows, parent = [], None
    for cells in table:
        if len(cells) != 5:
            continue  # заголовки разделов, пометки «в ред.»
        num, title, *values = [_clean(c) for c in cells]
        m = re.fullmatch(r"(\d+(?:\(\d+\))?)\.", num)
        if m:
            parent = (m.group(1), title)
            if any(values):
                rows.append(TableRow(m.group(1), title, dict(zip(CATEGORIES, values))))
        elif parent and (sub := re.match(r"([а-я])\)\s*(.*)", title)):
            rows.append(TableRow(parent[0] + sub.group(1), f"{parent[1].rstrip(':')} — {sub.group(2).rstrip(';')}",
                                 dict(zip(CATEGORIES, values))))
    return rows


def parse_range(text: str) -> dict | None:
    """«более или равно 50, но менее 1000» → {min: 50, min_incl: True, max: 1000, max_incl: False}.
    None — формулировка не числовая (вариант ответа: территория, уровень органа и т. п.)."""
    rng = {}
    for part in text.split(", но "):
        m = re.fullmatch(r"(более|менее)( или равно)? (\d+(?:,\d+)?)", part.strip())
        if not m:
            return None
        num = float(m.group(3).replace(",", "."))
        num = int(num) if num.is_integer() else num
        side = "min" if m.group(1) == "более" else "max"
        rng[side], rng[f"{side}_incl"] = num, bool(m.group(2))
    return rng


def _range_of(rule_value: dict) -> dict:
    return {k: rule_value[k] for k in ("min", "min_incl", "max", "max_incl") if k in rule_value}


@dataclass
class Mismatch:
    indicator: str
    what: str      # нет в пакете | нет в тексте | значение | тип
    details: str = ""

    def __str__(self) -> str:
        return f"Показатель {self.indicator}: {self.what}" + (f" — {self.details}" if self.details else "")


def compare_package(pkg_data: dict, rows: list[TableRow]) -> list[Mismatch]:
    """Расхождения пакета правил вида categorization с таблицей Перечня из текста документа.

    Числовые показатели сверяются по границам каждой категории (число и включение границы);
    у показателей-вариантов сверяется, что текст тоже не числовой (формулировки вариантов
    в пакете сокращены — их сверяет эксперт).
    """
    out = []
    rules = {i["id"]: i for i in pkg_data["indicators"]}
    for row in rows:
        rule = rules.get(row.id)
        if rule is None:
            out.append(Mismatch(row.id, "нет в пакете", row.title[:120]))
            continue
        parsed = {k: parse_range(t) for k, t in row.texts.items()}
        numeric = all(parsed.values())
        if numeric != (rule["type"] == "number"):
            out.append(Mismatch(row.id, "тип", f"в тексте {'число' if numeric else 'варианты'}, в пакете {rule['type']}"))
            continue
        if numeric:
            for k in CATEGORIES:
                if parsed[k] != _range_of(rule["values"][k]):
                    out.append(Mismatch(row.id, "значение", f"{k} категория: в тексте «{row.texts[k]}», "
                                                         f"в пакете «{rule['values'][k].get('text', '')}»"))
    ids = {r.id for r in rows}
    out += [Mismatch(i, "нет в тексте") for i in rules if i not in ids]
    return out


def _unit(title: str) -> str:
    m = re.search(r"\(([^()]*(?:человек|часов|процентов|единиц|рублей|штук|тыс\.)[^()]*)\)\s*$", title)
    return m.group(1) if m else ""


def draft_package(bases: list[dict], rows: list[TableRow], document: dict) -> dict:
    """Черновик пакета новой редакции.

    bases    — пакеты других редакций, по порядку предпочтения (первый — прежняя редакция):
               из них берутся общие правила, краткие названия, единицы, ограничения ввода
               и условия применимости показателей;
    rows     — таблица Перечня из текста новой редакции;
    document — паспорт нового пакета (kind, act, edition, effective_from, file, title).

    Показатель, который есть в одном из bases с тем же типом, получает значения и формулировку
    из текста. Новый показатель создаётся по тексту и помечается полем review — его проверяет
    эксперт. Показатели bases, которых нет в тексте, в черновик не входят. Условия применимости
    берутся только те, на которые ссылаются показатели черновика (их формулировки тоже проверяет
    эксперт — они пересказывают формулировку показателя).
    """
    def find(rule_id: str, numeric: bool):
        return next((i for b in bases for i in b["indicators"]
                     if i["id"] == rule_id and (i["type"] == "number") == numeric), None)

    draft = {"document": dict(document), "logic": copy.deepcopy(bases[0].get("logic", [])),
             "conditions": [], "indicators": []}
    for row in rows:
        parsed = {k: parse_range(t) for k, t in row.texts.items()}
        numeric = all(parsed.values())
        old = find(row.id, numeric)
        if old:
            rule = copy.deepcopy(old)
            rule.pop("warning", None)
            rule["title"] = row.title
        else:
            point = re.sub(r"([а-я])$", r", подп. «\1»", row.id)  # «2б» → «2, подп. «б»»
            rule = {"id": row.id, "short": row.title[:70], "section": "",
                    "title": row.title, "type": "number" if numeric else "choice",
                    "review": "новый показатель (или изменился его тип): проверьте краткое название, единицы, "
                              "ограничения ввода, раздел и условие применимости",
                    "source": f"ПП РФ № 127, Перечень показателей, п. {point}"}
            if numeric:
                rule["unit"] = _unit(row.title)
                rule["input"] = {"min": 0}
        if numeric:
            rule["values"] = {k: {**parsed[k], "text": row.texts[k]} for k in CATEGORIES}
        else:
            ids = [o["id"] for o in (old or {}).get("options", []) if o["category"] is not None]
            by_cat = {o["category"]: o["id"] for o in (old or {}).get("options", []) if o["category"]}
            rule["options"] = [{"id": "none", "text": "Не соответствует ни одному значению", "category": None}] + [
                {"id": by_cat.get(k, f"v{k}") if ids else f"v{k}", "text": row.texts[k], "category": k}
                for k in CATEGORIES]
        draft["indicators"].append(rule)
    used = list(dict.fromkeys(i["applies_if"] for i in draft["indicators"] if i.get("applies_if")))
    for cond_id in used:
        cond = next(c for b in bases for c in b.get("conditions", []) if c["id"] == cond_id)
        draft["conditions"].append(copy.deepcopy(cond))
    return draft
