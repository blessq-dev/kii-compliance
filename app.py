"""Интерфейс прототипа (Streamlit).

Запуск:  streamlit run app.py

Интерфейс только собирает ввод пользователя и показывает результат.
Вся логика оценки — в пакете engine/, все нормативные значения — в rules/*.yaml.
"""

import csv
import time
from datetime import datetime

import streamlit as st

from engine.assessment import assess, to_markdown
from engine.categorization import categorize
from engine.dataset import DATA_DIR, implemented_codes, load_objects
from engine.measures import group_title, required_measures
from engine.rules_loader import load_rules
from engine.validation import boundary_note, check_value, describe, reference

st.set_page_config(page_title="Оценка соответствия объекта КИИ", layout="wide")


@st.cache_resource
def get_rules():
    return load_rules()


rules = get_rules()
INDICATORS = rules.categorization["indicators"]
SPHERES = rules.spheres["spheres"] + [rules.spheres["other"]]
ss = st.session_state

# ---------- служебные функции состояния ----------

def reset_form():
    """Очищает все поля и перезапускает таймер оценки."""
    for key in list(ss.keys()):
        if key.startswith(("ind_", "m_")) or key in ("object_name", "sphere", "report_md"):
            del ss[key]
    ss.started_at = time.time()
    ss.saved = False


def load_example():
    """Заполняет форму объектом из тестового набора (для демонстрации)."""
    obj = next(o for o in load_objects() if o["id"] == ss.example_id)
    reset_form()
    ss.object_name = obj["name"]
    ss.sphere = obj["sphere"]
    for ind_id, value in (obj.get("indicators") or {}).items():
        # числовые поля формы работают с float
        ss[f"ind_{ind_id}"] = float(value) if rules.indicator(ind_id)["type"] == "number" else value
    for code in implemented_codes(rules, obj["implemented"]):
        ss[f"m_{code}"] = True


def set_group(codes: list[str], value: bool):
    for code in codes:
        ss[f"m_{code}"] = value


if "started_at" not in ss:
    reset_form()

# ---------- боковая панель ----------

with st.sidebar:
    st.header("Объект оценки")
    st.text_input("Наименование объекта", key="object_name")
    st.selectbox("Сфера деятельности (187-ФЗ, ст. 2, п. 8)",
                 [s["id"] for s in SPHERES],
                 format_func=lambda i: next(s["title"] for s in SPHERES if s["id"] == i),
                 key="sphere")
    st.divider()
    st.button("Новая оценка (сбросить)", on_click=reset_form)
    st.subheader("Демонстрация")
    st.selectbox("Объект из тестового набора", [o["id"] for o in load_objects()],
                 format_func=lambda i: f"{i}: " + next(o["name"] for o in load_objects() if o["id"] == i),
                 key="example_id")
    st.button("Загрузить пример", on_click=load_example)
    st.caption(f"Время с начала оценки: {(time.time() - ss.started_at) / 60:.1f} мин")

st.title("Оценка соответствия значимого объекта КИИ требованиям безопасности")

# ---------- шаг 1: показатели значимости ----------

st.header("1. Показатели критериев значимости (ПП РФ № 127)")
st.caption("Пустое поле или «Неприменимо» — показатель не применим к объекту.")

values = {}        # корректные значения — идут в категорирование
input_errors = {}  # {номер показателя: [ошибки]} — блокируют отчёт
for section in dict.fromkeys(i["section"] for i in INDICATORS):
    entered = sum(1 for i in INDICATORS if i["section"] == section and ss.get(f"ind_{i['id']}") is not None)
    with st.expander(f"{section}  (заполнено: {entered})", expanded=False):
        for ind in (i for i in INDICATORS if i["section"] == section):
            key = f"ind_{ind['id']}"
            label = f"{ind['id']}. {ind['title']}"
            if ind["type"] == "number":
                # value=None (пустое поле) задаём только при первом показе, иначе значение берётся из состояния
                default = {} if key in ss else {"value": None}
                st.number_input(f"{label} ({ind['unit']})", step=1.0,
                                format="%g", key=key, help=ind["source"], **default)
                # справочные значения дословно из Перечня ПП № 127
                st.caption("Справочно (" + ind["source"] + "): " + "; ".join(
                    f"**{k} кат.** — {t}" for k, t in reference(ind)) +
                    ". Ниже значений III категории — категория по показателю не присваивается.")
            else:
                st.selectbox(label, [None] + [o["id"] for o in ind["options"]],
                             format_func=lambda v, ind=ind: "Неприменимо" if v is None
                             else next(o["text"] for o in ind["options"] if o["id"] == v),
                             key=key, help=ind["source"])
            value = ss.get(key)
            if value is None:
                st.divider()
                continue
            errs, warns = check_value(ind, value)
            for e in errs:
                st.error(f"Ошибка ввода: {e}")
            for w in warns:
                st.warning(w)
            if errs:
                input_errors[ind["id"]] = errs
            else:
                values[ind["id"]] = value
                st.markdown(describe(ind, value))
                note = boundary_note(ind, value)
                if note:
                    st.info(note)
            st.divider()

# ---------- шаг 2: категория ----------

st.header("2. Категория значимости")
if input_errors:
    st.error("Исправьте ошибки ввода в показателях " + ", ".join(input_errors) +
             " — пока они не исправлены, эти показатели не учитываются, а отчёт не формируется.")
cat = categorize(rules, ss.sphere, values)
if not cat.is_kii_subject:
    st.warning("Объект не подлежит категорированию.")
elif cat.category is None:
    st.info("Категория значимости не присваивается.")
else:
    st.success(f"Категория значимости: **{cat.category}**")
for line in cat.explanation:
    st.write("•", line)
for w in cat.warnings:
    st.warning(w)

# ---------- шаг 3: реализованные меры ----------

required = required_measures(rules, cat.category)
st.header("3. Реализованные меры (приказ ФСТЭК № 239)")
if not required:
    st.write("Требования к значимым объектам не применяются: категория не присвоена.")
else:
    st.caption(f"Базовый набор для категории {cat.category}: {len(required)} мер. "
               "Отметьте меры, реализованные на объекте.")
    for group in dict.fromkeys(m["group"] for m in required):
        group_measures = [m for m in required if m["group"] == group]
        codes = [m["code"] for m in group_measures]
        done = sum(1 for c in codes if ss.get(f"m_{c}"))
        with st.expander(f"{group} — {group_title(rules, group)}  ({done}/{len(codes)})"):
            c1, c2 = st.columns(2)
            c1.button("Отметить все", key=f"all_{group}", on_click=set_group, args=(codes, True))
            c2.button("Снять все", key=f"none_{group}", on_click=set_group, args=(codes, False))
            for m in group_measures:
                st.checkbox(f"**{m['code']}** {m['title']}", key=f"m_{m['code']}",
                            help=m["source"] + (f"\n\n{m['note']}" if m.get("note") else ""))

# ---------- шаг 4: отчёт ----------

st.header("4. Отчёт о несоответствиях")
implemented = [m["code"] for m in rules.measures["measures"] if ss.get(f"m_{m['code']}")]
name = ss.object_name or "Без названия"

if st.button("Сформировать отчёт", type="primary", disabled=bool(input_errors)):
    report = assess(rules, name, ss.sphere, values, implemented)
    seconds = time.time() - ss.started_at
    ss.report_md = to_markdown(rules, report)

    if report.required:
        col1, col2, col3 = st.columns(3)
        col1.metric("Обязательных мер", len(report.required))
        col2.metric("Несоответствий", len(report.missing))
        col3.metric("Соответствие", f"{report.compliance_percent}%")

    # Журнал сессий — для метрики «время оценки через систему».
    if not ss.saved:
        path = DATA_DIR / "results" / "sessions.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["datetime", "object", "category", "required", "missing", "seconds"])
            w.writerow([datetime.now().isoformat(timespec="seconds"), name, report.categorization.category,
                        len(report.required), len(report.missing), round(seconds, 1)])
        ss.saved = True
        st.caption(f"Время оценки ({seconds / 60:.1f} мин) записано в data/results/sessions.csv")

if "report_md" in ss:
    st.markdown(ss.report_md)
    st.download_button("Скачать отчёт (.md)", ss.report_md,
                       file_name=f"report_{datetime.now():%Y%m%d_%H%M}.md", mime="text/markdown")
