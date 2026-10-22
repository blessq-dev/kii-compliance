"""Сверка пакетов правил с таблицей Перечня из текста документа и черновик пакета новой редакции.

Пометки «в ред.» не помогают, когда часть документа изложена в новой редакции целиком (Перечень
показателей ПП № 127 в ред. ПП РФ от 13.04.2019 № 452) — тогда сверяются сами значения.
"""

from pathlib import Path

import pytest

from engine.rules_loader import check_package, read_package
from engine.source_table import compare_package, draft_package, indicator_rows, parse_range
from engine.verification import verify_package

ROOT = Path(__file__).resolve().parent.parent
TEXTS = {"2019-04-13": "PP-127_red_2019-04-13.docx", "2022-12-20": "PP-127_red_2022-12-20.docx",
         "2025-11-07": "Postanovlenie_Pravitelstva_RF_ot_08_02_2018_N_127_red_ot.docx"}


def rows(edition: str):
    return indicator_rows(ROOT / "docs" / TEXTS[edition])


def package(edition: str):
    return read_package(ROOT / "rules" / "pp-127" / f"{edition}.yaml")


@pytest.mark.parametrize("text, expected", [
    ("более или равно 2, но менее 1000", {"min": 2, "min_incl": True, "max": 1000, "max_incl": False}),
    ("менее или равно 24, но более 12", {"max": 24, "max_incl": True, "min": 12, "min_incl": False}),
    ("более 0,0003, но менее или равно 0,0006", {"min": 0.0003, "min_incl": False, "max": 0.0006, "max_incl": True}),
    ("менее 1", {"max": 1, "max_incl": False}),
    ("выход за пределы территории одного субъекта Российской Федерации", None),
])
def test_parse_range(text, expected):
    assert parse_range(text) == expected


def test_indicator_rows_of_all_editions():
    assert [r.id for r in rows("2019-04-13")] == ["1", "2а", "2б", "3а", "3б", "4", "5", "6", "7", "8", "9", "10",
                                                  "11а", "11б", "12", "13а", "13б", "14"]
    assert len(rows("2022-12-20")) == 24
    # в тексте 2025 г. Перечень разрезан примечаниями КонсультантПлюс (вложенные таблицы)
    assert len(rows("2025-11-07")) == 30 and rows("2025-11-07")[-1].id == "14"


@pytest.mark.parametrize("edition", TEXTS)
def test_package_matches_its_text(edition):
    """Каждый пакет ПП № 127 совпадает с таблицей Перечня своей редакции по всем порогам."""
    assert compare_package(package(edition).data, rows(edition)) == []


def test_restated_list_found_by_values_not_marks():
    """Ред. 2019 г.: Перечень изложен заново, пометок у пунктов нет, но сверка значений находит отличия."""
    found = {str(m) for m in compare_package(package("2018-02-08").data, rows("2019-04-13"))}
    assert "Показатель 14: значение — 1 категория: в тексте «менее или равно 1», в пакете «более 1»" in found
    assert any(m.startswith("Показатель 2б: значение — 3 категория") for m in found)
    assert any(m.startswith("Показатель 4: нет в пакете") for m in found)
    assert "Показатель 9а: нет в тексте" in found


def test_draft_reproduces_reviewed_package():
    """Черновик по тексту 2019 г. совпадает с проверенным экспертом пакетом по показателям и значениям;
    новый показатель 4 помечен для проверки."""
    doc = dict(package("2019-04-13").passport)
    draft = draft_package([package("2018-02-08").data, package("2025-11-07").data], rows("2019-04-13"), doc)
    final = {i["id"]: i for i in package("2019-04-13").data["indicators"]}
    assert [i["id"] for i in draft["indicators"]] == list(final)
    for i in draft["indicators"]:
        if i["type"] == "number":
            assert i["values"] == final[i["id"]]["values"], i["id"]
    assert [i["id"] for i in draft["indicators"] if i.get("review")] == ["4"]
    assert verify_package(check_package(draft)) == []  # дефекты 2018 г. в ред. 2019 г. устранены


def test_editions_experiment():
    """Эксперимент experiment_editions.py: пометки не видят изменений ред. 2019 г., сверка значений — видит."""
    import experiment_editions as ex
    old, new = package("2018-02-08"), package("2019-04-13")
    expected = ex.truth(old.data, new.data)
    assert len(expected) == 15 and {"14", "9а", "4"} <= expected
    assert ex.by_values(old, ROOT / "docs" / TEXTS["2019-04-13"]) == expected
    from engine.source_text import read_paragraphs
    paragraphs = read_paragraphs(ROOT / "docs" / TEXTS["2019-04-13"])
    assert ex.by_marks(old, paragraphs) == set() and ex.by_marks(old, paragraphs, new) == set()
