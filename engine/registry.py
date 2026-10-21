"""Перечень оценок объектов субъекта КИИ — файлы JSON в папке data/assessments/.

Без базы данных: одна оценка — один файл. Файл содержит данные формы (для продолжения
оценки) и краткие итоги (для сводной таблицы перечня).
"""

import json
import re
from datetime import datetime
from pathlib import Path

from engine.paths import USER_DIR

REGISTRY_DIR = USER_DIR / "assessments"


def _slug(name: str) -> str:
    """Имя файла из наименования объекта: буквы, цифры, подчёркивания."""
    s = re.sub(r"[^\w]+", "_", name.strip().lower(), flags=re.UNICODE).strip("_")
    return s[:60] or "объект"


def save(state: dict, summary: dict, directory: Path = REGISTRY_DIR) -> Path:
    """Сохраняет оценку. Повторное сохранение того же объекта перезаписывает файл."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_slug(state.get('object_name', ''))}.json"
    data = {"saved_at": datetime.now().isoformat(timespec="seconds"), "summary": summary, "state": state}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_all(directory: Path = REGISTRY_DIR) -> list[dict]:
    """Все сохранённые оценки: [{file, saved_at, summary, state}], новые сверху. Битые файлы пропускаются."""
    if not directory.exists():
        return []
    items = []
    for f in directory.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            items.append({"file": f.name, **data})
        except (ValueError, OSError):
            continue
    return sorted(items, key=lambda i: i.get("saved_at", ""), reverse=True)


def load(file_name: str, directory: Path = REGISTRY_DIR) -> dict:
    return json.loads((directory / Path(file_name).name).read_text(encoding="utf-8"))["state"]


def delete(file_name: str, directory: Path = REGISTRY_DIR) -> None:
    (directory / Path(file_name).name).unlink(missing_ok=True)
