"""Проверка требований к системе безопасности значимых объектов (приказ ФСТЭК № 235).

Требования — организационный чек-лист из rules/security_system.yaml. Условные требования
(поле condition) можно отметить как «не применимо», если условие не выполняется
(например, у субъекта нет обособленных подразделений).
"""

from dataclasses import dataclass, field

from engine.rules_loader import RuleBase
from engine.validation import InputError


@dataclass
class SecurityResult:
    requirements: list[dict] = field(default_factory=list)    # все требования
    done: list[dict] = field(default_factory=list)            # выполнены
    not_applicable: list[dict] = field(default_factory=list)  # условие не выполняется
    missing: list[dict] = field(default_factory=list)         # не выполнены

    @property
    def applicable_count(self) -> int:
        return len(self.requirements) - len(self.not_applicable)

    @property
    def percent(self) -> float | None:
        """Доля выполненных требований среди применимых, %."""
        if not self.applicable_count:
            return None
        return round(100 * len(self.done) / self.applicable_count, 1)


def assess_security(rules: RuleBase, done_ids: list[str], na_ids: list[str] = ()) -> SecurityResult:
    """Оценивает выполнение требований № 235.

    done_ids — коды выполненных требований; na_ids — коды неприменимых (только условные).
    """
    errors = []
    for rid in list(done_ids) + list(na_ids):
        try:
            rules.requirement(rid)
        except KeyError:
            errors.append(f"неизвестное требование {rid!r}")
    for rid in na_ids:
        if rid in done_ids:
            errors.append(f"требование {rid} отмечено и как выполненное, и как неприменимое")
        elif not errors and not rules.requirement(rid).get("condition"):
            errors.append(f"требование {rid} не является условным и не может быть отмечено «не применимо»")
    if errors:
        raise InputError("Ошибки в отметках требований приказа № 235:\n" + "\n".join(errors))

    res = SecurityResult(requirements=list(rules.security["requirements"]))
    for r in res.requirements:
        if r["id"] in na_ids:
            res.not_applicable.append(r)
        elif r["id"] in done_ids:
            res.done.append(r)
        else:
            res.missing.append(r)
    return res
