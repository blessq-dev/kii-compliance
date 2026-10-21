"""Определение категории значимости объекта КИИ по ПП РФ № 127.

Алгоритм (Правила категорирования, п. 6–7):
  1. Каждый заполненный показатель сравнивается с диапазонами значений
     для III, II и I категорий из базы правил.
  2. Если значение попало в диапазоны нескольких категорий — берётся наивысшая.
  3. Итоговая категория объекта — наивысшая среди всех показателей.
  4. Если ни один показатель не дал категорию — категория не присваивается.

Категории хранятся числами 1, 2, 3. Наивысшая категория — 1 (п. 7 Правил),
поэтому «наивысшая» = минимальное число.
"""

from dataclasses import dataclass, field

from engine.rules_loader import RuleBase


@dataclass
class IndicatorResult:
    """Результат оценки одного показателя."""

    indicator_id: str
    value: object                 # введённое значение (число или id варианта)
    category: int | None          # категория по этому показателю (None — не соответствует)
    matched_text: str | None      # дословная формулировка значения, в которое попали
    source: str                   # ссылка на пункт Перечня


@dataclass
class CategorizationResult:
    """Итог категорирования объекта."""

    is_kii_subject: bool                   # относится ли сфера к ст. 2 п. 8 187-ФЗ
    category: int | None                   # 1, 2, 3 или None — категория не присвоена
    decisive: list[IndicatorResult] = field(default_factory=list)  # показатели, давшие итог
    details: list[IndicatorResult] = field(default_factory=list)   # все заполненные показатели
    warnings: list[str] = field(default_factory=list)              # замечания к тексту документа
    explanation: list[str] = field(default_factory=list)           # ход рассуждения для отчёта
    not_filled: list[str] = field(default_factory=list)            # не заполнены (считаются неприменимыми)


def highest(categories) -> int | None:
    """Наивысшая категория из набора (1 выше 2, 2 выше 3). None — если набор пуст."""
    real = [c for c in categories if c is not None]
    return min(real) if real else None


def in_range(value: float, rng: dict) -> bool:
    """Проверяет попадание числа в диапазон из базы правил.

    Диапазон задаётся полями min/max и флагами min_incl/max_incl
    («более или равно» — граница включена, «более» — не включена).
    """
    if "min" in rng:
        if rng.get("min_incl", False):
            if value < rng["min"]:
                return False
        elif value <= rng["min"]:
            return False
    if "max" in rng:
        if rng.get("max_incl", False):
            if value > rng["max"]:
                return False
        elif value >= rng["max"]:
            return False
    return True


def evaluate_indicator(rule: dict, value) -> IndicatorResult:
    """Определяет категорию по одному показателю."""
    if rule["type"] == "number":
        matched = {cat: rng for cat, rng in rule["values"].items() if in_range(float(value), rng)}
        category = highest(matched)  # п. 6 Правил: при попадании в несколько диапазонов — наивысшая
        text = matched[category]["text"] if category is not None else None
    elif rule["type"] == "choice":
        option = next((o for o in rule["options"] if o["id"] == value), None)
        if option is None:
            raise ValueError(f"Показатель {rule['id']}: недопустимый вариант {value!r}")
        category = option["category"]
        text = option["text"] if category is not None else None
    else:
        raise ValueError(f"Показатель {rule['id']}: неизвестный тип {rule['type']!r}")
    return IndicatorResult(rule["id"], value, category, text, rule["source"])


def categorize(rules: RuleBase, sphere: str, values: dict) -> CategorizationResult:
    """Категорирует объект.

    sphere — id сферы из пакета 187-ФЗ (rules/187-fz/);
    values — словарь {номер показателя: значение}. Отсутствующий или пустой
             показатель считается неприменимым к объекту.
    """
    # Шаг 0. Сфера деятельности: категорирование проводят только субъекты КИИ.
    if sphere not in rules.sphere_ids():
        src = rules.spheres["other"]["source"]
        return CategorizationResult(
            is_kii_subject=False,
            category=None,
            explanation=[f"Сфера деятельности не входит в перечень ст. 2 п. 8 187-ФЗ — "
                         f"объект не подлежит категорированию ({src})."],
        )

    result = CategorizationResult(is_kii_subject=True, category=None)

    # Шаг 1. Оценка каждого заполненного показателя.
    for rule in rules.categorization["indicators"]:
        value = values.get(rule["id"])
        if value is None or value == "":
            continue  # показатель неприменим к объекту
        res = evaluate_indicator(rule, value)
        result.details.append(res)
        if rule.get("warning"):
            result.warnings.append(f"Показатель {rule['id']}: {rule['warning']}")

    # Шаг 2. Итоговая категория — наивысшая среди показателей (п. 6 Правил).
    result.category = highest(r.category for r in result.details)
    filled = {r.indicator_id for r in result.details}
    result.not_filled = [i["id"] for i in rules.categorization["indicators"] if i["id"] not in filled]

    if result.category is None:
        result.explanation.append(
            "Объект не соответствует ни одному значению показателей (или показатели неприменимы) — "
            "категория значимости не присваивается (ПП РФ № 127, Правила, п. 6, абз. 3)."
        )
    else:
        result.decisive = [r for r in result.details if r.category == result.category]
        for r in result.decisive:
            # для числового показателя показываем введённое число, для выбора — только формулировку варианта
            value = f" = {r.value:g}".replace(".", ",") if isinstance(r.value, (int, float)) else ""
            result.explanation.append(
                f"Показатель {r.indicator_id}{value}: «{r.matched_text}» → "
                f"{r.category} категория ({r.source})."
            )
        result.explanation.append(
            f"Присвоена наивысшая из полученных категорий — {result.category} "
            f"(ПП РФ № 127, Правила, п. 6–7)."
        )
    if result.not_filled:
        result.explanation.append(
            f"Не заполнены и считаются неприменимыми к объекту ({len(result.not_filled)} из "
            f"{len(rules.categorization['indicators'])}): {', '.join(result.not_filled)} "
            "(ПП РФ № 127, Правила, п. 6, абз. 3)."
        )
    return result
