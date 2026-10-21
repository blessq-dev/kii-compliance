"""Тесты категорирования по ПП РФ № 127: границы диапазонов и общие правила п. 6–7.

Основные тесты — по действующей редакции (ред. от 07.11.2025). В конце — тесты исходной
редакции 2018 г.: её дефекты (п. 5, 9а, 14) движок обрабатывает по буквальному тексту.
"""

import pytest

from conftest import ORIGINAL_DATE
from engine.categorization import categorize, highest, in_range
from engine.rules_loader import load_rules


@pytest.fixture(scope="module")
def rules():
    return load_rules()


@pytest.fixture(scope="module")
def rules_2018():
    return load_rules(on_date=ORIGINAL_DATE)


def cat(rules, values, sphere="healthcare"):
    return categorize(rules, sphere, values).category


def test_highest():
    assert highest([3, 2, None]) == 2
    assert highest([3, 1, 2]) == 1
    assert highest([None, None]) is None
    assert highest([]) is None


@pytest.mark.parametrize("value, expected", [
    (5, True), (0, True), (10, True),   # [0; 10]
    (-1, False), (11, False),
])
def test_in_range_inclusive(value, expected):
    assert in_range(value, {"min": 0, "min_incl": True, "max": 10, "max_incl": True}) is expected


def test_in_range_exclusive():
    rng = {"min": 0, "min_incl": False, "max": 10, "max_incl": False}
    assert not in_range(0, rng)
    assert not in_range(10, rng)
    assert in_range(0.0001, rng)


def test_current_edition_selected(rules):
    assert rules.packages["categorization"].passport["edition"] == "в ред. от 07.11.2025"


# п. 1: III — [1; 50], II — (50; 500], I — > 500
@pytest.mark.parametrize("people, expected", [
    (0, None), (1, 3), (50, 3), (51, 2), (500, 2), (501, 1),
])
def test_indicator_1_boundaries(rules, people, expected):
    assert cat(rules, {"1": people}) == expected


# пп. 2б, 3б, 11б: III — [2; 1000), II — [1000; 5000), I — ≥ 5000 (тыс. человек)
@pytest.mark.parametrize("ind", ["2б", "3б", "11б"])
@pytest.mark.parametrize("value, expected", [
    (1.9, None), (2, 3), (999, 3), (1000, 2), (4999, 2), (5000, 1),
])
def test_people_thousands_boundaries(rules, ind, value, expected):
    assert cat(rules, {ind: value}) == expected


# п. 4а (абоненты, тыс.): III — [3; 1000), II — [1000; 5000), I — ≥ 5000
@pytest.mark.parametrize("value, expected", [
    (2.9, None), (3, 3), (999, 3), (1000, 2), (5000, 1),
])
def test_indicator_4a_subscribers(rules, value, expected):
    assert cat(rules, {"4а": value}, sphere="telecom") == expected


@pytest.mark.parametrize("ind", ["2а", "3а", "11а"])
@pytest.mark.parametrize("option, expected", [
    ("none", None), ("mo", 3), ("subject", 2), ("federal", 1),
])
def test_territory(rules, ind, option, expected):
    assert cat(rules, {ind: option}) == expected


@pytest.mark.parametrize("ind, option, expected", [
    ("3в", "multimodal", 3), ("3в", "dangerous_one_region", 2), ("3в", "dangerous_regions", 1),
    ("3г", "oti_3_4", 3), ("3г", "oti_2", 2), ("3г", "oti_1", 1), ("3г", "none", None),
    ("4б", "regional", 3), ("4б", "federal", 2), ("4б", "supreme", 1),
])
def test_new_choice_indicators(rules, ind, option, expected):
    assert cat(rules, {ind: option}, sphere="transport") == expected


# п. 8: III — [1; 10], II — (10; 20], I — > 20
@pytest.mark.parametrize("value, expected", [
    (0.9, None), (1, 3), (10, 3), (10.1, 2), (20, 2), (20.1, 1),
])
def test_indicator_8(rules, value, expected):
    assert cat(rules, {"8": value}) == expected


# п. 13а и 13б: III — (0; 10], II — (10; 15] / (10; 40], I — > 15 / > 40
@pytest.mark.parametrize("ind, value, expected", [
    ("13а", 0, None), ("13а", 0.1, 3), ("13а", 10, 3), ("13а", 15, 2), ("13а", 15.1, 1),
    ("13б", 0, None), ("13б", 10, 3), ("13б", 40, 2), ("13б", 40.1, 1),
])
def test_indicator_13(rules, ind, value, expected):
    assert cat(rules, {ind: value}, sphere="defense") == expected


# п. 9: III — (0,0003; 0,0006], II — (0,0006; 0,001], I — > 0,001 (% дохода федерального бюджета)
@pytest.mark.parametrize("value, expected", [
    (0.0003, None), (0.0004, 3), (0.0006, 3), (0.0007, 2), (0.001, 2), (0.0011, 1),
])
def test_indicator_9(rules, value, expected):
    assert cat(rules, {"9": value}, sphere="finance") == expected


# п. 10: III — ≤ 70, II — (70; 120], I — > 120 (млн операций); нижней границы у III нет
@pytest.mark.parametrize("value, expected", [
    (0, 3), (70, 3), (71, 2), (120, 2), (121, 1),
])
def test_indicator_10(rules, value, expected):
    assert cat(rules, {"10": value}, sphere="finance") == expected


# пп. 10(1)–10(7): границы «более или равно» / «менее»
@pytest.mark.parametrize("ind, value, expected", [
    ("10(1)", 0.99, 3), ("10(1)", 1, 2), ("10(1)", 10, 1),
    ("10(2)", 9.9, 3), ("10(2)", 10, 2), ("10(2)", 25, 1),
    ("10(3)", 49, None), ("10(3)", 50, 3), ("10(3)", 1000, 2), ("10(3)", 2000, 1),
    ("10(4)", 99, None), ("10(4)", 100, 3), ("10(4)", 1500, 2), ("10(4)", 5000, 1),
    ("10(5)", 24, None), ("10(5)", 25, 3), ("10(5)", 100, 2), ("10(5)", 150, 1),
    ("10(6)", 99, None), ("10(6)", 100, 3), ("10(6)", 1000, 2), ("10(6)", 5000, 1),
    ("10(7)", 29, None), ("10(7)", 30, 3), ("10(7)", 200, 2), ("10(7)", 500, 1),
])
def test_financial_indicators(rules, ind, value, expected):
    assert cat(rules, {ind: value}, sphere="finance") == expected


# п. 5а (часы): III — (12; 24], II — (6; 12], I — ≤ 6. Ровно 6 ч теперь — I категория.
@pytest.mark.parametrize("hours, expected", [
    (25, None), (24, 3), (13, 3), (12, 2), (7, 2), (6, 1), (0, 1),
])
def test_indicator_5a_hours(rules, hours, expected):
    assert cat(rules, {"5а": hours}) == expected


# п. 5б (% времени по регламенту): III — ≤ 30, II — (30; 70], I — > 70
@pytest.mark.parametrize("value, expected", [
    (0, 3), (30, 3), (31, 2), (70, 2), (71, 1),
])
def test_indicator_5b(rules, value, expected):
    assert cat(rules, {"5б": value}) == expected


# п. 14 (часы): III — (2; 4], II — (1; 2], I — ≤ 1
@pytest.mark.parametrize("hours, expected", [
    (5, None), (4, 3), (3, 3), (2, 2), (1, 1), (0, 1),
])
def test_indicator_14(rules, hours, expected):
    assert cat(rules, {"14": hours}, sphere="defense") == expected


def test_choice_13_1(rules):
    assert cat(rules, {"13(1)": "head_executor"}, sphere="defense") == 1
    assert cat(rules, {"13(1)": "co_executor"}, sphere="defense") == 3


def test_highest_across_indicators(rules):
    # п. 6 абз. 1: итог — наивысшая среди показателей
    assert cat(rules, {"1": 10, "2а": "subject", "11б": 6000}) == 1
    assert cat(rules, {"1": 10, "2а": "subject"}) == 2


def test_no_indicators_no_category(rules):
    res = categorize(rules, "science", {})
    assert res.is_kii_subject and res.category is None


def test_empty_values_are_ignored(rules):
    assert cat(rules, {"1": None, "2а": "", "4а": 1000}) == 2


def test_sphere_outside_law(rules):
    res = categorize(rules, "other", {"1": 1000})
    assert not res.is_kii_subject
    assert res.category is None


def test_new_sphere_real_estate(rules, rules_2018):
    """Сфера госрегистрации прав на недвижимость добавлена в 187-ФЗ (ФЗ № 312-ФЗ, № 58-ФЗ)."""
    assert categorize(rules, "real_estate", {"6": "regional"}).category == 3
    assert not categorize(rules_2018, "real_estate", {"6": "regional"}).is_kii_subject


def test_no_text_warnings_in_current_edition(rules):
    assert not any(i.get("warning") for i in rules.categorization["indicators"])


def test_explanation_refers_to_source(rules):
    res = categorize(rules, "healthcare", {"1": 30})
    assert any("п. 1" in e for e in res.explanation)
    assert [r.indicator_id for r in res.decisive] == ["1"]


def test_invalid_choice_raises(rules):
    with pytest.raises(ValueError):
        categorize(rules, "healthcare", {"2а": "нет такого варианта"})


# ---------------- исходная редакция ПП № 127 (2018 г.) ----------------

# пп. 2б, 3б, 4б, 11б: III — [50; 1000), II — [1000; 5000), I — ≥ 5000 (тыс. человек)
@pytest.mark.parametrize("ind", ["2б", "3б", "4б", "11б"])
@pytest.mark.parametrize("value, expected", [
    (49.9, None), (50, 3), (999, 3), (1000, 2), (4999, 2), (5000, 1),
])
def test_2018_people_thousands_boundaries(rules_2018, ind, value, expected):
    assert cat(rules_2018, {ind: value}) == expected


# п. 5 (часы): III — (12; 24], II — (6; 12], I — < 6; ровно 6 — вне диапазонов
@pytest.mark.parametrize("hours, expected", [
    (25, None), (24, 3), (13, 3), (12, 2), (7, 2), (6, None), (5.9, 1),
])
def test_2018_indicator_5_hours(rules_2018, hours, expected):
    assert cat(rules_2018, {"5": hours}) == expected


def test_2018_indicator_9a_overlap_gives_highest(rules_2018):
    # 0,01 попадает и в III (0,001; 0,05], и в II (0,005; 0,1] — по п. 6 Правил берётся II
    assert cat(rules_2018, {"9а": 0.01}) == 2
    assert cat(rules_2018, {"9б": 0.01}) == 3  # в п. 9б перекрытия нет


def test_2018_indicator_14_literal(rules_2018):
    # По буквальному тексту I категория — «более 1» часа
    assert cat(rules_2018, {"14": 3}, sphere="defense") == 1
    assert cat(rules_2018, {"14": 1}, sphere="defense") is None


def test_2018_warnings_for_anomalous_indicators(rules_2018):
    res = categorize(rules_2018, "healthcare", {"5": 6, "1": 5})
    assert any(w.startswith("Показатель 5:") for w in res.warnings)
    assert cat(rules_2018, {"5": 6, "1": 5}) == 3
