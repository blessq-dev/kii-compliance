"""Эксперимент для ВКР: прогон тестового набора объектов и расчёт метрик.

Запуск:  python experiment.py

Считает:
  1. Точность определения категории (accuracy) относительно эталона.
  2. Полноту (recall) и точность (precision) выявления несоответствий,
     долю ложных несоответствий.
  3. Время и качество оценки участниками: через систему (режим эксперимента,
     data/results/experiment_system.csv) и вручную (data/results/experiment_manual.csv).
Результаты по каждому объекту сохраняются в data/results/experiment_<дата>.csv.
"""

import csv
import time
from datetime import datetime
from pathlib import Path

from engine.assessment import assess
from engine import trials
from engine.dataset import DATA_DIR, implemented_codes, load_objects
from engine.metrics import Counts, category_accuracy
from engine.rules_loader import load_rules

RESULTS_DIR = DATA_DIR / "results"


def fmt_cat(c) -> str:
    return "—" if c is None else str(c)


def run_system(rules, objects) -> list[dict]:
    """Прогоняет каждый объект через движок и сравнивает с эталоном."""
    rows = []
    for obj in objects:
        start = time.perf_counter()
        rep = assess(rules, obj["name"], obj["sphere"], obj.get("indicators") or {},
                     implemented_codes(rules, obj["implemented"]), attributes=obj.get("attributes"))
        seconds = time.perf_counter() - start
        expected = set(obj["expected_missing"])
        found = set(rep.missing_codes)
        rows.append({
            "id": obj["id"],
            "name": obj["name"],
            "expected_category": obj["expected_category"],
            "system_category": rep.categorization.category,
            "category_ok": obj["expected_category"] == rep.categorization.category,
            "expected_missing": expected,
            "found_missing": found,
            "tp": len(expected & found),
            "fp": len(found - expected),
            "fn": len(expected - found),
            "seconds": seconds,
            "warnings": len(rep.warnings),
        })
    return rows


def summarize(title: str, pairs: list[tuple], counts: Counts) -> None:
    print(f"\n{title}")
    print(f"  Объектов:                              {len(pairs)}")
    print(f"  Точность определения категории:        {category_accuracy(pairs):.3f}")
    print(f"  Полнота выявления несоответствий:      {counts.recall:.3f}  (TP={counts.tp}, FN={counts.fn})")
    print(f"  Точность выявления несоответствий:     {counts.precision:.3f}  (FP={counts.fp})")
    print(f"  Доля ложных несоответствий:            {counts.false_rate:.3f}")


def participants_summary() -> None:
    """Сравнение «вручную vs через систему» по журналам участников эксперимента."""
    means = {}
    for title, path in (("УЧАСТНИКИ: ОЦЕНКА ЧЕРЕЗ СИСТЕМУ", trials.SYSTEM_LOG),
                        ("УЧАСТНИКИ: РУЧНАЯ ОЦЕНКА", trials.MANUAL_LOG)):
        rows = trials.read(path)
        if not rows:
            print(f"\n{title}: записей пока нет ({path.relative_to(DATA_DIR.parent)}).")
            continue
        pairs = [(r["expected_category"], r["category"]) for r in rows]
        counts = Counts(sum(int(r["tp"]) for r in rows), sum(int(r["fp"]) for r in rows),
                        sum(int(r["fn"]) for r in rows))
        summarize(title, pairs, counts)
        minutes = [float(r["minutes"]) for r in rows]
        means[title] = sum(minutes) / len(minutes)
        print(f"  Участников:                            {len({r['participant'] for r in rows})}")
        print(f"  Среднее время на объект:               {means[title]:.1f} мин")
    if len(means) == 2:
        sys_t, man_t = means.values()
        print(f"\nСокращение времени оценки: {man_t:.1f} → {sys_t:.1f} мин "
              f"({100 * (man_t - sys_t) / man_t:.0f} %)")


def save_csv(rows: list[dict]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"experiment_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig — чтобы Excel открыл кириллицу
        w = csv.writer(f, delimiter=";")
        w.writerow(["id", "объект", "категория (эталон)", "категория (система)", "совпало",
                    "TP", "FP", "FN", "пропущено", "ложные", "время, мс", "замечаний"])
        for r in rows:
            w.writerow([r["id"], r["name"], fmt_cat(r["expected_category"]), fmt_cat(r["system_category"]),
                        "да" if r["category_ok"] else "нет", r["tp"], r["fp"], r["fn"],
                        ", ".join(sorted(r["expected_missing"] - r["found_missing"])),
                        ", ".join(sorted(r["found_missing"] - r["expected_missing"])),
                        f"{r['seconds'] * 1000:.2f}", r["warnings"]])
    return path


def main() -> None:
    rules = load_rules()
    objects = load_objects()
    rows = run_system(rules, objects)

    print(f"{'id':6} {'эталон':>6} {'система':>7}  {'TP':>3} {'FP':>3} {'FN':>3}  объект")
    for r in rows:
        mark = "" if r["category_ok"] and not r["fp"] and not r["fn"] else "  <-- расхождение"
        print(f"{r['id']:6} {fmt_cat(r['expected_category']):>6} {fmt_cat(r['system_category']):>7}  "
              f"{r['tp']:>3} {r['fp']:>3} {r['fn']:>3}  {r['name']}{mark}")

    counts = Counts(sum(r["tp"] for r in rows), sum(r["fp"] for r in rows), sum(r["fn"] for r in rows))
    summarize("СИСТЕМА", [(r["expected_category"], r["system_category"]) for r in rows], counts)
    total = sum(r["seconds"] for r in rows)
    print(f"  Время автоматической оценки:           {total * 1000:.1f} мс на {len(rows)} объектов")

    participants_summary()
    print(f"\nРезультаты по объектам: {save_csv(rows)}")


if __name__ == "__main__":
    main()
