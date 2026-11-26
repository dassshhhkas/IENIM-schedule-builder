"""Export a semester timetable grid and supporting diagnostics to Excel."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


COURSE_COLORS = [
    "FFF2CC", "D9EAD3", "D9EAF7", "FCE4D6", "E4DFEC", "DDEBF7",
    "E2F0D9", "F4CCCC", "EADCF8", "D9E1F2", "FCE5CD", "D0E0E3",
]
DAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"]


def _repair_text(value: Any) -> str:
    """Repair common UTF-8-as-Windows-1251 mojibake in imported Russian text."""
    text = "" if value is None else str(value)
    if "Р" not in text and "С" not in text and "вЂ" not in text:
        return text
    try:
        fixed = text.encode("cp1251").decode("utf-8")
        return fixed if sum(ch in fixed for ch in "РС") < sum(ch in text for ch in "РС") else text
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _display(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_repair_text(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(f"{_repair_text(key)}: {_repair_text(item)}" for key, item in value.items())
    return _repair_text(value)


def _course_label(row: dict) -> str:
    name = _repair_text(row.get("course_name") or row.get("name") or "Занятие")
    return re.sub(r"\s*\((?:лекция|практика|лабораторная)\)\s*$", "", name, flags=re.I).strip()


def _lesson_type(row: dict) -> str:
    value = row.get("lesson_type") or row.get("lesson_kind")
    if value:
        text = _repair_text(value)
        normalized = text.casefold().replace("_", " ")
        if "lecture" in normalized or "лекц" in normalized:
            return "Лекция"
        if "practice" in normalized or "практ" in normalized:
            return "Практика"
        if "laboratory" in normalized or "лаборатор" in normalized or "lab" == normalized:
            return "Лабораторная"
        return text
    name = _repair_text(row.get("course_name") or "")
    match = re.search(r"\((лекция|практика|лабораторная)\)\s*$", name, re.I)
    return match.group(1) if match else "Занятие"


def _teacher_label(row: dict) -> str:
    teachers = row.get("teacher_ids") or ([row["teacher_id"]] if row.get("teacher_id") else [])
    teachers = [_repair_text(item) for item in teachers if not str(item).startswith("UNKNOWN:")]
    return ", ".join(teachers) if teachers else ""


def _weeks_text(weeks: list[int], semester_weeks: int) -> str:
    ordered = sorted({int(week) for week in weeks})
    if not ordered:
        return ""
    if ordered == list(range(1, semester_weeks + 1)):
        return "все недели"
    ranges: list[str] = []
    start = previous = ordered[0]
    for week in ordered[1:]:
        if week != previous + 1:
            ranges.append(str(start) if start == previous else f"{start}–{previous}")
            start = week
        previous = week
    ranges.append(str(start) if start == previous else f"{start}–{previous}")
    return ", ".join(ranges) + " нед."


def _room_label(row: dict) -> str:
    venue = str(row.get("venue_type") or "").casefold()
    room = _repair_text(row.get("room_id") or "")
    if venue == "sport" or room.startswith("__SPORT__"):
        return "Спортзал"
    if venue == "online" or room.startswith("__ONLINE__"):
        return "Онлайн"
    if venue == "external" or room.startswith("__EXTERNAL__"):
        return "Внешняя площадка"
    return room


def _color(row: dict) -> str:
    key = str(row.get("course_id") or row.get("course_name") or row.get("name") or "")
    return COURSE_COLORS[sum(ord(char) for char in key) % len(COURSE_COLORS)]


def _session_text(row: dict, semester_weeks: int, continuation: bool = False) -> str:
    parts = []
    if continuation:
        parts.append("↳ " + _course_label(row))
    else:
        parts.append(_course_label(row))
        lesson_type = _lesson_type(row)
        hours = row.get("hours") or row.get("duration_hours")
        type_line = lesson_type.capitalize()
        if hours:
            type_line += f" ({hours} ч.)"
        parts.append(type_line)
        teacher = _teacher_label(row)
        if teacher:
            parts.append(teacher)
    weeks = _weeks_text(row.get("weeks") or [], semester_weeks)
    if weeks and weeks != "все недели":
        parts.append(weeks)
    if row.get("is_preassigned"):
        parts.append("закреплено")
    if row.get("elective_group"):
        parts.append("электив — вариант по выбору")
    return "\n".join(parts)


def _make_schedule_sheet(
    workbook: Workbook,
    schedule: list[dict],
    time_slots: list[dict],
    group_ids: list[str],
    group_sizes: dict[str, int],
    semester_weeks: int,
) -> None:
    ws = workbook.create_sheet("Расписание")
    last_col = 2 + 2 * len(group_ids)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    ws.cell(1, 1, f"Расписание — {semester_weeks} недель")
    ws.merge_cells("A2:A3")
    ws.cell(2, 1, "День")
    ws.merge_cells("B2:B3")
    ws.cell(2, 2, "Время")
    group_column: dict[str, int] = {}
    for index, group_id in enumerate(group_ids):
        col = 3 + index * 2
        group_column[group_id] = col
        ws.cell(2, col, _repair_text(group_id))
        ws.cell(2, col + 1, "Ауд.")
        ws.cell(3, col, group_sizes.get(group_id, ""))

    slots_by_day: dict[str, list[dict]] = defaultdict(list)
    for slot in time_slots:
        slots_by_day[_repair_text(slot.get("day") or "")].append(slot)
    row_by_slot: dict[int, int] = {}
    current_row = 4
    day_ranges: list[tuple[int, int, str]] = []
    for day in DAYS:
        day_slots = sorted(slots_by_day.get(day, []), key=lambda item: int(item.get("slot_index") or 0))
        if not day_slots:
            continue
        start = current_row
        for slot in day_slots:
            row_by_slot[int(slot["id"])] = current_row
            ws.cell(current_row, 2, _repair_text(slot.get("time") or ""))
            ws.row_dimensions[current_row].height = 82
            current_row += 1
        end = current_row - 1
        ws.merge_cells(start_row=start, start_column=1, end_row=end, end_column=1)
        ws.cell(start, 1, day)
        day_ranges.append((start, end, day))

    buckets: dict[tuple[str, int], list[tuple[dict, bool]]] = defaultdict(list)
    for event in schedule:
        slot_ids = [int(slot_id) for slot_id in (event.get("timeslots_ids") or [])]
        if not slot_ids:
            continue
        for group_id in event.get("group_ids") or []:
            for index, slot_id in enumerate(slot_ids):
                if slot_id in row_by_slot:
                    buckets[(str(group_id), slot_id)].append((event, index > 0))

    for (group_id, slot_id), entries in buckets.items():
        col = group_column.get(group_id)
        row_index = row_by_slot.get(slot_id)
        if col is None or row_index is None:
            continue
        cell = ws.cell(row_index, col)
        room_cell = ws.cell(row_index, col + 1)
        distinct: list[tuple[dict, bool]] = []
        seen: set[tuple[str, str]] = set()
        for event, continuation in entries:
            signature = (_session_text(event, semester_weeks, continuation), _room_label(event))
            if signature not in seen:
                seen.add(signature)
                distinct.append((event, continuation))
        entries = distinct
        cell.value = "\n\n".join(_session_text(event, semester_weeks, continuation) for event, continuation in entries)
        room_cell.value = "\n".join(dict.fromkeys(_room_label(event) for event, _ in entries if _room_label(event)))
        cell.fill = PatternFill("solid", fgColor=_color(entries[0][0]))
        room_cell.fill = PatternFill("solid", fgColor=_color(entries[0][0]))

    thin = Side(style="thin", color="A6A6A6")
    medium = Side(style="medium", color="202020")
    for row in ws.iter_rows(min_row=1, max_row=current_row - 1, min_col=1, max_col=last_col):
        for cell in row:
            cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            if cell.row >= 4:
                cell.font = Font(name="Arial", size=8)
    for row in (2, 3):
        for cell in ws[row][:last_col]:
            cell.fill = PatternFill("solid", fgColor="D9EAF7" if row == 2 else "EAF2F8")
            cell.font = Font(name="Arial", size=9, bold=True)
    for cell in ws[1][:last_col]:
        cell.font = Font(name="Arial", size=12, bold=True)
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.font = Font(name="Arial", size=12, bold=True, color="FFFFFF")
    ws.row_dimensions[1].height = 28
    ws.row_dimensions[2].height = 30
    ws.row_dimensions[3].height = 20
    ws.column_dimensions["A"].width = 13
    ws.column_dimensions["B"].width = 16
    for column in range(3, last_col + 1):
        is_room = column % 2 == 0
        ws.column_dimensions[get_column_letter(column)].width = 8 if is_room else 22
    for start, end, _ in day_ranges:
        for cell in ws[start][:last_col]:
            cell.border = Border(left=medium, right=thin, top=medium, bottom=thin)
        for cell in ws[end][:last_col]:
            cell.border = Border(left=thin, right=thin, top=thin, bottom=medium)
    ws.freeze_panes = "C4"
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.page_setup.orientation = "landscape"
    ws.print_title_rows = "1:3"


def _add_summary(workbook: Workbook, presentation: dict, result: dict) -> None:
    ws = workbook.create_sheet("Сводка", 0)
    ws["A1"] = "Итог расчёта"
    ws["A1"].font = Font(name="Arial", size=14, bold=True, color="1F4E78")
    ws["A2"] = presentation.get("status_human") or ""
    ws["A2"].font = Font(name="Arial", size=11, bold=True)

    ws["A4"] = "Показатель"
    ws["B4"] = "Значение"
    for cell in (ws["A4"], ws["B4"]):
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.font = Font(name="Arial", size=9, bold=True, color="FFFFFF")

    rows = [
        ("Поставлено занятий", len(result.get("schedule") or [])),
        ("Не поставлено", len(presentation.get("unplaced_rows") or [])),
        ("Замечаний к уже поставленным", len(presentation.get("remark_rows") or [])),
    ]
    meta = result.get("meta") or {}
    if meta.get("solve_time_sec") is not None:
        rows.append(("Время расчёта, сек.", meta.get("solve_time_sec")))
    for index, (label, value) in enumerate(rows, start=5):
        ws.cell(index, 1, label)
        ws.cell(index, 2, value)

    start = 5 + len(rows) + 1
    ws.cell(start, 1, "Разбивка по типам")
    ws.cell(start, 1).font = Font(name="Arial", size=11, bold=True)
    ws.cell(start + 1, 1, "Тип")
    ws.cell(start + 1, 2, "Количество")
    for cell in (ws.cell(start + 1, 1), ws.cell(start + 1, 2)):
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.font = Font(name="Arial", size=9, bold=True, color="FFFFFF")

    counts = presentation.get("counts") or {}
    titles = presentation.get("category_titles") or {}
    row_index = start + 2
    for key in presentation.get("category_order") or []:
        if counts.get(key):
            ws.cell(row_index, 1, titles.get(key, key))
            ws.cell(row_index, 2, counts[key])
            row_index += 1

    row_index += 1
    ws.cell(row_index, 1, "Как читать файл")
    ws.cell(row_index, 1).font = Font(name="Arial", size=11, bold=True)
    ws.cell(row_index + 1, 1, "«Расписание» — сетка на семестр.")
    ws.cell(row_index + 2, 1, "«Непоставленные» — занятия, которых нет в сетке.")
    ws.cell(
        row_index + 3,
        1,
        "«Замечания» — занятия уже стоят, но с оговорками (суббота, поздняя пара и т.п.).",
    )
    ws.column_dimensions["A"].width = 58
    ws.column_dimensions["B"].width = 16
    for row in ws.iter_rows(min_row=1, max_row=row_index + 3, min_col=1, max_col=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def _add_unplaced(workbook: Workbook, presentation: dict) -> None:
    ws = workbook.create_sheet("Непоставленные")
    ws.append(["Занятие", "Группы", "Студентов", "Почему не встало", "Что проверить"])
    for row in presentation.get("unplaced_rows") or []:
        ws.append([
            row.get("lesson", ""),
            row.get("groups", ""),
            row.get("students", ""),
            row.get("text", ""),
            row.get("advice", ""),
        ])
    if not (presentation.get("unplaced_rows") or []):
        ws.append(["Все запрошенные занятия удалось поставить", "", "", "", ""])
    _style_table(ws, [42, 36, 12, 55, 45])


def _add_soft_remarks(workbook: Workbook, presentation: dict) -> None:
    ws = workbook.create_sheet("Замечания")
    ws.append(["Тип замечания", "Занятие", "Группы", "Подробности"])
    by_category = presentation.get("by_category") or {}
    titles = presentation.get("category_titles") or {}
    hints = presentation.get("category_hints") or {}
    wrote = False
    for key in presentation.get("category_order") or []:
        if key == "unplaced":
            continue
        rows = by_category.get(key) or []
        if not rows:
            continue
        # Разделитель-пояснение типа
        ws.append([titles.get(key, key), "", "", hints.get(key, "")])
        for cell in ws[ws.max_row]:
            cell.fill = PatternFill("solid", fgColor="D9EAF7")
            cell.font = Font(name="Arial", size=9, bold=True)
        for row in rows:
            ws.append([
                titles.get(key, key),
                row.get("lesson", ""),
                row.get("groups", ""),
                row.get("text", ""),
            ])
            wrote = True
    if not wrote:
        ws.append(["Замечаний к поставленным занятиям нет", "", "", ""])
    _style_table(ws, [42, 42, 28, 70])


def _style_table(ws, widths: list[int]) -> None:
    for cell in ws[1]:
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.font = Font(name="Arial", size=9, bold=True, color="FFFFFF")
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False


def export_result(result: dict, output_path: str | Path, source_data: dict | None = None) -> Path:
    """Write one semester-wide grid plus diagnostics and unplaced lessons."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    source_data = source_data or {}
    schedule = list(result.get("schedule") or [])
    course_labels = {
        str(course.get("id")): {
            "course_name": course.get("discipline"),
            "lesson_type": course.get("lesson_type"),
            "elective_group": course.get("elective_group"),
        }
        for course in (source_data.get("courses") or [])
    }
    schedule = [{**course_labels.get(str(row.get("course_id")), {}), **row} for row in schedule]
    source_groups = list(source_data.get("groups") or [])
    source_group_ids = {str(group.get("id")) for group in source_groups}
    for event in result.get("reserved_events") or []:
        event_groups = [str(group_id) for group_id in (event.get("group_ids") or [])]
        visible = [group_id for group_id in event_groups
                   if not source_group_ids or group_id in source_group_ids]
        if visible:
            schedule.append({**course_labels.get(str(event.get("course_id")), {}), **event, "group_ids": visible})

    time_slots = list(source_data.get("time_slots") or [])
    if not time_slots:
        unique: dict[int, dict] = {}
        for row in schedule:
            for slot_id in row.get("timeslots_ids") or []:
                unique.setdefault(int(slot_id), {"id": int(slot_id), "day": row.get("day"),
                                                  "slot_index": row.get("slot_index_start"), "time": row.get("time")})
        time_slots = list(unique.values())

    # This is an institute-wide grid: keep every input group visible, including
    # groups whose only event is a reserved PE slot or whose lessons are unplaced.
    group_ids = [str(group["id"]) for group in source_groups]
    known = set(group_ids)
    for row in schedule:
        for group_id in row.get("group_ids") or []:
            if str(group_id) not in known:
                group_ids.append(str(group_id))
                known.add(str(group_id))
    if not group_ids:
        group_ids = [str(group["id"]) for group in source_groups]
    group_sizes = {str(group.get("id")): group.get("size") for group in source_groups}
    weeks = [int(week) for row in schedule for week in (row.get("weeks") or [])]
    semester_weeks = int((source_data.get("config") or {}).get("semester_weeks") or 16)
    week_count = max([semester_weeks, *weeks]) if weeks else semester_weeks

    from app.report_present import build_presentation

    presentation = build_presentation(result)

    workbook = Workbook()
    workbook.remove(workbook.active)
    _add_summary(workbook, presentation, result)
    _make_schedule_sheet(workbook, schedule, time_slots, group_ids, group_sizes, week_count)
    _add_unplaced(workbook, presentation)
    _add_soft_remarks(workbook, presentation)
    workbook.save(target)
    return target
