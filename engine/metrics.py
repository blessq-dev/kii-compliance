"""Метрики эксперимента для ВКР.

- Точность определения категории (accuracy) — доля объектов, для которых
  категория совпала с эталонной.
- Полнота выявления несоответствий (recall) — доля эталонных отсутствующих
  мер, которые нашла система.
- Точность выявления несоответствий (precision) — доля найденных системой
  несоответствий, которые есть в эталоне; 1 − precision = доля ложных несоответствий.

recall и precision считаются микро-усреднением: TP, FP, FN суммируются
по всем объектам, затем делятся.
"""

from dataclasses import dataclass


@dataclass
class Counts:
    tp: int = 0  # несоответствие есть и в эталоне, и у системы
    fp: int = 0  # система нашла, в эталоне нет (ложное несоответствие)
    fn: int = 0  # в эталоне есть, система не нашла (пропуск)

    def add(self, expected: set[str], found: set[str]) -> None:
        self.tp += len(expected & found)
        self.fp += len(found - expected)
        self.fn += len(expected - found)

    @property
    def recall(self) -> float:
        # Если эталонных несоответствий нет совсем, пропустить было нечего — полнота 1.
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 1.0

    @property
    def precision(self) -> float:
        # Если система ничего не нашла, ложных несоответствий нет — точность 1.
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 1.0

    @property
    def false_rate(self) -> float:
        """Доля ложных несоответствий среди найденных."""
        return 1.0 - self.precision


def category_accuracy(pairs: list[tuple]) -> float:
    """pairs — список (эталонная категория, категория системы); None — «без категории»."""
    if not pairs:
        return 0.0
    return sum(1 for exp, got in pairs if exp == got) / len(pairs)
