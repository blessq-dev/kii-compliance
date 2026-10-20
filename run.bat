@echo off
chcp 65001 >nul
rem Запуск прототипа двойным щелчком.
rem Первый запуск: создаёт окружение .venv и ставит зависимости (нужен интернет, 1-3 минуты).
rem Следующие запуски: сразу открывает программу в браузере.
cd /d "%~dp0"

rem Ищем Python: сначала лаунчер py (ставится с python.org), затем python.
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY (
    echo Python не найден.
    echo Установите Python 3.11 или новее с https://www.python.org/downloads/
    echo и при установке отметьте галочку "Add python.exe to PATH".
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Первый запуск: установка зависимостей, подождите 1-3 минуты...
    %PY% -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :error
)

echo Программа запускается, через несколько секунд откроется браузер.
echo Адрес: http://localhost:8501
echo Чтобы завершить работу, закройте это окно.
start "" /b cmd /c "ping -n 5 127.0.0.1 >nul & start http://localhost:8501"
".venv\Scripts\python.exe" -m streamlit run app.py
exit /b 0

:error
echo.
echo Ошибка установки. Проверьте подключение к интернету и запустите run.bat ещё раз.
echo Если ошибка повторится, удалите папку .venv и попробуйте снова.
pause
exit /b 1
