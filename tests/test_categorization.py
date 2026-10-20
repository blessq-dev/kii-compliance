"""Тесты категорирования по ПП РФ № 127: границы диапазонов и общие правила п. 6–7."""

import pytest

from engine.categorization import categorize, highest, in_range
from engine.rules_loader import load_rules


@pytest.fixture(scope="module")
def rules():
    return load_rules()


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


# п. 1: III — [1; 50], II — (50; 500], I — > 500
@pytest.mark.parametrize("people, expected", [
    (0, None), (1, 3), (50, 3), (51, 2), (500, 2), (501, 1),
])
def test_indicator_1_boundaries(rules, people, expected):
    assert cat(rules, {"1": people}) == expected


# пп. 2б, 3б, 4б, 11б: III — [50; 1000), II — [1000; 5000), I — ≥ 5000 (тыс. человек)
@pytest.mark.parametrize("ind", ["2б", "3б", "4б", "11б"])
@pytest.mark.parametrize("value, expected", [
    (49.9, None), (50, 3), (999, 3), (1000, 2), (4999, 2), (5000, 1),
])
def test_people_thousands_boundaries(rules, ind, value, expected):
    assert cat(rules, {ind: value}) == expected


@pytest.mark.parametrize("ind", ["2а", "3а", "4а", "11а"])
@pytest.mark.parametrize("option, expected", [
    ("none", None), ("mo", 3), ("subject", 2), ("federal", 1),
])
def test_territory(rules, ind, option, expected):
    assert cat(rules, {ind: option}) == expected


# п. 8 и п. 13а: III — (5; 10], II — (10; 15], I — > 15
@pytest.mark.parametrize("ind", ["8", "13а"])
@pytest.mark.parametrize("value, expected", [
    (5, None), (5.1, 3), (10, 3), (10.1, 2), (15, 2), (15.1, 1),
])
def test_percent_5_10_15(rules, ind, value, expected):
    assert cat(rules, {ind: value}) == expected


# п. 10: III — (3; 70], II — (70; 120], I — > 120 (млн операций)
@pytest.mark.parametrize("value, expected", [
    (3, None), (4, 3), (70, 3), (71, 2), (120, 2), (121, 1),
])
def test_indicator_10(rules, value, expected):
    assert cat(rules, {"10": value}, sphere="finance") == expected


# п. 5 (часы): III — (12; 24], II — (6; 12], I — < 6; ровно 6 — вне диапазонов
@pytest.mark.parametrize("hours, expected", [
    (25, None), (24, 3), (13, 3), (12, 2), (7, 2), (6, None), (5.9, 1),
])
def test_indicator_5_hours(rules, hours, expected):
    assert cat(rules, {"5": hours}) == expected


def test_indicator_9a_overlap_gives_highest(rules):
    # 0,01 попадает и в III (0,001; 0,05], и в II (0,005; 0,1] — по п. 6 Правил берётся II
    assert cat(rules, {"9а": 0.01}) == 2
    assert cat(rules, {"9б": 0.01}) == 3  # в п. 9б перекрытия нет


def test_indicator_14_literal(rules):
    # По буквальному тексту I категория — «более 1» часа
    assert cat(rules, {"14": 3}, sphere="defense") == 1
    assert cat(rules, {"14": 1}, sphere="defense") is None


def test_highest_across_indicators(rules):
    # п. 6 абз. 1: итог — наивысшая среди показателей
    assert cat(rules, {"1": 10, "2а": "subject", "11б": 6000}) == 1
    assert cat(rules, {"1": 10, "2а": "subject"}) == 2


def test_no_indicators_no_category(rules):
    res = categorize(rules, "science", {})
    assert res.is_kii_subject and res.category is None


def test_empty_values_are_ignored(rules):
    assert cat(rules, {"1": None, "2а": "", "4б": 1000}) == 2


def test_sphere_outside_law(rules):
    res = categorize(rules, "other", {"1": 1000})
    assert not res.is_kii_subject
    assert res.category is None


def test_warnings_for_anomalous_indicators(rules):
    res = categorize(rules, "healthcare", {"5": 6, "1": 5})
    assert any(w.startswith("Показатель 5:") for w in res.warnings)
    assert cat(rules, {"5": 6, "1": 5}) == 3


def test_explanation_refers_to_source(rules):
    res = categorize(rules, "healthcare", {"1": 30})
    assert any("п. 1" in e for e in res.explanation)
    assert [r.indicator_id for r in res.decisive] == ["1"]


def test_invalid_choice_raises(rules):
    with pytest.raises(ValueError):
        categorize(rules, "healthcare", {"2а": "нет такого варианта"})
