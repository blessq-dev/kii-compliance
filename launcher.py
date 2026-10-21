"""Запуск программы в отдельном окне (основа сборки в один exe, см. build_exe.py).

Как работает:
  1. Запускается сервер интерфейса (Streamlit) — тот же exe с ключом --server, в фоне,
     на свободном порту только этого компьютера (localhost).
  2. Открывается окно программы (pywebview — встроенный браузер Windows, WebView2):
     сначала заставка «Загрузка…», затем интерфейс, как только сервер готов.
  3. При закрытии окна сервер останавливается.

Файлы пользователя (перечень объектов, журналы эксперимента, добавленные редакции правил)
сохраняются в папку «КИИ-Оценка — данные» рядом с exe (если там нельзя писать — в
%LOCALAPPDATA%\\КИИ-Оценка). Её передаёт серверу переменная окружения KII_USER_DIR
(см. engine/paths.py).

Запуск без сборки: python launcher.py
"""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)  # True — запущен собранный exe
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))  # app.py, engine/, rules/
TITLE = "Оценка соответствия значимого объекта КИИ"
SPLASH = """<html><body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
font-family:Segoe UI,sans-serif;background:#f5f7fb;color:#14233a"><div style="text-align:center">
<div style="font-size:48px">🛡️</div><div style="font-size:20px;font-weight:600;margin-top:12px">{title}</div>
<div style="color:#566175;margin-top:8px">{text}</div></div></body></html>"""


def user_dir() -> Path:
    """Папка для файлов пользователя: рядом с exe, если туда можно писать, иначе в профиле."""
    if not FROZEN:
        return BUNDLE / "data"
    for folder in (Path(sys.executable).resolve().parent / "КИИ-Оценка — данные",
                   Path(os.environ.get("LOCALAPPDATA", Path.home())) / "КИИ-Оценка"):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / ".проверка").write_text("", encoding="utf-8")
            (folder / ".проверка").unlink()
            return folder
        except OSError:
            continue
    raise OSError("Нет папки, доступной для записи")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_server(port: int) -> None:
    """Режим сервера: Streamlit с интерфейсом app.py (вызывается из того же exe с ключом --server)."""
    os.chdir(BUNDLE)  # здесь .streamlit/config.toml — тема и настройки интерфейса
    from streamlit.web import bootstrap
    flags = {"server.port": port, "server.address": "localhost", "server.headless": True,
             "server.fileWatcherType": "none", "server.runOnSave": False,
             "global.developmentMode": False, "browser.gatherUsageStats": False}
    bootstrap.load_config_options(flag_options=flags)
    bootstrap.run(str(BUNDLE / "app.py"), False, [], flags)


def wait_and_show(window, url: str, server: subprocess.Popen) -> None:
    """Ждёт, пока сервер ответит (до 90 с), и открывает в окне интерфейс."""
    for _ in range(180):
        if server.poll() is not None:
            break
        try:
            urllib.request.urlopen(url + "/_stcore/health", timeout=1)
            window.load_url(url)
            return
        except OSError:
            time.sleep(0.5)
    window.load_html(SPLASH.format(title=TITLE, text="Не удалось запустить программу. Закройте окно и "
                                                     "запустите её ещё раз."))


def main() -> None:
    import webview  # pywebview

    port = free_port()
    env = dict(os.environ, KII_USER_DIR=str(user_dir())) if FROZEN else dict(os.environ)
    cmd = [sys.executable, "--server", str(port)] if FROZEN else \
        [sys.executable, str(Path(__file__).resolve()), "--server", str(port)]
    server = subprocess.Popen(cmd, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        window = webview.create_window(TITLE, html=SPLASH.format(title=TITLE, text="Загрузка…"),
                                       width=1440, height=920, min_size=(1000, 650), maximized=True)
        webview.start(wait_and_show, (window, f"http://localhost:{port}", server))
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--server":
        run_server(int(sys.argv[2]))
    else:
        main()
