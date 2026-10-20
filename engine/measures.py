"""Формирование базового набора мер по категории значимости (приказ ФСТЭК № 239).

Базовый набор мер определяется на основе категории значимости в соответствии
с приложением к Требованиям (п. 23 Требований): в набор входят меры,
отмеченные в приложении знаком «+» для этой категории.
"""

from engine.rules_loader import RuleBase


def required_measures(rules: RuleBase, category: int | None) -> list[dict]:
    """Список правил мер, обязательных для объекта данной категории.

    Для объекта без категории требования приказа № 239 не применяются
    (они установлены для значимых объектов) — возвращается пустой список.
    """
    if category is None:
        return []
    return [m for m in rules.measures["measures"] if category in m["categories"]]


def group_title(rules: RuleBase, group_code: str) -> str:
    """Название группы мер по её коду (например, «ИАФ»)."""
    for g in rules.measures["groups"]:
        if g["code"] == group_code:
            return g["title"]
    return group_code
