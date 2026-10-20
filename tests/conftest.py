"""Добавляет корень проекта в путь импорта, чтобы тесты видели пакет engine."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
