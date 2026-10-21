"""Сборка программы в один файл dist/КИИ-Оценка.exe (Windows).

Запуск:  .venv\\Scripts\\python.exe build_exe.py
Нужны пакеты из requirements-build.txt (PyInstaller, pywebview).

В exe упаковываются: launcher.py (точка входа), интерфейс app.py, движок engine/, база
правил rules/, тестовый набор data/test_objects.yaml и настройки интерфейса .streamlit/.
Нормативные документы docs/ в exe не входят — они нужны для составления правил, а не для работы.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = "КИИ-Оценка"
ICON = ROOT / "assets" / "icon.ico"


def make_icon() -> None:
    """Значок программы: синий щит (рисуется один раз, если файла нет)."""
    if ICON.exists():
        return
    from PIL import Image, ImageDraw
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    shield = [(128, 14), (226, 50), (218, 140), (128, 242), (38, 140), (30, 50)]
    d.polygon(shield, fill=(31, 95, 168, 255))
    d.polygon([(128, 40), (202, 66), (196, 136), (128, 214), (60, 136), (54, 66)], fill=(234, 241, 250, 255))
    d.line([(88, 128), (118, 158), (172, 98)], fill=(31, 95, 168, 255), width=20, joint="curve")
    ICON.parent.mkdir(exist_ok=True)
    img.save(ICON, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def build() -> None:
    make_icon()
    sep = ";"  # разделитель «источник;папка в exe» для Windows
    data = [("app.py", "."), ("engine", "engine"), ("rules", "rules"), ("data/test_objects.yaml", "data"),
            (".streamlit", ".streamlit")]
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
           "--name", NAME, "--icon", str(ICON),
           "--exclude-module", "engine.__pycache__"]
    for src, dst in data:
        cmd += ["--add-data", f"{ROOT / src}{sep}{dst}"]
    # app.py и engine/ лежат в exe как данные, поэтому их библиотеки указываются явно
    for pkg in ("streamlit", "altair", "docx"):
        cmd += ["--collect-all", pkg]
    for mod in ("yaml", "pandas", "engine"):
        cmd += ["--hidden-import", mod]
    cmd += ["--copy-metadata", "streamlit", str(ROOT / "launcher.py")]
    subprocess.run(cmd, cwd=ROOT, check=True)
    print(f"\nГотово: {ROOT / 'dist' / (NAME + '.exe')}")


if __name__ == "__main__":
    build()
