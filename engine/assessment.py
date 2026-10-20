"""Оценка соответствия объекта КИИ: категория → обязательные меры → несоответствия.

Это главная точка входа движка. Интерфейс (app.py) и эксперимент (experiment.py)
вызывают только функцию assess() и печать отчёта to_markdown().
"""

from dataclasses import dataclass, field

from engine.categorization import CategorizationResult, categorize
from engine.measures import group_title, required_measures
from engine.rules_loader import RuleBase
from engine.validation import require_valid


@dataclass
class AssessmentReport:
    """Отчёт об оценке соответствия."""

    object_name: str
    categorization: CategorizationResult
    required: list[dict] = field(default_factory=list)     # обязательные меры (правила)
    implemented: list[str] = field(default_factory=list)   # коды мер, отмеченных как реализованные
    missing: list[dict] = field(default_factory=list)      # несоответствия: обязательные, но не реализованные
    warnings: list[str] = field(default_factory=list)      # замечания к тексту нормативных документов

    @property
    def missing_codes(self) -> list[str]:
        return [m["code"] for m in self.missing]

    @property
    def compliance_percent(self) -> float | None:
        """Доля реализованных обязательных мер, %. None — если мер нет."""
        if not self.required:
            return None
        return round(100 * (len(self.required) - len(self.missing)) / len(self.required), 1)


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


def assess(rules: RuleBase, object_name: str, sphere: str,
           indicator_values: dict, implemented: list[str]) -> AssessmentReport:
    """Полная оценка объекта.

    object_name       — наименование объекта (для отчёта);
    sphere            — id сферы из rules/spheres.yaml;
    indicator_values  — {номер показателя ПП № 127: значение};
    implemented       — коды мер, которые пользователь отметил как реализованные.
    """
    # Проверяем ввод: невозможные значения показателей и несуществующие меры не допускаются.
    require_valid(rules, indicator_values)
    for code in implemented:
        rules.measure(code)

    cat = categorize(rules, sphere, indicator_values)
    required = required_measures(rules, cat.category)
    done = set(implemented)
    report = AssessmentReport(
        object_name=object_name,
        categorization=cat,
        required=required,
        implemented=sorted(done),
        missing=[m for m in required if m["code"] not in done],
        warnings=list(cat.warnings),
    )
    if cat.category is not None:
        report.warnings += _non_monotonic_notes(rules, cat.category)
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
        lines.append(f"- Реализовано из обязательных: {len(r.required) - len(r.missing)}")
        lines.append(f"- Несоответствий: {len(r.missing)}")
        lines.append(f"- Уровень соответствия: {r.compliance_percent}%")
        lines.append("")
        if r.missing:
            lines.append("### Несоответствия (обязательные меры не реализованы)")
            lines.append("")
            lines.append("| Мера | Содержание | Группа | Источник |")
            lines.append("|---|---|---|---|")
            for m in r.missing:
                lines.append(f"| {m['code']} | {m['title']} | {group_title(rules, m['group'])} | {m['source']} |")
        else:
            lines.append("Несоответствий не выявлено.")
    lines.append("")

    if r.warnings:
        lines.append("## 3. Замечания к тексту нормативных документов")
        lines += [f"- {w}" for w in r.warnings]
        lines.append("")

    lines.append("---")
    lines.append("Оценка выполнена по базовому набору мер (п. 23 Требований, приказ ФСТЭК № 239). "
                 "Адаптация набора под угрозы и особенности объекта, компенсирующие меры "
                 "и дополнение мерами иных НПА в прототипе не учитываются.")
    return "\n".join(lines)
