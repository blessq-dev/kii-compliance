"""Интерфейс прототипа (Streamlit).

Запуск:  streamlit run app.py   (или двойной щелчок по run.bat)

Интерфейс только собирает ввод пользователя и показывает результат.
Вся логика оценки — в пакете engine/, все нормативные значения — в rules/*.yaml.

Шаги оценки оформлены вкладками: Streamlit отрисовывает все вкладки при каждом
обновлении страницы, поэтому введённые значения не теряются при переходе между шагами.
Названия вкладок и заголовки раскрывающихся блоков неизменные: если они меняются,
Streamlit пересоздаёт элемент (вкладка переключается на первую, блок сворачивается).
"""

import csv
import io
import json
import time
import zipfile
from datetime import date, datetime
from html import escape

import altair as alt
import pandas as pd
import streamlit as st

from engine import registry, trials
from engine.assessment import COMPENSATED, NOT_APPLICABLE, assess, check_status_text, to_markdown
from engine.categorization import categorize
from engine.dataset import implemented_codes, load_objects
from engine.paths import USER_DIR
from engine.measures import extract_codes, group_title, required_measures
from engine.report_docx import card_docx, to_act_docx, to_docx
from engine.impact import (ADDED, base_set_changes, diff_rules, impact_on_objects, previous_edition,
                           requirement_changes)
from engine.rules_loader import KINDS, RuleBaseError, edition_dates, find_packages, load_rules
from engine.verification import ERROR, compare_findings, install_package, verify_rules
from engine.source_table import compare_package, indicator_rows
from engine.source_text import document_kind, edition_of, read_paragraphs, stale_rules
from engine.validation import InputError, boundary_note, check_value, condition_error, reference, validate

st.set_page_config(page_title="Оценка соответствия объекта КИИ", page_icon="🛡️", layout="wide")

ROMAN = {1: "I", 2: "II", 3: "III"}
IMPLEMENTED, MISSING = "implemented", "missing"
STATUS_LABELS = {IMPLEMENTED: "Реализована", MISSING: "Не реализована",
                 NOT_APPLICABLE: "Не применяется (адаптация, п. 23)", COMPENSATED: "Компенсирована (п. 26)"}
# Единая палитра интерфейса. Акцент — синий (как primaryColor в .streamlit/config.toml).
# Цвета категорий: I — красный (самая высокая), II — оранжевый, III — жёлтый;
# сочетания «текст на фоне» подобраны с контрастом не ниже 4,5 : 1 (WCAG AA).
COLORS = {"accent": "#1f5fa8", "ink": "#14233a", "muted": "#566175", "done": "#1e7a46",
          "compensated": "#2f6fca", "missing": "#c0362c"}
CSS = """
<style>
:root {--acc:#1f5fa8; --acc-bg:#eaf1fa; --ink:#14233a; --muted:#566175; --line:#dde3ec; --soft:#f5f7fb;
       --c1:#a61b12; --c1bg:#fdecea; --c1ln:#f3c4bf; --c2:#97470a; --c2bg:#fef0e1; --c2ln:#f6d2ab;
       --c3:#6f5300; --c3bg:#fff5d1; --c3ln:#f0dc8f; --ok:#1b6e40; --okbg:#e3f4ea;}
.block-container {padding-top: 1.6rem; max-width: 1200px;}
h1, h2, h3, h4 {color: var(--ink);}
/* вкладки-шаги: крупнее и заметнее стандартных */
[data-testid="stTabs"] [role="tablist"] {gap: 1.6rem;}
[data-testid="stTab"] {padding-top: .35rem; padding-bottom: .35rem;}
[data-testid="stTab"] p {font-size: 1rem; font-weight: 600;}
[data-testid="stTab"][aria-selected="false"] p {color: var(--muted);}
[data-testid="stTab"][aria-selected="false"]:hover p {color: var(--acc);}
/* раскрывающиеся блоки */
[data-testid="stExpander"] details {border-radius: .7rem; border-color: var(--line);}
[data-testid="stExpander"] summary p {font-weight: 600;}
/* метки категорий */
.badge {display:inline-block; padding:.18rem .75rem; border-radius:999px; font-weight:600; font-size:.88rem;
        white-space:nowrap;}
.cat1 {background:var(--c1bg); color:var(--c1);} .cat2 {background:var(--c2bg); color:var(--c2);}
.cat3 {background:var(--c3bg); color:var(--c3);} .cat0 {background:#eef1f5; color:#4a5466;}
/* шапка */
.apptitle {font-size:1.85rem; font-weight:700; line-height:1.2; color:var(--ink);}
.appsub {font-size:1rem; color:var(--muted); margin:.25rem 0 1rem; display:flex; gap:.6rem; align-items:center;
         flex-wrap:wrap;}
/* сводка: сетка карточек, на узком экране переносится по строкам */
.summary {display:grid; grid-template-columns:repeat(auto-fit, minmax(175px, 1fr)); gap:.75rem; margin:0 0 1.1rem;}
.card {background:#fff; border:1px solid var(--line); border-top:4px solid #c3ccd9; border-radius:.75rem;
       padding:.8rem 1rem .85rem; color:var(--ink); min-width:0;}
.card .label {font-size:.78rem; font-weight:600; text-transform:uppercase; letter-spacing:.04em; color:var(--muted);}
.card .value {font-size:1.65rem; font-weight:700; line-height:1.25; margin-top:.15rem;}
.card .sub {font-size:.82rem; color:var(--muted); margin-top:.2rem;}
.card.cat1 {background:var(--c1bg); border-color:var(--c1ln); border-top-color:var(--c1);}
.card.cat2 {background:var(--c2bg); border-color:var(--c2ln); border-top-color:var(--c2);}
.card.cat3 {background:var(--c3bg); border-color:var(--c3ln); border-top-color:var(--c3);}
.card.cat1 .value, .card.cat1 .sub, .card.cat1 .label {color:var(--c1);}
.card.cat2 .value, .card.cat2 .sub, .card.cat2 .label {color:var(--c2);}
.card.cat3 .value, .card.cat3 .sub, .card.cat3 .label {color:var(--c3);}
.card.acc {border-top-color:var(--acc);}
.mini {height:6px; border-radius:3px; background:#e6eaf0; margin-top:.45rem; overflow:hidden;}
.mini span {display:block; height:100%; background:var(--acc); border-radius:3px;}
/* справочные значения показателя (ПП № 127) */
.ref {display:flex; gap:.4rem; margin:.3rem 0 .2rem; flex-wrap:wrap;}
.ref div {flex:1 1 150px; border-radius:.55rem; padding:.4rem .6rem; font-size:.8rem; line-height:1.3;
          border:1px solid var(--line); background:var(--soft); color:#3d4757;}
.ref div b {display:block; font-size:.72rem; letter-spacing:.03em; margin-bottom:.1rem; text-transform:uppercase;}
.ref .c1 b {color:var(--c1);} .ref .c2 b {color:var(--c2);} .ref .c3 b {color:var(--c3);}
.ref div.hit {border-width:2px; font-weight:600; box-shadow:0 1px 4px rgba(20,35,58,.12);}
.ref .c3.hit {background:var(--c3bg); border-color:var(--c3); color:var(--c3);}
.ref .c2.hit {background:var(--c2bg); border-color:var(--c2); color:var(--c2);}
.ref .c1.hit {background:var(--c1bg); border-color:var(--c1); color:var(--c1);}
/* группы мер */
.chips {display:flex; flex-wrap:wrap; gap:.35rem; margin:.2rem 0 .8rem;}
.chip {padding:.15rem .6rem; border-radius:999px; font-size:.8rem; font-weight:600; border:1px solid transparent;}
.chip.full {background:var(--okbg); color:var(--ok);} .chip.part {background:var(--c2bg); color:var(--c2);}
.chip.none {background:var(--c1bg); color:var(--c1);}
.legend {font-size:.8rem; color:var(--muted); margin:-.3rem 0 .6rem;}
.mnote {font-size:.82rem; margin:-.4rem 0 .5rem 1.9rem; color:var(--muted);}
/* подсказки «что дальше» и пустые состояния */
.hint {margin:1.2rem 0 .3rem; padding:.6rem .9rem; border-left:4px solid var(--acc); background:var(--acc-bg);
       border-radius:.4rem; font-size:.92rem; color:var(--ink);}
.empty {border:1px dashed #b9c3d1; border-radius:.8rem; padding:1.4rem 1.5rem; background:var(--soft);
        color:var(--ink); margin:.4rem 0 1rem;}
.empty .t {font-size:1.1rem; font-weight:700; margin-bottom:.3rem;}
.empty .d {color:var(--muted); font-size:.93rem; line-height:1.5;}
.empty ul {margin:.5rem 0 0 1.1rem; padding:0; color:var(--muted); font-size:.93rem;}
/* итог категорирования в отчёте */
.verdict {border-radius:.8rem; padding:1rem 1.25rem; margin:.3rem 0 .9rem; border:1px solid var(--line);
          border-left:6px solid #8b95a5;}
.verdict .vl {font-size:.78rem; font-weight:600; text-transform:uppercase; letter-spacing:.05em; opacity:.9;}
.verdict .vt {font-size:1.45rem; font-weight:700; line-height:1.3;}
.verdict .vs {font-size:.92rem; margin-top:.15rem;}
.verdict.cat1 {border-color:var(--c1ln); border-left-color:var(--c1);}
.verdict.cat2 {border-color:var(--c2ln); border-left-color:var(--c2);}
.verdict.cat3 {border-color:var(--c3ln); border-left-color:var(--c3);}
/* таблицы отчёта: текст переносится, а не обрезается */
.tblwrap {border:1px solid var(--line); border-radius:.6rem; overflow:auto; margin:.2rem 0 1rem;}
.tblwrap.scroll {max-height:430px;}
.tbl {width:100%; border-collapse:collapse; font-size:.88rem; color:var(--ink);}
.tbl th {position:sticky; top:0; background:var(--soft); text-align:left; font-weight:600; color:#3d4757;
         padding:.5rem .7rem; border-bottom:1px solid var(--line);}
.tbl td {padding:.45rem .7rem; border-bottom:1px solid #edf0f4; vertical-align:top; line-height:1.4;}
.tbl tr:last-child td {border-bottom:none;}
.tbl td:first-child {font-weight:600; white-space:nowrap;}
/* метрики отчёта — карточками */
[data-testid="stMetric"] {background:#fff; border:1px solid var(--line); border-radius:.75rem; padding:.65rem .9rem;}
[data-testid="stMetricLabel"] p {font-size:.82rem; color:var(--muted); white-space:normal;}
[data-testid="stMetricValue"] {font-size:1.6rem; font-weight:700; color:var(--ink);}
.st-key-charts [data-testid="stHorizontalBlock"] {flex-wrap:wrap; row-gap:1rem;}
.st-key-charts [data-testid="stColumn"] {min-width:300px;}
.st-key-charts [data-testid="stColumn"]:first-child {flex:1 1 300px !important;}
.st-key-charts [data-testid="stColumn"]:last-child {flex:2 1 360px !important;}
/* боковая панель */
.brand {display:flex; gap:.6rem; align-items:flex-start; margin:-.5rem 0 .4rem;}
.brand .logo {font-size:1.6rem; line-height:1;}
.brand .name {font-weight:700; font-size:1.05rem; line-height:1.25; color:var(--ink);}
.brand .docs {font-size:.8rem; color:var(--muted); margin-top:.25rem; line-height:1.35;}
.steps {display:flex; flex-direction:column; gap:.15rem; margin:.2rem 0;}
.step {display:flex; align-items:center; gap:.6rem; padding:.35rem .5rem; border-radius:.5rem; font-size:.93rem;
       color:var(--ink);}
.step .n {flex:0 0 1.55rem; height:1.55rem; border-radius:50%; display:flex; align-items:center;
          justify-content:center; font-size:.8rem; font-weight:700; border:2px solid #b6c0ce; color:var(--muted);
          background:#fff;}
.step.done .n {background:var(--ok); border-color:var(--ok); color:#fff;}
.step.next {background:var(--acc-bg); font-weight:600;}
.step.next .n {border-color:var(--acc); color:var(--acc);}
.exp {border:2px dashed var(--acc); border-radius:.8rem; padding:.6rem 1rem; margin-bottom:1rem; background:var(--acc-bg);}
/* «не применимо» у требований № 235 — второстепенная отметка, с отступом */
[class*="st-key-secna_"] {margin:-.55rem 0 .2rem 1.9rem;}
[class*="st-key-secna_"] label p {font-size:.82rem; color:var(--muted); font-style:italic;}
/* русские надписи у загрузки файла вместо встроенных английских */
[data-testid="stFileUploaderDropzone"] button > * {display:none !important;}
[data-testid="stFileUploaderDropzone"] button::after {content:"Выбрать файл"; font-size:.9rem;}
[data-testid="stFileUploaderDropzoneInstructions"] small {display:none;}
[data-testid="stFileUploaderDropzoneInstructions"] span {font-size:0;}
[data-testid="stFileUploaderDropzoneInstructions"] span::after {content:"или перетащите его сюда"; font-size:.9rem;}
/* длинные варианты ответа (дословный текст ПП № 127): кружок — напротив первой строки */
[data-testid="stRadioOption"] > div {align-items:flex-start !important;}
[data-testid="stRadioOption"] > div > div:first-child {margin-top:.2rem;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


@st.cache_resource
def get_rules(on_date: date):
    """База правил: редакции документов, действующие на дату оценки."""
    return load_rules(on_date=on_date)


@st.cache_resource
def get_packages():
    return find_packages()


@st.cache_resource
def get_findings(on_date: date):
    return verify_rules(get_rules(on_date))


st.session_state.setdefault("rules_date", date.today())
try:
    rules = get_rules(st.session_state.rules_date)
except RuleBaseError as _e:
    st.error(f"База правил на выбранную дату недоступна: {_e}. Использована текущая дата.")
    st.session_state.rules_date = date.today()
    rules = get_rules(date.today())
KIND_TITLES = {"spheres": "Сферы субъектов КИИ", "categorization": "Категорирование",
               "measures": "Меры защиты", "security_system": "Система безопасности"}
SHORT_ACT = {"spheres": "187-ФЗ", "categorization": "ПП № 127", "measures": "приказ № 239",
             "security_system": "приказ № 235"}
AREA_ACT = {"Показатель": "ПП № 127", "Условие": "ПП № 127", "Мера": "приказ № 239",
            "Требование": "приказ № 235", "Сфера": "187-ФЗ"}  # области анализа влияния → документ
INDICATORS = rules.categorization["indicators"]
CONDITIONS = rules.categorization["conditions"]  # условия применимости показателей (ПП № 127)
SPHERES = rules.spheres["spheres"] + [rules.spheres["other"]]
SPHERE_IDS = [s["id"] for s in SPHERES]
ALL_CODES = [m["code"] for m in rules.measures["measures"]]
REQS = rules.security["requirements"]
OBJECTS = load_objects()
ss = st.session_state

# Сохраняем значения полей между обновлениями, даже если поле сейчас скрыто фильтром.
for _k in list(ss.keys()):
    if _k.startswith(("ind_", "m_", "attr_", "sec_", "secna_")) or _k in ("object_name", "sphere"):
        ss[_k] = ss[_k]


# ---------------- служебные функции ----------------

def badge(category, text=None) -> str:
    cls = f"cat{category or 0}"
    if text is None:
        text = f"{ROMAN[category]} категория" if category else "без категории"
    return f'<span class="badge {cls}">{text}</span>'


def pct_text(x) -> str:
    return "—" if x is None else f"{x:.1f}".replace(".", ",") + " %"


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """Число со словом в нужной форме: 1 показатель, 2 показателя, 5 показателей."""
    if n % 10 == 1 and n % 100 != 11:
        word = forms[0]
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        word = forms[1]
    else:
        word = forms[2]
    return f"{n} {word}"


def html_table(rows: list[dict], scroll: bool = False) -> str:
    """Таблица для отчёта: длинный текст переносится по строкам, а не обрезается."""
    if not rows:
        return ""
    head = "".join(f"<th>{escape(str(c))}</th>" for c in rows[0])
    body = "".join("<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in r.values()) + "</tr>" for r in rows)
    return (f'<div class="tblwrap{" scroll" if scroll else ""}"><table class="tbl"><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def hint(text: str):
    """Подсказка внизу вкладки: что делать дальше."""
    st.markdown(f'<div class="hint">→ {text}</div>', unsafe_allow_html=True)


def empty_state(title: str, text: str, items: list[str] | None = None):
    """Пустое состояние вкладки: почему здесь ничего нет и что сделать."""
    lst = "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>" if items else ""
    st.markdown(f'<div class="empty"><div class="t">{title}</div><div class="d">{text}</div>{lst}</div>',
                unsafe_allow_html=True)


def reset_form():
    """Очищает данные оценки и перезапускает таймер (режим эксперимента и участник сохраняются)."""
    for key in list(ss.keys()):
        if key.startswith(("ind_", "m_", "flt_", "attr_", "sec_", "secna_", "card_")) or key in (
                "object_name", "sphere", "report", "report_sig", "report_values", "report_ctx", "trial_result"):
            del ss[key]
    ss.object_name = ""
    ss.sphere = SPHERE_IDS[0]
    ss.mst, ss.mdet = {}, {}
    ss.started_at = time.time()
    ss.saved = False


def apply_state(data: dict) -> list[str]:
    """Заполняет форму из словаря (пример, сохранённый файл, перечень объектов).
    Возвращает список замечаний о пропущенных данных."""
    notes = []
    reset_form()
    ss.object_name = str(data.get("object_name", ""))
    if data.get("sphere") in SPHERE_IDS:
        ss.sphere = data["sphere"]
    elif data.get("sphere"):
        notes.append(f"неизвестная сфера {data['sphere']!r}")
    known = {i["id"]: i for i in INDICATORS}
    for ind_id, value in (data.get("indicators") or {}).items():
        if ind_id not in known:
            notes.append(f"неизвестный показатель {ind_id!r}")
        elif known[ind_id]["type"] == "number":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                ss[f"ind_{ind_id}"] = float(value)  # числовые поля формы работают с float
            else:
                notes.append(f"показатель {ind_id}: не число {value!r}")
        elif value in {o["id"] for o in known[ind_id]["options"]}:
            ss[f"ind_{ind_id}"] = value
        else:
            notes.append(f"показатель {ind_id}: недопустимый вариант {value!r}")
    for code in data.get("implemented") or []:
        if code in ALL_CODES:
            ss[f"m_{code}"] = True
        else:
            notes.append(f"неизвестная мера {code!r}")
    for code, st_ in (data.get("statuses") or {}).items():
        if code in ALL_CODES and st_.get("status") in (NOT_APPLICABLE, COMPENSATED):
            ss.mst[code] = {"status": st_["status"], "text": str(st_.get("text", ""))}
            ss[f"m_{code}"] = False
        else:
            notes.append(f"особый статус меры {code!r} не распознан")
    for code, d in (data.get("details") or {}).items():
        if code in ALL_CODES:
            ss.mdet[code] = {"means": str(d.get("means", "")), "due": d.get("due")}
    attrs = data.get("attributes") or {}
    ss.attr_gis, ss.attr_ispdn = bool(attrs.get("is_gis")), bool(attrs.get("is_ispdn"))
    for c in CONDITIONS:
        ss[f"attr_{c['id']}"] = bool(attrs.get(c["id"]))
    sec = data.get("security") or {}
    req_ids = {r["id"] for r in REQS}
    for rid in sec.get("done", []):
        if rid in req_ids:
            ss[f"sec_{rid}"] = True
    for rid in sec.get("not_applicable", []):
        if rid in req_ids:
            ss[f"secna_{rid}"] = True
    return notes


def test_object_state(obj: dict) -> dict:
    return {"object_name": obj["name"], "sphere": obj["sphere"], "indicators": obj.get("indicators") or {},
            "attributes": obj.get("attributes") or {}, "implemented": implemented_codes(rules, obj["implemented"])}


def load_example():
    obj = next(o for o in OBJECTS if o["id"] == ss.example_id)
    apply_state(test_object_state(obj))
    ss.flash = ("success", f"Загружен пример {obj['id']}: {obj['name']}")


def load_session_file():
    f = ss.get("session_file")
    if f is None:
        return
    try:
        notes = apply_state(json.loads(f.getvalue().decode("utf-8")))
        ss.flash = ("warning", "Оценка загружена, пропущено: " + "; ".join(notes)) if notes \
            else ("success", "Оценка загружена из файла.")
    except (ValueError, UnicodeDecodeError, AttributeError) as e:
        ss.flash = ("error", f"Не удалось прочитать файл оценки: {e}")


def load_measures_file():
    f = ss.get("measures_file")
    if f is None:
        return
    found, unknown = extract_codes(rules, f.getvalue().decode("utf-8", errors="ignore"))
    for code in found:
        ss[f"m_{code}"] = True
        ss.mst.pop(code, None)
    msg = f"Из файла отмечено мер: {len(found)}."
    if unknown:
        msg += f" Не распознаны коды: {', '.join(unknown[:10])}{' …' if len(unknown) > 10 else ''}."
    ss.flash_measures = ("warning" if unknown else "success", msg)


def set_group(codes: list[str], value: bool):
    for code in codes:
        ss[f"m_{code}"] = value
        if value:
            ss.mst.pop(code, None)


def on_measure_check(code: str):
    """Отметка «реализована» снимает особый статус меры (не применяется / компенсирована)."""
    if ss.get(f"m_{code}"):
        ss.mst.pop(code, None)


def measure_status(code: str) -> str:
    if code in ss.mst:
        return ss.mst[code]["status"]
    return IMPLEMENTED if ss.get(f"m_{code}") else MISSING


def load_card():
    """Заполняет карточку меры сохранёнными сведениями при выборе меры."""
    code = ss.get("card_code")
    if not code:
        return
    ss.card_status = measure_status(code)
    st_text = ss.mst.get(code, {}).get("text", "")
    det = ss.mdet.get(code, {})
    ss.card_text = st_text or det.get("means", "")
    ss.card_due = date.fromisoformat(det["due"]) if det.get("due") else None


def save_card():
    code, status = ss.get("card_code"), ss.get("card_status")
    text = (ss.get("card_text") or "").strip()
    if not code:
        return
    if status in (NOT_APPLICABLE, COMPENSATED) and not text:
        ss.flash_card = ("error", "Для статуса «" + STATUS_LABELS[status] + "» нужно обоснование "
                                  "(для компенсирующей меры — её описание).")
        return
    problems = check_status_text(rules, code, {"status": status, "text": text})         if status in (NOT_APPLICABLE, COMPENSATED) else []
    if problems:
        ss.flash_card = ("error", "Сведения не сохранены: " + "; ".join(problems) + ".")
        return
    ss.mst.pop(code, None)
    det = ss.mdet.setdefault(code, {})
    det["means"], det["due"] = "", None
    if status == IMPLEMENTED:
        ss[f"m_{code}"] = True
        det["means"] = text
    elif status == MISSING:
        ss[f"m_{code}"] = False
        det["due"] = ss.card_due.isoformat() if ss.get("card_due") else None
        det["means"] = ""
    else:
        ss[f"m_{code}"] = False
        ss.mst[code] = {"status": status, "text": text}
    if not det["means"] and not det["due"]:
        ss.mdet.pop(code, None)
    ss.flash_card = ("success", f"Сведения о мере {code} сохранены: {STATUS_LABELS[status].lower()}.")


def toggle_req(rid: str, kind: str):
    """Требование № 235 не может быть одновременно выполненным и неприменимым."""
    if kind == "done" and ss.get(f"sec_{rid}"):
        ss[f"secna_{rid}"] = False
    if kind == "na" and ss.get(f"secna_{rid}"):
        ss[f"sec_{rid}"] = False


def current_attributes() -> dict:
    """Признаки объекта: ГИС/ИСПДн и подтверждённые условия применимости показателей."""
    attrs = {"is_gis": bool(ss.get("attr_gis")), "is_ispdn": bool(ss.get("attr_ispdn"))}
    attrs.update({c["id"]: bool(ss.get(f"attr_{c['id']}")) for c in CONDITIONS})
    return attrs


def current_state() -> dict:
    """Текущие данные формы — для сохранения в файл, перечня объектов и сверки с отчётом."""
    return {"object_name": ss.object_name, "sphere": ss.sphere,
            "indicators": {i["id"]: ss[f"ind_{i['id']}"] for i in INDICATORS
                           if ss.get(f"ind_{i['id']}") is not None},
            "implemented": [c for c in ALL_CODES if ss.get(f"m_{c}")],
            "statuses": dict(ss.mst), "details": {c: d for c, d in ss.mdet.items() if d.get("means") or d.get("due")},
            "attributes": current_attributes(),
            "security": {"done": [r["id"] for r in REQS if ss.get(f"sec_{r['id']}")],
                         "not_applicable": [r["id"] for r in REQS if ss.get(f"secna_{r['id']}")]}}


def add_package():
    """Добавление новой редакции документа (пакета правил) пользователем."""
    f = ss.get("pkg_file")
    if f is None:
        ss.flash_rules = ("error", "Выберите файл пакета правил (.yaml).")
        return
    try:
        path, findings = install_package(f.getvalue())
    except RuleBaseError as e:
        ss.flash_rules = ("error", f"Пакет не добавлен: {e}")
        return
    get_rules.clear()
    get_packages.clear()
    get_findings.clear()
    ss.flash_rules = ("success", f"Пакет добавлен: {path.parent.name}/{path.name}. Замечаний к тексту "
                                 f"документа: {len(findings)}. Редакция применяется к оценкам с даты, "
                                 "указанной в паспорте пакета.")


def show_flash(key="flash"):
    if key in ss:
        kind, text = ss.pop(key)
        getattr(st, kind)(text)


def start_trial():
    """Режим эксперимента: начать оценку тестового объекта с чистой формы."""
    if not (ss.get("exp_participant") or "").strip():
        ss.flash = ("error", "Укажите участника эксперимента.")
        return
    reset_form()
    ss.trial = {"participant": ss.exp_participant.strip(), "object_id": ss.exp_object, "started": time.time()}
    ss.flash = ("info", f"Начата оценка объекта {ss.exp_object}. Заполните данные по карточке объекта "
                        "и сформируйте отчёт — время и результат будут записаны в журнал эксперимента.")


def save_to_registry():
    if not (ss.object_name or "").strip():
        ss.flash = ("error", "Укажите наименование объекта, чтобы сохранить его в перечень.")
        return
    summary = {"category": cat.category, "kii_subject": cat.is_kii_subject,
               "compliance": compliance, "missing": len(missing_codes)}
    path = registry.save(current_state(), summary)
    ss.flash = ("success", f"Оценка сохранена в перечень объектов ({path.name}).")


def open_from_registry():
    notes = apply_state(registry.load(ss.reg_file))
    ss.flash = ("success", f"Открыта оценка из перечня: {ss.object_name}." +
                (" Пропущено: " + "; ".join(notes) if notes else ""))


def delete_from_registry():
    registry.delete(ss.reg_file)
    ss.reg_confirm = False
    ss.flash = ("success", "Оценка удалена из перечня.")


def edition_label(d: date, first: date) -> str:
    """Подпись состояния базы правил: какие редакции вступили в силу с этой даты."""
    if d == first:
        return f"с {d:%d.%m.%Y} — исходные редакции (первые в базе)"
    started = [p for p in get_packages() if p.effective_from == d]
    return f"с {d:%d.%m.%Y} — " + "; ".join(f"{SHORT_ACT[p.kind]} {p.passport['edition']}" for p in started)


def render_comparison(dates: list[date]):
    """Сравнение редакций: изменения правил, влияние на объекты, дефекты текста документов."""
    first = edition_dates(get_packages())[0]
    st.caption("Что изменится, если перейти от прежней базы правил к редакциям, действующим на дату оценки "
               f"({rules.on_date:%d.%m.%Y}): какие правила изменились, каких объектов это касается и какие "
               "дефекты текста документов устранены или появились.")
    old_date = st.selectbox("Сравнить с базой правил", dates, key="cmp_from",
                            format_func=lambda d: edition_label(d, first))
    old_rules = get_rules(old_date)
    changes = diff_rules(old_rules, rules)
    resolved, appeared, kept = compare_findings(get_findings(old_date), get_findings(rules.on_date))
    saved_states = [s["state"] for s in registry.list_all()]
    states = saved_states or [test_object_state(o) for o in OBJECTS]
    impact = impact_on_objects(old_rules, rules, states)
    touched = [i for i in impact if i.changed]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Изменений в правилах", len(changes))
    c2.metric("Затронуто объектов", f"{len(touched)} из {len(impact)}")
    c3.metric("Дефектов текста устранено", len(resolved))
    c4.metric("Новых замечаний к тексту", len(appeared))

    t1, t2, t3 = st.tabs(["Изменения в правилах", "Влияние на объекты", "Проверка текста документов"])
    with t1:
        if not changes:
            st.caption("Правила не изменились.")
        else:
            docs = list(dict.fromkeys(AREA_ACT[c.area] for c in changes))
            pick = st.segmented_control("Документ", ["все"] + docs, default="все", key="cmp_doc")
            st.dataframe(pd.DataFrame([{
                "Документ": AREA_ACT[c.area], "Правило": f"{c.area} {c.rule}", "Изменение": c.what,
                "Подробности": c.details} for c in changes if pick in (None, "все", AREA_ACT[c.area])]),
                hide_index=True, width="stretch")
    with t2:
        st.caption("Объекты " + ("из перечня." if saved_states else
                                 "тестового набора (перечень объектов пуст).") +
                   " Меры, отмеченные реализованными, те же; сравниваются категория, обязательные меры "
                   "и несоответствия.")
        st.dataframe(pd.DataFrame([{
            "Объект": i.name,
            "Категория": f"{ROMAN.get(i.category_old, '—')} → {ROMAN.get(i.category_new, '—')}",
            "Стали обязательными": ", ".join(i.became_required),
            "Перестали быть обязательными": ", ".join(i.no_longer_required),
            "Новые несоответствия": ", ".join(i.new_missing),
            "Замечание": i.error or ("" if i.changed else "без изменений")}
            for i in sorted(impact, key=lambda i: not i.changed)]), hide_index=True, width="stretch")
    with t3:
        st.caption("Автоматическая проверка пакетов правил: пересечения и разрывы шкал, монотонность, "
                   "тяжёлый край шкалы, порог значимости, вложенность наборов мер, направления п. 22 приказа № 239.")
        for title, items, show in (("Устранены в новой редакции", resolved, st.success),
                                   ("Появились в новой редакции", appeared, st.warning),
                                   ("Остались без изменений", kept, st.info)):
            st.markdown(f"**{title}: {len(items)}**")
            if items:
                show("\n".join(f"- **{f.rule}** ({f.package}): {f.text}" for f in items))


def render_text_check():
    """Проверка текста новой редакции документа: устарел ли пакет правил и какие правила затронуты."""
    st.caption("Загрузите текст документа из КонсультантПлюс (.docx). По пометкам «в ред.», «введен», "
               "«утратил силу» система найдёт места, изменённые после даты действующего пакета правил, и "
               "правила, которые на них основаны. Нормативный текст не интерпретируется — только пометки и даты.")
    f = st.file_uploader("Текст редакции документа (.docx)", type=["docx"], key="src_docx")
    if f is None:
        return
    try:
        paras = read_paragraphs(io.BytesIO(f.getvalue()))
    except (zipfile.BadZipFile, KeyError):
        st.error("Файл не является документом Word (.docx).")
        return
    kind, edition = document_kind(paras), edition_of(paras)
    if kind is None:
        st.error("Документ не относится к базе правил (ожидаются ПП РФ № 127, приказы ФСТЭК России № 239, № 235, "
                 "187-ФЗ). Заголовок: " + (paras[0][:150] if paras else "—"))
        return
    pkg = rules.packages[kind]
    if edition and edition < pkg.effective_from:
        st.info(f"Загружена редакция от {edition:%d.%m.%Y} — она старше действующего пакета правил "
                f"({pkg.title}, с {pkg.effective_from:%d.%m.%Y}). Проверяется только более новая редакция.")
        return
    items = stale_rules(pkg.data, pkg.effective_from, paras)
    # Для ПП № 127 значения показателей сверяются ещё и по таблице Перечня: если Перечень изложен
    # в новой редакции целиком, пометок «в ред.» у пунктов нет
    mismatches = compare_package(pkg.data, indicator_rows(io.BytesIO(f.getvalue()))) if kind == "categorization" else []
    st.markdown(f"**{SHORT_ACT[kind]}**" + (f", редакция от {edition:%d.%m.%Y}" if edition else "") +
                f". Сравнивается с пакетом: {pkg.title}, применяется с {pkg.effective_from:%d.%m.%Y}.")
    if mismatches:
        st.warning(f"Значения Перечня показателей в тексте расходятся с пакетом правил: {len(mismatches)}.")
        st.dataframe(pd.DataFrame([{"Показатель": m.indicator, "Расхождение": m.what, "Подробности": m.details}
                                   for m in mismatches]), hide_index=True, width="stretch")
    if not items:
        if not mismatches:
            st.success(f"Пакет правил соответствует тексту: пометок об изменениях позже "
                       f"{pkg.effective_from:%d.%m.%Y} нет"
                       + (", значения всех показателей совпадают." if kind == "categorization" else "."))
        return
    touched = sorted({r for i in items for r in i.rules})
    no_rule = [i for i in items if not i.rules]
    st.warning(f"Пакет правил устарел: после {pkg.effective_from:%d.%m.%Y} изменено мест в тексте — {len(items)}; "
               f"затронуто правил пакета — {len(touched)}; изменённых положений без правил — {len(no_rule)} "
               "(не формализованы или их нужно добавить).")
    st.dataframe(pd.DataFrame([{
        "Место в документе": i.place, "Изменение": i.kind, "Дата акта": f"{i.last:%d.%m.%Y}",
        "Правила пакета": ", ".join(i.rules) or "—"} for i in sorted(items, key=lambda i: not i.rules)]),
        hide_index=True, width="stretch")


if "started_at" not in ss:
    reset_form()
ss.setdefault("mst", {})
ss.setdefault("mdet", {})

# ---------------- расчёт по текущим данным (до отрисовки) ----------------

raw_values = {i["id"]: ss[f"ind_{i['id']}"] for i in INDICATORS if ss.get(f"ind_{i['id']}") is not None}
attributes = current_attributes()
validation = validate(rules, raw_values, attributes)
values = {k: v for k, v in raw_values.items() if k not in validation.errors}
cat = categorize(rules, ss.sphere, values)
required = required_measures(rules, cat.category)
req_codes = [m["code"] for m in required]
status_of = {c: measure_status(c) for c in req_codes}
na_codes = [c for c in req_codes if status_of[c] == NOT_APPLICABLE]
comp_codes = [c for c in req_codes if status_of[c] == COMPENSATED]
done_codes = [c for c in req_codes if status_of[c] == IMPLEMENTED]
missing_codes = [c for c in req_codes if status_of[c] == MISSING]
applicable = len(req_codes) - len(na_codes)
compliance = round(100 * (len(done_codes) + len(comp_codes)) / applicable, 1) if applicable else None
significant = cat.is_kii_subject and cat.category is not None
sec_done = [r for r in REQS if ss.get(f"sec_{r['id']}")]
sec_na = [r for r in REQS if ss.get(f"secna_{r['id']}")]
state_now = current_state()

# ---------------- боковая панель ----------------

with st.sidebar:
    st.markdown('<div class="brand"><div class="logo">🛡️</div><div><div class="name">Оценка соответствия '
                'значимого объекта КИИ</div><div class="docs">Категория — ПП РФ №&nbsp;127<br>Меры — приказ ФСТЭК '
                '№&nbsp;239<br>Система безопасности — №&nbsp;235</div></div></div>', unsafe_allow_html=True)
    st.date_input("Дата оценки", key="rules_date", format="DD.MM.YYYY",
                  min_value=date(2000, 1, 1), max_value=date(2100, 12, 31),
                  help="Оценка выполняется по редакциям документов, действующим на эту дату.")
    findings = get_findings(rules.on_date)
    with st.expander("База правил и редакции", icon=":material/library_books:"):
        show_flash("flash_rules")
        for kind, pkg in rules.packages.items():
            st.caption(f"**{KIND_TITLES[kind]}:** {pkg.title}, применяется с {pkg.effective_from:%d.%m.%Y}")
        others = [p for p in get_packages() if p.path not in {q.path for q in rules.packages.values()}]
        if others:
            st.caption("Другие редакции в базе: " + "; ".join(
                f"{p.passport['act']} ({p.passport['edition']}) — с {p.effective_from:%d.%m.%Y}" for p in others))
        st.caption(f"Проверка базы правил: ошибок {sum(f.level == ERROR for f in findings)}, "
                   f"замечаний к тексту документов {sum(f.level != ERROR for f in findings)}.")
        if findings:
            with st.popover("Замечания проверки", width="stretch"):
                st.caption("Дефекты текста документов, перенесённые в правила дословно. Сравнение с прежними "
                           "редакциями — вкладка 1, «Сравнение редакций».")
                for pkg_title in dict.fromkeys(f.package for f in findings):
                    st.markdown(f"**{pkg_title}**")
                    for f in (f for f in findings if f.package == pkg_title):
                        (st.error if f.level == ERROR else st.markdown)(f"- **{f.rule}**: {f.text}")
        st.file_uploader("Добавить редакцию (пакет правил .yaml)", type=["yaml", "yml"], key="pkg_file",
                         help="Пакет проверяется автоматически; пакет с ошибками не добавляется.")
        st.button("Проверить и добавить", on_click=add_package, width="stretch")
    st.divider()
    steps = [("Объект и сфера", bool(ss.object_name)),
             ("Показатели значимости", bool(raw_values) and validation.ok),
             ("Меры защиты", bool(done_codes or comp_codes or na_codes)),
             ("Система безопасности", bool(sec_done or sec_na)),
             ("Отчёт", "report" in ss)]
    # список шагов: выполненные — зелёной галочкой, первый невыполненный (следующий) подсвечен
    next_step = next((n for n, (_, ok) in enumerate(steps, 1) if not ok), None)
    rows = []
    for n, (title, ok) in enumerate(steps, 1):
        cls = "done" if ok else ("next" if n == next_step else "")
        rows.append(f'<div class="step {cls}"><span class="n">{"✓" if ok else n}</span>'
                    f'<span>{title}</span></div>')
    st.markdown(f'<div class="steps">{"".join(rows)}</div>', unsafe_allow_html=True)
    st.divider()
    st.caption(f"⏱ Время с начала оценки: {(time.time() - ss.started_at) / 60:.1f} мин".replace(".", ","))
    st.button("Начать новую оценку", on_click=reset_form, width="stretch", icon=":material/restart_alt:")
    st.toggle("Режим эксперимента", key="exp_mode",
              help="Для эксперимента ВКР: участник оценивает тестовый объект, время и результат "
                   "записываются в журнал и сравниваются с эталоном.")
    with st.expander("Как пользоваться"):
        st.markdown(
            "1. **Объект** — название, сфера, признаки ГИС/ИСПДн.\n"
            "2. **Показатели** — заполните применимые; под полем — справочные значения из ПП № 127.\n"
            "3. **Меры** — отметьте реализованные; в карточке меры — «не применяется», «компенсирована», "
            "чем реализована, плановый срок.\n"
            "4. **Система безопасности** — организационные требования приказа № 235.\n"
            "5. **Отчёт** — несоответствия, выгрузка отчёта и черновика акта в DOCX.")

# ---------------- шапка и сводка ----------------

_obj_title = escape(ss.object_name) if ss.object_name else "Объект не назван — начните с шага 1"
st.markdown(f'<div class="apptitle">Оценка соответствия значимого объекта КИИ</div>'
            f'<div class="appsub"><span>{_obj_title}</span>'
            f'{badge(cat.category) if cat.category else ""}</div>', unsafe_allow_html=True)
if ss.get("exp_mode") and ss.get("trial"):
    t = ss.trial
    st.markdown(f'<div class="exp">🧪 <b>Режим эксперимента.</b> Участник: {t["participant"]}, объект: '
                f'{t["object_id"]}, идёт {(time.time() - t["started"]) / 60:.1f} мин.</div>',
                unsafe_allow_html=True)

# Сводка — одна сетка карточек (на узком экране карточки переносятся, а не сжимаются)
if not cat.is_kii_subject:
    cat_sub = "сфера вне 187-ФЗ — не категорируется"
else:
    decisive = ", ".join(f"п. {r.indicator_id}" for r in cat.decisive)
    cat_sub = f"определяет показатель {decisive}" if decisive else "заполните показатели (шаг 2)"
closed_n = len(done_codes) + len(comp_codes)
ind_sub = (f'<span style="color:var(--c1)">ошибок ввода: {len(validation.errors)}</span>' if validation.errors
           else "заполнено из применимых" if raw_values else "пока не заполнены")
cards = [
    f'<div class="card cat{cat.category or 0}"><div class="label">Категория значимости</div>'
    f'<div class="value">{ROMAN.get(cat.category, "—")}</div><div class="sub">{cat_sub}</div></div>',
    f'<div class="card cat0"><div class="label">Показатели</div>'
    f'<div class="value">{len(raw_values)} / {len(INDICATORS)}</div><div class="sub">{ind_sub}</div></div>',
    f'<div class="card cat0"><div class="label">Меры базового набора</div>'
    f'<div class="value">{closed_n} / {applicable}</div>'
    f'<div class="sub">закрыто{f", не применяется: {len(na_codes)}" if na_codes else ""}</div>'
    f'<div class="mini"><span style="width:{100 * closed_n / applicable if applicable else 0:.0f}%"></span></div>'
    f'</div>',
    f'<div class="card acc"><div class="label">Соответствие</div><div class="value">'
    f'{pct_text(compliance) if req_codes else "—"}</div>'
    f'<div class="sub">{"несоответствий: " + str(len(missing_codes)) if req_codes else "появится после шага 2"}'
    f'</div></div>']
st.markdown(f'<div class="summary">{"".join(cards)}</div>', unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tab5 = st.tabs([f"{n}. {t}" for n, (t, _) in enumerate(steps, 1)])

# ================= Шаг 1. Объект =================

with tab1:
    show_flash()
    if ss.get("exp_mode"):
        with st.container(border=True):
            st.markdown("#### 🧪 Эксперимент «вручную vs система»")
            e1, e2, e3 = st.columns([2, 2, 1.4])
            e1.text_input("Участник (ФИО или код)", key="exp_participant")
            e2.selectbox("Тестовый объект", [o["id"] for o in OBJECTS], key="exp_object",
                         format_func=lambda i: f"{i}: " + next(o["name"] for o in OBJECTS if o["id"] == i))
            obj = next(o for o in OBJECTS if o["id"] == ss.exp_object)
            e3.download_button("Карточка объекта", card_docx(rules, obj, implemented_codes(rules, obj["implemented"])),
                               file_name=f"карточка_{obj['id']}.docx", width="stretch",
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               help="Исходные данные для участника (без правильных ответов)")
            st.button("▶ Начать оценку объекта через систему", on_click=start_trial, type="primary")
            if ss.get("trial_result"):
                tr = ss.trial_result
                st.success(f"Записано: {tr['minutes']} мин; категория {'верна' if tr['category_ok'] else 'НЕ верна'} "
                           f"(эталон: {tr['expected_category'] or 'без категории'}); несоответствия: "
                           f"найдено верно {tr['tp']}, лишних {tr['fp']}, пропущено {tr['fn']}.")
            with st.expander("Внести результат ручной оценки"):
                with st.form("manual_form", clear_on_submit=True):
                    f1, f2 = st.columns(2)
                    m_part = f1.text_input("Участник", key="man_part")
                    m_obj = f2.selectbox("Тестовый объект (ручная оценка)", [o["id"] for o in OBJECTS], key="man_obj")
                    f3, f4 = st.columns(2)
                    m_cat = f3.selectbox("Определённая категория", ["I", "II", "III", "Не присваивается"],
                                         key="man_cat")
                    m_min = f4.number_input("Затрачено, минут", min_value=0.0, step=1.0, key="man_min")
                    m_missing = st.text_area("Выявленные несоответствия (коды мер через пробел или запятую)",
                                             key="man_missing")
                    if st.form_submit_button("Сохранить результат"):
                        codes, unknown = extract_codes(rules, m_missing)
                        if not m_part.strip() or m_min <= 0:
                            st.error("Укажите участника и затраченное время.")
                        else:
                            row = trials.append(trials.MANUAL_LOG, m_part, m_obj, m_min,
                                                {"I": 1, "II": 2, "III": 3}.get(m_cat), codes)
                            st.success(f"Сохранено. Категория {'верна' if row['category_ok'] else 'НЕ верна'}; "
                                       f"верно {row['tp']}, лишних {row['fp']}, пропущено {row['fn']}."
                                       + (f" Не распознаны: {', '.join(unknown)}." if unknown else ""))
            st.caption(f"Записей в журналах: через систему — {len(trials.read(trials.SYSTEM_LOG))}, "
                       f"вручную — {len(trials.read(trials.MANUAL_LOG))}. Сводка: python experiment.py")

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Объект оценки")
        st.text_input("Наименование объекта КИИ", key="object_name",
                      placeholder="например, МИС областной клинической больницы")
        st.selectbox("Сфера деятельности субъекта КИИ (187-ФЗ, ст. 2, п. 8)", SPHERE_IDS,
                     format_func=lambda i: next(s["title"] for s in SPHERES if s["id"] == i), key="sphere")
        if ss.sphere == "other":
            st.warning("Сфера не входит в перечень ст. 2 п. 8 187-ФЗ — объект не подлежит категорированию.")
        a1, a2 = st.columns(2)
        a1.checkbox("Объект является ГИС", key="attr_gis",
                    help="Государственная информационная система (приказ ФСТЭК № 239, п. 24)")
        a2.checkbox("Объект является ИСПДн", key="attr_ispdn",
                    help="Информационная система персональных данных (приказ ФСТЭК № 239, п. 24)")
        if ss.get("attr_gis") or ss.get("attr_ispdn"):
            st.info("Меры принимаются в соответствии с более высокой категорией значимости, классом защищённости "
                    "или уровнем защищённости ПДн (приказ № 239, п. 24). Требования к ГИС и ИСПДн в базе "
                    "правил не учтены — их нужно проверить отдельно.")
    with right:
        with st.expander("Демонстрация: пример из тестового набора", icon=":material/school:"):
            st.caption("Заполняет все шаги данными тестового объекта — удобно для знакомства с программой.")
            st.selectbox("Объект", [o["id"] for o in OBJECTS], key="example_id",
                         format_func=lambda i: f"{i}: " + next(o["name"] for o in OBJECTS if o["id"] == i))
            st.button("Загрузить пример", on_click=load_example, type="primary", icon=":material/play_arrow:")
        st.subheader("Сохранение и загрузка")
        st.download_button("Сохранить оценку в файл", json.dumps(state_now, ensure_ascii=False, indent=2),
                           file_name=f"оценка_{datetime.now():%Y%m%d_%H%M}.json", mime="application/json",
                           width="stretch", icon=":material/save:")
        st.file_uploader("Продолжить сохранённую оценку (.json)", type=["json"], key="session_file",
                         on_change=load_session_file)
        with st.expander("Перечень объектов", icon=":material/folder_open:"):
            st.button("Сохранить текущую оценку в перечень", on_click=save_to_registry, width="stretch")
            saved = registry.list_all()
            if saved:
                st.dataframe(pd.DataFrame([{
                    "Объект": s["state"].get("object_name", ""),
                    "Категория": ROMAN.get(s["summary"].get("category"), "—"),
                    "Соответствие": pct_text(s["summary"].get("compliance")),
                    "Несоотв.": s["summary"].get("missing", 0),
                    "Сохранено": s.get("saved_at", "")[:16].replace("T", " ")} for s in saved]),
                    hide_index=True, width="stretch")
                st.selectbox("Оценка", [s["file"] for s in saved], key="reg_file",
                             format_func=lambda f: next(s["state"].get("object_name", f) for s in saved
                                                        if s["file"] == f))
                r1, r2 = st.columns(2)
                r1.button("Открыть", on_click=open_from_registry, width="stretch")
                confirm = r2.checkbox("подтверждаю удаление", key="reg_confirm")
                r2.button("Удалить", on_click=delete_from_registry, disabled=not confirm, width="stretch")
            else:
                st.caption("Перечень пока пуст: сохраните сюда текущую оценку кнопкой выше, чтобы вернуться "
                           "к ней позже (файлы хранятся в data/assessments/).")
    # Сравнение редакций — только если у какого-либо документа в базе больше одной редакции
    switch_dates = edition_dates(get_packages())
    current_from = max([d for d in switch_dates if d <= rules.on_date], default=None)
    other_dates = [d for d in switch_dates if d != current_from]
    if other_dates:
        with st.expander("Сравнение редакций и влияние на объекты", icon=":material/compare_arrows:"):
            render_comparison(other_dates)
    with st.expander("Проверка новой редакции документа (.docx)", icon=":material/find_in_page:"):
        render_text_check()
    hint("Далее — вкладка <b>«2. Показатели значимости»</b>: по ним определяется категория объекта."
         if ss.object_name else "Укажите наименование объекта и сферу деятельности, затем перейдите "
         "на вкладку <b>«2. Показатели значимости»</b>. Для знакомства загрузите пример (блок «Демонстрация»).")

# ================= Шаг 2. Показатели =================

with tab2:
    st.markdown("Заполните **только показатели, применимые к объекту**: пустое поле или «Неприменимо» — "
                "показатель не учитывается. Под числовым полем — пороги категорий из ПП № 127; диапазон, "
                "в который попало значение, выделяется. Итоговая категория — наивысшая из полученных "
                "(ПП № 127, Правила, п. 6).")
    for n_section, section in enumerate(dict.fromkeys(i["section"] for i in INDICATORS)):
        items = [i for i in INDICATORS if i["section"] == section]
        filled = sum(1 for i in items if i["id"] in raw_values)
        with st.expander(f"{section} · {plural(len(items), ('показатель', 'показателя', 'показателей'))}",
                         expanded=n_section == 0):
            st.caption(f"Заполнено {filled} из {len(items)}")
            # Условия применимости показателей этого раздела (признаки субъекта или объекта)
            cond_ids = list(dict.fromkeys(i["applies_if"] for i in items if i.get("applies_if")))
            if cond_ids:
                st.markdown("**Вид субъекта (объекта).** Отметьте, что относится к объекту, — откроются "
                            "показатели, которые применяются только при этом условии.")
            for cond_id in cond_ids:
                cond = rules.condition(cond_id)
                used = ", ".join(i["id"] for i in items if i.get("applies_if") == cond_id)
                st.checkbox(f"{cond['short']} (показатель {used})", key=f"attr_{cond_id}",
                            help=f"{cond['text']}.\n\nИсточник: {cond['source']}. Если условие не выполняется, "
                                 "показатель к объекту неприменим.")
            # Условный показатель без подтверждённого условия скрыт (если значение уже введено —
            # остаётся видимым, чтобы можно было исправить ошибку).
            hidden = [i["id"] for i in items if i.get("applies_if") and not attributes.get(i["applies_if"])
                      and ss.get(f"ind_{i['id']}") is None]
            if hidden:
                st.caption(f"Скрыто условных показателей: {len(hidden)} ({', '.join(hidden)}) — "
                           "условие выше не отмечено.")
            for ind in items:
                if ind["id"] in hidden:
                    continue
                key = f"ind_{ind['id']}"
                with st.container(border=True):
                    head, res = st.columns([4, 1.4])
                    head.markdown(f"**{ind['id']}. {ind['short']}**")
                    tip = f"{ind['title']}\n\nИсточник: {ind['source']}"
                    if ind["type"] == "number":
                        default = {} if key in ss else {"value": None}
                        head.number_input(f"Значение, {ind['unit']}", step=1.0, format="%g", key=key,
                                          help=tip, placeholder="не применимо", **default)
                    else:
                        head.radio("Значение", [None] + [o["id"] for o in ind["options"]], key=key, help=tip,
                                   format_func=lambda v, ind=ind: "Неприменимо" if v is None
                                   else next(o["text"] for o in ind["options"] if o["id"] == v))
                    value = ss.get(key)
                    errs, warns = check_value(ind, value) if value is not None else ([], [])
                    if value is not None and condition_error(rules, ind, attributes):
                        errs.append(condition_error(rules, ind, attributes))
                    hit = None
                    if value is not None and not errs:
                        hit = next((r.category for r in cat.details if r.indicator_id == ind["id"]), None)
                        res.markdown("<br>" + badge(hit, None if hit else "вне порогов категорий"),
                                     unsafe_allow_html=True)
                    if ind["type"] == "number":
                        cells = "".join(f'<div class="c{k}{" hit" if k == hit else ""}"><b>{ROMAN[k]} категория</b>'
                                        f'{t}</div>' for k, t in reference(ind))
                        st.markdown(f'<div class="ref">{cells}</div>', unsafe_allow_html=True)
                    for e in errs:
                        st.error(f"Ошибка ввода: {e}")
                    for w in warns:
                        st.warning(w)
                    if value is not None and not errs:
                        note = boundary_note(ind, value)
                        if note:
                            st.info(note)
    if validation.errors:
        hint("Исправьте ошибки ввода в показателях " + ", ".join(validation.errors) + " — пока они есть, "
             "отчёт не формируется.")
    elif significant:
        hint(f"Определена {ROMAN[cat.category]} категория значимости. Далее — вкладка "
             "<b>«3. Меры защиты»</b>: отметьте меры, которые уже реализованы.")
    elif cat.is_kii_subject:
        hint("Пока ни один показатель не даёт категорию. Если показатели заполнены верно, категория "
             "не присваивается — можно сразу перейти к вкладке <b>«5. Отчёт»</b>.")

# ================= Шаг 3. Меры =================

with tab3:
    if not significant:
        empty_state("Сначала нужна категория значимости",
                    "Меры защиты приказа ФСТЭК России № 239 обязательны только для значимых объектов, "
                    "а их состав зависит от категории. "
                    + ("Сфера деятельности не входит в 187-ФЗ — объект не категорируется (вкладка 1)."
                       if not cat.is_kii_subject else
                       "Заполните показатели на вкладке «2. Показатели значимости» — здесь появится "
                       "базовый набор мер для полученной категории."))
    else:
        st.markdown(f"Базовый набор мер для {badge(cat.category)} — **{plural(len(required), ('мера', 'меры', 'мер'))}** "
                    f"(приказ ФСТЭК России № 239, п. 23 и приложение). Отметьте галочкой реализованные меры; "
                    f"особые случаи — в карточке меры.", unsafe_allow_html=True)
        st.progress((len(done_codes) + len(comp_codes)) / applicable if applicable else 1.0,
                    text=f"Закрыто {len(done_codes) + len(comp_codes)} из {applicable} применимых мер"
                         + (f" (не применяются: {len(na_codes)})" if na_codes else ""))
        # Что изменилось в наборе этой категории по сравнению с предыдущей редакцией приказа № 239
        meas_pkg = rules.packages["measures"]
        prev_meas = previous_edition(get_packages(), meas_pkg)
        new_req, dropped = base_set_changes(prev_meas, meas_pkg, cat.category) if prev_meas else ([], [])
        if new_req or dropped:
            st.info(f"**Приказ № 239 {meas_pkg.passport['edition']}** по сравнению с предыдущей редакцией "
                    f"({prev_meas.passport['edition']}) для {ROMAN[cat.category]} категории: "
                    f"стали обязательными — {', '.join(new_req) or 'нет'}; перестали быть обязательными — "
                    f"{', '.join(dropped) or 'нет'}. Новые обязательные меры помечены в списке.")
        show_flash("flash_measures")
        f1, f2, f3 = st.columns([2, 1.2, 2])
        search = f1.text_input("Поиск меры", key="flt_search", placeholder="код или слово, например УПД или журнал")
        only_open = f2.toggle("Только нереализованные", key="flt_open")
        f3.file_uploader("Отметить меры из файла (TXT/CSV со списком кодов)", type=["txt", "csv"],
                         key="measures_file", on_change=load_measures_file)

        with st.expander("Карточка меры: адаптация, компенсирующие меры, сведения о реализации",
                         icon=":material/edit_note:"):
            st.caption("«Не применяется» — мера исключена из базового набора, т. к. связана с технологиями "
                       "или характеристиками, которых нет в объекте (п. 23, абз. 3). «Компенсирована» — вместо "
                       "меры применена компенсирующая мера (п. 26). Для обоих статусов нужно обоснование.")
            show_flash("flash_card")
            k1, k2 = st.columns([2, 2])
            k1.selectbox("Мера", req_codes, key="card_code", on_change=load_card, index=None,
                         placeholder="выберите меру",
                         format_func=lambda c: f"{c} — {rules.measure(c)['title']}")
            k2.radio("Статус", list(STATUS_LABELS), key="card_status", format_func=STATUS_LABELS.get)
            st.text_area("Обоснование / описание компенсирующей меры / чем реализована", key="card_text",
                         height=80)
            k3, k4 = st.columns([1, 2], vertical_alignment="bottom")
            k3.date_input("Плановый срок (для нереализованной)", key="card_due", format="DD.MM.YYYY",
                          **({} if "card_due" in ss else {"value": None}))
            k4.button("Сохранить сведения о мере", on_click=save_card, disabled=not ss.get("card_code"),
                      type="primary")
            special = [(c, STATUS_LABELS[status_of[c]], ss.mst[c]["text"]) for c in req_codes if c in ss.mst]
            special += [(c, "Сведения", (d.get("means") or "") + (f" срок: {d['due']}" if d.get("due") else ""))
                        for c, d in ss.mdet.items() if c in req_codes and c not in ss.mst]
            if special:
                st.dataframe(pd.DataFrame(special, columns=["Мера", "Статус", "Обоснование / сведения"]),
                             hide_index=True, width="stretch")

        q = search.strip().lower()
        chips = []
        for group in dict.fromkeys(m["group"] for m in required):
            codes = [m["code"] for m in required if m["group"] == group]
            appl = [c for c in codes if status_of[c] != NOT_APPLICABLE]
            closed = sum(1 for c in appl if status_of[c] in (IMPLEMENTED, COMPENSATED))
            cls = "full" if closed == len(appl) else ("part" if closed else "none")
            chips.append(f'<span class="chip {cls}" title="{group_title(rules, group)}">'
                         f'{group} {closed}/{len(appl)}</span>')
        st.markdown(f'<div class="chips">{"".join(chips)}</div><div class="legend">Группы мер: '
                    f'<span style="color:var(--ok)">●</span> все закрыты · <span style="color:var(--c2)">●</span> '
                    f'частично · <span style="color:var(--c1)">●</span> ни одной; число — закрыто / применимо. '
                    f'Наведите на группу, чтобы увидеть её название.</div>', unsafe_allow_html=True)
        shown_any = False
        for group in dict.fromkeys(m["group"] for m in required):
            gm = [m for m in required if m["group"] == group]
            codes = [m["code"] for m in gm]
            appl = [c for c in codes if status_of[c] != NOT_APPLICABLE]
            closed = sum(1 for c in appl if status_of[c] in (IMPLEMENTED, COMPENSATED))
            visible = [m for m in gm if (not q or q in m["code"].lower() or q in m["title"].lower())
                       and not (only_open and status_of[m["code"]] != MISSING)]
            if not visible:
                continue
            shown_any = True
            with st.expander(f"{group} · {group_title(rules, group)} · {plural(len(codes), ('мера', 'меры', 'мер'))}",
                             expanded=bool(q) or only_open):
                st.progress(closed / len(appl) if appl else 1.0, text=f"Закрыто {closed} из {len(appl)}")
                b1, b2, _ = st.columns([1, 1, 3])
                b1.button("Отметить все", key=f"all_{group}", on_click=set_group, args=(codes, True),
                          icon=":material/done_all:", width="stretch")
                b2.button("Снять все", key=f"none_{group}", on_click=set_group, args=(codes, False),
                          icon=":material/remove_done:", width="stretch")
                for m in visible:
                    c = m["code"]
                    tag = f" :blue-badge[обязательна с {meas_pkg.effective_from:%d.%m.%Y}]" if c in new_req else ""
                    st.checkbox(f"**{c}** — {m['title']}{tag}", key=f"m_{c}", on_change=on_measure_check, args=(c,),
                                help=m["source"] + (f"\n\n{m['note']}" if m.get("note") else ""))
                    if c in ss.mst:
                        icon = "⚪" if ss.mst[c]["status"] == NOT_APPLICABLE else "🔵"
                        st.markdown(f'<div class="mnote">{icon} {STATUS_LABELS[ss.mst[c]["status"]]}: '
                                    f'{ss.mst[c]["text"]}</div>', unsafe_allow_html=True)
                    elif ss.mdet.get(c, {}).get("due") and status_of[c] == MISSING:
                        st.markdown(f'<div class="mnote">🗓 плановый срок: {ss.mdet[c]["due"]}</div>',
                                    unsafe_allow_html=True)
        if not shown_any and only_open and not q:
            st.success("Все применимые меры базового набора закрыты.")
        elif not shown_any:
            st.info("По запросу «" + search.strip() + "» мер не найдено — проверьте код (например, УПД.3) "
                    "или очистите поле поиска.")
        hint("Далее — вкладка <b>«4. Система безопасности»</b>: организационные требования приказа № 235.")

# ================= Шаг 4. Система безопасности (приказ № 235) =================

with tab4:
    if not significant:
        empty_state("Сначала нужна категория значимости",
                    "Требования приказа ФСТЭК России № 235 к системе безопасности относятся к значимым "
                    "объектам. Определите категорию на вкладке «2. Показатели значимости».")
    else:
        sec_appl = len(REQS) - len(sec_na)
        st.markdown("Организационные требования к системе безопасности значимых объектов субъекта КИИ "
                    "(приказ ФСТЭК России № 235). Требования относятся к субъекту в целом (п. 3). "
                    "Отметьте выполненные; условные требования, не относящиеся к субъекту, отметьте "
                    "«не применимо».")
        st.progress(len(sec_done) / sec_appl if sec_appl else 1.0,
                    text=f"Выполнено {len(sec_done)} из {sec_appl} применимых требований")
        sec_pkg = rules.packages["security_system"]
        prev_sec = previous_edition(get_packages(), sec_pkg)
        req_changed = requirement_changes(prev_sec, sec_pkg) if prev_sec else {}
        if req_changed:
            added = [i for i, w in req_changed.items() if w == ADDED]
            st.info(f"**Приказ № 235 {sec_pkg.passport['edition']}** по сравнению с предыдущей редакцией "
                    f"({prev_sec.passport['edition']}): новые требования — {', '.join(added) or 'нет'}; "
                    f"изменены формулировки — {', '.join(i for i in req_changed if i not in added) or 'нет'}. "
                    "Они помечены в списке.")
        for section in dict.fromkeys(r["section"] for r in REQS):
            items = [r for r in REQS if r["section"] == section]
            with st.expander(f"{section} · {plural(len(items), ('требование', 'требования', 'требований'))}"):
                n_done = sum(1 for r in items if ss.get(f"sec_{r['id']}"))
                n_appl = len(items) - sum(1 for r in items if ss.get(f"secna_{r['id']}"))
                st.caption(f"Выполнено {n_done} из {n_appl}")
                for r in items:
                    what = req_changed.get(r["id"])
                    tag = (f" :blue-badge[{'новое' if what == ADDED else 'изменено'} с "
                           f"{sec_pkg.effective_from:%d.%m.%Y}]" if what else "")
                    st.checkbox(f"**{r['id']}** — {r['text']}{tag}", key=f"sec_{r['id']}", help=r["source"],
                                on_change=toggle_req, args=(r["id"], "done"))
                    if r.get("condition"):
                        st.checkbox(f"Не применимо (требование действует, только если {r['condition']})",
                                    key=f"secna_{r['id']}", on_change=toggle_req, args=(r["id"], "na"))
        hint("Далее — вкладка <b>«5. Отчёт»</b>: сформируйте отчёт о несоответствиях и выгрузите его в DOCX.")

# ================= Шаг 5. Отчёт =================

with tab5:
    if validation.errors:
        st.error("Исправьте ошибки ввода в показателях " + ", ".join(validation.errors) +
                 " (шаг «Показатели») — пока они есть, отчёт не формируется.")
    if st.button("Сформировать отчёт", type="primary", disabled=bool(validation.errors),
                 icon=":material/assignment:"):
        try:
            ss.report = assess(rules, ss.object_name or "Без названия", ss.sphere, values, state_now["implemented"],
                               statuses=state_now["statuses"], details=state_now["details"],
                               attributes=state_now["attributes"], security=state_now["security"])
        except InputError as e:
            st.error(str(e))
        else:
            ss.report_sig = json.dumps(state_now, sort_keys=True, ensure_ascii=False)
            ss.report_ctx = {"sphere": ss.sphere, "values": dict(values), "attributes": state_now["attributes"]}
            seconds = time.time() - ss.started_at
            if ss.get("exp_mode") and ss.get("trial"):  # режим эксперимента — запись в журнал
                t = ss.pop("trial")
                tr = ss.trial_result = trials.append(trials.SYSTEM_LOG, t["participant"], t["object_id"],
                                                     (time.time() - t["started"]) / 60,
                                                     ss.report.categorization.category, ss.report.missing_codes)
                st.success(f"🧪 Записано в журнал эксперимента: {tr['minutes']} мин; категория "
                           f"{'верна' if tr['category_ok'] else 'НЕ верна'}; несоответствия: найдено верно "
                           f"{tr['tp']}, лишних {tr['fp']}, пропущено {tr['fn']}.")
            elif not ss.saved:  # общий журнал времени оценок через интерфейс
                path = USER_DIR / "results" / "sessions.csv"
                path.parent.mkdir(parents=True, exist_ok=True)
                new = not path.exists()
                with open(path, "a", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    if new:
                        w.writerow(["datetime", "object", "category", "required", "missing", "seconds"])
                    w.writerow([datetime.now().isoformat(timespec="seconds"), ss.report.object_name,
                                ss.report.categorization.category, len(ss.report.required),
                                len(ss.report.missing), round(seconds, 1)])
                ss.saved = True
                st.toast(f"Время оценки {seconds / 60:.1f} мин записано в журнал".replace(".", ","))

    if "report" not in ss:
        # шаги 3–4 нужны только значимому объекту
        todo = [title for title, ok in steps[:4 if significant else 2] if not ok]
        empty_state("Отчёт ещё не сформирован",
                    "Нажмите «Сформировать отчёт» — система проверит введённые данные и покажет категорию "
                    "с обоснованием, несоответствия по мерам и требованиям, а также предложит выгрузку "
                    "в DOCX. Отчёт можно пересоздать в любой момент после изменений."
                    + (" Ещё не заполнены шаги:" if todo else ""), todo)

    if "report" in ss:
        r = ss.report
        rc = r.categorization
        ctx = ss.report_ctx
        if ss.report_sig != json.dumps(state_now, sort_keys=True, ensure_ascii=False):
            st.warning("Данные изменились после формирования отчёта — нажмите «Сформировать отчёт» ещё раз.")

        st.subheader(f"Отчёт: {r.object_name}")
        verdict = ("Объект не подлежит категорированию" if not rc.is_kii_subject
                   else "Категория значимости не присваивается" if rc.category is None
                   else f"Категория значимости: {ROMAN[rc.category]}")
        if not rc.is_kii_subject:
            v_sub = "Сфера деятельности не входит в перечень 187-ФЗ (ст. 2, п. 8)."
        elif rc.category is None:
            v_sub = "Ни один показатель не достиг порогов категорий ПП № 127."
        else:
            v_sub = (f"Определяет показатель {', '.join(x.indicator_id for x in rc.decisive)}; базовый набор — "
                     f"{plural(len(r.required), ('мера', 'меры', 'мер'))} приказа № 239.")
        st.markdown(f'<div class="verdict cat{rc.category or 0}"><div class="vl">Итог категорирования</div>'
                    f'<div class="vt">{verdict}</div><div class="vs">{v_sub}</div></div>', unsafe_allow_html=True)
        with st.expander("Обоснование категории", expanded=True):
            for line in rc.explanation:
                st.markdown(f"• {line}")
        for n in r.notices:
            st.info(n)

        if r.required:
            st.markdown("#### Меры защиты (приказ ФСТЭК № 239)")
            # метрики в строке с переносом: на узком экране не обрезаются
            with st.container(horizontal=True, wrap=True, key="metrics"):
                st.metric("Обязательных мер", len(r.required), width=150)
                st.metric("Не применяются", len(r.not_applicable), width=150)
                st.metric("Реализовано", r.covered_count - len(r.compensated), width=150,
                          help=f"Ещё компенсировано: {len(r.compensated)}" if r.compensated else None)
                st.metric("Несоответствий", len(r.missing), width=150)
                st.metric("Соответствие", pct_text(r.compliance_percent), width=150)

            # две диаграммы рядом; на узком экране вторая переносится под первую (CSS .st-key-charts)
            g1, g2 = st.container(key="charts").columns([1, 1.9], gap="large")
            counts = {"Реализовано": r.covered_count - len(r.compensated), "Компенсировано": len(r.compensated),
                      "Не реализовано": len(r.missing)}
            colors = {"Реализовано": COLORS["done"], "Компенсировано": COLORS["compensated"],
                      "Не реализовано": COLORS["missing"]}
            # в легенде только встречающиеся статусы, сразу с числом мер
            pie = pd.DataFrame([{"Статус": f"{k} — {v}", "Мер": v, "c": colors[k]} for k, v in counts.items() if v])
            base = alt.Chart(pie).encode(
                theta=alt.Theta("Мер:Q", stack=True),
                color=alt.Color("Статус:N", scale=alt.Scale(domain=list(pie["Статус"]), range=list(pie["c"])),
                                legend=alt.Legend(orient="bottom", direction="vertical", title=None,
                                                  labelFontSize=13, symbolType="circle")),
                tooltip=["Статус", "Мер"])
            center = alt.Chart(pd.DataFrame({"t": [pct_text(r.compliance_percent).replace(" ", "")]})).mark_text(
                fontSize=26, fontWeight="bold", color=COLORS["ink"]).encode(text="t:N")
            with g1:
                st.markdown("**Статус мер базового набора**")
                st.altair_chart((base.mark_arc(innerRadius=62, outerRadius=95, stroke="#fff", strokeWidth=2)
                                 + center).properties(height=280), width="stretch")
            with g2:
                st.markdown("**Несоответствия по группам мер**")
                if r.missing:
                    by_group = pd.DataFrame([{"Группа": f"{m['group']} · {group_title(rules, m['group'])}"}
                                             for m in r.missing]).value_counts().reset_index(name="Несоответствий")
                    # подписи чисел у столбцов вместо оси: читается сразу, без сетки
                    bar = alt.Chart(by_group).encode(
                        x=alt.X("Несоответствий:Q", axis=None,
                                scale=alt.Scale(domain=[0, int(by_group["Несоответствий"].max()) * 1.15])),
                        y=alt.Y("Группа:N", sort="-x", title=None,
                                axis=alt.Axis(labelLimit=340, labelFontSize=12, labelColor=COLORS["ink"],
                                              ticks=False, domain=False),
                                scale=alt.Scale(paddingInner=0.35)),
                        tooltip=["Группа", "Несоответствий"])
                    chart = (bar.mark_bar(color=COLORS["missing"], cornerRadiusEnd=4)
                             + bar.mark_text(align="left", dx=5, fontSize=12, fontWeight="bold",
                                             color=COLORS["ink"]).encode(text="Несоответствий:Q"))
                    st.altair_chart(chart.properties(height=alt.Step(30)).configure_view(stroke=None),
                                    width="stretch")
                else:
                    st.success("Все применимые меры базового набора закрыты — несоответствий не выявлено.")
            if r.missing:
                st.markdown(f"#### Перечень несоответствий · {len(r.missing)}")
                st.markdown(html_table([{"Мера": m["code"], "Содержание": m["title"],
                                         "Группа": group_title(rules, m["group"]),
                                         "Плановый срок": r.details.get(m["code"], {}).get("due") or "—"}
                                        for m in r.missing], scroll=True), unsafe_allow_html=True)
            for title, items in (("Исключены при адаптации базового набора (п. 23)", r.not_applicable),
                                 ("Компенсирующие меры (п. 26)", r.compensated)):
                if items:
                    st.markdown(f"#### {title}")
                    st.markdown(html_table([{"Мера": i["measure"]["code"], "Содержание": i["measure"]["title"],
                                             "Обоснование": i["text"]} for i in items]), unsafe_allow_html=True)
        else:
            st.info("Требования к значимым объектам не применяются: категория не присвоена.")

        if r.security:
            s = r.security
            st.markdown("#### Система безопасности (приказ ФСТЭК № 235)")
            st.progress(len(s.done) / s.applicable_count if s.applicable_count else 1.0,
                        text=f"Выполнено {len(s.done)} из {s.applicable_count} применимых требований")
            if not s.done and not s.not_applicable:
                st.info("Чек-лист требований приказа № 235 не заполнялся — отметьте выполненные требования "
                        "на вкладке «4. Система безопасности». Перечень всех требований — в отчёте DOCX.")
            elif s.missing:
                with st.expander(f"Невыполненные требования · {len(s.missing)}"):
                    st.markdown(html_table([{"Код": q["id"], "Требование": q["text"], "Источник": q["source"]}
                                            for q in s.missing], scroll=True), unsafe_allow_html=True)

        if r.warnings:
            with st.expander(f"Замечания к тексту нормативных документов ({len(r.warnings)})",
                             icon=":material/warning:"):
                for w in r.warnings:
                    st.markdown(f"• {w}")

        st.markdown("#### Выгрузка результатов")
        st.caption("DOCX открывается в Word. Файл данных (JSON) позволяет продолжить оценку позже — "
                   "вкладка 1, «Продолжить сохранённую оценку».")
        stamp = f"{datetime.now():%Y%m%d_%H%M}"
        docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        with st.container(horizontal=True, wrap=True, key="downloads"):
            st.download_button("Отчёт (DOCX)", to_docx(rules, r, ctx["sphere"], ctx["values"], ctx["attributes"]),
                               file_name=f"отчёт_{stamp}.docx", type="primary", mime=docx_mime,
                               icon=":material/description:")
            st.download_button("Черновик акта (DOCX)",
                               to_act_docx(rules, r, ctx["sphere"], ctx["values"], ctx["attributes"]),
                               file_name=f"акт_категорирования_{stamp}.docx", mime=docx_mime,
                               icon=":material/contract:",
                               help="Состав сведений — по п. 16 Правил категорирования (ПП РФ № 127)")
            st.download_button("Отчёт (Markdown)", to_markdown(rules, r), file_name=f"отчёт_{stamp}.md",
                               mime="text/markdown", icon=":material/article:")
            st.download_button("Данные оценки (JSON)", json.dumps(state_now, ensure_ascii=False, indent=2),
                               file_name=f"оценка_{stamp}.json", mime="application/json",
                               icon=":material/data_object:")
        st.caption("Документы базы правил: " + "; ".join(r.editions))
