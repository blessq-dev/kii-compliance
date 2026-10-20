"""QA-тесты интерфейса: Streamlit-приложение запускается без браузера (streamlit.testing)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")
SESSIONS = Path(__file__).resolve().parent.parent / "data" / "results" / "sessions.csv"


@pytest.fixture
def app():
    existed = SESSIONS.exists()
    before = SESSIONS.read_bytes() if existed else None
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    yield at
    # тесты не должны портить журнал реальных оценок
    if existed:
        SESSIONS.write_bytes(before)
    elif SESSIONS.exists():
        SESSIONS.unlink()


def report_button(at):
    return next(b for b in at.button if b.label == "Сформировать отчёт")


def texts(elements):
    return " ".join(str(e.value) for e in elements)


def test_starts_empty(app):
    assert "не присваивается" in texts(app.info)
    assert not report_button(app).disabled


def test_negative_value_blocks_report(app):
    app.number_input(key="ind_1").set_value(-5).run()
    assert "меньше 0" in texts(app.error)
    assert report_button(app).disabled


def test_fractional_people_blocks_report(app):
    app.number_input(key="ind_1").set_value(12.5).run()
    assert "целым" in texts(app.error)
    assert report_button(app).disabled


def test_percent_over_100_blocks_report(app):
    app.number_input(key="ind_8").set_value(150.0).run()
    assert "100 %" in texts(app.error)
    assert report_button(app).disabled


def test_units_warning_does_not_block(app):
    app.number_input(key="ind_2б").set_value(300000.0).run()
    assert "ТЫСЯЧАХ" in texts(app.warning)
    assert not report_button(app).disabled
    assert "Категория значимости: **1**" in texts(app.success)


def test_boundary_value_shows_note(app):
    app.number_input(key="ind_1").set_value(50.0).run()
    assert "граница" in texts(app.info)
    assert "Категория значимости: **3**" in texts(app.success)


def test_reference_values_shown(app):
    captions = texts(app.caption)
    assert "более или равно 1, но менее или равно 50" in captions  # п. 1, III категория
    assert "более 120" in captions                               # п. 10, I категория


def test_fix_error_unblocks_report(app):
    app.number_input(key="ind_1").set_value(-5).run()
    assert report_button(app).disabled
    app.number_input(key="ind_1").set_value(30.0).run()
    assert not report_button(app).disabled
    report_button(app).click().run()
    assert not app.exception
    assert any("Отчёт об оценке" in str(m.value) for m in app.markdown)


def test_example_object_full_flow(app):
    app.sidebar.selectbox(key="example_id").set_value("obj02").run()
    next(b for b in app.sidebar.button if b.label == "Загрузить пример").click().run()
    assert "Категория значимости: **2**" in texts(app.success)
    report_button(app).click().run()
    assert {"Несоответствий": "2"}.items() <= {m.label: m.value for m in app.metric}.items()
