"""QA-тесты интерфейса: Streamlit-приложение запускается без браузера (streamlit.testing)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from engine import trials
from engine.rules_loader import load_rules

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")
RESULTS = ROOT / "data" / "results"
# файлы, которые приложение дописывает: тесты не должны портить реальные журналы
LOGS = [RESULTS / "sessions.csv", RESULTS / "experiment_system.csv", RESULTS / "experiment_manual.csv"]
REGISTRY = ROOT / "data" / "assessments"


@pytest.fixture
def app():
    saved = {p: p.read_bytes() for p in LOGS if p.exists()}
    reg_before = set(REGISTRY.glob("*.json")) if REGISTRY.exists() else set()
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    yield at
    for p in LOGS:
        if p in saved:
            p.write_bytes(saved[p])
        elif p.exists():
            p.unlink()
    if REGISTRY.exists():
        for f in set(REGISTRY.glob("*.json")) - reg_before:
            f.unlink()


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


def measure_boxes(at):
    """Галочки мер на странице (без галочек ГИС/ИСПДн и требований № 235)."""
    return [c for c in at.checkbox if c.key and c.key.startswith("m_")]


def checked(at) -> int:
    """Сколько мер отмечено как реализованные (по состоянию сессии, включая скрытые фильтром)."""
    return sum(1 for c in CODES if f"m_{c}" in at.session_state and at.session_state[f"m_{c}"])


# ---------------- структура ----------------

def test_starts_with_four_steps(app):
    assert [t.label for t in app.tabs] == [
        "1. Объект и сфера", "2. Показатели значимости", "3. Меры защиты", "4. Система безопасности", "5. Отчёт"]
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
    assert [c.key for c in measure_boxes(app)] == ["m_УПД.3"]
    app.text_input(key="flt_search").set_value("").run()
    assert checked(app) == 108  # отметки скрытых мер не потерялись


def test_only_open_measures(app):
    load_example(app, "obj02")
    app.toggle(key="flt_open").set_value(True).run()
    assert sorted(c.key for c in measure_boxes(app)) == ["m_ЗИС.4", "m_СОВ.1"]


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


# ---------------- карточка меры: адаптация и компенсирующие меры ----------------

def open_card(at, code, status, text=""):
    at.selectbox(key="card_code").set_value(code).run()
    at.radio(key="card_status").set_value(status).run()
    at.text_area(key="card_text").set_value(text).run()
    button(at, "Сохранить сведения о мере").click().run()
    assert not at.exception


def test_card_requires_justification(app):
    app.number_input(key="ind_1").set_value(30.0).run()
    open_card(app, "ЗИС.32", "not_applicable", "")
    assert "нужно обоснование" in texts(app.error)
    assert "не применяется" not in texts(m for m in app.markdown if "Меры базового набора" in m.value)


def test_card_not_applicable_and_compensated(app):
    app.number_input(key="ind_1").set_value(30.0).run()
    open_card(app, "ЗИС.32", "not_applicable", "беспроводных сетей нет")
    open_card(app, "АВЗ.2", "compensated", "фильтрация почты на шлюзе")
    card = texts(m for m in app.markdown if "Меры базового набора" in m.value)
    assert "1 / 86" in card and "не применяется: 1" in card  # АВЗ.2 закрыта компенсирующей мерой
    button(app, "Сформировать отчёт").click().run()
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Не применяются"] == "1" and metrics["Несоответствий"] == "85"


def test_checking_measure_clears_special_status(app):
    app.number_input(key="ind_1").set_value(30.0).run()
    open_card(app, "АВЗ.2", "compensated", "фильтрация почты на шлюзе")
    app.checkbox(key="m_АВЗ.2").check().run()
    assert "АВЗ.2" not in app.session_state["mst"]


# ---------------- ГИС / ИСПДн и приказ № 235 ----------------

def test_gis_notice(app):
    app.checkbox(key="attr_gis").check().run()
    assert "п. 24" in texts(app.info)


def test_conditional_indicator_needs_condition(app):
    """П. 13 ПП № 127 применяется, только если субъект выполняет гособоронзаказ."""
    app.number_input(key="ind_13а").set_value(20.0).run()
    assert "только если" in texts(app.error)
    assert app.session_state["ind_13а"] == 20.0
    app.checkbox(key="attr_defense_order").check().run()
    assert "только если" not in texts(app.error)
    button(app, "Сформировать отчёт").click().run()
    assert not app.exception
    assert app.session_state["report"].categorization.category == 1


def test_security_done_and_na_are_exclusive(app):
    app.number_input(key="ind_1").set_value(30.0).run()
    app.checkbox(key="secna_С.3").check().run()
    app.checkbox(key="sec_С.3").check().run()
    assert app.session_state["sec_С.3"] and not app.session_state["secna_С.3"]
    button(app, "Сформировать отчёт").click().run()
    assert not app.exception
    assert any("Выполнено 1 из 46" in str(p.proto.text) for p in app.get("progress"))


# ---------------- перечень объектов ----------------

def test_registry_save_and_open(app):
    load_example(app, "obj02")
    button(app, "Сохранить текущую оценку в перечень").click().run()
    assert "сохранена в перечень" in texts(app.success)
    button(app, "Начать новую оценку").click().run()
    assert summary_category(app) == "cat0"
    button(app, "Открыть").click().run()
    assert summary_category(app) == "cat2" and checked(app) == 108


# ---------------- режим эксперимента ----------------

def test_experiment_trial_is_logged(app):
    app.toggle(key="exp_mode").set_value(True).run()
    app.text_input(key="exp_participant").set_value("Участник 1").run()
    app.selectbox(key="exp_object").set_value("obj01").run()
    button(app, "▶ Начать оценку объекта через систему").click().run()
    assert "Режим эксперимента" in texts(app.markdown)
    app.number_input(key="ind_1").set_value(30.0).run()
    button(app, "Сформировать отчёт").click().run()
    row = trials.read(trials.SYSTEM_LOG)[-1]
    assert (row["participant"], row["object_id"], row["category_ok"]) == ("Участник 1", "obj01", "1")
    assert int(row["fn"]) == 0 and int(row["fp"]) == 87 - 3  # меры не отмечены — лишние несоответствия
    assert "Записано" in texts(app.success)


def test_experiment_start_requires_participant(app):
    app.toggle(key="exp_mode").set_value(True).run()
    button(app, "▶ Начать оценку объекта через систему").click().run()
    assert "Укажите участника" in texts(app.error)


def test_manual_result_form(app):
    app.toggle(key="exp_mode").set_value(True).run()
    app.text_input(key="man_part").set_value("Эксперт А")
    app.selectbox(key="man_obj").set_value("obj02")
    app.selectbox(key="man_cat").set_value("II")
    app.number_input(key="man_min").set_value(25.0)
    app.text_area(key="man_missing").set_value("СОВ.1, ЗИС.4")
    button(app, "Сохранить результат").click().run()
    assert not app.exception
    row = trials.read(trials.MANUAL_LOG)[-1]
    assert (row["participant"], row["object_id"], row["category_ok"], row["tp"], row["fp"], row["fn"]) == \
        ("Эксперт А", "obj02", "1", "2", "0", "0")


def test_rule_editions_shown(app):
    """Боковая панель показывает редакции документов и итог проверки базы правил."""
    captions = texts(app.sidebar.caption)
    assert "Постановление Правительства РФ от 08.02.2018 № 127" in captions
    assert "ошибок 0, замечаний к тексту документов 7" in captions


def test_date_without_edition_falls_back_to_today(app):
    from datetime import date
    app.date_input(key="rules_date").set_value(date(2000, 1, 1)).run()
    assert not app.exception
    assert "недоступна" in texts(app.error)
    assert app.session_state["rules_date"] == date.today()



def test_card_rejects_self_compensation(app):
    app.number_input(key="ind_1").set_value(30.0).run()
    open_card(app, "ИАФ.1", "compensated", "ИАФ.1 компенсирована ИАФ.1")
    assert "не может совпадать" in texts(app.error)
    assert "ИАФ.1" not in app.session_state["mst"]
