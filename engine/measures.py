"""Формирование базового набора мер по категории значимости (приказ ФСТЭК № 239).

Базовый набор мер определяется на основе категории значимости в соответствии
с приложением к Требованиям (п. 23 Требований): в набор входят меры,
отмеченные в приложении знаком «+» для этой категории.
"""

import re

from engine.rules_loader import RuleBase

# латинские буквы и цифра 0, похожие на русские буквы в кодах мер
_LOOKALIKE = str.maketrans("ABCEHKMOPTXY0", "АВСЕНКМОРТХУО")


def required_measures(rules: RuleBase, category: int | None) -> list[dict]:
    """Список правил мер, обязательных для объекта данной категории.

    Для объекта без категории требования приказа № 239 не применяются
    (они установлены для значимых объектов) — возвращается пустой список.
    """
    if category is None:
        return []
    return [m for m in rules.measures["measures"] if category in m["categories"]]


def extract_codes(rules: RuleBase, text: str) -> tuple[list[str], list[str]]:
    """Находит коды мер в произвольном тексте (например, в выгрузке перечня реализованных мер).

    Возвращает (известные коды, неизвестные коды). Исправляются типичные опечатки:
    латинские буквы, похожие на русские («A» вместо «А»), и цифра «0» вместо буквы «О»
    (как в тексте приложения к приказу № 239: «0ДТ.2»).
    """
    known = {m["code"] for m in rules.measures["measures"]}
    found, unknown = [], []
    for raw in re.findall(r"[А-ЯЁA-Z0]{3}\.\d+", text.upper()):
        code = raw[:3].translate(_LOOKALIKE) + raw[3:]
        target = found if code in known else unknown
        if code not in target:
            target.append(code)
    return found, unknown


def group_title(rules: RuleBase, group_code: str) -> str:
    """Название группы мер по её коду (например, «ИАФ»)."""
    for g in rules.measures["groups"]:
        if g["code"] == group_code:
            return g["title"]
    return group_code
