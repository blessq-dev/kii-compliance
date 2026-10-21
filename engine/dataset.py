"""Чтение тестового набора объектов (data/test_objects.yaml) для тестов и эксперимента."""

from pathlib import Path

import yaml

from engine.measures import required_measures
from engine.paths import DATA_DIR
from engine.rules_loader import RuleBase


def load_objects(path: Path | str = DATA_DIR / "test_objects.yaml") -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["objects"]


def implemented_codes(rules: RuleBase, spec: dict) -> list[str]:
    """Разворачивает краткую запись «базовый набор категории N кроме ... плюс ...»
    в явный список кодов реализованных мер."""
    base = [m["code"] for m in required_measures(rules, spec.get("base_category"))]
    skip = set(spec.get("except", []))
    return [c for c in base if c not in skip] + list(spec.get("extra", []))
