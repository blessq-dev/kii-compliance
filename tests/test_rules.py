"""Проверки целостности базы правил: структура, ссылки на источники, сверка с выжимкой."""

import re
from pathlib import Path

import pytest

from engine.rules_loader import load_rules

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def rules():
    return load_rules()


def test_every_indicator_has_source(rules):
    for ind in rules.categorization["indicators"]:
        assert ind.get("source", "").startswith("ПП РФ № 127"), ind["id"]


def test_every_indicator_has_short_title(rules):
    for ind in rules.categorization["indicators"]:
        assert ind.get("short") and len(ind["short"]) < len(ind["title"]), ind["id"]


def test_every_measure_and_group_has_source(rules):
    for m in rules.measures["measures"]:
        assert "№ 239" in m["source"], m["code"]
    for g in rules.measures["groups"]:
        assert "№ 239" in g["source"], g["code"]


def test_every_sphere_has_source(rules):
    for s in rules.spheres["spheres"]:
        assert "187-ФЗ" in s["source"], s["id"]


def test_indicator_count(rules):
    # Перечень ПП № 127: 14 показателей, 21 оцениваемое значение (с подпунктами)
    ids = [i["id"] for i in rules.categorization["indicators"]]
    assert len(ids) == 21
    assert len(set(ids)) == 21
    assert {re.match(r"\d+", i).group() for i in ids} == {str(n) for n in range(1, 15)}


def test_number_indicators_have_all_categories(rules):
    for ind in rules.categorization["indicators"]:
        if ind["type"] == "number":
            assert set(ind["values"]) == {1, 2, 3}, ind["id"]
            for rng in ind["values"].values():
                assert "min" in rng or "max" in rng
                assert rng["text"]


def test_choice_indicators_cover_all_categories(rules):
    for ind in rules.categorization["indicators"]:
        if ind["type"] == "choice":
            assert {o["category"] for o in ind["options"]} == {None, 1, 2, 3}, ind["id"]


def test_measure_counts(rules):
    # Приложение к приказу № 239: 17 групп, 152 меры
    measures = rules.measures["measures"]
    assert len(rules.measures["groups"]) == 17
    assert len(measures) == 152
    assert len({m["code"] for m in measures}) == 152
    assert sum(3 in m["categories"] for m in measures) == 87
    assert sum(2 in m["categories"] for m in measures) == 110
    assert sum(1 in m["categories"] for m in measures) == 124


def test_measures_match_notes(rules):
    """YAML совпадает с таблицей в notes/fstek239_measures.md построчно."""
    text = (ROOT / "notes" / "fstek239_measures.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| ([А-Я]{3}\.\d+)[ ¹²]* \| .+? \| (\+?) \| (\+?) \| (\+?) \|$", text, re.M)
    assert len(rows) == 152
    for code, c3, c2, c1 in rows:
        expected = sorted(c for c, v in ((3, c3), (2, c2), (1, c1)) if v)
        assert sorted(rules.measure(code)["categories"]) == expected, code


def test_measure_groups_exist(rules):
    groups = {g["code"] for g in rules.measures["groups"]}
    for m in rules.measures["measures"]:
        assert m["group"] in groups
        assert m["code"].startswith(m["group"] + ".")
