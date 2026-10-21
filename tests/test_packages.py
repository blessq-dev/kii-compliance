"""Пакеты правил, редакции документов, верификация и анализ влияния.

Главный сценарий — «вышла новая редакция приказа»: в копию папки rules/ добавляется
новый файл-пакет, и движок без изменения кода начинает оценивать по нему объекты
с даты вступления редакции в силу, а прежняя редакция остаётся для прошлых дат.
"""

import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from engine.assessment import assess
from engine.dataset import implemented_codes, load_objects
from engine.impact import ADDED, CHANGED, diff_rules, impact_on_objects
from engine.measures import required_measures
from engine.rules_loader import (KINDS, RULES_DIR, RuleBaseError, check_package, find_packages, load_rules,
                                 read_package)
from engine.verification import ERROR, WARNING, verify_package, verify_rules

OLD_DATE, NEW_DATE = date(2026, 10, 1), date(2027, 3, 1)


def _read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


@pytest.fixture
def rules_copy(tmp_path):
    """Копия базы правил, в которую тест может добавлять новые редакции."""
    dst = tmp_path / "rules"
    shutil.copytree(RULES_DIR, dst)
    return dst


def new_edition_239(rules_dir: Path) -> Path:
    """Условная новая редакция приказа № 239 (для теста): ДНС.5 включена в набор 2 категории
    (устранено нарушение вложенности) и ЗИС.32 исключена из набора 3 категории."""
    old = _read(next((rules_dir / "fstek-239").glob("*.yaml")))
    old["document"].update(edition="условная редакция для теста", effective_from=date(2027, 1, 1))
    for m in old["measures"]:
        if m["code"] == "ДНС.5":
            m["categories"] = [1, 2, 3]
        if m["code"] == "ЗИС.32":
            m["categories"] = [c for c in m["categories"] if c != 3]
    path = rules_dir / "fstek-239" / "2027-01-01.yaml"
    _write(path, old)
    return path


def new_edition_127(rules_dir: Path) -> Path:
    """Условная новая редакция ПП № 127: у п. 14 для I категории «менее или равно 1»."""
    old = _read(next((rules_dir / "pp-127").glob("*.yaml")))
    old["document"].update(edition="условная редакция для теста", effective_from=date(2027, 1, 1))
    for ind in old["indicators"]:
        if ind["id"] == "14":
            ind["values"][1] = {"max": 1, "max_incl": True, "text": "менее или равно 1"}
            ind.pop("warning", None)
    path = rules_dir / "pp-127" / "2027-01-01.yaml"
    _write(path, old)
    return path


# ---------------- загрузка пакетов ----------------

def test_current_rule_base_is_packages():
    packages = find_packages()
    assert {p.kind for p in packages} == set(KINDS)
    for p in packages:
        assert p.path.parent.parent == RULES_DIR      # rules/<документ>/<дата>.yaml
        assert p.path.stem == f"{p.effective_from:%Y-%m-%d}"
        assert Path(p.passport["file"]).parts[0] == "docs"


def test_editions_selected_by_date(rules_copy):
    new_edition_239(rules_copy)
    old, new = load_rules(rules_copy, OLD_DATE), load_rules(rules_copy, NEW_DATE)
    assert old.packages["measures"].passport["edition"] != "условная редакция для теста"
    assert new.packages["measures"].passport["edition"] == "условная редакция для теста"
    # остальные документы не менялись — выбраны те же пакеты
    assert old.packages["categorization"].path == new.packages["categorization"].path
    assert "условная редакция для теста" in " ".join(new.editions())


def test_new_edition_changes_assessment_without_code_changes(rules_copy):
    """«Вышел новый приказ»: тот же объект, те же меры — другой результат по новой редакции."""
    new_edition_239(rules_copy)
    old, new = load_rules(rules_copy, OLD_DATE), load_rules(rules_copy, NEW_DATE)
    implemented = [m["code"] for m in required_measures(old, 2)]  # весь набор II категории по старой редакции
    rep_old = assess(old, "АСУ", "healthcare", {"1": 100}, implemented)
    rep_new = assess(new, "АСУ", "healthcare", {"1": 100}, implemented)
    assert rep_old.categorization.category == rep_new.categorization.category == 2
    assert rep_old.missing_codes == []
    assert rep_new.missing_codes == ["ДНС.5"]


def test_no_edition_for_date(rules_copy):
    with pytest.raises(RuleBaseError, match="Нет редакции"):
        load_rules(rules_copy, date(2000, 1, 1))


def test_two_packages_with_same_date_rejected(rules_copy):
    src = next((rules_copy / "fstek-239").glob("*.yaml"))
    shutil.copy(src, src.with_name("копия.yaml"))
    with pytest.raises(RuleBaseError, match="Несколько пакетов"):
        load_rules(rules_copy)


@pytest.mark.parametrize("damage, fragment", [
    (lambda d: d.pop("document"), "нет паспорта"),
    (lambda d: d["document"].pop("effective_from"), "effective_from"),
    (lambda d: d["document"].update(kind="неизвестно"), "неизвестный вид"),
    (lambda d: d["document"].update(effective_from="вчера"), "датой"),
    (lambda d: d.update(measures=[]), "нет правил"),
])
def test_broken_package_rejected(damage, fragment):
    data = _read(next((RULES_DIR / "fstek-239").glob("*.yaml")))
    damage(data)
    with pytest.raises(RuleBaseError, match=fragment):
        check_package(data)


def test_invalid_yaml_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("document: [не закрыт", encoding="utf-8")
    with pytest.raises(RuleBaseError, match="YAML"):
        read_package(bad)


# ---------------- верификация ----------------

def test_current_rules_have_no_errors_and_known_text_defects():
    """Действующая база корректна; замечания — ровно известные дефекты текста ПП № 127 и приказа № 239."""
    findings = verify_rules(load_rules())
    assert [f for f in findings if f.level == ERROR] == []
    assert {f.rule for f in findings if f.level == WARNING} == {"5", "9а", "14", "ДНС.5"}


def test_verification_finds_uncovered_severe_edge_of_item_14():
    """П. 14: допустимый простой до 1 ч включительно (самый тяжёлый случай) не даёт категорию."""
    findings = verify_rules(load_rules())
    assert any(f.rule == "14" and "самые тяжёлые значения" in f.text for f in findings)


def test_new_edition_fixes_are_detected(rules_copy):
    """Если новая редакция устраняет дефект, замечание пропадает автоматически."""
    pkg_239 = read_package(new_edition_239(rules_copy))
    pkg_127 = read_package(new_edition_127(rules_copy))
    assert not any(f.rule == "ДНС.5" for f in verify_package(pkg_239))
    assert not any(f.rule == "14" for f in verify_package(pkg_127))


@pytest.mark.parametrize("damage, rule, fragment", [
    (lambda ms: ms.append(dict(ms[0])), "ИАФ.0", "дважды"),
    (lambda ms: ms[0].pop("source"), "ИАФ.0", "источник"),
    (lambda ms: ms[0].update(categories=[4]), "ИАФ.0", "недопустимые категории"),
    (lambda ms: ms[0].update(code="ЖЖЖ.1"), "ЖЖЖ.1", "groups"),
])
def test_verification_errors_in_measures(damage, rule, fragment):
    data = _read(next((RULES_DIR / "fstek-239").glob("*.yaml")))
    damage(data["measures"])
    found = [f for f in verify_package(check_package(data)) if f.level == ERROR]
    assert any(f.rule == rule and fragment in f.text for f in found)


def test_verification_errors_in_categorization():
    data = _read(next((RULES_DIR / "pp-127").glob("*.yaml")))
    inds = {i["id"]: i for i in data["indicators"]}
    inds["1"]["applies_if"] = "нет_такого"
    inds["2б"]["values"] = {k: v for k, v in inds["2б"]["values"].items() if k != 1}  # якорь YAML — копия
    inds["2а"].pop("source")
    found = [f for f in verify_package(check_package(data)) if f.level == ERROR]
    assert [(f.rule, f.text.split()[0]) for f in found] == [("1", "условие"), ("2а", "нет"), ("2б", "диапазоны")]


# ---------------- анализ влияния ----------------

def test_diff_between_editions(rules_copy):
    new_edition_239(rules_copy)
    new_edition_127(rules_copy)
    changes = diff_rules(load_rules(rules_copy, OLD_DATE), load_rules(rules_copy, NEW_DATE))
    text = [str(c) for c in changes]
    assert "Мера ДНС.5: изменено — добавлена в набор 2 категории" in text
    assert "Мера ЗИС.32: изменено — исключена из набора 3 категории" in text
    assert any(c.area == "Показатель" and c.rule == "14" and c.what == CHANGED for c in changes)
    assert len(changes) == 3


def test_diff_detects_added_rules(rules_copy):
    path = new_edition_239(rules_copy)
    data = _read(path)
    data["measures"].append({"code": "ИАФ.99", "title": "Новая мера", "categories": [1],
                             "source": "условный пункт для теста"})
    _write(path, data)
    changes = diff_rules(load_rules(rules_copy, OLD_DATE), load_rules(rules_copy, NEW_DATE))
    assert any(c.rule == "ИАФ.99" and c.what == ADDED for c in changes)


def test_same_rules_no_diff():
    assert diff_rules(load_rules(), load_rules()) == []


def test_impact_on_reference_objects(rules_copy):
    new_edition_239(rules_copy)
    new_edition_127(rules_copy)
    old, new = load_rules(rules_copy, OLD_DATE), load_rules(rules_copy, NEW_DATE)
    states = [{"object_name": o["name"], "sphere": o["sphere"], "indicators": o.get("indicators") or {},
               "attributes": o.get("attributes") or {}, "implemented": implemented_codes(old, o["implemented"])}
              for o in load_objects()]
    impact = {i.name: i for i in impact_on_objects(old, new, states)}
    assert all(i.error is None for i in impact.values())

    # obj10: п. 14 = 3 ч — по старой редакции I категория (буквальное «более 1»), по новой — III
    obj10 = impact["Информационная система оборонного предприятия"]
    assert (obj10.category_old, obj10.category_new) == (1, 3)
    assert obj10.no_longer_required and not obj10.became_required

    # объект II категории: ДНС.5 стала обязательной и не реализована — новое несоответствие
    obj02 = impact["АСУ ТП районной котельной"]
    assert obj02.category_old == obj02.category_new == 2
    assert obj02.became_required == ["ДНС.5"] and obj02.new_missing == ["ДНС.5"]

    # объект без категории не затронут
    assert not impact["CRM-система торговой сети"].changed


def test_impact_reports_inputs_invalid_under_new_edition(rules_copy):
    """Если по новой редакции исходных данных недостаточно, объект помечается, а не теряется."""
    path = new_edition_127(rules_copy)
    data = _read(path)
    for ind in data["indicators"]:
        if ind["id"] == "1":
            ind["applies_if"] = "state_org"
    _write(path, data)
    old, new = load_rules(rules_copy, OLD_DATE), load_rules(rules_copy, NEW_DATE)
    [res] = impact_on_objects(old, new, [{"object_name": "Х", "sphere": "healthcare", "indicators": {"1": 30},
                                          "implemented": []}])
    assert res.error and "уточнить исходные данные" in res.error and res.category_old == 3


# ---------------- добавление пакета пользователем ----------------

def test_install_new_edition(rules_copy):
    from engine.verification import install_package
    src = new_edition_239(rules_copy)
    raw = src.read_bytes()
    src.unlink()
    path, findings = install_package(raw, rules_copy)
    assert path == rules_copy / "fstek-239" / "2027-01-01.yaml"
    assert all(f.level == WARNING for f in findings)
    assert load_rules(rules_copy, NEW_DATE).packages["measures"].path == path
    with pytest.raises(RuleBaseError, match="уже есть"):
        install_package(raw, rules_copy)


def test_install_rejects_package_with_errors(rules_copy):
    from engine.verification import install_package
    data = _read(next((rules_copy / "fstek-239").glob("*.yaml")))
    data["document"]["effective_from"] = date(2027, 1, 1)
    data["measures"][0].pop("source")
    before = sorted(rules_copy.rglob("*.yaml"))
    with pytest.raises(RuleBaseError, match="ошибки"):
        install_package(yaml.safe_dump(data, allow_unicode=True).encode("utf-8"), rules_copy)
    with pytest.raises(RuleBaseError, match="YAML"):
        install_package(b"\xff\xfe", rules_copy)
    assert sorted(rules_copy.rglob("*.yaml")) == before
