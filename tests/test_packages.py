"""Пакеты правил, редакции документов, верификация и анализ влияния.

Главный сценарий — «вышла новая редакция приказа»: в папку rules/ добавляется новый
файл-пакет, и движок без изменения кода начинает оценивать по нему объекты с даты
вступления редакции в силу, а прежняя редакция остаётся для прошлых дат.

В базе правил есть реальные редакции: исходные (2017–2019 гг.) и действующие (2023–2025 гг.).
Переход между ними проверяется на настоящих документах; для сценариев «следующая редакция»
к копии базы правил добавляются условные редакции на 2027 г.
"""

import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from conftest import ORIGINAL_DATE
from engine.assessment import assess
from engine.dataset import implemented_codes, load_objects
from engine.impact import (ADDED, CHANGED, REMOVED, base_set_changes, diff_rules, impact_on_objects,
                           previous_edition, requirement_changes)
from engine.measures import required_measures
from engine.rules_loader import (KINDS, RULES_DIR, RuleBaseError, check_package, edition_dates, find_packages,
                                 load_rules, read_package)
from engine.verification import ERROR, WARNING, compare_findings, verify_package, verify_rules

CURRENT_DATE, NEXT_DATE = date(2026, 10, 1), date(2027, 3, 1)


def _read(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _latest(rules_dir: Path, folder: str) -> Path:
    """Пакет последней редакции документа (файлы названы датами, сортировка по имени)."""
    return sorted((rules_dir / folder).glob("*.yaml"))[-1]


@pytest.fixture
def rules_copy(tmp_path):
    """Копия базы правил, в которую тест может добавлять новые редакции."""
    dst = tmp_path / "rules"
    shutil.copytree(RULES_DIR, dst)
    return dst


@pytest.fixture(scope="module")
def original():
    return load_rules(on_date=ORIGINAL_DATE)


@pytest.fixture(scope="module")
def current():
    return load_rules(on_date=CURRENT_DATE)


def new_edition_239(rules_dir: Path) -> Path:
    """Условная следующая редакция приказа № 239 (для теста): УПД.8 снова включена в набор
    1 категории, ЗИС.32 исключена из набора 3 категории."""
    old = _read(_latest(rules_dir, "fstek-239"))
    old["document"].update(edition="условная редакция для теста", effective_from=date(2027, 1, 1))
    for m in old["measures"]:
        if m["code"] == "УПД.8":
            m["categories"] = [1]
        if m["code"] == "ЗИС.32":
            m["categories"] = [c for c in m["categories"] if c != 3]
    path = rules_dir / "fstek-239" / "2027-01-01.yaml"
    _write(path, old)
    return path


def new_edition_127(rules_dir: Path) -> Path:
    """Условная следующая редакция ПП № 127: у п. 10 для III категории введён порог «более 3»."""
    old = _read(_latest(rules_dir, "pp-127"))
    old["document"].update(edition="условная редакция для теста", effective_from=date(2027, 1, 1))
    for ind in old["indicators"]:
        if ind["id"] == "10":
            ind["values"][3] = {"min": 3, "min_incl": False, "max": 70, "max_incl": True,
                                "text": "более 3, но менее или равно 70"}
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
        assert (RULES_DIR.parent / p.passport["file"]).exists(), p.passport["file"]


def test_two_real_editions_of_each_document(original, current):
    """Для каждого документа в базе две редакции: исходная и действующая."""
    for kind in KINDS:
        assert original.packages[kind].path != current.packages[kind].path
    assert {k: p.path.name for k, p in current.packages.items()} == {
        "spheres": "2025-04-07.yaml", "categorization": "2025-11-07.yaml",
        "measures": "2024-08-28.yaml", "security_system": "2023-04-20.yaml"}


def test_editions_selected_by_date(rules_copy):
    new_edition_239(rules_copy)
    old, new = load_rules(rules_copy, CURRENT_DATE), load_rules(rules_copy, NEXT_DATE)
    assert old.packages["measures"].passport["edition"] == "в ред. от 28.08.2024"
    assert new.packages["measures"].passport["edition"] == "условная редакция для теста"
    # остальные документы не менялись — выбраны те же пакеты
    assert old.packages["categorization"].path == new.packages["categorization"].path
    assert "условная редакция для теста" in " ".join(new.editions())


def test_new_edition_changes_assessment_without_code_changes(original, current):
    """«Вышел новый приказ»: тот же объект, те же меры — другой результат по новой редакции.
    Объект II категории реализовал весь набор по приказу № 239 в ред. 2018 г.; по действующей
    редакции в набор II категории вошли ДНС.5, ЗИС.6, ИНЦ.6 — это новые несоответствия."""
    implemented = [m["code"] for m in required_measures(original, 2)]
    rep_old = assess(original, "АСУ", "healthcare", {"1": 100}, implemented)
    rep_new = assess(current, "АСУ", "healthcare", {"1": 100}, implemented)
    assert rep_old.categorization.category == rep_new.categorization.category == 2
    assert rep_old.missing_codes == []
    assert sorted(rep_new.missing_codes) == ["ДНС.5", "ЗИС.6", "ИНЦ.6"]


def test_no_edition_for_date(rules_copy):
    with pytest.raises(RuleBaseError, match="Нет редакции"):
        load_rules(rules_copy, date(2000, 1, 1))


def test_two_packages_with_same_date_rejected(rules_copy):
    src = _latest(rules_copy, "fstek-239")
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
    data = _read(_latest(RULES_DIR, "fstek-239"))
    damage(data)
    with pytest.raises(RuleBaseError, match=fragment):
        check_package(data)


def test_invalid_yaml_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("document: [не закрыт", encoding="utf-8")
    with pytest.raises(RuleBaseError, match="YAML"):
        read_package(bad)


# ---------------- верификация ----------------

def test_original_editions_known_text_defects(original):
    """Исходные редакции: замечания — ровно известные дефекты текста ПП № 127 и приказа № 239."""
    findings = verify_rules(original)
    assert [f for f in findings if f.level == ERROR] == []
    assert {f.rule for f in findings if f.level == WARNING} == {"5", "9а", "14", "ДНС.5"}


def test_verification_finds_uncovered_severe_edge_of_item_14(original):
    """П. 14 (2018): допустимый простой до 1 ч включительно (самый тяжёлый случай) не даёт категорию."""
    assert any(f.rule == "14" and "самые тяжёлые значения" in f.text for f in verify_rules(original))


def test_current_editions_fix_original_defects(current):
    """Действующие редакции устранили дефекты исходных (п. 5, 9а, 14, ДНС.5): замечания пропали
    автоматически, без изменения кода. Новые замечания — порог значимости и п. 22 «т»."""
    findings = verify_rules(current)
    assert [f for f in findings if f.level == ERROR] == []
    assert {f.rule for f in findings if f.level == WARNING} == {"5б", "10", "10(1)", "10(2)", "п. 22 «т»"}


def test_verification_finds_missing_significance_threshold(current):
    """П. 10 (ред. 2025): у III категории нет нижней границы — любой банк получает категорию."""
    f = [f for f in verify_rules(current) if f.rule == "10"]
    assert len(f) == 1 and "нет порога значимости" in f[0].text


def test_verification_finds_direction_without_measures(current):
    """П. 22 «т» (защита от DDoS, приказ № 159) — направление без группы мер в приложении."""
    f = [f for f in verify_rules(current) if f.rule == "п. 22 «т»"]
    assert len(f) == 1 and "нет соответствующей группы мер" in f[0].text


def test_verification_of_directions_detects_mismatch():
    data = _read(_latest(RULES_DIR, "fstek-239"))
    data["directions"][0]["group"] = None                     # «а» без группы → ИАФ ни к чему не привязана
    data["directions"][1]["group"] = "ЖЖЖ"                    # несуществующая группа — ошибка
    data["measures"] = [m for m in data["measures"] if m["group"] != "ОПС"]  # группа ОПС пуста
    found = {(f.level, f.rule) for f in verify_package(check_package(data))}
    assert {(WARNING, "п. 22 «а»"), (ERROR, "п. 22 «б»"), (WARNING, "п. 22 «в»"), (WARNING, "ИАФ"),
            (WARNING, "УПД")} <= found


def test_new_edition_fix_is_detected(rules_copy):
    """Если следующая редакция устанавливает порог для п. 10, замечание к п. 10 пропадает."""
    pkg_127 = read_package(new_edition_127(rules_copy))
    assert not any(f.rule == "10" for f in verify_package(pkg_127))


@pytest.mark.parametrize("damage, rule, fragment", [
    (lambda ms: ms.append(dict(ms[0])), "ИАФ.0", "дважды"),
    (lambda ms: ms[0].pop("source"), "ИАФ.0", "источник"),
    (lambda ms: ms[0].update(categories=[4]), "ИАФ.0", "недопустимые категории"),
    (lambda ms: ms[0].update(code="ЖЖЖ.1"), "ЖЖЖ.1", "groups"),
])
def test_verification_errors_in_measures(damage, rule, fragment):
    data = _read(_latest(RULES_DIR, "fstek-239"))
    damage(data["measures"])
    found = [f for f in verify_package(check_package(data)) if f.level == ERROR]
    assert any(f.rule == rule and fragment in f.text for f in found)


def test_verification_errors_in_categorization():
    data = _read(_latest(RULES_DIR, "pp-127"))
    inds = {i["id"]: i for i in data["indicators"]}
    inds["1"]["applies_if"] = "нет_такого"
    inds["2б"]["values"] = {k: v for k, v in inds["2б"]["values"].items() if k != 1}  # якорь YAML — копия
    inds["2а"].pop("source")
    found = [f for f in verify_package(check_package(data)) if f.level == ERROR]
    assert [(f.rule, f.text.split()[0]) for f in found] == [("1", "условие"), ("2а", "нет"), ("2б", "диапазоны")]


# ---------------- анализ влияния ----------------

def test_diff_between_real_editions(original, current):
    """Изменения исходных редакций → действующих, найденные автоматически."""
    text = [str(c) for c in diff_rules(original, current)]
    for expected in ("Мера ДНС.5: изменено — добавлена в набор 2 категории",
                     "Мера ЗИС.31: изменено — исключена из набора 1 категории",
                     "Показатель 9а: исключено", "Показатель 5: исключено",
                     "Сфера real_estate: добавлено — Государственная регистрация прав на недвижимое имущество "
                     "и сделок с ним"):
        assert expected in text, expected
    assert any(t.startswith("Показатель 10(7): добавлено") for t in text)
    assert any(t.startswith("Требование С.7: изменено") for t in text)
    assert any(t.startswith("Требование С.18: добавлено") for t in text)


def test_diff_between_next_editions(rules_copy):
    new_edition_239(rules_copy)
    new_edition_127(rules_copy)
    changes = diff_rules(load_rules(rules_copy, CURRENT_DATE), load_rules(rules_copy, NEXT_DATE))
    text = [str(c) for c in changes]
    assert "Мера УПД.8: изменено — добавлена в набор 1 категории" in text
    assert "Мера ЗИС.32: изменено — исключена из набора 3 категории" in text
    assert any(c.area == "Показатель" and c.rule == "10" and c.what == CHANGED for c in changes)
    assert len(changes) == 3


def test_diff_detects_added_rules(rules_copy):
    path = new_edition_239(rules_copy)
    data = _read(path)
    data["measures"].append({"code": "ИАФ.99", "title": "Новая мера", "categories": [1],
                             "source": "условный пункт для теста"})
    _write(path, data)
    changes = diff_rules(load_rules(rules_copy, CURRENT_DATE), load_rules(rules_copy, NEXT_DATE))
    assert any(c.rule == "ИАФ.99" and c.what == ADDED for c in changes)


def test_same_rules_no_diff():
    assert diff_rules(load_rules(), load_rules()) == []


def test_impact_on_reference_objects(original, current):
    """Влияние перехода с исходных редакций на действующие на объекты тестового набора."""
    states = [{"object_name": o["name"], "sphere": o["sphere"], "indicators": o.get("indicators") or {},
               "attributes": o.get("attributes") or {}, "implemented": implemented_codes(original, o["implemented"])}
              for o in load_objects()]
    impact = {i.name: i for i in impact_on_objects(original, current, states)}

    # п. 14 = 3 ч — по исходной редакции I категория (буквальное «более 1»), по действующей — III
    obj10 = impact["Информационная система оборонного предприятия"]
    assert (obj10.category_old, obj10.category_new) == (1, 3)
    assert obj10.no_longer_required
    assert obj10.became_required == ["ЗИС.6"]  # ЗИС.6 не входила ни в один набор 2018 г., теперь — во все

    # объект II категории: в набор II вошли ДНС.5, ЗИС.6, ИНЦ.6 — новые несоответствия;
    # ЗИС.23–29 из набора II исключены
    obj02 = impact["АСУ ТП районной котельной"]
    assert obj02.category_old == obj02.category_new == 2
    assert obj02.became_required == obj02.new_missing == ["ДНС.5", "ЗИС.6", "ИНЦ.6"]
    assert obj02.no_longer_required == ["ЗИС.23", "ЗИС.24", "ЗИС.25", "ЗИС.28", "ЗИС.29"]

    # показатели, которых не было в исходной редакции (п. 9, 5а, 10(1)), — оценка по ней невозможна
    assert "по прежней редакции невозможна" in impact["Информационная система крупного налогоплательщика"].error

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
    old, new = load_rules(rules_copy, CURRENT_DATE), load_rules(rules_copy, NEXT_DATE)
    [res] = impact_on_objects(old, new, [{"object_name": "Х", "sphere": "healthcare", "indicators": {"1": 30},
                                          "implemented": []}])
    assert res.error and "уточнить исходные данные" in res.error and res.category_old == 3


def test_impact_of_changed_indicator_type(original, current):
    """П. 4а в исходной редакции — территория (выбор), в действующей — число абонентов:
    прежние данные объекта не подходят, анализ влияния просит уточнить их."""
    [res] = impact_on_objects(original, current, [{"object_name": "Х", "sphere": "telecom",
                                                   "indicators": {"4а": "subject"}, "implemented": []}])
    assert res.category_old == 2 and "уточнить исходные данные" in res.error
    assert any(c.rule == "4а" and c.what == CHANGED for c in diff_rules(original, current))
    assert not any(c.what == REMOVED and c.rule == "4а" for c in diff_rules(original, current))


# ---------------- добавление пакета пользователем ----------------

def test_install_new_edition(rules_copy):
    from engine.verification import install_package
    src = new_edition_239(rules_copy)
    raw = src.read_bytes()
    src.unlink()
    path, findings = install_package(raw, rules_copy)
    assert path == rules_copy / "fstek-239" / "2027-01-01.yaml"
    assert all(f.level == WARNING for f in findings)
    assert load_rules(rules_copy, NEXT_DATE).packages["measures"].path == path
    with pytest.raises(RuleBaseError, match="уже есть"):
        install_package(raw, rules_copy)


def test_install_rejects_package_with_errors(rules_copy):
    from engine.verification import install_package
    data = _read(_latest(rules_copy, "fstek-239"))
    data["document"]["effective_from"] = date(2027, 1, 1)
    data["measures"][0].pop("source")
    before = sorted(rules_copy.rglob("*.yaml"))
    with pytest.raises(RuleBaseError, match="ошибки"):
        install_package(yaml.safe_dump(data, allow_unicode=True).encode("utf-8"), rules_copy)
    with pytest.raises(RuleBaseError, match="YAML"):
        install_package(b"\xff\xfe", rules_copy)
    assert sorted(rules_copy.rglob("*.yaml")) == before


# ---------------- состояния базы правил и замечания в отчёте ----------------

def test_edition_dates():
    """Даты смены редакций: первая — когда есть пакеты всех видов (приказ № 235 ред. 2019 г.)."""
    assert [f"{d:%Y-%m-%d}" for d in edition_dates(find_packages())] == [
        "2019-03-27", "2023-04-20", "2024-08-28", "2025-04-07", "2025-11-07"]


def test_compare_findings(original, current):
    resolved, appeared, kept = compare_findings(verify_rules(original), verify_rules(current))
    assert {f.rule for f in resolved} == {"5", "9а", "14", "ДНС.5"}
    assert {f.rule for f in appeared} == {"5б", "10", "10(1)", "10(2)", "п. 22 «т»"}
    assert kept == []


def test_report_contains_verifier_notes(current):
    """В отчёт попадают замечания проверки к заполненным показателям и к п. 22 приказа № 239."""
    rep = assess(current, "АБС", "finance", {"10": 50}, [], attributes={"financial_org": True})
    assert any(w.startswith("Показатель 10:") and "порога значимости" in w for w in rep.warnings)
    assert any("п. 22 «т»" in w for w in rep.warnings)
    rep = assess(current, "МИС", "healthcare", {"1": 30}, [])
    assert not any(w.startswith("Показатель") for w in rep.warnings)
    assert assess(current, "НИИ", "science", {}, []).warnings == []  # не значимый — без замечаний к мерам


def test_changes_against_previous_edition(current):
    """Пометки «новое в редакции»: изменения действующей редакции относительно предыдущей."""
    packages = find_packages()
    meas, sec = current.packages["measures"], current.packages["security_system"]
    prev_meas, prev_sec = previous_edition(packages, meas), previous_edition(packages, sec)
    assert prev_meas.path.name == "2018-08-09.yaml" and prev_sec.path.name == "2019-03-27.yaml"
    assert base_set_changes(prev_meas, meas, 2) == (["ДНС.5", "ЗИС.6", "ИНЦ.6"],
                                                    ["ЗИС.23", "ЗИС.24", "ЗИС.25", "ЗИС.28", "ЗИС.29"])
    changes = requirement_changes(prev_sec, sec)
    assert {i for i, w in changes.items() if w == ADDED} == {"С.18", "Т.8"}
    assert changes["С.7"] == CHANGED and "С.2" not in changes
    assert previous_edition(packages, prev_meas) is None
