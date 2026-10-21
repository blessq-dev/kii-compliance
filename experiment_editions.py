"""Эксперимент: насколько точно выявляются изменения Перечня показателей ПП № 127 между редакциями.

Для каждой пары соседних редакций (пакеты rules/pp-127/, тексты docs/):
  - эталон  — показатели, правила которых действительно изменились между пакетами
              (добавлены, исключены, изменены значения, варианты, тип или условие применимости;
              пакеты составлены и проверены экспертом, их совпадение с текстом проверено тестом);
  - метод 1 — пометки «в ред.» / «введен» / «утратил силу» в тексте новой редакции (engine/source_text.py):
              показатели, источник которых указывает на изменённый пункт;
  - метод 2 — сверка значений таблицы Перечня новой редакции с прежним пакетом (engine/source_table.py);
  - методы 1 + 2 — объединение.
Метрики: TP, FP, FN, полнота (recall) и точность (precision) по показателям.

Запуск: python experiment_editions.py  — таблица в консоли и data/results/editions_<дата>.csv
"""

import csv
from datetime import datetime
from pathlib import Path

from engine.metrics import Counts
from engine.paths import USER_DIR
from engine.rules_loader import read_package
from engine.source_table import compare_package, indicator_rows
from engine.source_text import read_paragraphs, stale_rules

ROOT = Path(__file__).resolve().parent
EDITIONS = [("2018-02-08", None), ("2019-04-13", "PP-127_red_2019-04-13.docx"),
            ("2022-12-20", "PP-127_red_2022-12-20.docx"),
            ("2025-11-07", "Postanovlenie_Pravitelstva_RF_ot_08_02_2018_N_127_red_ot.docx")]
COMPARED = ("type", "values", "options", "applies_if")  # что составляет правило показателя


def truth(old: dict, new: dict) -> set[str]:
    """Показатели, правила которых изменились между пакетами (эталон)."""
    a = {i["id"]: i for i in old["indicators"]}
    b = {i["id"]: i for i in new["indicators"]}
    changed = {k for k in a.keys() & b.keys()
               if any(_norm(a[k].get(f), f) != _norm(b[k].get(f), f) for f in COMPARED)}
    return changed | (a.keys() ^ b.keys())


def _norm(value, field: str):
    """Значения сравниваются по границам; формулировки вариантов — по категории (тексты пересказаны)."""
    if field == "values" and value:
        return {k: {x: v[x] for x in ("min", "min_incl", "max", "max_incl") if x in v} for k, v in value.items()}
    if field == "options" and value:
        return sorted((o["id"], o["category"]) for o in value)
    return value


def by_marks(old_pkg, new_pkg, paragraphs) -> set[str]:
    """Метод 1: показатели прежнего и нового пакета, основанные на пунктах с пометками после даты прежнего."""
    indicators = {i["id"] for p in (old_pkg, new_pkg) for i in p.data["indicators"]}
    found = set()
    for pkg in (old_pkg, new_pkg):
        for item in stale_rules(pkg.data, old_pkg.effective_from, paragraphs):
            found |= {r for r in item.rules if r in indicators}
    return found


def by_values(old_pkg, path) -> set[str]:
    """Метод 2: показатели с расхождениями таблицы новой редакции и прежнего пакета."""
    return {m.indicator for m in compare_package(old_pkg.data, indicator_rows(path))}


def main() -> None:
    rows = []
    for (old_ed, _), (new_ed, text) in zip(EDITIONS, EDITIONS[1:]):
        old_pkg = read_package(ROOT / "rules" / "pp-127" / f"{old_ed}.yaml")
        new_pkg = read_package(ROOT / "rules" / "pp-127" / f"{new_ed}.yaml")
        path = ROOT / "docs" / text
        expected = truth(old_pkg.data, new_pkg.data)
        marks, values = by_marks(old_pkg, new_pkg, read_paragraphs(path)), by_values(old_pkg, path)
        for method, found in (("пометки «в ред.»", marks), ("сверка значений", values),
                              ("пометки + значения", marks | values)):
            c = Counts()
            c.add(expected, found)
            rows.append({"редакции": f"{old_ed} → {new_ed}", "метод": method, "изменено (эталон)": len(expected),
                         "TP": c.tp, "FP": c.fp, "FN": c.fn, "полнота": round(c.recall, 3),
                         "точность": round(c.precision, 3),
                         "пропущены": ", ".join(sorted(expected - found)), "лишние": ", ".join(sorted(found - expected))})

    print(f"{'редакции':26} {'метод':20} {'эталон':>6} {'TP':>3} {'FP':>3} {'FN':>3} {'полнота':>8} {'точность':>8}")
    for r in rows:
        print(f"{r['редакции']:26} {r['метод']:20} {r['изменено (эталон)']:>6} {r['TP']:>3} {r['FP']:>3} {r['FN']:>3} "
              f"{r['полнота']:>8} {r['точность']:>8}" + (f"  пропущены: {r['пропущены']}" if r["пропущены"] else ""))
    out = USER_DIR / "results" / f"editions_{datetime.now():%Y%m%d_%H%M%S}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter=";")
        w.writeheader()
        w.writerows(rows)
    print(f"\nРезультаты: {out}")


if __name__ == "__main__":
    main()
