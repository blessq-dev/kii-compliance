"""Оценка соответствия объекта КИИ: категория → обязательные меры → несоответствия.

Это главная точка входа движка. Интерфейс (app.py) и эксперимент (experiment.py)
вызывают функцию assess() и печать отчёта to_markdown().

Статусы мер базового набора (приказ ФСТЭК № 239):
  - реализована                — мера отмечена в перечне реализованных;
  - не применяется             — исключена при адаптации базового набора, т. к. связана
                                 с технологиями (характеристиками), которых нет в объекте
                                 (п. 23, абз. 3); обязательно обоснование;
  - компенсирована             — вместо меры применена компенсирующая мера (п. 26);
                                 обязательно описание компенсирующей меры;
  - не реализована             — несоответствие.
Уровень соответствия = (реализованные + компенсированные) / (обязательные − неприменимые).
"""

import re
from dataclasses import dataclass, field

from engine.categorization import CategorizationResult, categorize
from engine.measures import group_title, required_measures
from engine.rules_loader import RuleBase
from engine.security_system import SecurityResult, assess_security
from engine.validation import InputError, require_valid

NOT_APPLICABLE = "not_applicable"
COMPENSATED = "compensated"
STATUS_TITLES = {NOT_APPLICABLE: "не применяется (адаптация, п. 23 приказа № 239)",
                 COMPENSATED: "компенсирована (п. 26 приказа № 239)"}

GIS_ISPDN_NOTICE = ("Объект является {what}: меры по обеспечению безопасности значимого объекта и меры защиты "
                    "информации принимаются в соответствии с более высокой категорией значимости, классом "
                    "защищённости или уровнем защищённости персональных данных (приказ ФСТЭК России № 239, п. 24). "
                    "Требования к защите ГИС и ИСПДн в базе правил прототипа не учтены.")


@dataclass
class AssessmentReport:
    """Отчёт об оценке соответствия."""

    object_name: str
    categorization: CategorizationResult
    required: list[dict] = field(default_factory=list)        # обязательные меры (правила)
    implemented: list[str] = field(default_factory=list)      # коды мер, отмеченных как реализованные
    missing: list[dict] = field(default_factory=list)         # несоответствия
    not_applicable: list[dict] = field(default_factory=list)  # [{measure, text}] — исключены при адаптации
    compensated: list[dict] = field(default_factory=list)     # [{measure, text}] — компенсированы
    details: dict = field(default_factory=dict)               # {код: {means, due}} — сведения о мерах
    security: SecurityResult | None = None                    # требования приказа № 235
    notices: list[str] = field(default_factory=list)          # особенности применения требований
    warnings: list[str] = field(default_factory=list)         # замечания к тексту нормативных документов
    editions: list[str] = field(default_factory=list)         # документы и редакции базы правил

    @property
    def missing_codes(self) -> list[str]:
        return [m["code"] for m in self.missing]

    @property
    def applicable_count(self) -> int:
        return len(self.required) - len(self.not_applicable)

    @property
    def covered_count(self) -> int:
        """Реализованные и компенсированные обязательные меры."""
        return self.applicable_count - len(self.missing)

    @property
    def compliance_percent(self) -> float | None:
        """Доля закрытых обязательных мер среди применимых, %. None — если мер нет."""
        if not self.applicable_count:
            return None
        return round(100 * self.covered_count / self.applicable_count, 1)


def _non_monotonic_notes(rules: RuleBase, category: int) -> list[str]:
    """Замечания к мерам, которые входят в набор более низкой категории,
    но отсутствуют в наборе текущей (например, ДНС.5 для категории 2)."""
    notes = []
    for m in rules.measures["measures"]:
        lower = [c for c in m["categories"] if c > category]  # 3 ниже 2, 2 ниже 1
        if lower and category not in m["categories"]:
            notes.append(
                f"Мера {m['code']} входит в базовый набор категории {', '.join(map(str, lower))}, "
                f"но не категории {category} — так в тексте приложения к приказу № 239. "
                f"{m.get('note', '')}".strip()
            )
    return notes


def _check_statuses(rules: RuleBase, implemented: set, statuses: dict, details: dict) -> None:
    """Проверяет особые статусы и сведения о мерах; при ошибках — InputError."""
    errors = []
    for code, st in statuses.items():
        try:
            rules.measure(code)
        except KeyError:
            errors.append(f"неизвестная мера {code!r}")
            continue
        if st.get("status") not in STATUS_TITLES:
            errors.append(f"мера {code}: недопустимый статус {st.get('status')!r}")
        elif not str(st.get("text", "")).strip():
            what = "обоснование неприменимости" if st["status"] == NOT_APPLICABLE else "описание компенсирующей меры"
            errors.append(f"мера {code}: не указано {what}")
        if code in implemented:
            errors.append(f"мера {code}: отмечена как реализованная и одновременно имеет статус "
                          f"«{STATUS_TITLES.get(st.get('status'), st.get('status'))}»")
    for code, d in details.items():
        try:
            rules.measure(code)
        except KeyError:
            errors.append(f"неизвестная мера {code!r} в сведениях о мерах")
        due = d.get("due")
        if due and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(due)):
            errors.append(f"мера {code}: срок {due!r} должен быть датой в формате ГГГГ-ММ-ДД")
    if errors:
        raise InputError("Ошибки в сведениях о мерах:\n" + "\n".join(errors))


def assess(rules: RuleBase, object_name: str, sphere: str, indicator_values: dict, implemented: list[str],
           statuses: dict | None = None, details: dict | None = None, attributes: dict | None = None,
           security: dict | None = None) -> AssessmentReport:
    """Полная оценка объекта.

    object_name       — наименование объекта (для отчёта);
    sphere            — id сферы из пакета 187-ФЗ (rules/187-fz/);
    indicator_values  — {номер показателя ПП № 127: значение};
    implemented       — коды мер, которые пользователь отметил как реализованные;
    statuses          — особые статусы мер {код: {"status": not_applicable|compensated, "text": обоснование}};
    details           — сведения о мерах {код: {"means": чем реализована, "due": "ГГГГ-ММ-ДД"}};
    attributes        — признаки объекта {"is_gis": bool, "is_ispdn": bool} и подтверждённые условия
                        применимости показателей {id условия из categorization.yaml: bool};
    security          — отметки требований № 235 {"done": [коды], "not_applicable": [коды]}.
    """
    statuses, details, attributes = statuses or {}, details or {}, attributes or {}
    # Проверяем ввод: невозможные значения показателей, показатели без подтверждённого условия
    # применимости и несуществующие меры не допускаются.
    require_valid(rules, indicator_values, attributes)
    for code in implemented:
        rules.measure(code)
    done = set(implemented)
    _check_statuses(rules, done, statuses, details)

    cat = categorize(rules, sphere, indicator_values)
    required = required_measures(rules, cat.category)
    report = AssessmentReport(object_name=object_name, categorization=cat, required=required,
                              implemented=sorted(done), warnings=list(cat.warnings),
                              editions=rules.editions())
    for m in required:
        st = statuses.get(m["code"])
        if st and st["status"] == NOT_APPLICABLE:
            report.not_applicable.append({"measure": m, "text": st["text"].strip()})
        elif st and st["status"] == COMPENSATED:
            report.compensated.append({"measure": m, "text": st["text"].strip()})
        elif m["code"] not in done:
            report.missing.append(m)
    req_codes = {m["code"] for m in required}
    report.details = {c: d for c, d in details.items() if c in req_codes and (d.get("means") or d.get("due"))}

    if cat.category is not None:
        report.warnings += _non_monotonic_notes(rules, cat.category)
        what = " и ".join(w for w, flag in (("государственной информационной системой", attributes.get("is_gis")),
                                             ("информационной системой персональных данных",
                                              attributes.get("is_ispdn"))) if flag)
        if what:
            report.notices.append(GIS_ISPDN_NOTICE.format(what=what))
        if security is not None:
            report.security = assess_security(rules, security.get("done", []), security.get("not_applicable", []))
    return report


def to_markdown(rules: RuleBase, r: AssessmentReport) -> str:
    """Текст отчёта о несоответствиях в формате Markdown."""
    c = r.categorization
    lines = [f"# Отчёт об оценке соответствия: {r.object_name}", ""]

    lines.append("## 1. Категория значимости")
    if not c.is_kii_subject:
        lines.append("Объект не подлежит категорированию.")
    elif c.category is None:
        lines.append("Категория значимости не присвоена.")
    else:
        lines.append(f"**Категория значимости: {c.category}**")
    lines.append("")
    lines += [f"- {e}" for e in c.explanation]
    lines.append("")

    lines.append("## 2. Соответствие требованиям приказа ФСТЭК № 239")
    if not r.required:
        lines.append("Требования к значимым объектам не применяются: категория не присвоена.")
    else:
        lines.append(f"- Обязательных мер (базовый набор): {len(r.required)}")
        lines.append(f"- Не применяются (адаптация): {len(r.not_applicable)}")
        lines.append(f"- Реализовано: {r.covered_count - len(r.compensated)}, компенсировано: {len(r.compensated)}")
        lines.append(f"- Несоответствий: {len(r.missing)}")
        lines.append(f"- Уровень соответствия: {r.compliance_percent}%")
        lines.append("")
        if r.missing:
            lines.append("### Несоответствия (обязательные меры не реализованы)")
            lines.append("")
            lines.append("| Мера | Содержание | Группа | Плановый срок | Источник |")
            lines.append("|---|---|---|---|---|")
            for m in r.missing:
                due = r.details.get(m["code"], {}).get("due") or "—"
                lines.append(f"| {m['code']} | {m['title']} | {group_title(rules, m['group'])} | {due} "
                             f"| {m['source']} |")
        else:
            lines.append("Несоответствий не выявлено.")
        for title, items in (("Меры, исключённые при адаптации базового набора (п. 23)", r.not_applicable),
                             ("Компенсирующие меры (п. 26)", r.compensated)):
            if items:
                lines += ["", f"### {title}", "", "| Мера | Содержание | Обоснование |", "|---|---|---|"]
                lines += [f"| {i['measure']['code']} | {i['measure']['title']} | {i['text']} |" for i in items]
    lines.append("")

    if r.security:
        s = r.security
        lines.append("## 3. Требования к системе безопасности (приказ ФСТЭК № 235)")
        lines.append(f"- Выполнено {len(s.done)} из {s.applicable_count} применимых требований ({s.percent}%)")
        if s.missing:
            lines += ["", "| Код | Требование | Источник |", "|---|---|---|"]
            lines += [f"| {q['id']} | {q['text']} | {q['source']} |" for q in s.missing]
        lines.append("")

    if r.notices:
        lines.append("## Особенности применения требований")
        lines += [f"- {n}" for n in r.notices]
        lines.append("")
    if r.warnings:
        lines.append("## Замечания к тексту нормативных документов")
        lines += [f"- {w}" for w in r.warnings]
        lines.append("")

    lines.append("---")
    lines.append("Оценка выполнена по базовому набору мер с учётом отмеченной адаптации (п. 23 Требований, "
                 "приказ ФСТЭК № 239). Дополнение набора мерами иных НПА в прототипе не учитывается.")
    lines.append("")
    lines.append("Документы базы правил: " + "; ".join(r.editions) + ".")
    return "\n".join(lines)
