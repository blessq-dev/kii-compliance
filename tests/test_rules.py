"""Проверки целостности базы правил: структура, ссылки на источники, сверка с выжимкой.

Структурные проверки выполняются для обеих редакций (исходной и действующей).
"""

import re
from pathlib import Path

import pytest

from conftest import ORIGINAL_DATE
from engine.rules_loader import load_rules

ROOT = Path(__file__).resolve().parent.parent
CURRENT, ORIGINAL = load_rules(), load_rules(on_date=ORIGINAL_DATE)


@pytest.fixture(scope="module", params=[ORIGINAL, CURRENT], ids=["исходная", "действующая"])
def rules(request):
    return request.param


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


def test_indicator_count_original():
    # Перечень ПП № 127 (2018): 14 показателей, 21 оцениваемое значение (с подпунктами)
    ids = [i["id"] for i in ORIGINAL.categorization["indicators"]]
    assert len(ids) == 21 and len(set(ids)) == 21
    assert {re.match(r"\d+", i).group() for i in ids} == {str(n) for n in range(1, 15)}


def test_indicator_count_current():
    # Перечень ПП № 127 (ред. 07.11.2025): пп. 1–14, 10(1)–10(7), 13(1); 30 оцениваемых значений
    ids = [i["id"] for i in CURRENT.categorization["indicators"]]
    assert len(ids) == 30 and len(set(ids)) == 30
    assert {re.match(r"\d+", i).group() for i in ids} == {str(n) for n in range(1, 15)}
    assert {i for i in ids if "(" in i} == {f"10({n})" for n in range(1, 8)} | {"13(1)"}


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


@pytest.mark.parametrize("rules, counts", [(ORIGINAL, (87, 110, 124)), (CURRENT, (90, 108, 117))],
                         ids=["исходная", "действующая"])
def test_measure_counts(rules, counts):
    # Приложение к приказу № 239: 17 групп, 152 меры
    measures = rules.measures["measures"]
    assert len(rules.measures["groups"]) == 17
    assert len(measures) == 152
    assert len({m["code"] for m in measures}) == 152
    assert tuple(sum(k in m["categories"] for m in measures) for k in (3, 2, 1)) == counts


def _notes_table() -> dict[str, list[int]]:
    """Таблица раздела 2 выжимки notes/fstek239_measures.md (исходная редакция)."""
    text = (ROOT / "notes" / "fstek239_measures.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| ([А-Я]{3}\.\d+)[ ¹²]* \| .+? \| (\+?) \| (\+?) \| (\+?) \|$", text, re.M)
    assert len(rows) == 152
    return {code: sorted(c for c, v in ((3, c3), (2, c2), (1, c1)) if v) for code, c3, c2, c1 in rows}


def _notes_changes() -> dict[str, list[int]]:
    """Таблица 4.1 выжимки: изменения базовых наборов в действующей редакции."""
    text = (ROOT / "notes" / "fstek239_measures.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| ([А-Я]{3}\.\d+) \| [+— /]+ \| ([+—]) / ([+—]) / ([+—]) \|$", text, re.M)
    assert rows
    return {code: sorted(c for c, v in ((3, c3), (2, c2), (1, c1)) if v == "+") for code, c3, c2, c1 in rows}


def test_measures_match_notes_original():
    """Пакет исходной редакции совпадает с таблицей выжимки построчно."""
    for code, expected in _notes_table().items():
        assert sorted(ORIGINAL.measure(code)["categories"]) == expected, code


def test_measures_match_notes_current():
    """Пакет действующей редакции = таблица исходной редакции + изменения из раздела 4.1 выжимки."""
    expected = {**_notes_table(), **_notes_changes()}
    for code, cats in expected.items():
        assert sorted(CURRENT.measure(code)["categories"]) == cats, code


def test_measure_groups_exist(rules):
    groups = {g["code"] for g in rules.measures["groups"]}
    for m in rules.measures["measures"]:
        assert m["group"] in groups
        assert m["code"].startswith(m["group"] + ".")


def test_directions_of_p22_current():
    """П. 22 действующей редакции: 18 направлений, 17 из них — группы приложения, «т» — без группы."""
    dirs = CURRENT.measures["directions"]
    assert len(dirs) == 18
    assert {d["group"] for d in dirs if d["group"]} == {g["code"] for g in CURRENT.measures["groups"]}
    assert [d["id"] for d in dirs if not d["group"]] == ["т"]
