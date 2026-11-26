"""Человекочитаемое представление предупреждений и непоставленных занятий."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any


REQUIREMENT_LABELS_RU = {
    "board": "доска",
    "chalkboard": "меловая доска",
    "whiteboard": "маркерная доска",
    "multimedia_board": "мультимедиа-доска",
    "screen": "экран / проектор",
    "computer_class": "компьютерный класс",
    "software": "специальное ПО",
    "internet": "интернет",
    "blinds": "жалюзи",
    "acoustic_system": "акустика",
}

CATEGORY_ORDER = [
    "unplaced",
    "late",
    "saturday",
    "teacher_wish",
    "raw_wish",
    "fixed_room",
    "missing_teacher",
    "equipment",
    "time_limit",
    "other",
]

CATEGORY_TITLES = {
    "unplaced": "Не удалось поставить",
    "late": "Стоят на поздних парах",
    "saturday": "Стоят в субботу",
    "teacher_wish": "Не совпало с желаемым временем преподавателя",
    "raw_wish": "Пожелание из анкеты не удалось учесть автоматически",
    "fixed_room": "Закреплённая аудитория не подошла",
    "missing_teacher": "Не указан преподаватель",
    "equipment": "Аудитория без желаемого оснащения",
    "time_limit": "Не хватило времени на полный поиск",
    "other": "Прочие замечания",
}

CATEGORY_HINTS = {
    "unplaced": "Эти занятия не попали в сетку.",
    "late": "Занятие поставлено, но на 5-й паре или позже.",
    "saturday": "Занятие поставлено в субботу.",
    "teacher_wish": "Расписание допустимо, но слот не из предпочтений преподавателя.",
    "raw_wish": "В анкете был свободный текст; его не удалось превратить в правило.",
    "fixed_room": "В анкете указали аудиторию, но она не подошла — искали другую.",
    "missing_teacher": "В нагрузке не было ФИО.",
    "equipment": "Занятие поставлено, но без экрана/проектора, который просили.",
    "time_limit": "Поиск остановили по таймеру.",
    "other": "Замечания вне основных групп.",
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _lesson_title(item: dict) -> str:
    for key in ("name", "course_name", "title"):
        value = _text(item.get(key))
        if value and not re.fullmatch(r"c\d+", value, flags=re.I):
            return value
    message = _text(item.get("message"))
    match = re.search(r"['«\"]([^'»\"]+)['»\"]", message)
    if match:
        return match.group(1)
    return _text(item.get("course_id")) or "Занятие"


def _groups_text(item: dict) -> str:
    groups = [_text(group) for group in (item.get("group_ids") or []) if _text(group)]
    if not groups:
        return ""
    if len(groups) <= 4:
        return ", ".join(groups)
    return ", ".join(groups[:4]) + f" и ещё {len(groups) - 4}"


def _requirements_text(requirements: Any) -> str:
    if not requirements:
        return "без особых требований к оснащению"
    labels = [REQUIREMENT_LABELS_RU.get(_text(req), _text(req)) for req in requirements]
    return ", ".join(label for label in labels if label)


def _pair_word(slot_index: Any) -> str:
    try:
        number = int(slot_index)
    except (TypeError, ValueError):
        return "поздней паре"
    return f"{number}-й паре"


def classify_user_category(item: dict) -> str:
    code = _text(item.get("code"))
    mapping = {
        "UNPLACEABLE_INSTANCE_DROPPED": "unplaced",
        "SCHEDULED_LATE_SLOT": "late",
        "SCHEDULED_ON_SATURDAY": "saturday",
        "UNMET_WANTED_SLOT": "teacher_wish",
        "UNMET_SOFT_TIME_WISH": "teacher_wish",
        "UNMANAGED_TIME_WISH": "raw_wish",
        "INFEASIBLE_FIXED_ROOM_IGNORED": "fixed_room",
        "MISSING_TEACHER_PLACEHOLDER": "missing_teacher",
        "UNMET_SOFT_EQUIPMENT": "equipment",
        "PLACEMENT_MAX_NOT_PROVEN": "time_limit",
    }
    if code in mapping:
        return mapping[code]
    try:
        from mvp_1 import classify_warning_kind

        kind = classify_warning_kind(item)
        if kind == "unplaced":
            return "unplaced"
    except Exception:  # noqa: BLE001
        pass
    return "other"


def humanize_unplaced_reason(item: dict) -> tuple[str, str]:
    """Краткая причина и совет пользователю."""
    cause = _text(item.get("cause_code"))
    students = item.get("students_needed")
    requirements = item.get("requirements") or []
    message = _text(item.get("message")).casefold()

    if cause == "NO_FEASIBLE_ROOM" or "нет подходящей аудитории" in message:
        if isinstance(students, int) and students >= 200:
            return (
                f"Группа слишком большая для имеющихся аудиторий ({students} чел.).",
                "Проверьте потоки и нарезку подгрупп или найдите более вместительную аудиторию.",
            )
        if "по вместимости подходят, но не по оснащению" in message or requirements:
            reason = f"Нет аудитории с нужным оснащением ({_requirements_text(requirements)})"
            if students:
                reason += f", нужно место примерно на {students} чел."
            else:
                reason += "."
            return (
                reason,
                "Проверьте справочник аудиторий: флаги оснащения и вместимость.",
            )
        return (
            "Не нашлось подходящей аудитории"
            + (f" (нужно около {students} чел.)" if students else "")
            + ".",
            "Проверьте вместимость, оснащение и закреплённые аудитории.",
        )

    if cause == "NO_FEASIBLE_SLOT_OR_ROOM" or "не удалось поставить при текущих" in message:
        return (
            "Не удалось согласовать время, преподавателя, группы и аудиторию.",
            "Посмотрите конфликты по преподавателю и группам и занятость подходящих аудиторий.",
        )

    return (
        "Занятие не попало в расписание при текущих ограничениях.",
        "Проверьте нагрузку, аудитории и анкету преподавателей.",
    )


def humanize_soft_text(item: dict) -> str:
    code = _text(item.get("code"))
    title = _lesson_title(item)

    if code == "SCHEDULED_ON_SATURDAY":
        return f"«{title}» стоит в субботу."

    if code == "SCHEDULED_LATE_SLOT":
        return f"«{title}» стоит на {_pair_word(item.get('slot_index'))}."

    if code == "UNMET_WANTED_SLOT":
        return f"«{title}»: слот не из предпочтений преподавателя."

    if code == "UNMET_SOFT_TIME_WISH":
        return f"«{title}»: мягкое пожелание по времени не выполнено."

    if code == "UNMANAGED_TIME_WISH":
        raw = _text(item.get("time_wish_raw")) or "текст из анкеты"
        reason = _text(item.get("reason"))
        if reason.startswith("foreign_teacher"):
            return f"«{title}»: в пожелании указан другой преподаватель — «{raw}»."
        if "no_rule" in reason:
            return f"«{title}»: свободный текст пожелания не разобран — «{raw}»."
        return f"«{title}»: пожелание не удалось учесть автоматически — «{raw}»."

    if code == "INFEASIBLE_FIXED_ROOM_IGNORED":
        room = _text(item.get("fixed_room")) or "указанная"
        parts = []
        if item.get("students_needed"):
            parts.append(f"нужно ~{item['students_needed']} чел.")
        if item.get("requirements"):
            parts.append(_requirements_text(item.get("requirements")))
        suffix = f" ({'; '.join(parts)})" if parts else ""
        return (
            f"«{title}»: закреплённая аудитория {room} не подошла{suffix}; "
            "подобрали другую."
        )

    if code == "MISSING_TEACHER_PLACEHOLDER":
        return f"«{title}»: в нагрузке не указан преподаватель."

    if code == "UNMET_SOFT_EQUIPMENT":
        missing = item.get("missing_soft_requirements") or ["screen"]
        labels = ", ".join(
            REQUIREMENT_LABELS_RU.get(_text(req), _text(req)) for req in missing
        )
        room = _text(item.get("room_id"))
        where = f" в аудитории {room}" if room else ""
        return f"«{title}»{where} без желаемого оснащения: {labels}."

    if code == "PLACEMENT_MAX_NOT_PROVEN":
        placed = item.get("placed_instances")
        if placed:
            return (
                f"Поиск остановили по времени: успели разобрать слоты для {placed} занятий; "
                "часть непоставленных при большем лимите могла бы встать."
            )
        return CATEGORY_HINTS["time_limit"]

    message = _text(item.get("message"))
    for noise in (
        " (unplaceable_instance_policy=warn)",
        " (infeasible_fixed_room_policy=warn)",
        " (fixed_schedule_mismatch_policy=warn)",
    ):
        message = message.replace(noise, "")
    message = message.replace("fixed_room", "закреплённая аудитория")
    message = message.replace("hard-требованиям", "жёстким требованиям")
    return message or f"«{title}»: замечание без подробностей."


def present_item(item: dict) -> dict[str, Any]:
    category = classify_user_category(item)
    title = _lesson_title(item)
    row: dict[str, Any] = {
        "category": category,
        "category_title": CATEGORY_TITLES[category],
        "lesson": title,
        "groups": _groups_text(item),
        "students": item.get("students_needed") if item.get("students_needed") is not None else "",
    }
    if category == "unplaced":
        reason, advice = humanize_unplaced_reason(item)
        row["text"] = reason
        row["advice"] = advice
        row["requirements"] = _requirements_text(item.get("requirements") or []) if item.get("requirements") else ""
    else:
        row["text"] = humanize_soft_text(item)
        row["advice"] = ""
        row["requirements"] = ""
    return row


def build_presentation(result: dict) -> dict[str, Any]:
    """Структура для Excel/UI: сводка + строки по категориям."""
    groups = result.get("warning_groups") or {}
    warnings = list(result.get("warnings") or [])
    unplaced_raw = list(groups.get("unplaced") or result.get("unplaced") or [])
    soft_raw = list(groups.get("soft") or [])
    other_raw = list(groups.get("other") or [])

    if not soft_raw and not other_raw:
        for item in warnings:
            category = classify_user_category(item)
            if category == "unplaced":
                continue
            if category == "other":
                other_raw.append(item)
            else:
                soft_raw.append(item)
    if not unplaced_raw:
        unplaced_raw = [
            item for item in warnings if classify_user_category(item) == "unplaced"
        ]

    presented = [present_item(item) for item in unplaced_raw + soft_raw + other_raw]
    by_category: dict[str, list[dict]] = defaultdict(list)
    for row in presented:
        by_category[row["category"]].append(row)

    counts = {key: len(by_category.get(key) or []) for key in CATEGORY_ORDER}
    status = _text(result.get("status"))
    lessons = len(result.get("schedule") or [])
    if status.startswith("SUCCESS"):
        status_human = "Расписание собрано"
        if counts.get("unplaced"):
            status_human += " с непоставленными занятиями"
        elif sum(counts.values()):
            status_human += " с замечаниями"
    elif status == "NO_SOLUTION":
        status_human = "Подходящее расписание не найдено"
    elif status.startswith("ERROR") or result.get("errors"):
        status_human = "Расчёт завершился с ошибкой"
    else:
        status_human = status or "Готово"

    summary_lines = [
        status_human,
        f"Поставлено занятий: {lessons}",
        f"Не поставлено: {counts.get('unplaced', 0)}",
        f"Замечаний к уже поставленным: {sum(counts.get(key, 0) for key in counts if key != 'unplaced')}",
    ]
    for key in CATEGORY_ORDER:
        if key == "unplaced" or not counts.get(key):
            continue
        summary_lines.append(f"  — {CATEGORY_TITLES[key]}: {counts[key]}")

    return {
        "status_human": status_human,
        "summary_lines": summary_lines,
        "counts": counts,
        "by_category": dict(by_category),
        "unplaced_rows": by_category.get("unplaced") or [],
        "remark_rows": [
            row
            for key in CATEGORY_ORDER
            if key != "unplaced"
            for row in (by_category.get(key) or [])
        ],
        "category_titles": CATEGORY_TITLES,
        "category_hints": CATEGORY_HINTS,
        "category_order": CATEGORY_ORDER,
    }


def summarize_counts(presentation: dict) -> list[tuple[str, int]]:
    counts = presentation.get("counts") or {}
    return [
        (CATEGORY_TITLES[key], counts[key])
        for key in CATEGORY_ORDER
        if counts.get(key)
    ]
