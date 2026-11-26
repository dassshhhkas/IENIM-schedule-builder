@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Конструктор расписания ИЕНИМ

where python >nul 2>&1
if errorlevel 1 (
  echo Не найден Python. Установите Python 3.11+ и отметьте "Add to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Создаю виртуальное окружение...
  python -m venv .venv
  if errorlevel 1 (
    echo Не удалось создать .venv
    pause
    exit /b 1
  )
)

.venv\Scripts\python.exe -c "import streamlit, ortools, openpyxl, pandas" >nul 2>&1
if errorlevel 1 (
  echo Устанавливаю зависимости (первый запуск может занять несколько минут)...
  .venv\Scripts\python.exe -m ensurepip --upgrade >nul 2>&1
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -e .
  if errorlevel 1 (
    echo Установка не удалась.
    pause
    exit /b 1
  )
)

echo Открываю интерфейс в браузере...
echo Окно можно свернуть; не закрывайте его, пока работаете с расписанием.
echo.
.venv\Scripts\python.exe -m streamlit run app\ui.py --browser.gatherUsageStats false
echo.
pause
