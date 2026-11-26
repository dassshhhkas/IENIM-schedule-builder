#!/bin/bash
cd "$(dirname "$0")"
set -e

if ! command -v python3 >/dev/null 2>&1; then
  echo "Не найден python3. Установите Python 3.11+."
  read -r -p "Нажмите Enter, чтобы закрыть…"
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Создаю виртуальное окружение..."
  python3 -m venv .venv
fi

if ! .venv/bin/python -c "import streamlit, ortools, openpyxl, pandas" >/dev/null 2>&1; then
  echo "Устанавливаю зависимости (первый запуск может занять несколько минут)..."
  .venv/bin/python -m ensurepip --upgrade >/dev/null 2>&1 || true
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e .
fi

echo "Открываю интерфейс в браузере..."
echo "Это окно можно свернуть; не закрывайте его, пока работаете с расписанием."
.venv/bin/python -m streamlit run app/ui.py --browser.gatherUsageStats false
echo
read -r -p "Нажмите Enter, чтобы закрыть…"
