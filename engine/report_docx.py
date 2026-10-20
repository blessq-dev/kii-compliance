"""Выгрузка отчёта об оценке соответствия в формате DOCX (для приложения к акту).

Модуль только оформляет уже готовый результат assess(): никаких правил
и вычислений категории здесь нет.
"""

import io
from datetime import datetime

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from engine.assessment import AssessmentReport
from engine.measures import group_title
from engine.rules_loader import RuleBase

ROMAN = {1: "I", 2: "II", 3: "III"}


def _font(run, size=11, bold=False, color=None):
    run.font.name = "Times New Roman"
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "Times New Roman")
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def _p(doc, text="", size=11, bold=False, align=None, color=None, space_after=4):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    if align:
        p.alignment = align
    if text:
        _font(p.add_run(text), size, bold, color)
    return p


def _shade(cell, hex_color):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def _table(doc, header, rows, widths):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        _font(c.paragraphs[0].add_run(h), 10, bold=True)
        _shade(c, "E8EEF8")
    for r in rows:
        cells = t.add_row().cells
        for i, v in enumerate(r):
            cells[i].text = ""
            _font(cells[i].paragraphs[0].add_run(str(v)), 10)
    for row in t.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Cm(w)
    return t


def _fmt_value(rule: dict, value) -> str:
    if rule["type"] == "number":
        return f"{value:g}".replace(".", ",") + f" {rule['unit']}"
    return next(o["text"] for o in rule["options"] if o["id"] == value)


def to_docx(rules: RuleBase, report: AssessmentReport, sphere: str, indicator_values: dict) -> bytes:
    """Формирует DOCX-отчёт и возвращает его содержимое (байты) для скачивания."""
    doc = Document()
    for s in doc.sections:
        s.left_margin, s.right_margin, s.top_margin, s.bottom_margin = Cm(2.5), Cm(1.5), Cm(2), Cm(2)
    c = report.categorization

    _p(doc, "ОТЧЁТ", 14, True, WD_ALIGN_PARAGRAPH.CENTER, space_after=0)
    _p(doc, "об оценке соответствия объекта КИИ требованиям безопасности", 12, True,
       WD_ALIGN_PARAGRAPH.CENTER)
    _p(doc, f"Дата формирования: {datetime.now():%d.%m.%Y %H:%M}", 10, align=WD_ALIGN_PARAGRAPH.RIGHT)

    sphere_title = next((s["title"] for s in rules.spheres["spheres"] if s["id"] == sphere),
                        rules.spheres["other"]["title"])
    _p(doc, "1. Сведения об объекте", 12, True)
    _table(doc, ["Параметр", "Значение"],
           [["Наименование объекта", report.object_name],
            ["Сфера деятельности (187-ФЗ, ст. 2, п. 8)", sphere_title]], [6, 11])

    _p(doc)
    _p(doc, "2. Значения показателей критериев значимости (ПП РФ № 127)", 12, True)
    by_id = {r.indicator_id: r for r in c.details}
    rows = []
    for rule in rules.categorization["indicators"]:
        if rule["id"] in indicator_values and indicator_values[rule["id"]] not in (None, ""):
            res = by_id.get(rule["id"])
            cat = ROMAN[res.category] + " категория" if res and res.category else "не соответствует"
            rows.append([rule["id"], rule["short"], _fmt_value(rule, indicator_values[rule["id"]]), cat])
    if rows:
        _table(doc, ["№", "Показатель", "Значение", "Результат"], rows, [1.2, 6.5, 6, 3.3])
    else:
        _p(doc, "Показатели не заполнены (неприменимы к объекту).")

    _p(doc)
    _p(doc, "3. Категория значимости", 12, True)
    if not c.is_kii_subject:
        verdict, color = "Объект не подлежит категорированию", "555555"
    elif c.category is None:
        verdict, color = "Категория значимости не присваивается", "555555"
    else:
        verdict, color = f"Присвоена {ROMAN[c.category]} категория значимости", "B42318"
    _p(doc, verdict, 12, True, color=color)
    for line in c.explanation:
        _p(doc, "• " + line, 10)

    _p(doc)
    _p(doc, "4. Соответствие требованиям приказа ФСТЭК России № 239", 12, True)
    if not report.required:
        _p(doc, "Требования к значимым объектам не применяются: категория не присвоена.")
    else:
        _table(doc, ["Обязательных мер", "Реализовано", "Несоответствий", "Уровень соответствия"],
               [[len(report.required), len(report.required) - len(report.missing), len(report.missing),
                 f"{report.compliance_percent}%".replace(".", ",")]], [4.25] * 4)
        _p(doc)
        if report.missing:
            _p(doc, "Перечень несоответствий (обязательные меры не реализованы):", 11, True)
            _table(doc, ["Мера", "Содержание меры", "Группа мер"],
                   [[m["code"], m["title"], group_title(rules, m["group"])] for m in report.missing],
                   [2, 9, 6])
        else:
            _p(doc, "Несоответствий не выявлено.", 11, True, color="1E7B34")

    if report.warnings:
        _p(doc)
        _p(doc, "5. Замечания к тексту нормативных документов", 12, True)
        for w in report.warnings:
            _p(doc, "• " + w, 10)

    _p(doc)
    _p(doc, "Оценка выполнена по базовому набору мер (п. 23 Требований, утв. приказом ФСТЭК России № 239). "
            "Адаптация набора мер, компенсирующие меры и дополнение мерами иных НПА не учитываются.",
       9, color="555555")
    _p(doc)
    _p(doc, "Оценку выполнил: ____________________ / ____________________ /", 11)
    _p(doc, "                         (подпись)                    (ФИО)", 9, color="555555")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
