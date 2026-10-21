"""Журнал эксперимента «вручную vs система» (данные для главы ВКР).

Участник получает карточку тестового объекта (data/test_objects.yaml) и оценивает его
  - через систему (режим эксперимента в интерфейсе) → data/results/experiment_system.csv;
  - вручную по документам, результат вносится через форму   → data/results/experiment_manual.csv.
Каждая запись сравнивается с эталоном: совпадение категории и TP/FP/FN по несоответствиям.
"""

import csv
from datetime import datetime
from pathlib import Path

from engine.dataset import load_objects
from engine.paths import USER_DIR

RESULTS_DIR = USER_DIR / "results"
SYSTEM_LOG = RESULTS_DIR / "experiment_system.csv"
MANUAL_LOG = RESULTS_DIR / "experiment_manual.csv"
FIELDS = ["datetime", "participant", "object_id", "minutes", "category", "expected_category",
          "category_ok", "missing", "tp", "fp", "fn"]


def _fmt_cat(c) -> str:
    return "" if c is None else str(c)


def compare(object_id: str, category, missing: list[str]) -> dict:
    """Сравнение результата участника с эталоном тестового объекта."""
    obj = next(o for o in load_objects() if o["id"] == object_id)
    expected, found = set(obj["expected_missing"]), set(missing)
    return {"expected_category": obj["expected_category"],
            "category_ok": obj["expected_category"] == category,
            "tp": len(expected & found), "fp": len(found - expected), "fn": len(expected - found)}


def append(path: Path, participant: str, object_id: str, minutes: float, category, missing: list[str]) -> dict:
    """Добавляет запись в журнал и возвращает её (с результатами сравнения)."""
    cmp = compare(object_id, category, missing)
    row = {"datetime": datetime.now().isoformat(timespec="seconds"), "participant": participant.strip(),
           "object_id": object_id, "minutes": round(float(minutes), 2), "category": _fmt_cat(category),
           "expected_category": _fmt_cat(cmp["expected_category"]), "category_ok": int(cmp["category_ok"]),
           "missing": " ".join(sorted(missing)), "tp": cmp["tp"], "fp": cmp["fp"], "fn": cmp["fn"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    return row


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))
