# Тестовое покрытие

Документ описывает, **что** покрыто автотестами, **как** их запускать и **куда** добавлять новые кейсы.  
Код тестов: каталог `tests/`. Фреймворк: **pytest**.

Связанные документы: [solver-constraints.md](solver-constraints.md), [SCHEMA-course-instances.md](SCHEMA-course-instances.md), [TZ-parser.md](TZ-parser.md), [TZ-solver.md](TZ-solver.md).

---

## 1. Запуск

Нужен Python 3.11+ и виртуальное окружение проекта.

```bash
# один раз — зависимости для разработки (pytest)
.venv/bin/python -m pip install -e ".[dev]"

# все тесты
.venv/bin/python -m pytest

# один файл / один тест
.venv/bin/python -m pytest tests/test_capacity.py -v
.venv/bin/python -m pytest tests/test_solver_smoke.py::test_monolithic_smoke_places_one_lesson -v
```

Windows (PowerShell):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

Конфиг pytest: секция `[tool.pytest.ini_options]` в `pyproject.toml`  
(`testpaths = ["tests"]`, `pythonpath = ["."]`, тихий режим `-q`).

Ожидаемый результат на актуальном дереве: **33 passed**, время порядка 1–2 с (без полного прогона на реальном `data.json`).

---

## 2. Принципы

| Принцип | Как соблюдаем |
|---------|----------------|
| Быстро | Нет полного солва на институтском Excel; smoke — крошечный JSON |
| Изолированно | Фикстуры в `tests/conftest.py`, временные файлы через `tmp_path` |
| Близко к продукту | Проверяем правила из ТЗ/constraints и человекочитаемый отчёт |
| Без хрупкости UI | Streamlit-страницу не кликаем; проверяем `report_present` и Excel-экспорт |

**Не покрываем (пока):** полный прогон на `parser/data.json`, UI Streamlit end-to-end, нагрузочный OOM, визуальную вёрстку сетки.

---

## 3. Карта покрытия

### 3.1. Сводка по модулям

| Область | Файл тестов | Кол-во | Код продукта |
|---------|-------------|--------|--------------|
| Вместимость +20% | `test_capacity.py` | 4 | `mvp_1.py` → `room_fits_students`, `effective_room_capacity` |
| Soft `screen` / `internet` | `test_soft_equipment.py` | 7 | `room_meets_requirements`, soft-штраф / proxy |
| Классификация warnings | `test_warnings.py` | 2 | `classify_warning_kind`, `partition_warnings` |
| Парсер: подгруппы и sport | `test_parser_instances.py` | 5 | `parser/importer.py` |
| Человекочитаемый отчёт | `test_report_present.py` | 7 | `app/report_present.py` |
| Excel-экспорт | `test_exporter.py` | 1 | `exporter.py` |
| Smoke солвера | `test_solver_smoke.py` | 7 | `solve_schedule`, нормализация week/duration |
| **Итого** | | **33** | |

### 3.2. Солвер — ограничения и адаптер

| Правило / поведение | Где тест | Статус |
|---------------------|----------|--------|
| `students ≤ capacity × 1.2` | `test_capacity`, smoke overbook | покрыто |
| `internet` не hard-kill | `test_soft_equipment` | покрыто |
| `screen` не hard-kill + proxy тип `м` / multimedia | `test_soft_equipment`, smoke | покрыто |
| `computer_class` остаётся hard | `test_soft_equipment` | покрыто |
| `weekly` → week_pattern `all` | `test_solver_smoke` | покрыто |
| `duration_slots` 1.5 → ceil 2 | `test_solver_smoke` | покрыто |
| `venue_type=sport` → виртуальная площадка | `test_solver_smoke` | покрыто |
| Мини-SUCCESS на 1 занятии | `test_solver_smoke` | покрыто |
| Warnings → unplaced / soft / other | `test_warnings` | покрыто |
| Полный two_phase на реальных данных | — | **не покрыто** (ручной / UI-прогон) |
| Repair rounds / лимит времени | — | **не покрыто** |

### 3.3. Парсер

| Правило / поведение | Где тест | Статус |
|---------------------|----------|--------|
| Практика без числа подгрупп + несколько групп → 1 instance на группу | `test_parser_instances` | покрыто |
| Лекция с несколькими группами → один stream | `test_parser_instances` | покрыто |
| Явное число подгрупп → общие `group_ids` на instances | `test_parser_instances` | покрыто |
| Finalize: `students_needed` по своей группе после автонарезки | `test_parser_instances` | покрыто |
| Sport/PE: `needs_physical_room=false`, пустой `allowed_room_ids` | `test_parser_instances` | покрыто |
| Импорт реальных `table.xlsx` / `table2` / `table3` | — | **не покрыто** (дорого; smoke вручную) |
| Раскрытие маркера «все» у физкультуры | частично через finalize/sport | расширить при регрессиях |

### 3.4. Отчёт и экспорт для пользователей

| Правило / поведение | Где тест | Статус |
|---------------------|----------|--------|
| Категории: непостановка / суббота / поздние / wishes… | `test_report_present` | покрыто |
| Тексты без машинных кодов (`UNPLACEABLE_…`) | `test_report_present`, `test_exporter` | покрыто |
| Причина «слишком большая группа» | `test_report_present` | покрыто |
| Листы Excel: Сводка, Расписание, Непоставленные, Замечания | `test_exporter` | покрыто |
| Заголовки пользовательских колонок (без «Код», entity_id) | `test_exporter` | покрыто |

---

## 4. Структура каталога `tests/`

```
tests/
  conftest.py                 # фикстуры: tiny_schedule_data, solver_config, sample_result_with_warnings
  test_capacity.py
  test_soft_equipment.py
  test_warnings.py
  test_parser_instances.py
  test_report_present.py
  test_exporter.py
  test_solver_smoke.py
```

### Фикстуры (`conftest.py`)

- **`tiny_schedule_data`** — минимальный валидный JSON для `solve_schedule` (1 комната, 1 группа, 1 курс, 2 слота).
- **`solver_config`** — короткий monolithic-прогон (`max_time_in_seconds=5`, 1 worker).
- **`sample_result_with_warnings`** — готовый ответ солвера с unplaced + soft для отчёта/Excel.
- **`dumps`** — `json.dumps(..., ensure_ascii=False)`.

---

## 5. Как добавить тест

1. Выбрать файл по области или создать `tests/test_<тема>.py`.
2. Импортировать только нужные функции (без тяжёлого I/O).
3. Для солвера — расширять `tiny_schedule_data`, не подключать `parser/data.json`.
4. Для Excel — писать во `tmp_path`, читать через `openpyxl`.
5. Имя теста: `test_<что_проверяем>` на русском смысле в docstring модуля.
6. Прогнать: `.venv/bin/python -m pytest tests/test_<файл>.py -v`.

Пример (новый кейс вместимости):

```python
def test_overbook_factor_from_config():
    from mvp_1 import resolve_capacity_overbook_factor
    assert resolve_capacity_overbook_factor({"capacity_overbook_factor": 1.5}) == 1.5
```

---

## 6. Пробелы и приоритет доработки

| Приоритет | Что добавить | Зачем |
|-----------|--------------|--------|
| Высокий | Регрессия `time_wish_rules` → hard/soft домен | стык парсер↔солвер (§13.1 A) |
| Высокий | `unplaceable_instance_policy=warn` → warning + частичный schedule | политики dirty-data |
| Средний | Раскрытие PE «все» → нарезка instances | парсер § sport |
| Средний | `weight_preferred_screen` → `UNMET_SOFT_EQUIPMENT` в soft warnings | отчёт по оснащению |
| Низкий | Snapshot листа «Расписание» на 1 группе | визуальная регрессия сетки |
| Низкий | CI (GitHub Actions): `pytest` на PR | дисциплина |

При закрытии пункта из ТЗ или constraints — **в том же PR** добавляйте или обновляйте тест и строку в таблице §3 этого файла.

---

## 7. Связь с ручной приёмкой

Автотесты **не заменяют** полный UI-прогон:

1. `start.command` / `start.bat` → загрузка трёх Excel.  
2. Сборка расписания (лимит ~900 с).  
3. Проверка листов «Сводка» / «Непоставленные» / «Замечания» глазами диспетчера.

Автотесты ловят регресс логики за секунды; ручной прогон — стык данных института и UX.
