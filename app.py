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
import json
import time
from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st

from engine import registry, trials
from engine.assessment import COMPENSATED, NOT_APPLICABLE, assess, to_markdown
from engine.categorization import categorize
from engine.dataset import DATA_DIR, implemented_codes, load_objects
from engine.measures import extract_codes, group_title, required_measures
from engine.report_docx import card_docx, to_act_docx, to_docx
from engine.rules_loader import load_rules
from engine.validation import InputError, boundary_note, check_value, reference, validate

st.set_page_config(page_title="Оценка соответствия объекта КИИ", page_icon="🛡️", layout="wide")

ROMAN = {1: "I", 2: "II", 3: "III"}
IMPLEMENTED, MISSING = "implemented", "missing"
STATUS_LABELS = {IMPLEMENTED: "Реализована", MISSING: "Не реализована",
                 NOT_APPLICABLE: "Не применяется (адаптация, п. 23)", COMPENSATED: "Компенсирована (п. 26)"}
# цвета категорий: I — красный (самая высокая), II — оранжевый, III — жёлтый
CSS = """
<style>
.block-container {padding-top: 2rem; max-width: 1200px;}
.badge {display:inline-block; padding:.2rem .75rem; border-radius:999px; font-weight:600; font-size:.9rem;}
.cat1 {background:#fde2e1; color:#9b1c1c;} .cat2 {background:#ffe8cc; color:#8a4b0f;}
.cat3 {background:#fff4c2; color:#6b5600;} .cat0 {background:#eceff3; color:#4b5563;}
.card {border-radius:.9rem; padding:1rem 1.2rem; height:100%;}
.card .label {font-size:.8rem; opacity:.75; margin-bottom:.2rem;}
.card .value {font-size:1.6rem; font-weight:700; line-height:1.2;}
.card .sub {font-size:.8rem; opacity:.8; margin-top:.3rem;}
.ref {display:flex; gap:.4rem; margin:.3rem 0 .2rem;}
.ref div {flex:1; border-radius:.55rem; padding:.4rem .55rem; font-size:.78rem; line-height:1.25;
          border:2px solid transparent; opacity:.5; color:#1f2328;}
.ref div b {display:block; font-size:.72rem; letter-spacing:.03em; margin-bottom:.1rem;}
.ref div.hit {opacity:1; border-color:#1f2328;}
.ref .c3 {background:#fff4c2;} .ref .c2 {background:#ffe8cc;} .ref .c1 {background:#fde2e1;}
.chips {display:flex; flex-wrap:wrap; gap:.35rem; margin:.2rem 0 .8rem;}
.chip {padding:.15rem .55rem; border-radius:999px; font-size:.8rem; font-weight:600;}
.chip.full {background:#dcf2e3; color:#1e6b3a;} .chip.part {background:#ffe8cc; color:#8a4b0f;}
.chip.none {background:#fde2e1; color:#9b1c1c;}
.mnote {font-size:.8rem; margin:-.4rem 0 .4rem 1.9rem; opacity:.85;}
.apptitle {font-size:1.9rem; font-weight:700; line-height:1.2;}
.appsub {font-size:.95rem; opacity:.65; margin:.2rem 0 1rem;}
.exp {border:2px dashed #1f5fa8; border-radius:.8rem; padding:.6rem 1rem; margin-bottom:1rem; background:#eef4fb;}
/* русские надписи у загрузки файла вместо встроенных английских */
[data-testid="stFileUploaderDropzone"] button > * {display:none !important;}
[data-testid="stFileUploaderDropzone"] button::after {content:"📂 Выбрать файл"; font-size:.9rem;}
[data-testid="stFileUploaderDropzoneInstructions"] small {display:none;}
[data-testid="stFileUploaderDropzoneInstructions"] span {font-size:0;}
[data-testid="stFileUploaderDropzoneInstructions"] span::after {content:"Перетащите файл сюда"; font-size:.9rem;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


@st.cache_resource
def get_rules():
    return load_rules()


rules = get_rules()
INDICATORS = rules.categorization["indicators"]
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
            "implemented": implemented_codes(rules, obj["implemented"])}


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


def current_state() -> dict:
    """Текущие данные формы — для сохранения в файл, перечня объектов и сверки с отчётом."""
    return {"object_name": ss.object_name, "sphere": ss.sphere,
            "indicators": {i["id"]: ss[f"ind_{i['id']}"] for i in INDICATORS
                           if ss.get(f"ind_{i['id']}") is not None},
            "implemented": [c for c in ALL_CODES if ss.get(f"m_{c}")],
            "statuses": dict(ss.mst), "details": {c: d for c, d in ss.mdet.items() if d.get("means") or d.get("due")},
            "attributes": {"is_gis": bool(ss.get("attr_gis")), "is_ispdn": bool(ss.get("attr_ispdn"))},
            "security": {"done": [r["id"] for r in REQS if ss.get(f"sec_{r['id']}")],
                         "not_applicable": [r["id"] for r in REQS if ss.get(f"secna_{r['id']}")]}}


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


if "started_at" not in ss:
    reset_form()
ss.setdefault("mst", {})
ss.setdefault("mdet", {})

# ---------------- расчёт по текущим данным (до отрисовки) ----------------

raw_values = {i["id"]: ss[f"ind_{i['id']}"] for i in INDICATORS if ss.get(f"ind_{i['id']}") is not None}
validation = validate(rules, raw_values)
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
    st.markdown("### 🛡️ Оценка соответствия\nзначимого объекта КИИ")
    st.caption("Категорирование по ПП РФ № 127, меры по приказу ФСТЭК России № 239, "
               "система безопасности по приказу № 235.")
    st.divider()
    steps = [("Объект и сфера", bool(ss.object_name)),
             ("Показатели значимости", bool(raw_values) and validation.ok),
             ("Меры защиты", bool(done_codes or comp_codes or na_codes)),
             ("Система безопасности", bool(sec_done or sec_na)),
             ("Отчёт", "report" in ss)]
    for n, (title, ok) in enumerate(steps, 1):
        st.markdown(f"{'✅' if ok else '○'} **{n}.** {title}")
    st.divider()
    st.caption(f"⏱ Время с начала оценки: {(time.time() - ss.started_at) / 60:.1f} мин")
    st.button("Начать новую оценку", on_click=reset_form, width="stretch")
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

st.markdown(f'<div class="apptitle">Оценка соответствия значимого объекта КИИ</div>'
            f'<div class="appsub">{ss.object_name or "Объект не назван"}</div>', unsafe_allow_html=True)
if ss.get("exp_mode") and ss.get("trial"):
    t = ss.trial
    st.markdown(f'<div class="exp">🧪 <b>Режим эксперимента.</b> Участник: {t["participant"]}, объект: '
                f'{t["object_id"]}, идёт {(time.time() - t["started"]) / 60:.1f} мин.</div>',
                unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
if not cat.is_kii_subject:
    cat_sub = "сфера вне 187-ФЗ"
else:
    decisive = ", ".join(f"п. {r.indicator_id}" for r in cat.decisive)
    cat_sub = f"определяет: {decisive}" if decisive else "показатели не дают категорию"
c1.markdown(f'<div class="card cat{cat.category or 0}"><div class="label">Категория значимости</div>'
            f'<div class="value">{ROMAN.get(cat.category, "—")}</div><div class="sub">{cat_sub}</div></div>',
            unsafe_allow_html=True)
c2.markdown(f'<div class="card cat0"><div class="label">Показатели</div>'
            f'<div class="value">{len(raw_values)} / {len(INDICATORS)}</div>'
            f'<div class="sub">{"ошибок ввода: " + str(len(validation.errors)) if validation.errors else "заполнено"}'
            f'</div></div>', unsafe_allow_html=True)
c3.markdown(f'<div class="card cat0"><div class="label">Меры базового набора</div>'
            f'<div class="value">{len(done_codes) + len(comp_codes)} / {applicable}</div>'
            f'<div class="sub">закрыто{f", не применяется: {len(na_codes)}" if na_codes else ""}</div></div>',
            unsafe_allow_html=True)
c4.markdown(f'<div class="card cat0"><div class="label">Соответствие</div><div class="value">'
            f'{pct_text(compliance) if req_codes else "—"}</div>'
            f'<div class="sub">несоответствий: {len(missing_codes)}</div></div>', unsafe_allow_html=True)
st.write("")

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
        st.subheader("Сохранение и загрузка")
        st.download_button("💾 Сохранить оценку в файл", json.dumps(state_now, ensure_ascii=False, indent=2),
                           file_name=f"оценка_{datetime.now():%Y%m%d_%H%M}.json", mime="application/json",
                           width="stretch")
        st.file_uploader("Продолжить сохранённую оценку (.json)", type=["json"], key="session_file",
                         on_change=load_session_file)
        with st.expander("📁 Перечень объектов"):
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
                st.caption("Перечень пуст. Сохранённые оценки хранятся в data/assessments/.")
        with st.expander("🎓 Демонстрация: пример из тестового набора"):
            st.selectbox("Объект", [o["id"] for o in OBJECTS], key="example_id",
                         format_func=lambda i: f"{i}: " + next(o["name"] for o in OBJECTS if o["id"] == i))
            st.button("Загрузить пример", on_click=load_example)

# ================= Шаг 2. Показатели =================

with tab2:
    st.caption("Заполните только показатели, применимые к объекту; пустое поле или «Неприменимо» — показатель "
               "не учитывается. Итоговая категория — наивысшая из полученных (ПП № 127, Правила, п. 6).")
    for n_section, section in enumerate(dict.fromkeys(i["section"] for i in INDICATORS)):
        items = [i for i in INDICATORS if i["section"] == section]
        filled = sum(1 for i in items if i["id"] in raw_values)
        with st.expander(f"{section} ({len(items)} показ.)", expanded=n_section == 0):
            st.caption(f"Заполнено {filled} из {len(items)}")
            for ind in items:
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
                    hit = None
                    if value is not None and not errs:
                        hit = next((r.category for r in cat.details if r.indicator_id == ind["id"]), None)
                        res.markdown("<br>" + badge(hit, None if hit else "не соответствует"),
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

# ================= Шаг 3. Меры =================

with tab3:
    if not significant:
        st.info("Требования приказа ФСТЭК № 239 применяются к значимым объектам. "
                "Сначала определите категорию на шаге «Показатели».")
    else:
        st.markdown(f"Базовый набор мер для {badge(cat.category)} — **{len(required)}** мер "
                    f"(приказ ФСТЭК России № 239, п. 23 и приложение).", unsafe_allow_html=True)
        st.progress((len(done_codes) + len(comp_codes)) / applicable if applicable else 1.0,
                    text=f"Закрыто {len(done_codes) + len(comp_codes)} из {applicable} применимых мер"
                         + (f" (не применяются: {len(na_codes)})" if na_codes else ""))
        show_flash("flash_measures")
        f1, f2, f3 = st.columns([2, 1.2, 2])
        search = f1.text_input("Поиск меры", key="flt_search", placeholder="код или слово, например УПД или журнал")
        only_open = f2.toggle("Только нереализованные", key="flt_open")
        f3.file_uploader("Отметить меры из файла (TXT/CSV со списком кодов)", type=["txt", "csv"],
                         key="measures_file", on_change=load_measures_file)

        with st.expander("🗂 Карточка меры: адаптация, компенсирующие меры, сведения о реализации"):
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
            k3, k4 = st.columns([1, 2])
            k3.date_input("Плановый срок (для нереализованной)", key="card_due", format="DD.MM.YYYY",
                          **({} if "card_due" in ss else {"value": None}))
            k4.write("")
            k4.button("Сохранить сведения о мере", on_click=save_card, disabled=not ss.get("card_code"))
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
        st.markdown(f'<div class="chips">{"".join(chips)}</div>', unsafe_allow_html=True)
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
            with st.expander(f"{group} · {group_title(rules, group)} ({len(codes)} мер)",
                             expanded=bool(q) or only_open):
                st.progress(closed / len(appl) if appl else 1.0, text=f"Закрыто {closed} из {len(appl)}")
                b1, b2, _ = st.columns([1, 1, 3])
                b1.button("Отметить все", key=f"all_{group}", on_click=set_group, args=(codes, True))
                b2.button("Снять все", key=f"none_{group}", on_click=set_group, args=(codes, False))
                for m in visible:
                    c = m["code"]
                    st.checkbox(f"**{c}** — {m['title']}", key=f"m_{c}", on_change=on_measure_check, args=(c,),
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
            st.info("Ничего не найдено.")

# ================= Шаг 4. Система безопасности (приказ № 235) =================

with tab4:
    if not significant:
        st.info("Требования приказа ФСТЭК № 235 к системе безопасности относятся к значимым объектам. "
                "Сначала определите категорию на шаге «Показатели».")
    else:
        sec_appl = len(REQS) - len(sec_na)
        st.markdown("Организационные требования к системе безопасности значимых объектов субъекта КИИ "
                    "(приказ ФСТЭК России № 235). Требования относятся к субъекту в целом (п. 3).")
        st.progress(len(sec_done) / sec_appl if sec_appl else 1.0,
                    text=f"Выполнено {len(sec_done)} из {sec_appl} применимых требований")
        for section in dict.fromkeys(r["section"] for r in REQS):
            items = [r for r in REQS if r["section"] == section]
            with st.expander(f"{section} ({len(items)} треб.)"):
                for r in items:
                    st.checkbox(f"**{r['id']}** — {r['text']}", key=f"sec_{r['id']}", help=r["source"],
                                on_change=toggle_req, args=(r["id"], "done"))
                    if r.get("condition"):
                        st.checkbox(f"Не применимо (требование действует, только если {r['condition']})",
                                    key=f"secna_{r['id']}", on_change=toggle_req, args=(r["id"], "na"))

# ================= Шаг 5. Отчёт =================

with tab5:
    if validation.errors:
        st.error("Исправьте ошибки ввода в показателях " + ", ".join(validation.errors) +
                 " (шаг «Показатели») — пока они есть, отчёт не формируется.")
    if st.button("Сформировать отчёт", type="primary", disabled=bool(validation.errors)):
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
                path = DATA_DIR / "results" / "sessions.csv"
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
                st.toast(f"Время оценки {seconds / 60:.1f} мин записано в журнал")

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
        st.markdown(f"### {badge(rc.category, verdict)}", unsafe_allow_html=True)
        with st.expander("Обоснование категории", expanded=True):
            for line in rc.explanation:
                st.markdown(f"• {line}")
        for n in r.notices:
            st.info(n)

        if r.required:
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Обязательных мер", len(r.required))
            m2.metric("Не применяются", len(r.not_applicable))
            m3.metric("Реализовано", r.covered_count - len(r.compensated),
                      help=f"Ещё компенсировано: {len(r.compensated)}" if r.compensated else None)
            m4.metric("Несоответствий", len(r.missing))
            m5.metric("Соответствие", f"{r.compliance_percent}%".replace(".", ","))

            g1, g2 = st.columns([1, 2], gap="large")
            pie = pd.DataFrame({"Статус": ["Реализовано", "Компенсировано", "Не реализовано"],
                                "Мер": [r.covered_count - len(r.compensated), len(r.compensated), len(r.missing)]})
            colors = {"Реализовано": "#2e9e5b", "Компенсировано": "#3b7dd8", "Не реализовано": "#d64545"}
            pie = pie[pie["Мер"] > 0]  # в легенде только встречающиеся статусы
            base = alt.Chart(pie).encode(
                theta=alt.Theta("Мер:Q", stack=True),
                color=alt.Color("Статус:N", scale=alt.Scale(domain=list(pie["Статус"]),
                                                            range=[colors[s] for s in pie["Статус"]]),
                                legend=alt.Legend(orient="bottom", direction="vertical", title=None)),
                tooltip=["Статус", "Мер"])
            center = alt.Chart(pd.DataFrame({"t": [pct_text(r.compliance_percent).replace(" ", "")]})).mark_text(
                fontSize=26, fontWeight="bold", color="#1f2328").encode(text="t:N")
            g1.altair_chart((base.mark_arc(innerRadius=62, outerRadius=95) + center).properties(height=260),
                            width="stretch")
            if r.missing:
                by_group = pd.DataFrame([{"Группа": f"{m['group']} · {group_title(rules, m['group'])}"}
                                         for m in r.missing]).value_counts().reset_index(name="Несоответствий")
                bars = alt.Chart(by_group).mark_bar(color="#d64545", cornerRadiusEnd=4).encode(
                    x=alt.X("Несоответствий:Q", axis=alt.Axis(tickMinStep=1, format="d")),
                    y=alt.Y("Группа:N", sort="-x", title=None, axis=alt.Axis(labelLimit=380),
                            scale=alt.Scale(paddingInner=0.45)),
                    tooltip=["Группа", "Несоответствий"]).properties(
                    title="Несоответствия по группам мер", height=alt.Step(34))
                g2.altair_chart(bars, width="stretch")
                st.markdown("#### Перечень несоответствий")
                st.dataframe(pd.DataFrame([{"Мера": m["code"], "Содержание": m["title"],
                                            "Группа": group_title(rules, m["group"]),
                                            "Плановый срок": r.details.get(m["code"], {}).get("due") or ""}
                                           for m in r.missing]), hide_index=True, width="stretch")
            else:
                g2.success("Все применимые меры базового набора закрыты — несоответствий не выявлено.")
            for title, items in (("Исключены при адаптации базового набора (п. 23)", r.not_applicable),
                                 ("Компенсирующие меры (п. 26)", r.compensated)):
                if items:
                    st.markdown(f"#### {title}")
                    st.dataframe(pd.DataFrame([{"Мера": i["measure"]["code"], "Содержание": i["measure"]["title"],
                                                "Обоснование": i["text"]} for i in items]),
                                 hide_index=True, width="stretch")
        else:
            st.info("Требования к значимым объектам не применяются: категория не присвоена.")

        if r.security:
            s = r.security
            st.markdown("#### Система безопасности (приказ ФСТЭК № 235)")
            st.progress(len(s.done) / s.applicable_count if s.applicable_count else 1.0,
                        text=f"Выполнено {len(s.done)} из {s.applicable_count} применимых требований")
            if s.missing:
                st.dataframe(pd.DataFrame([{"Код": q["id"], "Невыполненное требование": q["text"],
                                            "Источник": q["source"]} for q in s.missing]),
                             hide_index=True, width="stretch")

        if r.warnings:
            with st.expander(f"⚠️ Замечания к тексту нормативных документов ({len(r.warnings)})"):
                for w in r.warnings:
                    st.markdown(f"• {w}")
        st.caption("Документы базы правил: " + "; ".join(r.editions))

        d1, d2, d3, d4 = st.columns(4)
        stamp = f"{datetime.now():%Y%m%d_%H%M}"
        docx_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        d1.download_button("📄 Отчёт (DOCX)", to_docx(rules, r, ctx["sphere"], ctx["values"], ctx["attributes"]),
                           file_name=f"отчёт_{stamp}.docx", type="primary", width="stretch", mime=docx_mime)
        d2.download_button("📝 Черновик акта (DOCX)",
                           to_act_docx(rules, r, ctx["sphere"], ctx["values"], ctx["attributes"]),
                           file_name=f"акт_категорирования_{stamp}.docx", width="stretch", mime=docx_mime,
                           help="Состав сведений — по п. 16 Правил категорирования (ПП РФ № 127)")
        d3.download_button("Отчёт (Markdown)", to_markdown(rules, r), file_name=f"отчёт_{stamp}.md",
                           mime="text/markdown", width="stretch")
        d4.download_button("Данные оценки (JSON)", json.dumps(state_now, ensure_ascii=False, indent=2),
                           file_name=f"оценка_{stamp}.json", mime="application/json", width="stretch")
