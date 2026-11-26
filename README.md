# Конструктор расписания ИЕНИМ — MVP

## Быстрый запуск (для пользователей)

**Windows:** дважды щёлкните `start.bat`  
**macOS:** дважды щёлкните `start.command` (при первом запуске система может спросить разрешение)

Откроется страница в браузере. Загрузите три Excel-файла:

1. нагрузка (курсы и группы);
2. аудитории и сетка слотов;
3. анкета преподавателей.

Нажмите **«Собрать расписание»** и скачайте готовый `schedule.xlsx`.  
Полный прогон на всех данных может занять несколько минут — окно запуска не закрывайте.

Первый запуск сам создаст `.venv` и поставит зависимости (нужен установленный Python 3.11+).

## Тесты

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

macOS / Linux:

```bash
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
```

Покрыты: вместимость +20%, soft `screen`/`internet`, автонарезка подгрупп парсера, sport/PE, человекочитаемый отчёт/экспорт, smoke солвера на мини-данных.  
Подробная карта покрытия и пробелы: [`docs/testing.md`](docs/testing.md).

## Запуск из терминала (для разработки)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m parser.importer
.\.venv\Scripts\python.exe mvp_1.py --scope c25,c26,c27,c38,c45
```

Импортёр читает Excel из `parser/tables` и формирует `parser/data.json`. Физкультура из импортированной сетки передаётся решателю как закреплённые события. Для заранее занятой аудитории можно запустить импортёр с `--parse-room-occupancy`.

Решатель формирует `outputs/schedule.xlsx` и `outputs/result.json` (или файлы в `runs/<id>/` при запуске через интерфейс). В Excel есть общая сетка на семестр, лист диагностики и лист непоставленных занятий.

Команда выше ограничивает запуск пятью курсами для демо. Для полного набора уберите `--scope …`.

Интерфейс вручную:

```powershell
.\.venv\Scripts\streamlit.exe run app\ui.py
```

## Параметры решателя (CLI)

- `--input PATH` — JSON импортёра; по умолчанию `parser/data.json`.
- `--output PATH` — Excel; по умолчанию `outputs/schedule.xlsx`.
- `--json-output PATH` — JSON результата; по умолчанию `outputs/result.json`.
- `--scope c1,c2` — ограничить запуск указанными ID курсов.
- `--max-time SECONDS` — лимит времени поиска.
- `--strategy auto|monolithic|two_phase` — стратегия решателя.

## Формат и ограничения

Контракт JSON импортёра описан в `docs/SCHEMA-course-instances.md`, ограничения решателя — в `docs/solver-constraints.md`, тесты — в `docs/testing.md`.
