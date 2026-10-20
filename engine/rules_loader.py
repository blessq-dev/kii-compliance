"""Загрузка базы правил из YAML-файлов папки rules/.

Движок не содержит ни одного нормативного значения в коде: все показатели,
диапазоны и меры читаются из YAML. Это позволяет обновить базу правил
(например, при выходе новой редакции документа), не меняя программу.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

# Папка с правилами по умолчанию: <корень проекта>/rules
RULES_DIR = Path(__file__).resolve().parent.parent / "rules"


@dataclass
class RuleBase:
    """Вся база правил, загруженная в память."""

    categorization: dict  # rules/categorization.yaml
    measures: dict        # rules/measures.yaml
    spheres: dict         # rules/spheres.yaml
    security: dict        # rules/security_system.yaml (приказ ФСТЭК № 235)

    def indicator(self, indicator_id: str) -> dict:
        """Возвращает правило показателя по его номеру в Перечне (например, «2б»)."""
        for ind in self.categorization["indicators"]:
            if ind["id"] == indicator_id:
                return ind
        raise KeyError(f"Показатель {indicator_id!r} отсутствует в базе правил")

    def measure(self, code: str) -> dict:
        """Возвращает правило меры по её коду (например, «УПД.3»)."""
        for m in self.measures["measures"]:
            if m["code"] == code:
                return m
        raise KeyError(f"Мера {code!r} отсутствует в базе правил")

    def requirement(self, req_id: str) -> dict:
        """Требование к системе безопасности по коду (например, «Д.1»)."""
        for r in self.security["requirements"]:
            if r["id"] == req_id:
                return r
        raise KeyError(f"Требование {req_id!r} отсутствует в базе правил")

    def editions(self) -> list[str]:
        """Документы и редакции, по которым выполняется оценка (для отчёта)."""
        return [f"{d['act']} ({d['edition']})" for d in
                (self.categorization["document"], self.measures["document"], self.security["document"])]

    def sphere_ids(self) -> set[str]:
        """Идентификаторы сфер из ст. 2 п. 8 187-ФЗ."""
        return {s["id"] for s in self.spheres["spheres"]}


def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_rules(rules_dir: Path | str = RULES_DIR) -> RuleBase:
    """Читает файлы базы правил и возвращает объект RuleBase."""
    rules_dir = Path(rules_dir)
    return RuleBase(
        categorization=_read_yaml(rules_dir / "categorization.yaml"),
        measures=_read_yaml(rules_dir / "measures.yaml"),
        spheres=_read_yaml(rules_dir / "spheres.yaml"),
        security=_read_yaml(rules_dir / "security_system.yaml"),
    )
