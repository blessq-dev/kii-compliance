"""Проверка ввода показателей значимости и подсказки для пользователя.

Два уровня замечаний:
  - ошибка (error)        — значение невозможно (отрицательное, дробное число людей,
                            процент больше 100, неизвестный показатель). Оценка не выполняется.
  - предупреждение (warning) — значение возможно, но вероятна ошибка единиц
                            (например, человек введено вместо тысяч человек).
Ограничения берутся из поля input в rules/categorization.yaml. Это инженерные
ограничения ввода, а не нормативные требования: категорию по-прежнему определяют
только диапазоны из ПП РФ № 127.
"""

import math
from dataclasses import dataclass, field

from engine.categorization import evaluate_indicator
from engine.rules_loader import RuleBase


class InputError(ValueError):
    """Ввод содержит ошибки — оценка невозможна."""


@dataclass
class ValidationResult:
    errors: dict[str, list[str]] = field(default_factory=dict)    # {номер показателя: [сообщения]}
    warnings: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def _add(self, where: dict, ind_id: str, text: str) -> None:
        where.setdefault(ind_id, []).append(text)

    def all_errors(self) -> list[str]:
        return [f"Показатель {i}: {t}" for i, msgs in self.errors.items() for t in msgs]


def _fmt(x: float) -> str:
    """Число без лишних нулей, с запятой как десятичным разделителем."""
    return f"{x:g}".replace(".", ",")


def check_value(rule: dict, value) -> tuple[list[str], list[str]]:
    """Проверяет одно значение. Возвращает (ошибки, предупреждения)."""
    errors, warnings = [], []
    if rule["type"] == "choice":
        if value not in {o["id"] for o in rule["options"]}:
            errors.append(f"недопустимый вариант ответа {value!r}")
        return errors, warnings

    # числовой показатель
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return [f"ожидается число, получено {value!r}"], warnings
    if math.isnan(value) or math.isinf(value):
        return ["значение не является конечным числом"], warnings
    lim = rule.get("input", {})
    if "min" in lim and value < lim["min"]:
        errors.append(f"значение не может быть меньше {_fmt(lim['min'])}")
    if "max" in lim and value > lim["max"]:
        errors.append(lim.get("max_text", f"значение не может быть больше {_fmt(lim['max'])}"))
    if lim.get("integer") and value != int(value):
        errors.append(f"количество ({rule['unit']}) должно быть целым числом")
    if "warn_above" in lim and value > lim["warn_above"]:
        warnings.append(lim["warn_text"])
    return errors, warnings


def validate(rules: RuleBase, values: dict) -> ValidationResult:
    """Проверяет все введённые значения показателей. Пустые значения пропускаются."""
    res = ValidationResult()
    known = {i["id"] for i in rules.categorization["indicators"]}
    for ind_id, value in values.items():
        if value is None or value == "":
            continue
        if ind_id not in known:
            res._add(res.errors, ind_id, "такого показателя нет в Перечне ПП РФ № 127")
            continue
        errs, warns = check_value(rules.indicator(ind_id), value)
        for e in errs:
            res._add(res.errors, ind_id, e)
        for w in warns:
            res._add(res.warnings, ind_id, w)
    return res


def require_valid(rules: RuleBase, values: dict) -> ValidationResult:
    """Как validate(), но при ошибках выбрасывает InputError (используется движком оценки)."""
    res = validate(rules, values)
    if not res.ok:
        raise InputError("Ошибки ввода показателей:\n" + "\n".join(res.all_errors()))
    return res


# ---------------- подсказки для пользователя ----------------

def reference(rule: dict) -> list[tuple[int, str]]:
    """Справочные значения показателя: [(категория, формулировка ПП № 127)], от III к I."""
    if rule["type"] == "number":
        return [(k, rule["values"][k]["text"]) for k in (3, 2, 1)]
    options = [(o["category"], o["text"]) for o in rule["options"] if o["category"] is not None]
    return sorted(options, key=lambda kt: -kt[0])


def boundary_note(rule: dict, value: float) -> str | None:
    """Если значение совпадает с границей диапазона — поясняет, в какую категорию входит граница."""
    if rule["type"] != "number":
        return None
    hits = []
    for k, rng in rule["values"].items():
        for side, incl in (("min", "min_incl"), ("max", "max_incl")):
            if side in rng and value == rng[side]:
                verdict = "входит" if rng.get(incl, False) else "не входит"
                hits.append(f"в диапазон {k} категории («{rng['text']}») граница {verdict}")
    if not hits:
        return None
    return f"Значение {_fmt(value)} — граница диапазонов: " + "; ".join(hits) + "."


def describe(rule: dict, value) -> str:
    """Короткий итог по введённому значению для показа под полем ввода."""
    res = evaluate_indicator(rule, value)
    if res.category is None:
        return "не соответствует ни одному значению — категория по этому показателю не присваивается"
    return f"→ {res.category} категория («{res.matched_text}»)"
