"""QA-тесты интерфейса: Streamlit-приложение запускается без браузера (streamlit.testing)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from engine.rules_loader import load_rules

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


def button(at, label):
    return next(b for b in at.button if b.label == label)


def texts(elements):
    return " ".join(str(e.value) for e in elements)


def summary_category(at) -> str:
    """Класс карточки категории в сводке: cat1/cat2/cat3, cat0 — без категории."""
    card = next(m.value for m in at.markdown if "Категория значимости</div>" in m.value)
    return card.split('class="card ')[1].split('"')[0]


def load_example(at, obj_id):
    at.selectbox(key="example_id").set_value(obj_id).run()
    button(at, "Загрузить пример").click().run()
    assert not at.exception


CODES = [m["code"] for m in load_rules().measures["measures"]]


def checked(at) -> int:
    """Сколько мер отмечено как реализованные (по состоянию сессии, включая скрытые фильтром)."""
    return sum(1 for c in CODES if f"m_{c}" in at.session_state and at.session_state[f"m_{c}"])


# ---------------- структура ----------------

def test_starts_with_four_steps(app):
    assert [t.label for t in app.tabs] == [
        "1. Объект и сфера", "2. Показатели значимости", "3. Меры защиты", "4. Отчёт"]
    assert summary_category(app) == "cat0"
    assert not button(app, "Сформировать отчёт").disabled


def test_reference_values_shown(app):
    refs = texts(m for m in app.markdown if 'class="ref"' in m.value)
    assert "более или равно 1, но менее или равно 50" in refs  # п. 1, III категория
    assert "более 120" in refs                                  # п. 10, I категория


# ---------------- проверка ввода ----------------

def test_negative_value_blocks_report(app):
    app.number_input(key="ind_1").set_value(-5).run()
    assert "меньше 0" in texts(app.error)
    assert button(app, "Сформировать отчёт").disabled


def test_fractional_people_blocks_report(app):
    app.number_input(key="ind_1").set_value(12.5).run()
    assert "целым" in texts(app.error)
    assert button(app, "Сформировать отчёт").disabled


def test_percent_over_100_blocks_report(app):
    app.number_input(key="ind_8").set_value(150.0).run()
    assert "100 %" in texts(app.error)
    assert button(app, "Сформировать отчёт").disabled


def test_units_warning_does_not_block(app):
    app.number_input(key="ind_2б").set_value(300000.0).run()
    assert "ТЫСЯЧАХ" in texts(app.warning)
    assert not button(app, "Сформировать отчёт").disabled
    assert summary_category(app) == "cat1"


def test_boundary_value_shows_note_and_highlight(app):
    app.number_input(key="ind_1").set_value(50.0).run()
    assert "граница" in texts(app.info)
    assert summary_category(app) == "cat3"
    assert 'class="c3 hit"' in texts(m for m in app.markdown if 'class="ref"' in m.value)


def test_choice_indicator(app):
    app.radio(key="ind_2а").set_value("federal").run()
    assert summary_category(app) == "cat1"


def test_fix_error_unblocks_report(app):
    app.number_input(key="ind_1").set_value(-5).run()
    assert button(app, "Сформировать отчёт").disabled
    app.number_input(key="ind_1").set_value(30.0).run()
    button(app, "Сформировать отчёт").click().run()
    assert not app.exception
    assert "Отчёт:" in texts(app.subheader)


# ---------------- меры ----------------

def test_example_object_full_flow(app):
    load_example(app, "obj02")
    assert summary_category(app) == "cat2"
    button(app, "Сформировать отчёт").click().run()
    assert {m.label: m.value for m in app.metric}["Несоответствий"] == "2"
    assert not app.exception


def test_filter_keeps_hidden_checkmarks(app):
    load_example(app, "obj02")
    assert checked(app) == 108
    app.text_input(key="flt_search").set_value("УПД.3").run()
    assert [c.label for c in app.checkbox][0].startswith("**УПД.3**")
    assert len(app.checkbox) == 1
    app.text_input(key="flt_search").set_value("").run()
    assert checked(app) == 108  # отметки скрытых мер не потерялись


def test_only_open_measures(app):
    load_example(app, "obj02")
    app.toggle(key="flt_open").set_value(True).run()
    assert sorted(c.label.split("**")[1] for c in app.checkbox) == ["ЗИС.4", "СОВ.1"]


def test_report_reacts_to_changes(app):
    load_example(app, "obj02")
    button(app, "Сформировать отчёт").click().run()
    app.checkbox(key="m_СОВ.1").check().run()
    assert "Данные изменились" in texts(app.warning)


def test_layout_is_stable_while_filling(app):
    """Регрессия: если название вкладки или заголовок блока меняется при вводе, Streamlit
    пересоздаёт элемент — вкладка переключается на первую, а блок сворачивается после
    каждой галочки. Названия должны оставаться неизменными."""
    def layout(at):
        return [t.label for t in at.tabs], [e.label for e in at.expander]

    app.number_input(key="ind_1").set_value(30.0).run()   # появляется категория → блоки мер
    before = layout(app)
    app.number_input(key="ind_1").set_value(40.0).run()   # другое значение в том же разделе
    app.checkbox(key="m_ИАФ.0").check().run()              # первая галочка (шаг 3 становится выполненным)
    app.checkbox(key="m_ИАФ.1").check().run()
    assert layout(app) == before


def test_reset_clears_form(app):
    load_example(app, "obj02")
    button(app, "Начать новую оценку").click().run()
    assert summary_category(app) == "cat0"
    assert checked(app) == 0
