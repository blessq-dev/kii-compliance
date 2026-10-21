"""Выявление изменений по тексту документов (.docx КонсультантПлюс) без ИИ.

На реальных редакциях ПП № 127 (2019, 2021, 2022, 2024, 2025 гг.) проверяется, что по пометкам
«в ред.», «введен», «утратил силу» программа находит изменённые пункты и правила пакета,
которые на них основаны.
"""

from datetime import date
from pathlib import Path

import pytest

from engine.rules_loader import read_package
from engine.source_text import amendments, read_paragraphs, stale_rules

ROOT = Path(__file__).resolve().parent.parent
EDITIONS = {"PP-127_red_2019-04-13.docx": date(2019, 4, 13), "PP-127_red_2021-12-24.docx": date(2021, 12, 24),
            "PP-127_red_2022-12-20.docx": date(2022, 12, 20), "PP-127_red_2024-09-19.docx": date(2024, 9, 19),
            "Postanovlenie_Pravitelstva_RF_ot_08_02_2018_N_127_red_ot.docx": date(2025, 11, 7)}
OLD = read_package(ROOT / "rules" / "pp-127" / "2018-02-08.yaml")
CURRENT = read_package(ROOT / "rules" / "pp-127" / "2025-11-07.yaml")


def text(name: str) -> list[str]:
    return read_paragraphs(ROOT / "docs" / name)


@pytest.mark.parametrize("name, edition", EDITIONS.items())
def test_last_amendment_is_edition_date(name, edition):
    """Самая поздняя пометка в тексте совпадает с датой редакции из заголовка документа."""
    assert f"ред. от {edition:%d.%m.%Y}" in text(name)[0]
    assert max(a.last for a in amendments(text(name))) == edition


def test_current_package_is_up_to_date():
    """Пакет действующей редакции соответствует тексту: изменений после его даты нет."""
    assert stale_rules(CURRENT.data, CURRENT.effective_from, text("Postanovlenie_Pravitelstva_RF_ot_08_02_2018_N_127_red_ot.docx")) == []


def test_old_package_is_stale_against_2022_edition():
    items = {s.place: s for s in stale_rules(OLD.data, OLD.effective_from, text("PP-127_red_2022-12-20.docx"))}
    assert items["Перечень, п. 9"].rules == ["9а", "9б", "9в"]          # правила, которые надо пересмотреть
    assert items["Перечень, п. 10"].rules == ["10", "financial_org"]
    assert items["Перечень, п. 10(1)"].kind == "введено" and items["Перечень, п. 10(1)"].rules == []  # нужно добавить
    assert items["Перечень, п. 5"].last == date(2022, 12, 20)
    assert "Перечень, п. 14" not in items                               # п. 14 не менялся


def test_changes_between_neighbour_editions():
    """Между редакциями 2021 и 2022 гг. изменения Перечня — только актами 2022 г."""
    items = stale_rules(OLD.data, date(2021, 12, 24), text("PP-127_red_2022-12-20.docx"))
    perechen = {s.place for s in items if s.place.startswith("Перечень")}
    assert perechen == {"Перечень, п. 3", "Перечень, п. 5", "Перечень, п. 8", "Перечень, п. 9", "Перечень, п. 10",
                        "Перечень, п. 10(1)", "Перечень, п. 10(2)", "Перечень, п. 10(3)", "Перечень, п. 10(4)",
                        "Перечень, п. 10(5)", "Перечень, п. 13"}
    assert all(s.last > date(2021, 12, 24) for s in items)
