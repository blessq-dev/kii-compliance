"""Чтение текста нормативного документа (.docx КонсультантПлюс) и выявление изменений без ИИ.

В тексте КонсультантПлюс после изменённого пункта стоит пометка вида
«(п. 5 в ред. Постановления Правительства РФ от 20.12.2022 N 2360)», «(пп. "а" введен …)»
или абзац «… утратил силу. - Постановление … от 07.11.2025 N 1762». По датам изменяющих
актов можно автоматически определить, какие места документа изменились после даты,
на которую составлен пакет правил, — то есть устарел ли пакет и что в нём проверить.
"""

import html
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# «от 20.12.2022 N 2360», «от 07.04.2025 N 58-ФЗ»
ACT = re.compile(r"от (\d{2})\.(\d{2})\.(\d{4}) N (\d+(?:-ФЗ)?)")
MARK = re.compile(r"в ред\.|введен|утратил", re.IGNORECASE)


@dataclass
class Amendment:
    place: str               # где изменение: пункт из пометки или начало изменённого абзаца
    kind: str                # изменено | введено | утратило силу
    acts: list[tuple[date, str]]  # изменяющие акты (дата, номер)
    note: str                # текст пометки

    @property
    def last(self) -> date:
        return max(d for d, _ in self.acts)


def read_paragraphs(path: Path | str) -> list[str]:
    """Абзацы документа .docx (включая ячейки таблиц), пустые пропускаются."""
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    out = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        text = html.unescape("".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))).strip()
        if text:
            out.append(text)
    return out


def _kind(note: str) -> str:
    low = note.lower()
    if "утратил" in low:
        return "утратило силу"
    if "введен" in low and "в ред." not in low:
        return "введено"
    return "изменено"


POINT = re.compile(r"^(\d+(?:\(\d+\)|\.\d+)?)\.(?:\s|$)")  # «5.», «10(1).», «10.1. Текст …»
CODE = re.compile(r"^[А-Я0-9]{3}\.\d+$")  # код меры в таблице приложения (приказ № 239)
PARTS = {"ПРАВИЛА": "Правила", "ПЕРЕЧЕНЬ": "Перечень", "ТРЕБОВАНИЯ": "Требования"}  # заголовки частей


def _place(paragraphs: list[str], i: int) -> str:
    """Место изменения для пометки paragraphs[i]: пункт из самой пометки («п. 10(1)»),
    иначе ближайший выше номер пункта (абзац «5.» в таблице или «19(2). …» в тексте),
    иначе начало изменённого абзаца."""
    note = paragraphs[i]
    m = re.match(r"\((пп?\. [^ ]+)", note)
    if m:
        return m.group(1)
    if not note.startswith("("):  # абзац «… утратил силу. - …» сам является местом изменения
        m = POINT.match(note)
        return f"п. {m.group(1)}" if m else note[:90] + ("…" if len(note) > 90 else "")
    for j in range(i - 1, max(i - 40, -1), -1):  # строки таблицы п. 3 — до 30 абзацев
        if CODE.match(paragraphs[j]):
            return "мера " + re.sub(r"^0", "О", paragraphs[j])  # «0ДТ.2» в тексте КонсультантПлюс
        m = POINT.match(paragraphs[j])
        if m:
            return f"п. {m.group(1)}"
    prev = paragraphs[i - 1] if i else ""
    return prev[:90] + ("…" if len(prev) > 90 else "")


def amendments(paragraphs: list[str]) -> list[Amendment]:
    """Все пометки об изменениях в тексте, кроме «Списков изменяющих документов» в шапках."""
    out, part = [], ""
    for i, p in enumerate(paragraphs):
        part = PARTS.get(p, part)
        if not MARK.search(p) or not ACT.search(p):
            continue
        if i > 0 and paragraphs[i - 1].startswith("Список изменяющих документов"):
            continue  # шапка документа или части — перечень всех изменяющих актов
        if p.startswith("(") or "утратил" in p.lower():
            acts = [(date(int(y), int(mo), int(d)), n) for d, mo, y, n in ACT.findall(p)]
            place = _place(paragraphs, i)
            out.append(Amendment(f"{part}, {place}" if part else place, _kind(p), acts, p))
    return out


def changed_after(paragraphs: list[str], since: date) -> list[Amendment]:
    """Места документа, изменённые актами, принятыми после даты since (дата пакета правил)."""
    return [a for a in amendments(paragraphs) if a.last > since]


# ---------------- связь изменений с правилами пакета ----------------

# «ПП РФ № 127, Перечень показателей, п. 10(1)», «… № 239, Требования, п. 22», «Приказ ФСТЭК России № 235, п. 10.1»
SOURCE_POINT = re.compile(r"(Правил[а-я]*|Перечень показателей|Требования|№ 235)[^,]*, (?:приложение, )?"
                          r"п\. (\d+(?:\(\d+\)|\.\d+)?)")


def _rule_points(pkg_data: dict) -> dict[tuple[str, str], list[str]]:
    """{(часть документа, номер пункта): [коды правил]} по полю source всех правил пакета."""
    out: dict[tuple[str, str], list[str]] = {}
    for items in pkg_data.values():
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict) or "source" not in it:
                continue
            code = str(it.get("id") or it.get("code"))
            if CODE.match(code):
                out.setdefault(("мера", code), []).append(code)
            for part, num in SOURCE_POINT.findall(it["source"]):
                key = ("Перечень" if part.startswith("Перечень") else
                       "Правила" if part.startswith("Правил") else "Требования", num)
                out.setdefault(key, []).append(code)
    return out


@dataclass
class StaleItem:
    place: str               # часть документа и пункт
    kind: str                # изменено | введено | утратило силу
    last: date               # дата последнего изменяющего акта
    rules: list[str]         # правила пакета, основанные на этом пункте (пусто — правила нет)


def stale_rules(pkg_data: dict, since: date, paragraphs: list[str]) -> list[StaleItem]:
    """Что в тексте документа изменилось после даты пакета since и какие правила пакета это затрагивает.

    Пустой список — пакет соответствует тексту (по пометкам об изменениях). Пункт без правил
    означает, что изменилось положение, которое в пакете не формализовано (или его нужно добавить).
    """
    points = _rule_points(pkg_data)
    out: dict[str, StaleItem] = {}
    for a in changed_after(paragraphs, since):
        m = re.search(r"(Правила|Перечень|Требования), п\. (\d+(?:\(\d+\)|\.\d+)?)$", a.place)
        code = re.search(r"мера (\S+)$", a.place)
        rules = (points.get((m.group(1), m.group(2)), []) if m else
                 points.get(("мера", code.group(1)), []) if code else [])
        item = out.get(a.place)
        if item is None or a.last > item.last:
            out[a.place] = StaleItem(a.place, a.kind, a.last, sorted(set(rules)))
    return list(out.values())


# Документ по заголовку (первый абзац текста КонсультантПлюс) → вид правил пакета
DOCUMENT_KINDS = [(r"N 127(?!\d)", "categorization"), (r"N 239(?!\d)", "measures"),
                  (r"N 235(?!\d)", "security_system"), (r"N 187-ФЗ", "spheres")]


def document_kind(paragraphs: list[str]) -> str | None:
    """Вид правил, к которому относится документ (по заголовку), или None — документ не из базы правил."""
    head = paragraphs[0] if paragraphs else ""
    return next((kind for pattern, kind in DOCUMENT_KINDS if re.search(pattern, head)), None)


def edition_of(paragraphs: list[str]) -> date | None:
    """Дата редакции из заголовка «… (ред. от 07.11.2025) …»."""
    m = re.search(r"ред\. от (\d{2})\.(\d{2})\.(\d{4})", paragraphs[0] if paragraphs else "")
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None
