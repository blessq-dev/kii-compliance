"""Интерфейс прототипа (Streamlit).

Запуск:  streamlit run app.py   (или двойной щелчок по run.bat)

Интерфейс только собирает ввод пользователя и показывает результат.
Вся логика оценки — в пакете engine/, все нормативные значения — в rules/*.yaml.

Шаги оценки оформлены вкладками: Streamlit отрисовывает все вкладки при каждом
обновлении страницы, поэтому введённые значения не теряются при переходе между шагами.
"""

import csv
import json
import time
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

from engine.assessment import assess, to_markdown
from engine.categorization import categorize
from engine.dataset import DATA_DIR, implemented_codes, load_objects
from engine.measures import extract_codes, group_title, required_measures
from engine.report_docx import to_docx
from engine.rules_loader import load_rules
from engine.validation import boundary_note, check_value, reference, validate

st.set_page_config(page_title="Оценка соответствия объекта КИИ", page_icon="🛡️", layout="wide")

ROMAN = {1: "I", 2: "II", 3: "III"}
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
.apptitle {font-size:1.9rem; font-weight:700; line-height:1.2;}
.appsub {font-size:.95rem; opacity:.65; margin:.2rem 0 1rem;}
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
ss = st.session_state

# Сохраняем значения полей между обновлениями, даже если поле сейчас скрыто фильтром.
for _k in list(ss.keys()):
    if _k.startswith(("ind_", "m_")) or _k in ("object_name", "sphere"):
        ss[_k] = ss[_k]


# ---------------- служебные функции ----------------

def badge(category, text=None) -> str:
    cls = f"cat{category or 0}"
    if text is None:
        text = f"{ROMAN[category]} категория" if category else "без категории"
    return f'<span class="badge {cls}">{text}</span>'


def fmt_num(x) -> str:
    return f"{x:g}".replace(".", ",")


def reset_form():
    """Очищает все поля и перезапускает таймер оценки."""
    for key in list(ss.keys()):
        if key.startswith(("ind_", "m_", "flt_")) or key in ("object_name", "sphere", "report", "report_sig", "report_values"):
            del ss[key]
    ss.object_name = ""
    ss.sphere = SPHERE_IDS[0]
    ss.started_at = time.time()
    ss.saved = False


def apply_state(data: dict) -> list[str]:
    """Заполняет форму из словаря (пример из тестового набора или сохранённый файл).
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
    return notes


def load_example():
    obj = next(o for o in load_objects() if o["id"] == ss.example_id)
    apply_state({"object_name": obj["name"], "sphere": obj["sphere"],
                 "indicators": obj.get("indicators") or {},
                 "implemented": implemented_codes(rules, obj["implemented"])})
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
    msg = f"Из файла отмечено мер: {len(found)}."
    if unknown:
        msg += f" Не распознаны коды: {', '.join(unknown[:10])}{' …' if len(unknown) > 10 else ''}."
    ss.flash_measures = ("warning" if unknown else "success", msg)


def set_group(codes: list[str], value: bool):
    for code in codes:
        ss[f"m_{code}"] = value


def current_state() -> dict:
    """Текущие данные формы — для сохранения в файл и для сверки с отчётом."""
    return {"object_name": ss.object_name, "sphere": ss.sphere,
            "indicators": {i["id"]: ss[f"ind_{i['id']}"] for i in INDICATORS
                           if ss.get(f"ind_{i['id']}") is not None},
            "implemented": [c for c in ALL_CODES if ss.get(f"m_{c}")]}


def show_flash(key="flash"):
    if key in ss:
        kind, text = ss.pop(key)
        getattr(st, kind)(text)


if "started_at" not in ss:
    reset_form()

# ---------------- расчёт по текущим данным (до отрисовки) ----------------

raw_values = {i["id"]: ss[f"ind_{i['id']}"] for i in INDICATORS if ss.get(f"ind_{i['id']}") is not None}
validation = validate(rules, raw_values)
values = {k: v for k, v in raw_values.items() if k not in validation.errors}
cat = categorize(rules, ss.sphere, values)
required = required_measures(rules, cat.category)
req_codes = [m["code"] for m in required]
done_codes = [c for c in req_codes if ss.get(f"m_{c}")]
state_now = current_state()

# ---------------- боковая панель ----------------

with st.sidebar:
    st.markdown("### 🛡️ Оценка соответствия\nзначимого объекта КИИ")
    st.caption("Категорирование по ПП РФ № 127 и проверка мер по приказу ФСТЭК России № 239.")
    st.divider()
    steps = [("Объект и сфера", bool(ss.object_name)),
             ("Показатели значимости", bool(raw_values) and validation.ok),
             ("Меры защиты", bool(done_codes)),
             ("Отчёт", "report" in ss)]
    for n, (title, ok) in enumerate(steps, 1):
        st.markdown(f"{'✅' if ok else '○'} **{n}.** {title}")
    st.divider()
    st.caption(f"⏱ Время с начала оценки: {(time.time() - ss.started_at) / 60:.1f} мин")
    st.button("Начать новую оценку", on_click=reset_form, width="stretch")
    with st.expander("Как пользоваться"):
        st.markdown(
            "1. **Объект** — название и сфера деятельности.\n"
            "2. **Показатели** — заполните только применимые к объекту; под каждым полем — "
            "справочные значения из ПП № 127, подсвечивается диапазон, в который попало значение.\n"
            "3. **Меры** — отметьте реализованные меры вручную или загрузите их перечень из файла.\n"
            "4. **Отчёт** — несоответствия со ссылками на приказ № 239, выгрузка в DOCX.")

# ---------------- шапка и сводка ----------------

st.markdown(f'<div class="apptitle">Оценка соответствия значимого объекта КИИ</div>'
            f'<div class="appsub">{ss.object_name or "Объект не назван"}</div>', unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
if not cat.is_kii_subject:
    cat_html, cat_sub = badge(None, "не подлежит"), "сфера вне 187-ФЗ"
else:
    decisive = ", ".join(f"п. {r.indicator_id}" for r in cat.decisive)
    cat_html = badge(cat.category)
    cat_sub = f"определяет: {decisive}" if decisive else "показатели не дают категорию"
c1.markdown(f'<div class="card cat{cat.category or 0}"><div class="label">Категория значимости</div>'
            f'<div class="value">{ROMAN.get(cat.category, "—")}</div><div class="sub">{cat_sub}</div></div>',
            unsafe_allow_html=True)
c2.markdown(f'<div class="card cat0"><div class="label">Показатели</div>'
            f'<div class="value">{len(raw_values)} / {len(INDICATORS)}</div>'
            f'<div class="sub">{"ошибок ввода: " + str(len(validation.errors)) if validation.errors else "заполнено"}'
            f'</div></div>', unsafe_allow_html=True)
c3.markdown(f'<div class="card cat0"><div class="label">Меры базового набора</div>'
            f'<div class="value">{len(done_codes)} / {len(req_codes)}</div>'
            f'<div class="sub">реализовано</div></div>', unsafe_allow_html=True)
pct = f"{100 * len(done_codes) / len(req_codes):.1f}".replace(".", ",") + " %" if req_codes else "—"
c4.markdown(f'<div class="card cat0"><div class="label">Соответствие</div><div class="value">{pct}</div>'
            f'<div class="sub">несоответствий: {len(req_codes) - len(done_codes)}</div></div>',
            unsafe_allow_html=True)
st.write("")

tab1, tab2, tab3, tab4 = st.tabs([f"{'✅' if ok else '○'} {n}. {t}" for n, (t, ok) in enumerate(steps, 1)])

# ================= Шаг 1. Объект =================

with tab1:
    show_flash()
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Объект оценки")
        st.text_input("Наименование объекта КИИ", key="object_name",
                      placeholder="например, МИС областной клинической больницы")
        st.selectbox("Сфера деятельности субъекта КИИ (187-ФЗ, ст. 2, п. 8)", SPHERE_IDS,
                     format_func=lambda i: next(s["title"] for s in SPHERES if s["id"] == i), key="sphere")
        if ss.sphere == "other":
            st.warning("Сфера не входит в перечень ст. 2 п. 8 187-ФЗ — объект не подлежит категорированию.")
    with right:
        st.subheader("Сохранение и загрузка")
        st.download_button("💾 Сохранить оценку в файл", json.dumps(state_now, ensure_ascii=False, indent=2),
                           file_name=f"оценка_{datetime.now():%Y%m%d_%H%M}.json", mime="application/json",
                           width="stretch")
        st.file_uploader("Продолжить сохранённую оценку (.json)", type=["json"], key="session_file",
                         on_change=load_session_file)
        with st.expander("🎓 Демонстрация: пример из тестового набора"):
            st.selectbox("Объект", [o["id"] for o in load_objects()], key="example_id",
                         format_func=lambda i: f"{i}: " + next(o["name"] for o in load_objects() if o["id"] == i))
            st.button("Загрузить пример", on_click=load_example)

# ================= Шаг 2. Показатели =================

with tab2:
    st.caption("Заполните только показатели, применимые к объекту; пустое поле или «Неприменимо» — показатель "
               "не учитывается. Итоговая категория — наивысшая из полученных (ПП № 127, Правила, п. 6).")
    for section in dict.fromkeys(i["section"] for i in INDICATORS):
        items = [i for i in INDICATORS if i["section"] == section]
        filled = sum(1 for i in items if i["id"] in raw_values)
        with st.expander(f"{section} · заполнено {filled} из {len(items)}", expanded=filled > 0):
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
    if not cat.is_kii_subject or cat.category is None:
        st.info("Требования приказа ФСТЭК № 239 применяются к значимым объектам. "
                "Сначала определите категорию на шаге «Показатели».")
    else:
        st.markdown(f"Базовый набор мер для {badge(cat.category)} — **{len(required)}** мер "
                    f"(приказ ФСТЭК России № 239, п. 23 и приложение).", unsafe_allow_html=True)
        st.progress(len(done_codes) / len(req_codes),
                    text=f"Реализовано {len(done_codes)} из {len(req_codes)} мер")
        show_flash("flash_measures")
        f1, f2, f3 = st.columns([2, 1.2, 2])
        search = f1.text_input("Поиск меры", key="flt_search", placeholder="код или слово, например УПД или журнал")
        only_open = f2.toggle("Только нереализованные", key="flt_open")
        f3.file_uploader("Отметить меры из файла (TXT/CSV со списком кодов)", type=["txt", "csv"],
                         key="measures_file", on_change=load_measures_file)
        q = search.strip().lower()
        shown_any = False
        for group in dict.fromkeys(m["group"] for m in required):
            gm = [m for m in required if m["group"] == group]
            codes = [m["code"] for m in gm]
            done = sum(1 for c in codes if ss.get(f"m_{c}"))
            visible = [m for m in gm if (not q or q in m["code"].lower() or q in m["title"].lower())
                       and not (only_open and ss.get(f"m_{m['code']}"))]
            if not visible:
                continue
            shown_any = True
            mark = "✅" if done == len(codes) else ("🟠" if done else "⬜")
            with st.expander(f"{mark} {group} · {group_title(rules, group)} — {done} из {len(codes)}",
                             expanded=bool(q) or only_open):
                st.progress(done / len(codes))
                b1, b2, _ = st.columns([1, 1, 3])
                b1.button("Отметить все", key=f"all_{group}", on_click=set_group, args=(codes, True))
                b2.button("Снять все", key=f"none_{group}", on_click=set_group, args=(codes, False))
                for m in visible:
                    st.checkbox(f"**{m['code']}** — {m['title']}", key=f"m_{m['code']}",
                                help=m["source"] + (f"\n\n{m['note']}" if m.get("note") else ""))
        if not shown_any and only_open and not q:
            st.success("Все меры базового набора отмечены как реализованные.")
        elif not shown_any:
            st.info("Ничего не найдено.")

# ================= Шаг 4. Отчёт =================

with tab4:
    if validation.errors:
        st.error("Исправьте ошибки ввода в показателях " + ", ".join(validation.errors) +
                 " (шаг «Показатели») — пока они есть, отчёт не формируется.")
    if st.button("Сформировать отчёт", type="primary", disabled=bool(validation.errors)):
        ss.report = assess(rules, ss.object_name or "Без названия", ss.sphere, values, state_now["implemented"])
        ss.report_sig = json.dumps(state_now, sort_keys=True, ensure_ascii=False)
        ss.report_values = dict(values)
        if not ss.saved:  # журнал сессий — для метрики «время оценки через систему»
            seconds = time.time() - ss.started_at
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

        if r.required:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Обязательных мер", len(r.required))
            m2.metric("Реализовано", len(r.required) - len(r.missing))
            m3.metric("Несоответствий", len(r.missing))
            m4.metric("Соответствие", f"{r.compliance_percent}%".replace(".", ","))

            g1, g2 = st.columns([1, 2], gap="large")
            pie = pd.DataFrame({"Статус": ["Реализовано", "Не реализовано"],
                                "Мер": [len(r.required) - len(r.missing), len(r.missing)]})
            base = alt.Chart(pie).encode(
                theta=alt.Theta("Мер:Q", stack=True),
                color=alt.Color("Статус:N", scale=alt.Scale(domain=["Реализовано", "Не реализовано"],
                                                            range=["#2e9e5b", "#d64545"]),
                                legend=alt.Legend(orient="bottom", title=None)),
                tooltip=["Статус", "Мер"])
            center = alt.Chart(pd.DataFrame({"t": [f"{r.compliance_percent:g}%".replace(".", ",")]})).mark_text(
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
                                            "Группа": group_title(rules, m["group"])} for m in r.missing]),
                             hide_index=True, width="stretch")
            else:
                g2.success("Все меры базового набора реализованы — несоответствий не выявлено.")
        else:
            st.info("Требования к значимым объектам не применяются: категория не присвоена.")

        if r.warnings:
            with st.expander(f"⚠️ Замечания к тексту нормативных документов ({len(r.warnings)})"):
                for w in r.warnings:
                    st.markdown(f"• {w}")

        d1, d2, d3 = st.columns(3)
        stamp = f"{datetime.now():%Y%m%d_%H%M}"
        d1.download_button("📄 Скачать отчёт (DOCX)", to_docx(rules, r, ss.sphere, ss.report_values),
                           file_name=f"отчёт_{stamp}.docx", type="primary", width="stretch",
                           mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        d2.download_button("Скачать отчёт (Markdown)", to_markdown(rules, r), file_name=f"отчёт_{stamp}.md",
                           mime="text/markdown", width="stretch")
        d3.download_button("Сохранить данные оценки (JSON)", json.dumps(state_now, ensure_ascii=False, indent=2),
                           file_name=f"оценка_{stamp}.json", mime="application/json", width="stretch")
