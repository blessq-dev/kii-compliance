"""QA-тесты ввода показателей и граничных значений.

Ключевая идея: независимый эталон (оракул). Дословные формулировки значений из ПП № 127
(поле text, например «более или равно 1, но менее или равно 50») разбираются здесь
регулярным выражением в интервал, НЕ используя числа min/max из YAML и код движка.
С этим эталоном сверяются и числа в базе правил, и ответы движка —
так ловятся ошибки переноса границ из документа в YAML.
"""

import math
import random

import pytest

from engine.assessment import assess
from engine.categorization import categorize, highest
from engine.dataset import implemented_codes, load_objects
from engine.rules_loader import load_rules
from engine.validation import (InputError, boundary_note, check_value, describe, reference,
                               validate)

RULES = load_rules()
NUMBER = [i for i in RULES.categorization["indicators"] if i["type"] == "number"]
CHOICE = [i for i in RULES.categorization["indicators"] if i["type"] == "choice"]


# ---------------- независимый эталон по тексту ПП № 127 ----------------

def parse_text(text: str) -> dict:
    """«более или равно 50, но менее 1000» → {min: 50, min_incl: True, max: 1000, max_incl: False}."""
    rng = {}
    for part in text.split(", но "):
        num = float(part.split()[-1].replace(",", "."))
        incl = "или равно" in part
        if part.startswith("более"):
            rng.update(min=num, min_incl=incl)
        elif part.startswith("менее"):
            rng.update(max=num, max_incl=incl)
        else:
            raise ValueError(f"Не удалось разобрать формулировку: {text!r}")
    return rng


def oracle(rule: dict, value: float):
    """Категория по показателю, вычисленная только по тексту формулировок."""
    cats = []
    for k, r in rule["values"].items():
        p = parse_text(r["text"])
        ok = True
        if "min" in p:
            ok &= value >= p["min"] if p["min_incl"] else value > p["min"]
        if "max" in p:
            ok &= value <= p["max"] if p["max_incl"] else value < p["max"]
        if ok:
            cats.append(k)
    return highest(cats)


def boundaries(rule: dict) -> list[float]:
    return sorted({r[s] for r in rule["values"].values() for s in ("min", "max") if s in r})


# ---------------- 1. текст ПП № 127 ↔ числа в YAML ----------------

@pytest.mark.parametrize("rule", NUMBER, ids=lambda r: r["id"])
def test_yaml_numbers_match_document_text(rule):
    for k, r in rule["values"].items():
        p = parse_text(r["text"])
        assert r.get("min") == p.get("min"), (rule["id"], k)
        assert r.get("max") == p.get("max"), (rule["id"], k)
        if "min" in p:
            assert r.get("min_incl", False) == p["min_incl"], (rule["id"], k)
        if "max" in p:
            assert r.get("max_incl", False) == p["max_incl"], (rule["id"], k)


# ---------------- 2. граничные значения: движок ↔ эталон ----------------

def _probe_points(rule):
    pts = {0.0}
    for b in boundaries(rule):
        d = max(abs(b), 1.0) * 1e-6
        pts |= {b - d, b, b + d, b * 2 + 1}
    return sorted(p for p in pts if p >= 0)


@pytest.mark.parametrize("rule", NUMBER, ids=lambda r: r["id"])
def test_boundaries_match_oracle(rule):
    for v in _probe_points(rule):
        got = categorize(RULES, "healthcare", {rule["id"]: v}).category
        assert got == oracle(rule, v), f"показатель {rule['id']}, значение {v!r}"


# ---------------- 3. случайные значения (fuzz) ----------------

@pytest.mark.parametrize("rule", NUMBER, ids=lambda r: r["id"])
def test_fuzz_random_values(rule):
    rnd = random.Random(42)  # фиксированное зерно — тест воспроизводим
    for _ in range(500):
        v = 10 ** rnd.uniform(-4, 6)
        got = categorize(RULES, "healthcare", {rule["id"]: v}).category
        assert got in (None, 1, 2, 3)
        assert got == oracle(rule, v)


# ---------------- 4. монотонность шкал ----------------

def test_documented_anomalies_are_exactly_known():
    """Замечания к тексту ПП № 127 есть ровно у трёх показателей (см. notes/)."""
    assert {i["id"] for i in RULES.categorization["indicators"] if i.get("warning")} == {"5", "9а", "14"}


@pytest.mark.parametrize("rule", [r for r in NUMBER if not r.get("warning")], ids=lambda r: r["id"])
def test_monotonic_scale(rule):
    """Для показателей без замечаний: чем дальше по шкале «тяжести», тем выше (или равна) категория."""
    harm_grows_with_value = rule["values"][3].get("min", -math.inf) < rule["values"][1].get("min", math.inf)
    pts = _probe_points(rule)
    cats = [categorize(RULES, "healthcare", {rule["id"]: v}).category for v in pts]
    rank = [4 if c is None else c for c in cats]  # «без категории» ниже III
    if not harm_grows_with_value:
        rank = rank[::-1]
    assert all(a >= b for a, b in zip(rank, rank[1:])), f"{rule['id']}: {list(zip(pts, cats))}"


# ---------------- 5. проверка ввода: ошибки ----------------

@pytest.mark.parametrize("ind_id, value, fragment", [
    ("1", -1, "меньше 0"),
    ("1", 10.5, "целым"),
    ("2б", -0.1, "меньше 0"),
    ("8", 100.5, "100 %"),
    ("9а", 150, "100 %"),
    ("13а", 101, "100 %"),
    ("5", float("nan"), "конечным"),
    ("14", float("inf"), "конечным"),
    ("1", "пятьдесят", "ожидается число"),
    ("1", True, "ожидается число"),
    ("2а", "нет такого", "недопустимый вариант"),
])
def test_invalid_input_is_error(ind_id, value, fragment):
    errs, _ = check_value(RULES.indicator(ind_id), value)
    assert any(fragment in e for e in errs), errs


def test_unknown_indicator_is_error():
    res = validate(RULES, {"15": 10, "1": 5})
    assert not res.ok and "15" in res.errors and "1" not in res.errors


@pytest.mark.parametrize("ind_id, value", [
    ("1", 0), ("1", 50), ("8", 100), ("9а", 0.005), ("13б", 250), ("10", 1000), ("2а", "mo"),
])
def test_valid_input_has_no_errors(ind_id, value):
    errs, warns = check_value(RULES.indicator(ind_id), value)
    assert errs == [] and warns == []


# ---------------- 6. проверка ввода: предупреждения ----------------

@pytest.mark.parametrize("ind_id", ["2б", "3б", "4б", "11б"])
def test_people_in_units_instead_of_thousands_warns(ind_id):
    errs, warns = check_value(RULES.indicator(ind_id), 300000)  # ввели 300 тыс. человек в человеках
    assert errs == [] and any("ТЫСЯЧАХ" in w for w in warns)


@pytest.mark.parametrize("ind_id", ["5", "14"])
def test_hours_more_than_year_warns(ind_id):
    errs, warns = check_value(RULES.indicator(ind_id), 9000)
    assert errs == [] and warns


def test_every_number_indicator_has_input_constraints():
    for r in NUMBER:
        assert r.get("input", {}).get("min") == 0, r["id"]


# ---------------- 7. движок не принимает ошибочный ввод ----------------

def test_assess_rejects_invalid_input():
    with pytest.raises(InputError):
        assess(RULES, "тест", "healthcare", {"1": -5}, [])
    with pytest.raises(InputError):
        assess(RULES, "тест", "healthcare", {"8": 120}, [])
    with pytest.raises(InputError):
        assess(RULES, "тест", "healthcare", {"нет_такого": 1}, [])


@pytest.mark.parametrize("obj", load_objects(), ids=lambda o: o["id"])
def test_reference_objects_are_valid_input(obj):
    assert validate(RULES, obj.get("indicators") or {}, obj.get("attributes") or {}).ok
    assess(RULES, obj["name"], obj["sphere"], obj.get("indicators") or {},
           implemented_codes(RULES, obj["implemented"]), attributes=obj.get("attributes"))


# ---------------- 7а. условия применимости показателей ----------------

CONDITIONAL = {"8": "state_org", "10": "financial_org", "13а": "defense_order", "13б": "defense_order",
               "14": "defense_is"}


def test_conditions_in_rules():
    """Условные показатели — ровно те, у которых условие записано в формулировке Перечня."""
    assert {i["id"]: i["applies_if"] for i in RULES.categorization["indicators"] if i.get("applies_if")}         == CONDITIONAL
    for c in RULES.categorization["conditions"]:
        assert c["source"].startswith("ПП РФ № 127, Перечень показателей, п.")
    for ind_id, cond_id in CONDITIONAL.items():
        num = ind_id.rstrip("абв")
        assert RULES.condition(cond_id)["source"].endswith(f"п. {num}")


@pytest.mark.parametrize("ind_id, cond_id", CONDITIONAL.items())
def test_conditional_indicator_requires_condition(ind_id, cond_id):
    values = {ind_id: 20}
    res = validate(RULES, values, {})
    assert ind_id in res.errors and "применяется, только если" in res.errors[ind_id][0]
    assert validate(RULES, values, {cond_id: True}).ok
    assert validate(RULES, values).ok  # без признаков объекта условия не проверяются
    with pytest.raises(InputError, match="только если"):
        assess(RULES, "тест", "defense", values, [])
    assert assess(RULES, "тест", "defense", values, [], attributes={cond_id: True}).categorization.category


def test_unconditional_indicator_needs_no_attributes():
    assert validate(RULES, {"1": 30}, {}).ok


# ---------------- 8. подсказки ----------------

@pytest.mark.parametrize("rule", NUMBER + CHOICE, ids=lambda r: r["id"])
def test_reference_lists_three_categories(rule):
    ref = reference(rule)
    assert [k for k, _ in ref] == [3, 2, 1]
    assert all(t for _, t in ref)


def test_boundary_note_explains_inclusion():
    note = boundary_note(RULES.indicator("1"), 50)
    assert "в диапазон 3 категории" in note and "граница входит" in note
    assert "в диапазон 2 категории" in note and "граница не входит" in note
    assert boundary_note(RULES.indicator("1"), 30) is None
    assert boundary_note(RULES.indicator("2а"), "mo") is None


def test_describe_value():
    assert describe(RULES.indicator("1"), 51).startswith("→ 2 категория")
    assert "не присваивается" in describe(RULES.indicator("1"), 0)
    assert describe(RULES.indicator("2а"), "federal").startswith("→ 1 категория")
