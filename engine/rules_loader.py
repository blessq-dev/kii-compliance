"""Загрузка базы правил из пакетов в папке rules/.

Движок не содержит ни одного нормативного значения в коде: все показатели,
диапазоны и меры читаются из YAML. Это позволяет обновить базу правил
(например, при выходе новой редакции документа), не меняя программу.

База правил состоит из пакетов. Пакет — один YAML-файл с правилами одного документа
в одной редакции: rules/<документ>/<дата редакции>.yaml. В начале пакета — паспорт
(раздел document):
  kind           — вид правил (типовая конструкция), который понимает движок;
  act, edition   — документ и его редакция (выводятся в отчёт);
  effective_from — дата, с которой применяется эта редакция.

Для каждого вида правил на дату оценки выбирается действующая редакция — пакет
с наибольшей датой effective_from, не превышающей дату оценки. Новая редакция
документа подключается добавлением нового файла: старый остаётся для оценок
на прошлые даты и для анализа влияния изменений.
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

# Папка с правилами по умолчанию: <корень проекта>/rules
RULES_DIR = Path(__file__).resolve().parent.parent / "rules"

# Виды правил (типовые конструкции) и раздел пакета, в котором лежат сами правила.
KINDS = {
    "spheres": "spheres",                # перечень сфер деятельности субъектов КИИ (187-ФЗ)
    "categorization": "indicators",      # показатели значимости с диапазонами по категориям (ПП № 127)
    "measures": "measures",              # меры с базовыми наборами по категориям (приказ № 239)
    "security_system": "requirements",   # чек-лист организационных требований (приказ № 235)
}
PASSPORT_FIELDS = ("kind", "act", "edition", "effective_from")


class RuleBaseError(ValueError):
    """Пакет правил не может быть загружен (ошибка структуры или паспорта)."""


@dataclass
class Package:
    """Пакет правил: один документ в одной редакции."""

    path: Path
    data: dict

    @property
    def passport(self) -> dict:
        return self.data["document"]

    @property
    def kind(self) -> str:
        return self.passport["kind"]

    @property
    def effective_from(self) -> date:
        return self.passport["effective_from"]

    @property
    def title(self) -> str:
        """Документ и редакция — для отчёта и интерфейса."""
        return f"{self.passport['act']} ({self.passport['edition']})"


@dataclass
class RuleBase:
    """Вся база правил, загруженная в память (редакции, действующие на дату оценки)."""

    categorization: dict  # пакет вида categorization (ПП № 127)
    measures: dict        # пакет вида measures (приказ № 239)
    spheres: dict         # пакет вида spheres (187-ФЗ)
    security: dict        # пакет вида security_system (приказ № 235)
    on_date: date | None = None                                 # дата, на которую выбраны редакции
    packages: dict[str, Package] = field(default_factory=dict)  # {вид правил: выбранный пакет}

    def indicator(self, indicator_id: str) -> dict:
        """Возвращает правило показателя по его номеру в Перечне (например, «2б»)."""
        for ind in self.categorization["indicators"]:
            if ind["id"] == indicator_id:
                return ind
        raise KeyError(f"Показатель {indicator_id!r} отсутствует в базе правил")

    def condition(self, condition_id: str) -> dict:
        """Условие применимости показателя по id (например, «defense_order»)."""
        for c in self.categorization.get("conditions", []):
            if c["id"] == condition_id:
                return c
        raise KeyError(f"Условие применимости {condition_id!r} отсутствует в базе правил")

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


def check_package(data, path: Path | str = "пакет") -> "Package":
    """Проверка структуры пакета: паспорт, известный вид правил, раздел с правилами.

    Это проверка «можно ли загрузить пакет». Содержательная проверка правил
    (разрывы шкал, вложенность наборов и т. п.) — в engine/verification.py.
    """
    name = Path(path).name
    if not isinstance(data, dict) or not isinstance(data.get("document"), dict):
        raise RuleBaseError(f"{name}: нет паспорта пакета (раздел document)")
    passport = data["document"]
    missing = [f for f in PASSPORT_FIELDS if not passport.get(f)]
    if missing:
        raise RuleBaseError(f"{name}: в паспорте не заполнены поля: {', '.join(missing)}")
    if passport["kind"] not in KINDS:
        raise RuleBaseError(f"{name}: неизвестный вид правил {passport['kind']!r} "
                            f"(допустимы: {', '.join(KINDS)})")
    if not isinstance(passport["effective_from"], date):
        raise RuleBaseError(f"{name}: effective_from должна быть датой в формате ГГГГ-ММ-ДД")
    section = KINDS[passport["kind"]]
    if not isinstance(data.get(section), list) or not data[section]:
        raise RuleBaseError(f"{name}: нет правил (раздел {section})")
    return Package(Path(path), data)


def read_package(path: Path | str) -> Package:
    """Читает пакет из файла и проверяет его структуру."""
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise RuleBaseError(f"{path.name}: файл не является корректным YAML ({e})") from e
    return check_package(data, path)


def find_packages(rules_dir: Path | str = RULES_DIR) -> list[Package]:
    """Все пакеты в папке правил (во вложенных папках), по виду правил и дате редакции."""
    packages = [read_package(p) for p in sorted(Path(rules_dir).rglob("*.yaml"))]
    return sorted(packages, key=lambda p: (p.kind, p.effective_from))


def select_packages(packages: list[Package], on_date: date) -> dict[str, Package]:
    """Для каждого вида правил — редакция, действующая на дату on_date."""
    chosen = {}
    for kind in KINDS:
        valid = [p for p in packages if p.kind == kind and p.effective_from <= on_date]
        if not valid:
            raise RuleBaseError(f"Нет редакции правил вида {kind!r}, действующей на {on_date:%d.%m.%Y}")
        latest = max(p.effective_from for p in valid)
        same = [p for p in valid if p.effective_from == latest]
        if len(same) > 1:
            raise RuleBaseError(f"Несколько пакетов вида {kind!r} с одной датой {latest:%d.%m.%Y}: "
                                + ", ".join(p.path.name for p in same))
        chosen[kind] = same[0]
    return chosen


def build_rules(chosen: dict[str, Package], on_date: date | None = None) -> RuleBase:
    """База правил из выбранных пакетов (по одному на каждый вид правил)."""
    return RuleBase(
        categorization=chosen["categorization"].data,
        measures=chosen["measures"].data,
        spheres=chosen["spheres"].data,
        security=chosen["security_system"].data,
        on_date=on_date,
        packages=dict(chosen),
    )


def load_rules(rules_dir: Path | str = RULES_DIR, on_date: date | None = None) -> RuleBase:
    """Читает пакеты правил и возвращает базу, действующую на дату on_date (по умолчанию — сегодня)."""
    on_date = on_date or date.today()
    return build_rules(select_packages(find_packages(rules_dir), on_date), on_date)
