import json
import math
from pathlib import Path

from ortools.sat.python import cp_model

DEFAULT_DATA_PATH = Path(__file__).resolve().parent / "parser" / "data.json"

DEFAULT_CONFIG = {
    # для полного прогона ставьте 300–900; тесты оставляют короткий лимит
    "max_time_in_seconds": 10.0,
    "num_search_workers": 8,
    # стратегия масштаба: auto | monolithic | two_phase
    "solve_strategy": "auto",
    # порог оценки |inst|×|starts|×|rooms| → two_phase в режиме auto
    "var_threshold_two_phase": 80_000,
    # после feasibility оставить не больше N аудиторий (0 = без лимита)
    "max_candidate_rooms": 24,
    # если two_phase phase2 не сошёлся — fallback на monolithic с остатком времени
    "repair_on_two_phase_fail": True,
    # доля времени на phase1 в two_phase (остальное phase2 / repair)
    "two_phase_time_fraction": 0.55,
    # soft weights for teachers_wanted_slots
    "weight_wanted_slot": 10,
    "weight_preferred_capacity": 1,
    "weight_preferred_room_type": 1,
    # вместимость, если парсер не дал students_needed
    "default_group_size": 30,
    # для lecture_stream при «дефолтных» size у всех групп потока
    "lecture_stream_size_factor": 0.8,
    # календарь семестра: недели start .. start+n-1
    "semester_weeks": 16,
    "semester_week_start": 1,
    # duration_slots: не рвать блок через обед (между slot_index 2 и 3)
    "allow_duration_across_lunch": False,
    "lunch_break_after_slot_index": 2,
    # missing teacher: placeholder | strict (strict / true → не запускать solve)
    "missing_teacher_policy": "placeholder",
    "strict": False,
    # fixed_schedules count mismatch (физкультура vs много instances): strict|warn
    "fixed_schedule_mismatch_policy": "strict",
    # анкетный fixed_room не вмещает / нет в справочнике: strict|warn
    "infeasible_fixed_room_policy": "strict",
    # нет ни одной аудитории под students/requirements: strict|warn (warn → drop instance)
    "unplaceable_instance_policy": "strict",
    # soft-штраф за нарушение time_wishes со strength=soft
    "weight_time_wish": 8,
    # soft objective (п.14)
    "weight_group_gap": 5,
    "weight_late_slot": 2,
    "weight_saturday": 4,
    # пары с slot_index >= late_slot_from считаются поздними
    "late_slot_from": 5,
}

DAY_NAME_ALIASES = {
    "пн": "понедельник",
    "пон": "понедельник",
    "понедельник": "понедельник",
    "monday": "понедельник",
    "mon": "понедельник",
    "вт": "вторник",
    "вторник": "вторник",
    "tuesday": "вторник",
    "tue": "вторник",
    "ср": "среда",
    "среда": "среда",
    "wednesday": "среда",
    "wed": "среда",
    "чт": "четверг",
    "четверг": "четверг",
    "thursday": "четверг",
    "thu": "четверг",
    "пт": "пятница",
    "пятница": "пятница",
    "friday": "пятница",
    "fri": "пятница",
    "сб": "суббота",
    "суббота": "суббота",
    "saturday": "суббота",
    "sat": "суббота",
    "вс": "воскресенье",
    "воскресенье": "воскресенье",
    "sunday": "воскресенье",
    "sun": "воскресенье",
}

# course.requirements value -> room feature flag(s)
REQUIREMENT_FLAGS = {
    "multimedia_board": ("has_multimedia_board",),
    "chalkboard": ("has_chalkboard",),
    "whiteboard": ("has_whiteboard",),
    "screen": ("has_screen",),
    "blinds": ("has_blinds",),
    "acoustic_system": ("has_acoustic_system",),
    # any board is enough
    "board": ("has_board", "has_chalkboard", "has_whiteboard", "has_multimedia_board"),
}

# labels from table3 / teachers_wanted_slots.room_requirements
ROOM_REQUIREMENT_LABELS = {
    "мультимедиа доска": "multimedia_board",
    "multimedia_board": "multimedia_board",
    "меловая доска": "chalkboard",
    "chalkboard": "chalkboard",
    "маркерная доска": "whiteboard",
    "whiteboard": "whiteboard",
    "любая доска": "board",
    "board": "board",
    "экран": "screen",
    "screen": "screen",
    "жалюзи": "blinds",
    "blinds": "blinds",
    "акустическая система": "acoustic_system",
    "акустич. система": "acoustic_system",
    "acoustic_system": "acoustic_system",
}

NEUTRAL_ROOM_TYPES = {
    "",
    "без разницы",
    "любая",
    "any",
    "none",
    "nan",
}

# Канонические venue_type без аудитории ИЕНИМ
VENUE_TYPES_WITHOUT_ROOM = frozenset({
    "online",
    "external",
    "sport",
    "virtual",
})

# Сырые ярлыки парсера / Excel → канон (room|online|external|sport|unspecified)
VENUE_TYPE_ALIASES = {
    "room": "room",
    "ienim": "room",
    "aud": "room",
    "аудитория": "room",
    "очно": "room",
    "очный": "room",
    "offline": "room",
    "online": "online",
    "онлайн": "online",
    "дистант": "online",
    "дистанционно": "online",
    "remote": "online",
    "нтк": "online",
    "ntk": "online",
    "external": "external",
    "внешн": "external",
    "внешняя": "external",
    "выезд": "external",
    "выездная": "external",
    "sport": "sport",
    "sports": "sport",
    "sportzal": "sport",
    "спортзал": "sport",
    "gym": "sport",
    "физкультура": "sport",
    "virtual": "virtual",
    "unspecified": "unspecified",
    "unknown": "unspecified",
}


def load_data(path: str | Path = DEFAULT_DATA_PATH) -> dict:
    """Загрузить JSON, сформированный парсером."""
    with Path(path).open(encoding="utf-8") as file:
        return json.load(file)


def resolve_solver_config(data: dict, config: dict | None = None) -> dict:
    """Собрать конфиг солвера: defaults < data['config'] < явный config."""
    merged = dict(DEFAULT_CONFIG)
    merged.update(data.get("config") or {})
    if config:
        merged.update(config)
    return merged


def prepare_parser_data(data: dict) -> dict:
    """
    Legacy-адаптер перед solve_schedule.

    Новый парсер уже отдаёт lessons_per_week / week_pattern / instances —
    их не пересчитываем из hours_per_semester (поля может не быть).
    Старый JSON без lessons_per_week: lessons_per_week = max(1, ceil(hours/32)).
    """
    courses = []
    for course in data["courses"]:
        updated = dict(course)
        if _course_has_prepared_load(updated):
            courses.append(updated)
            continue
        hours = updated.get("hours_per_semester") or 0
        try:
            hours_val = float(hours)
        except (TypeError, ValueError):
            hours_val = 0.0
        updated["lessons_per_week"] = max(1, math.ceil(hours_val / 32))
        courses.append(updated)
    return {**data, "courses": courses}


def _course_has_prepared_load(course: dict) -> bool:
    """True, если нагрузка уже посчитана парсером / явно задана."""
    if course.get("lessons_per_week") is not None and course.get("lessons_per_week") != "":
        try:
            return int(course["lessons_per_week"]) >= 1
        except (TypeError, ValueError):
            pass
    if course.get("instances"):
        return True
    if course.get("week_pattern") not in (None, ""):
        return True
    return False


def _room_has_any_flag(room: dict, flags: tuple[str, ...]) -> bool:
    return any(bool(room.get(flag)) for flag in flags)


def room_meets_requirements(room: dict, requirements: list[str] | None) -> bool:
    """Проверить hard-требования курса к оснащению аудитории."""
    for req in requirements or []:
        flags = REQUIREMENT_FLAGS.get(req)
        if flags is None:
            # неизвестное требование: не отсекаем размещение молча —
            # считаем невыполненным, чтобы не нарушить hard-семантику
            return False
        if not _room_has_any_flag(room, flags):
            return False
    return True


def room_meets_software(room: dict, needs_software: object) -> bool:
    """Учесть needs_software / тип комнаты, если поля есть в JSON."""
    if not needs_software:
        return True
    if room.get("has_computers") or room.get("is_computer_class"):
        return True
    room_type = str(room.get("type") or room.get("kind") or "").lower()
    if room_type in {"компьютерный", "computer", "pc", "комп", "к"}:
        return True
    software = room.get("software") or room.get("available_software")
    if isinstance(needs_software, str) and software:
        if isinstance(software, (list, tuple, set)):
            return needs_software in software
        return needs_software in str(software)
    if software:
        return True
    return False


def room_capacity_value(room: dict) -> int | None:
    """Вместимость аудитории; None / отсутствующее → неизвестна (не в hard-домене)."""
    if "capacity" not in room:
        return None
    raw = room.get("capacity")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def room_is_feasible(
    room: dict,
    *,
    total_students: int,
    requirements: list[str] | None = None,
    needs_software: object = None,
) -> bool:
    capacity = room_capacity_value(room)
    if capacity is None or capacity < total_students:
        return False
    if not room_meets_requirements(room, requirements):
        return False
    if not room_meets_software(room, needs_software):
        return False
    return True


def _missing_requirements_for_room(room: dict, requirements: list[str] | None) -> list[str]:
    missing = []
    for req in requirements or []:
        flags = REQUIREMENT_FLAGS.get(req)
        if flags is None or not _room_has_any_flag(room, flags):
            missing.append(req)
    return missing


def normalize_course_name(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def instance_teacher_ids(inst: dict) -> set[str]:
    teachers: set[str] = set()
    for teacher_id in list(inst.get("teacher_ids") or []):
        if not _is_missing_teacher_id(teacher_id):
            teachers.add(str(teacher_id).strip())
    if not _is_missing_teacher_id(inst.get("teacher_id")):
        teachers.add(str(inst["teacher_id"]).strip())
    return teachers


def restriction_matches_instance(restriction: dict, inst: dict) -> bool:
    """Сопоставить запись teachers_impossible_slots с занятием."""
    teacher_id = restriction.get("teacher_id")
    if not teacher_id or teacher_id not in instance_teacher_ids(inst):
        return False

    # Явная связь от парсера
    if restriction.get("course_id"):
        return restriction["course_id"] == inst["course_id"]
    course_ids = restriction.get("course_ids") or []
    if course_ids:
        return inst["course_id"] in course_ids

    course_name = str(restriction.get("course_name") or "").strip()
    group_ids = [g for g in (restriction.get("group_ids") or []) if g]

    # Нет дисциплины и групп → запрет на все занятия преподавателя
    if not course_name and not group_ids:
        return True

    if course_name:
        left = normalize_course_name(course_name)
        right = normalize_course_name(inst.get("name"))
        if left != right and left not in right and right not in left:
            return False

    if group_ids and not (set(group_ids) & set(inst.get("group_ids") or [])):
        return False

    return True


def collect_forbidden_slots_by_instance(
    course_instances: list[dict],
    restrictions: list[dict] | None,
) -> dict[str, set[int]]:
    """instance_id -> множество запрещённых timeslot id."""
    forbidden: dict[str, set[int]] = {inst["instance_id"]: set() for inst in course_instances}
    for restriction in restrictions or []:
        slot_ids = {
            int(slot_id)
            for slot_id in (restriction.get("timeslots_ids") or [])
            if slot_id is not None
        }
        if not slot_ids:
            continue
        for inst in course_instances:
            if restriction_matches_instance(restriction, inst):
                forbidden[inst["instance_id"]].update(slot_ids)
    return forbidden


def normalize_room_id(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "null"}:
        return None
    # "304.0" from excel → "304"
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def normalize_room_type(value: object) -> str | None:
    text = " ".join(str(value or "").casefold().split())
    if text in NEUTRAL_ROOM_TYPES:
        return None
    return text or None


def map_room_requirement_label(label: object) -> str | None:
    key = " ".join(str(label or "").casefold().split())
    return ROOM_REQUIREMENT_LABELS.get(key)


def parse_preferred_capacity(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value != value:  # NaN
            return None
        return int(value)
    text = str(value).strip().replace(",", ".")
    if not text or text.casefold() in {"nan", "none", "null"}:
        return None
    digits = []
    for ch in text:
        if ch.isdigit():
            digits.append(ch)
        elif digits:
            break
    return int("".join(digits)) if digits else None


def collect_wanted_prefs_by_instance(
    course_instances: list[dict],
    wanted_rows: list[dict] | None,
) -> tuple[dict[str, dict], list[dict]]:
    """Собрать пожелания по instance_id и список конфликтов fixed_room."""
    prefs: dict[str, dict] = {
        inst["instance_id"]: {
            "fixed_rooms": set(),
            "wanted_slot_ids": set(),
            "extra_requirements": set(),
            "preferred_capacity": None,
            "preferred_room_types": set(),
        }
        for inst in course_instances
    }
    conflicts: list[dict] = []

    for row in wanted_rows or []:
        slot_ids = {
            int(slot_id)
            for slot_id in (row.get("timeslots_ids") or [])
            if slot_id is not None
        }
        fixed_room = normalize_room_id(row.get("fixed_room"))
        mapped_reqs = {
            mapped
            for label in (row.get("room_requirements") or [])
            if (mapped := map_room_requirement_label(label))
        }
        preferred_capacity = parse_preferred_capacity(row.get("capacity"))
        preferred_type = normalize_room_type(row.get("room_type"))

        if not any([slot_ids, fixed_room, mapped_reqs, preferred_capacity, preferred_type]):
            continue

        for inst in course_instances:
            if not restriction_matches_instance(row, inst):
                continue
            pref = prefs[inst["instance_id"]]
            pref["wanted_slot_ids"].update(slot_ids)
            pref["extra_requirements"].update(mapped_reqs)
            if fixed_room:
                pref["fixed_rooms"].add(fixed_room)
            if preferred_capacity is not None:
                current = pref["preferred_capacity"]
                pref["preferred_capacity"] = (
                    preferred_capacity if current is None else max(current, preferred_capacity)
                )
            if preferred_type:
                pref["preferred_room_types"].add(preferred_type)

    for inst in course_instances:
        pref = prefs[inst["instance_id"]]
        fixed_rooms = sorted(pref["fixed_rooms"])
        if len(fixed_rooms) > 1:
            conflicts.append({
                "code": "CONFLICTING_FIXED_ROOMS",
                "message": (
                    f"Для курса '{inst['name']}' указаны разные fixed_room: {fixed_rooms}"
                ),
                "course_id": inst["course_id"],
                "entity_ids": [inst["instance_id"]],
                "teacher_id": inst.get("teacher_id"),
                "fixed_rooms": fixed_rooms,
            })
        pref["fixed_room"] = fixed_rooms[0] if len(fixed_rooms) == 1 else None
        pref["wanted_slot_ids"] = {int(s) for s in pref["wanted_slot_ids"]}
        pref["extra_requirements"] = sorted(pref["extra_requirements"])
        pref["preferred_room_types"] = sorted(pref["preferred_room_types"])

    return prefs, conflicts


def room_matches_preferred_type(room: dict, preferred_types: list[str] | None) -> bool:
    if not preferred_types:
        return True
    room_type = normalize_room_type(room.get("type") or room.get("kind") or room.get("room_type"))
    if room_type is None:
        return False
    return room_type in preferred_types


# Общий «пустой» teacher без уникального id — нельзя оставлять как есть
MISSING_TEACHER_SENTINELS = frozenset({
    "",
    "nan",
    "none",
    "null",
    "undefined",
    "unknown",
    "н/д",
    "нд",
    "нет",
    "нет преподавателя",
    "без преподавателя",
    "?",
    "-",
    "—",
    "–",
})


def _is_missing_teacher_id(value: object) -> bool:
    """True для null/пустого/общего sentinel без привязки к курсу."""
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    folded = text.casefold()
    if folded in MISSING_TEACHER_SENTINELS:
        return True
    # Голый UNKNOWN без суффикса курса — общий null, не уникальный placeholder
    if folded == "unknown" or text == "UNKNOWN":
        return True
    return False


def _is_teacher_placeholder(teacher_id: object) -> bool:
    text = str(teacher_id or "").strip()
    return text.startswith("UNKNOWN:")


def resolve_missing_teacher_policy(config: dict) -> str:
    """
    placeholder — подставить UNIQUE UNKNOWN:{course_id} + warning.
    strict — ERROR и не запускать solve (для очных; online/sport — placeholder).
    """
    raw = config.get("missing_teacher_policy")
    if raw is not None and str(raw).strip() != "":
        text = str(raw).casefold().strip()
        if text in {"strict", "error", "fail"}:
            return "strict"
        if text in {"placeholder", "soft", "warn", "warning"}:
            return "placeholder"
    if config.get("strict") is True:
        return "strict"
    return "placeholder"


def _resolve_teacher_ids(source: dict, fallback: dict | None = None) -> list[str]:
    """Собрать список преподавателей; Mode A = несколько id на одном занятии."""
    teachers: list[str] = []

    def _add(teacher_id: object) -> None:
        if _is_missing_teacher_id(teacher_id):
            return
        text = str(teacher_id).strip()
        if text not in teachers:
            teachers.append(text)

    for teacher_id in source.get("teacher_ids") or []:
        _add(teacher_id)
    _add(source.get("teacher_id"))
    if not teachers and fallback is not None:
        return _resolve_teacher_ids(fallback, None)
    return teachers


def resolve_semester_weeks(data: dict, config: dict) -> list[int]:
    """Список номеров недель семестра."""
    if isinstance(data.get("semester_weeks"), list) and data["semester_weeks"]:
        return [int(w) for w in data["semester_weeks"]]
    semester = data.get("semester") or {}
    if isinstance(semester.get("weeks"), list) and semester["weeks"]:
        return [int(w) for w in semester["weeks"]]
    count = int(config.get("semester_weeks", 16))
    start = int(config.get("semester_week_start", 1))
    return list(range(start, start + count))


def normalize_week_pattern(raw: object) -> dict:
    """
    Канонический week_pattern:
      {"type": "all"|"odd"|"even"}
      {"type": "range", "from": a, "to": b}
      {"type": "list", "weeks": [...]}
    """
    if raw is None or raw == "":
        return {"type": "all"}

    if isinstance(raw, dict):
        typ = str(raw.get("type") or "").casefold().strip()
        if typ in {
            "all", "weekly", "каждую неделю", "каждая неделя",
            "odd", "even", "нечет", "нечёт", "чет", "чёт",
        }:
            if typ in {"нечет", "нечёт"}:
                typ = "odd"
            elif typ in {"чет", "чёт"}:
                typ = "even"
            elif typ in {"weekly", "каждую неделю", "каждая неделя"}:
                typ = "all"
            return {"type": typ}
        if typ == "range" or ("from" in raw and "to" in raw):
            return {
                "type": "range",
                "from": int(raw["from"]),
                "to": int(raw["to"]),
            }
        weeks = raw.get("weeks") or raw.get("list")
        if weeks is not None:
            return {"type": "list", "weeks": sorted({int(w) for w in weeks})}
        if typ == "list":
            return {"type": "list", "weeks": sorted({int(w) for w in (raw.get("weeks") or [])})}
        return {"type": "all"}

    if isinstance(raw, (list, tuple, set)):
        return {"type": "list", "weeks": sorted({int(w) for w in raw})}

    text = str(raw).casefold().strip()
    if text in {
        "all", "weekly", "все", "вся", "каждый", "каждая", "full",
        "каждую неделю", "каждая неделя",
    }:
        return {"type": "all"}
    if text in {"odd", "нечет", "нечёт", "нечетная", "нечётная", "нечетн", "нечётн"}:
        return {"type": "odd"}
    if text in {"even", "чет", "чёт", "четная", "чётная", "четн", "чётн"}:
        return {"type": "even"}

    # "2-9" / "2–9"
    for sep in ("-", "–", "—", ".."):
        if sep in text:
            left, right = text.split(sep, 1)
            if left.strip().isdigit() and right.strip().isdigit():
                return {"type": "range", "from": int(left), "to": int(right)}

    return {"type": "all"}


def expand_weeks(pattern: dict, semester_weeks: list[int]) -> frozenset[int]:
    """Множество недель занятия внутри календаря семестра."""
    weeks = list(semester_weeks)
    typ = pattern.get("type", "all")
    if typ == "all":
        return frozenset(weeks)
    if typ == "odd":
        return frozenset(w for w in weeks if w % 2 == 1)
    if typ == "even":
        return frozenset(w for w in weeks if w % 2 == 0)
    if typ == "range":
        low = int(pattern["from"])
        high = int(pattern["to"])
        if low > high:
            low, high = high, low
        return frozenset(w for w in weeks if low <= w <= high)
    if typ == "list":
        wanted = {int(w) for w in pattern.get("weeks") or []}
        return frozenset(w for w in weeks if w in wanted)
    return frozenset(weeks)


def weeks_intersect(weeks_a: frozenset[int] | set[int], weeks_b: frozenset[int] | set[int]) -> bool:
    return bool(weeks_a & weeks_b)


def normalize_day_name(raw: object) -> str | None:
    """Каноническое имя дня (lowercase рус.) или None."""
    if raw is None or raw == "":
        return None
    text = str(raw).casefold().strip()
    if text in DAY_NAME_ALIASES:
        return DAY_NAME_ALIASES[text]
    for alias, canon in DAY_NAME_ALIASES.items():
        if alias and alias in text:
            return canon
    return text or None


def slot_day_canon(slot: dict) -> str | None:
    return normalize_day_name(slot.get("day"))


# day_part из парсера → допустимый диапазон slot_index (SCHEMA §17)
DAY_PART_PAIR_BOUNDS: dict[str, tuple[int, int]] = {
    "morning": (1, 3),
    "afternoon": (4, 6),
    "evening": (5, 6),
}


def normalize_time_wish(raw: object) -> dict | None:
    """
    Канон правила:
      {type, strength, day?, slot_index?, timeslots_ids?}
    Типы: no_slot_after | no_slot_before | no_first_slot | no_saturday |
          no_day | forbid_slots | prefer_slots
    """
    if not isinstance(raw, dict):
        return None
    typ = str(raw.get("type") or raw.get("rule") or "").casefold().strip()
    aliases = {
        "no_after": "no_slot_after",
        "not_after": "no_slot_after",
        "after_slot_forbidden": "no_slot_after",
        "no_before": "no_slot_before",
        "not_before": "no_slot_before",
        "no_first": "no_first_slot",
        "not_first": "no_first_slot",
        "no_first_pair": "no_first_slot",
        "no_sat": "no_saturday",
        "not_saturday": "no_saturday",
        "forbid_day": "no_day",
        "no_weekday": "no_day",
        "forbidden_slots": "forbid_slots",
        "forbid_timeslots": "forbid_slots",
        "preferred_slots": "prefer_slots",
        "want_slots": "prefer_slots",
    }
    typ = aliases.get(typ, typ)
    if not typ:
        return None

    strength_raw = str(raw.get("strength") or raw.get("mode") or "").casefold().strip()
    if strength_raw in {"soft", "prefer", "preference", "wish"}:
        strength = "soft"
    elif strength_raw in {"hard", "forbid", "must", "constraint"}:
        strength = "hard"
    elif typ in {"prefer_slots"}:
        strength = "soft"
    else:
        strength = "hard"

    wish: dict = {"type": typ, "strength": strength}
    day = normalize_day_name(raw.get("day") or raw.get("weekday"))
    if day:
        wish["day"] = day
    if typ == "no_saturday":
        wish["day"] = "суббота"
        wish["type"] = "no_day"
        typ = "no_day"

    for key in ("slot_index", "after_slot", "before_slot", "pair"):
        if raw.get(key) is None or raw.get(key) == "":
            continue
        try:
            wish["slot_index"] = int(raw[key])
            break
        except (TypeError, ValueError):
            continue

    slots = raw.get("timeslots_ids") or raw.get("slot_ids") or raw.get("slots")
    if slots is not None:
        try:
            wish["timeslots_ids"] = [int(slot_id) for slot_id in slots]
        except (TypeError, ValueError):
            wish["timeslots_ids"] = list(slots)

    if typ == "no_slot_after" and "slot_index" not in wish:
        return None
    if typ == "no_slot_before" and "slot_index" not in wish:
        return None
    if typ == "no_day" and not wish.get("day"):
        return None
    if typ in {"forbid_slots", "prefer_slots"} and not wish.get("timeslots_ids"):
        return None
    if typ not in {
        "no_slot_after",
        "no_slot_before",
        "no_first_slot",
        "no_day",
        "forbid_slots",
        "prefer_slots",
    }:
        return None
    return wish


def _rule_soft_flag(rule: dict) -> bool:
    """Парсерный soft: true → soft wish; false/absent → hard."""
    if "soft" not in rule:
        strength = str(rule.get("strength") or rule.get("mode") or "").casefold()
        return strength in {"soft", "prefer", "preference", "wish"}
    value = rule.get("soft")
    if isinstance(value, bool):
        return value
    text = str(value).casefold().strip()
    return text in {"1", "true", "yes", "soft", "prefer"}


def map_time_wish_rule(
    rule: dict,
    *,
    max_pair_index: int = 6,
) -> list[dict]:
    """
    Элемент parser `time_wish_rules` → канонические time_wishes.

    soft=false → strength=hard; soft=true → strength=soft.
    max_pairs_per_day схемой слот-wish не выражается — пропускается.
    """
    if not isinstance(rule, dict):
        return []

    # Уже канонический wish с type — прогоняем через normalize
    if rule.get("type") or rule.get("rule"):
        wish = normalize_time_wish(rule)
        return [wish] if wish else []

    strength = "soft" if _rule_soft_flag(rule) else "hard"
    raw_wishes: list[dict] = []

    for day_raw in rule.get("forbidden_days") or []:
        day = normalize_day_name(day_raw)
        if day:
            raw_wishes.append({
                "type": "no_day",
                "strength": strength,
                "day": day,
            })

    slot_ids_raw = rule.get("forbidden_slot_ids") or []
    if slot_ids_raw:
        slot_ids: list[int] = []
        for slot_id in slot_ids_raw:
            try:
                slot_ids.append(int(slot_id))
            except (TypeError, ValueError):
                continue
        if slot_ids:
            raw_wishes.append({
                "type": "forbid_slots",
                "strength": strength,
                "timeslots_ids": sorted(set(slot_ids)),
            })

    min_pair = rule.get("min_pair_index")
    max_pair = rule.get("max_pair_index")
    try:
        min_pair = int(min_pair) if min_pair is not None and min_pair != "" else None
    except (TypeError, ValueError):
        min_pair = None
    try:
        max_pair = int(max_pair) if max_pair is not None and max_pair != "" else None
    except (TypeError, ValueError):
        max_pair = None

    day_part = str(rule.get("day_part") or "").casefold().strip()
    if day_part in DAY_PART_PAIR_BOUNDS:
        part_min, part_max = DAY_PART_PAIR_BOUNDS[day_part]
        min_pair = part_min if min_pair is None else max(min_pair, part_min)
        max_pair = part_max if max_pair is None else min(max_pair, part_max)

    if min_pair is not None and min_pair > 1:
        if min_pair == 2:
            raw_wishes.append({"type": "no_first_slot", "strength": strength})
        else:
            raw_wishes.append({
                "type": "no_slot_before",
                "strength": strength,
                "slot_index": min_pair,
            })

    if max_pair is not None and max_pair < max_pair_index:
        raw_wishes.append({
            "type": "no_slot_after",
            "strength": strength,
            "slot_index": max_pair,
        })

    wishes: list[dict] = []
    for item in raw_wishes:
        wish = normalize_time_wish(item)
        if wish is not None:
            wishes.append(wish)
    return wishes


def collect_time_wishes(course: dict, source: dict | None = None) -> tuple[list[dict], str | None]:
    """Структурированные time_wishes + сырой текст с course/instance.

    Читает и legacy `time_wishes`/`time_constraints`, и parser `time_wish_rules`.
    """
    source = source or {}
    raw_text = source.get("time_wish_raw")
    if raw_text is None:
        raw_text = course.get("time_wish_raw")
    if raw_text is not None:
        raw_text = str(raw_text).strip() or None

    bags: list = []
    for bag in (
        source.get("time_wishes"),
        source.get("time_constraints"),
        course.get("time_wishes"),
        course.get("time_constraints"),
        (source.get("wishes") or {}).get("time") if isinstance(source.get("wishes"), dict) else None,
        (course.get("wishes") or {}).get("time") if isinstance(course.get("wishes"), dict) else None,
    ):
        if bag:
            bags.append(bag)

    # TZ-solver §13.1.A: time_wish_rules → канон
    rule_bags = []
    for bag in (source.get("time_wish_rules"), course.get("time_wish_rules")):
        if not bag:
            continue
        items = bag if isinstance(bag, list) else [bag]
        expanded: list[dict] = []
        for rule in items:
            expanded.extend(map_time_wish_rule(rule if isinstance(rule, dict) else {}))
        if expanded:
            rule_bags.append(expanded)
    bags.extend(rule_bags)

    wishes: list[dict] = []
    seen: set[str] = set()
    for bag in bags:
        items = bag if isinstance(bag, list) else [bag]
        for item in items:
            wish = normalize_time_wish(item)
            if wish is None:
                continue
            key = json.dumps(wish, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            wishes.append(wish)
    return wishes, raw_text


def slot_violates_time_wish(slot: dict, wish: dict) -> bool:
    """True, если слот нарушает правило (для hard — запрет, для soft — штраф)."""
    typ = wish.get("type")
    day_filter = wish.get("day")
    slot_day = slot_day_canon(slot)
    if day_filter and slot_day != day_filter:
        # prefer_slots / forbid_slots по id — день не фильтруем отдельно
        if typ not in {"forbid_slots", "prefer_slots"}:
            return False

    slot_index = int(slot.get("slot_index") or 0)
    if typ == "no_slot_after":
        return slot_index > int(wish["slot_index"])
    if typ == "no_slot_before":
        return slot_index < int(wish["slot_index"])
    if typ == "no_first_slot":
        return slot_index == 1
    if typ == "no_day":
        return slot_day == wish.get("day")
    if typ == "forbid_slots":
        return slot["id"] in set(wish.get("timeslots_ids") or [])
    if typ == "prefer_slots":
        # нарушение soft-предпочтения: слот вне желаемого списка
        return slot["id"] not in set(wish.get("timeslots_ids") or [])
    return False


def block_violates_hard_time_wishes(block: list[dict], wishes: list[dict]) -> bool:
    hard = [wish for wish in wishes if wish.get("strength") != "soft"]
    for wish in hard:
        # prefer_slots только soft по умолчанию; на всякий случай skip soft-типов
        if wish.get("type") == "prefer_slots":
            continue
        for slot in block:
            if slot_violates_time_wish(slot, wish):
                return True
    return False


def soft_time_wish_penalty(block: list[dict], wishes: list[dict]) -> int:
    """Число мягких нарушений на блок (чем больше — тем хуже)."""
    soft = [wish for wish in wishes if wish.get("strength") == "soft"]
    penalty = 0
    for wish in soft:
        if wish.get("type") == "prefer_slots":
            # штраф, если старт (первый слот блока) не из желаемых
            if block and slot_violates_time_wish(block[0], wish):
                penalty += 1
            continue
        if any(slot_violates_time_wish(slot, wish) for slot in block):
            penalty += 1
    return penalty


def late_slot_penalty(block: list[dict], *, late_from: int) -> int:
    """Штраф за поздние пары: сумма (slot_index - late_from + 1) по слотам блока >= late_from."""
    if late_from <= 0:
        return 0
    penalty = 0
    for slot in block:
        idx = int(slot.get("slot_index") or 0)
        if idx >= late_from:
            penalty += idx - late_from + 1
    return penalty


def saturday_penalty(block: list[dict]) -> int:
    """1, если блок в субботу (по первому слоту)."""
    if not block:
        return 0
    return 1 if slot_day_canon(block[0]) == "суббота" else 0


def count_group_gaps_in_schedule(schedule: list[dict]) -> int:
    """
    Число «дырок» в днях групп: пустой slot_index между первой и последней
    парой группы в этот день (для приёмки п.14).
    """
    by_group_day: dict[tuple[str, str], set[int]] = {}
    for row in schedule:
        day = normalize_day_name(row.get("day")) or str(row.get("day") or "")
        start = int(row.get("slot_index_start") or row.get("slot_index") or 0)
        end = int(row.get("slot_index_end") or row.get("slot_index") or start)
        for group_id in row.get("group_ids") or []:
            key = (str(group_id), day)
            by_group_day.setdefault(key, set()).update(range(start, end + 1))

    gaps = 0
    for indices in by_group_day.values():
        if len(indices) < 2:
            continue
        low, high = min(indices), max(indices)
        for idx in range(low, high + 1):
            if idx not in indices:
                gaps += 1
    return gaps


def add_group_gap_objective_terms(
    model: cp_model.CpModel,
    x: dict,
    *,
    course_instances: list[dict],
    time_slots: list[dict],
    rooms: list[dict],
    covering_by_duration: dict[int, dict[int, list[int]]],
    weight: int,
) -> list:
    """
    Soft-штраф окон у академической группы: пустой слот между занятыми
    в тот же день (before ∧ after ∧ ¬occ).
    """
    if weight <= 0:
        return []

    def covering_vars(inst: dict, slot_id: int) -> list:
        duration = int(inst.get("duration_slots") or 1)
        covering = covering_by_duration.get(duration) or {}
        found = []
        for start_id in covering.get(slot_id, []):
            for room in rooms:
                key = (inst["instance_id"], start_id, room["id"])
                if key in x:
                    found.append(x[key])
        return found

    slots_by_day: dict[str, list[dict]] = {}
    for slot in time_slots:
        day = slot_day_canon(slot) or str(slot.get("day") or "")
        slots_by_day.setdefault(day, []).append(slot)
    for day_slots in slots_by_day.values():
        day_slots.sort(key=lambda item: int(item["slot_index"]))

    group_ids = sorted({
        group_id
        for inst in course_instances
        for group_id in (inst.get("group_ids") or [])
    })
    terms: list = []

    for group_id in group_ids:
        group_insts = [
            inst for inst in course_instances
            if group_id in (inst.get("group_ids") or [])
        ]
        if not group_insts:
            continue
        for day, day_slots in slots_by_day.items():
            # slot_index -> occupancy bool (или None, если нет переменных)
            occ_by_index: dict[int, object] = {}
            index_order: list[int] = []
            for slot in day_slots:
                idx = int(slot["slot_index"])
                if idx in occ_by_index:
                    continue
                index_order.append(idx)
                vars_for_index: list = []
                for candidate in day_slots:
                    if int(candidate["slot_index"]) != idx:
                        continue
                    for inst in group_insts:
                        vars_for_index.extend(covering_vars(inst, candidate["id"]))
                if not vars_for_index:
                    occ_by_index[idx] = None
                    continue
                occ = model.NewBoolVar(f"gap_occ_g{group_id}_{day}_i{idx}")
                model.AddMaxEquality(occ, vars_for_index)
                occ_by_index[idx] = occ

            usable = [idx for idx in index_order if occ_by_index[idx] is not None]
            if len(usable) < 3:
                # нужно хотя бы край-дырка-край
                continue
            for pos, idx in enumerate(usable):
                before_vars = [occ_by_index[u] for u in usable[:pos]]
                after_vars = [occ_by_index[u] for u in usable[pos + 1:]]
                if not before_vars or not after_vars:
                    continue
                before = model.NewBoolVar(f"gap_before_g{group_id}_{day}_i{idx}")
                after = model.NewBoolVar(f"gap_after_g{group_id}_{day}_i{idx}")
                model.AddMaxEquality(before, before_vars)
                model.AddMaxEquality(after, after_vars)
                hole = model.NewBoolVar(f"gap_hole_g{group_id}_{day}_i{idx}")
                occ = occ_by_index[idx]
                # hole >= 1, если before ∧ after ∧ ¬occ
                model.Add(before + after - occ <= 1 + hole)
                terms.append(-weight * hole)

    return terms


def collect_unmanaged_wish_warnings(
    course_instances: list[dict],
    courses: list[dict],
) -> list[dict]:
    """Сырой time_wish_raw / time_wish_unmanaged без применимых правил → warning."""
    warnings: list[dict] = []
    seen: set[str] = set()

    courses_by_id = {course["id"]: course for course in courses}
    for course in courses:
        for item in course.get("warnings") or []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").casefold()
            if code not in {"unmanaged_wish", "unmanaged_time_wish"}:
                continue
            key = f"course:{course['id']}:{item.get('message')}"
            if key in seen:
                continue
            seen.add(key)
            warnings.append({
                "code": "UNMANAGED_TIME_WISH",
                "message": item.get("message") or (
                    f"Нераспознанное пожелание времени у курса '{course['id']}'"
                ),
                "course_id": course["id"],
                "entity_ids": [],
                "time_wish_raw": item.get("time_wish_raw") or course.get("time_wish_raw"),
            })

        for item in course.get("time_wish_unmanaged") or []:
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("source") or "").strip()
                reason = item.get("reason")
            else:
                text = str(item).strip()
                reason = None
            if not text:
                continue
            key = f"unmanaged:{course['id']}:{text}:{reason}"
            if key in seen:
                continue
            seen.add(key)
            message = (
                f"Неформализованное пожелание времени у курса '{course['id']}': {text}"
            )
            if reason:
                message = f"{message} (reason={reason})"
            warnings.append({
                "code": "UNMANAGED_TIME_WISH",
                "message": message,
                "course_id": course["id"],
                "entity_ids": [],
                "time_wish_raw": text,
                "reason": reason,
            })

    for inst in course_instances:
        raw = inst.get("time_wish_raw")
        wishes = inst.get("time_wishes") or []
        if not raw:
            course = courses_by_id.get(inst["course_id"]) or {}
            raw = course.get("time_wish_raw")
        if not raw:
            continue
        if wishes:
            continue
        key = f"raw:{inst['course_id']}:{raw}"
        if key in seen:
            continue
        seen.add(key)
        warnings.append({
            "code": "UNMANAGED_TIME_WISH",
            "message": (
                f"У курса '{inst['name']}' есть time_wish_raw без структурированных "
                f"правил: {raw}"
            ),
            "course_id": inst["course_id"],
            "entity_ids": [inst["instance_id"]],
            "time_wish_raw": raw,
        })
    return warnings


def normalize_duration_slots(raw: object) -> int | None:
    """
    Дробный duration_slots парсера (1.0 / 1.5 / 2) → целое число слотов.

    Правило: ceil (1.5 → 2). Не использовать int(), он обрезает 1.5 → 1.
    """
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0 or math.isnan(value) or math.isinf(value):
        return None
    return max(1, int(math.ceil(value)))


def resolve_duration_slots(course: dict, source: dict | None = None) -> int:
    """Число непрерывных таймслотов одного размещения (>=1), один раз при expand."""
    source = source or {}
    for raw in (source.get("duration_slots"), course.get("duration_slots")):
        value = normalize_duration_slots(raw)
        if value is not None:
            return value
    return 1


def crosses_lunch_break(
    slot_a: dict,
    slot_b: dict,
    *,
    lunch_after_slot_index: int,
) -> bool:
    """True, если пара соседних по индексу слотов одного дня пересекает обед."""
    if slot_a.get("day") != slot_b.get("day"):
        return True
    ia = int(slot_a["slot_index"])
    ib = int(slot_b["slot_index"])
    if abs(ia - ib) != 1:
        return True
    lo, hi = (ia, ib) if ia < ib else (ib, ia)
    return lo == int(lunch_after_slot_index) and hi == int(lunch_after_slot_index) + 1


def build_duration_blocks(
    time_slots: list[dict],
    duration: int,
    config: dict | None = None,
) -> dict[int, list[dict]]:
    """
    Допустимые старты для duration непрерывных слотов одного дня.
    Ключ — id стартового слота, значение — список слотов блока.
    """
    duration = max(1, int(duration))
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    allow_lunch = bool(cfg.get("allow_duration_across_lunch", False))
    lunch_after = int(cfg.get("lunch_break_after_slot_index", 2))

    by_day: dict[str, list[dict]] = {}
    for slot in time_slots:
        by_day.setdefault(slot["day"], []).append(slot)
    for day_slots in by_day.values():
        day_slots.sort(key=lambda s: int(s["slot_index"]))

    blocks: dict[int, list[dict]] = {}
    for day_slots in by_day.values():
        if duration == 1:
            for slot in day_slots:
                blocks[slot["id"]] = [slot]
            continue
        for i in range(len(day_slots) - duration + 1):
            block = day_slots[i : i + duration]
            ok = True
            for left, right in zip(block, block[1:]):
                if int(right["slot_index"]) != int(left["slot_index"]) + 1:
                    ok = False
                    break
                if not allow_lunch and crosses_lunch_break(
                    left,
                    right,
                    lunch_after_slot_index=lunch_after,
                ):
                    ok = False
                    break
            if ok:
                blocks[block[0]["id"]] = block
    return blocks


def index_blocks_by_occupied_slot(
    blocks: dict[int, list[dict]],
) -> dict[int, list[int]]:
    """slot_id -> список start_slot_id, чьи блоки покрывают этот слот."""
    covering: dict[int, list[int]] = {}
    for start_id, block in blocks.items():
        for slot in block:
            covering.setdefault(slot["id"], []).append(start_id)
    return covering


def instance_weeks(inst: dict) -> frozenset[int]:
    """Множество недель instance (уже раскрытое expand_course_instances)."""
    weeks = inst.get("weeks")
    if isinstance(weeks, frozenset):
        return weeks
    if weeks is not None:
        return frozenset(int(w) for w in weeks)
    pattern = normalize_week_pattern(inst.get("week_pattern", "all"))
    return expand_weeks(pattern, resolve_semester_weeks({}, DEFAULT_CONFIG))


def add_pairwise_week_conflicts(model: cp_model.CpModel, var_groups: list[list]) -> None:
    """
    Жёсткий конфликт ресурсов только при пересечении недель:
    для каждой пары (vars_i, weeks_i) / (vars_j, weeks_j) с пересечением
    запрещаем одновременный выбор (sum(vars_i) + sum(vars_j) <= 1).
    var_groups: [(vars_list, weeks_set), ...]
    """
    n = len(var_groups)
    for i in range(n):
        vars_i, weeks_i = var_groups[i]
        if not vars_i:
            continue
        for j in range(i + 1, n):
            vars_j, weeks_j = var_groups[j]
            if not vars_j:
                continue
            if not weeks_intersect(weeks_i, weeks_j):
                continue
            model.Add(sum(vars_i) + sum(vars_j) <= 1)


def resolve_course_display_name(course: dict, source: dict | None = None) -> str:
    """
    Отображаемое имя занятия без обязательного courses[].name.

    Порядок: instance/source.name → discipline (lesson_type) → legacy course.name → id.
    """
    source = source or {}
    for raw in (
        source.get("name"),
        course.get("name"),
    ):
        text = str(raw).strip() if raw is not None else ""
        if text:
            return text

    discipline = str(
        source.get("discipline") or course.get("discipline") or ""
    ).strip()
    lesson_type = str(
        source.get("lesson_type") or course.get("lesson_type") or ""
    ).strip()
    if discipline and lesson_type:
        return f"{discipline} ({lesson_type})"
    if discipline:
        return discipline
    if lesson_type:
        return lesson_type
    return str(course.get("id") or source.get("id") or source.get("instance_id") or "")


def resolve_lesson_kind(course: dict, source: dict | None = None) -> str:
    """
    lecture_stream | practice_subgroup | other.

    Явное поле lesson_kind предпочтительнее; иначе эвристика по имени/типу.
    """
    source = source or {}
    raw = (
        source.get("lesson_kind")
        or course.get("lesson_kind")
        or source.get("lesson_type")
        or course.get("lesson_type")
        or ""
    )
    kind = str(raw).casefold().strip()
    if kind in {"lecture_stream", "lecture", "лекция", "лек"}:
        return "lecture_stream"
    if kind in {
        "practice_subgroup",
        "practice",
        "lab",
        "лабораторная",
        "практика",
        "лаб",
    }:
        return "practice_subgroup"

    name = resolve_course_display_name(course, source).casefold()
    if "(лекция)" in name or name.endswith("лекция"):
        return "lecture_stream"
    if "(практика)" in name or "(лабораторная)" in name:
        return "practice_subgroup"
    if "лекц" in name:
        return "lecture_stream"
    if "практ" in name or "лаб" in name:
        return "practice_subgroup"
    # подгруппы без явного типа — практика/лаб
    if source.get("subgroup_index") is not None or course.get("instances"):
        return "practice_subgroup"
    return "other"


def resolve_students_needed(
    course: dict,
    source: dict | None,
    *,
    group_ids: list[str],
    group_sizes: dict[str, int],
    lesson_kind: str,
    config: dict,
) -> int:
    """
    Сколько мест нужно в аудитории.

    Приоритет: явный students_needed / stream_size → оценка по lesson_kind.
    Capacity аудиторий никогда не меняем.
    """
    source = source or {}
    for key in ("students_needed", "stream_size", "total_students"):
        for obj in (source, course):
            value = obj.get(key)
            if value is None or value == "":
                continue
            try:
                number = int(float(value))
            except (TypeError, ValueError):
                continue
            if number >= 0:
                return number

    default_size = int(config.get("default_group_size", 30))
    sizes = [int(group_sizes.get(group_id, default_size)) for group_id in group_ids]
    if not sizes:
        return default_size

    raw_sum = sum(sizes)
    if lesson_kind == "practice_subgroup":
        return max(1, raw_sum)

    if lesson_kind == "lecture_stream":
        factor = float(config.get("lecture_stream_size_factor", 0.8))
        # Если парсер оставил дефолтные size у всего потока — не раздувать до 30×N
        if (
            len(sizes) >= 2
            and all(size == default_size for size in sizes)
            and 0 < factor < 1
        ):
            return max(default_size, int(round(raw_sum * factor)))
        return max(1, raw_sum)

    return max(1, raw_sum)


def _ensure_teacher_ids(
    teacher_ids: list[str],
    *,
    course_id: str,
    subgroup_index: object = None,
) -> list[str]:
    """
    Пустой teacher не должен обходить конфликт занятости.
    Уникальный placeholder на курс/подгруппу.
    """
    if teacher_ids:
        return teacher_ids
    if subgroup_index is None:
        return [f"UNKNOWN:{course_id}"]
    return [f"UNKNOWN:{course_id}:sg{subgroup_index}"]


def make_missing_teacher_error(
    *,
    course_id: str,
    course_name: str,
    instance_id: str,
    venue_type: str,
) -> dict:
    return {
        "code": "MISSING_TEACHER",
        "message": (
            f"У курса '{course_name}' ({course_id}) нет преподавателя; "
            f"в режиме strict solve не запускается "
            f"(venue_type={venue_type})"
        ),
        "course_id": course_id,
        "entity_ids": [instance_id],
        "venue_type": venue_type,
    }


def make_missing_teacher_warning(
    *,
    course_id: str,
    course_name: str,
    instance_id: str,
    teacher_id: str,
) -> dict:
    return {
        "code": "MISSING_TEACHER_PLACEHOLDER",
        "message": (
            f"У курса '{course_name}' нет преподавателя; "
            f"подставлен уникальный placeholder '{teacher_id}' "
            f"(участвует в конфликте занятости)"
        ),
        "course_id": course_id,
        "entity_ids": [instance_id],
        "teacher_id": teacher_id,
    }


def validate_instance_teachers(course_instances: list[dict]) -> list[dict]:
    """
    После expand: никакого общего null; каждый instance с непустым teacher_ids
    участвует в H-C.
    """
    errors: list[dict] = []
    for inst in course_instances:
        raw_ids = list(inst.get("teacher_ids") or [])
        if any(_is_missing_teacher_id(teacher_id) for teacher_id in raw_ids):
            errors.append({
                "code": "MISSING_TEACHER_UNRESOLVED",
                "message": (
                    f"У занятия '{inst['instance_id']}' остался пустой/общий "
                    f"teacher_id {raw_ids}; нужен уникальный id"
                ),
                "course_id": inst["course_id"],
                "entity_ids": [inst["instance_id"]],
                "teacher_ids": raw_ids,
            })
            continue
        if not instance_teacher_ids(inst):
            errors.append({
                "code": "MISSING_TEACHER_UNRESOLVED",
                "message": (
                    f"У занятия '{inst['instance_id']}' нет teacher_ids для "
                    f"ограничения занятости преподавателя"
                ),
                "course_id": inst["course_id"],
                "entity_ids": [inst["instance_id"]],
            })
    return errors


def expand_course_instances(
    courses: list[dict],
    *,
    group_sizes: dict[str, int],
    fixed_entry_by_course: dict[str, dict],
    config: dict | None = None,
    semester_weeks: list[int] | None = None,
) -> tuple[list[dict], dict[str, int], list[dict], list[dict]]:
    """
    Построить размещаемые units.

    Mode B (п.5): courses[].instances — отдельные занятия/подгруппы.
    Mode A (п.6): один unit с несколькими teacher_ids — все заняты в выбранном слоте.

    Возвращает (instances, counts_by_course, errors, warnings).
    """
    solver_config = {**DEFAULT_CONFIG, **(config or {})}
    teacher_policy = resolve_missing_teacher_policy(solver_config)
    weeks_calendar = list(semester_weeks or resolve_semester_weeks({}, solver_config))
    course_instances: list[dict] = []
    instances_per_course: dict[str, int] = {}
    errors: list[dict] = []
    warnings: list[dict] = []

    for course in courses:
        fixed_entry = fixed_entry_by_course.get(course["id"])
        base_lessons = int(course.get("lessons_per_week") or 1)
        raw_subgroups = course.get("instances")

        if raw_subgroups:
            subgroup_units = list(raw_subgroups)
            teaching_mode = "subgroup"  # Mode B
        else:
            subgroup_units = [None]
            teaching_mode = "co_teach"  # может стать solo, если teacher один

        created_for_course = 0
        for subgroup_pos, subgroup in enumerate(subgroup_units, start=1):
            source = subgroup if isinstance(subgroup, dict) else {}
            venue_type = resolve_venue_type(course, source, fixed_entry)
            if source.get("needs_room") is not None:
                needs_room_flag = source.get("needs_room")
            elif course.get("needs_room") is not None:
                needs_room_flag = course.get("needs_room")
            elif fixed_entry is not None and fixed_entry.get("needs_room") is not None:
                needs_room_flag = fixed_entry.get("needs_room")
            else:
                needs_room_flag = None
            needs_room = venue_needs_physical_room(
                venue_type,
                needs_room=needs_room_flag,
            )
            group_ids = list(
                source.get("group_ids")
                if source.get("group_ids") is not None
                else course.get("group_ids") or []
            )
            lesson_kind = resolve_lesson_kind(course, source)
            total_students = resolve_students_needed(
                course,
                source,
                group_ids=group_ids,
                group_sizes=group_sizes,
                lesson_kind=lesson_kind,
                config=solver_config,
            )
            week_pattern = normalize_week_pattern(
                source.get("week_pattern", course.get("week_pattern", "all"))
            )
            weeks = expand_weeks(week_pattern, weeks_calendar)
            duration_slots = resolve_duration_slots(course, source)

            subgroup_index = source.get(
                "subgroup_index",
                subgroup_pos if raw_subgroups else None,
            )
            resolved_teachers = _resolve_teacher_ids(source, course)
            teacher_was_missing = not resolved_teachers
            # В strict очные без ФИО — ошибка; online/external/sport → placeholder.
            if (
                teacher_was_missing
                and teacher_policy == "strict"
                and venue_needs_physical_room(venue_type, needs_room=needs_room_flag)
            ):
                # instance_id ещё не финальный для всех lesson_idx — ошибка на курс/подгруппу
                provisional_id = (
                    f"{course['id']}_{source.get('id') or source.get('instance_id')}"
                    if (source.get("id") or source.get("instance_id"))
                    else (
                        f"{course['id']}_sg{subgroup_index}"
                        if raw_subgroups
                        else course["id"]
                    )
                )
                errors.append(make_missing_teacher_error(
                    course_id=course["id"],
                    course_name=resolve_course_display_name(course, source),
                    instance_id=provisional_id,
                    venue_type=venue_type,
                ))
                continue

            teacher_ids = _ensure_teacher_ids(
                resolved_teachers,
                course_id=course["id"],
                subgroup_index=subgroup_index,
            )
            teacher_id = teacher_ids[0]
            unit_mode = (
                teaching_mode
                if teaching_mode == "subgroup"
                else ("co_teach" if len(teacher_ids) > 1 else "solo")
            )
            requirements = list(
                source["requirements"]
                if source.get("requirements") is not None
                else course.get("requirements") or []
            )
            lessons = int(source.get("lessons_per_week") or base_lessons)
            subgroup_count = source.get(
                "subgroup_count",
                len(subgroup_units) if raw_subgroups else None,
            )
            team_label = source.get("team_label")
            subgroup_id = source.get("id") or source.get("instance_id")
            allowed_room_ids = resolve_allowed_room_ids(course, source)
            same_room_as_course_id = resolve_same_room_as_course_id(course, source)
            time_wishes, time_wish_raw = collect_time_wishes(course, source)

            for lesson_idx in range(lessons):
                if subgroup_id:
                    instance_id = f"{course['id']}_{subgroup_id}_L{lesson_idx}"
                elif raw_subgroups:
                    instance_id = f"{course['id']}_sg{subgroup_index}_L{lesson_idx}"
                else:
                    instance_id = f"{course['id']}_inst_{lesson_idx}"

                if not weeks:
                    errors.append({
                        "code": "EMPTY_WEEK_PATTERN",
                        "message": (
                            f"У курса '{course['id']}' week_pattern {week_pattern} "
                            f"не даёт ни одной недели в календаре {weeks_calendar[:3]}..."
                        ),
                        "course_id": course["id"],
                        "entity_ids": [instance_id],
                        "week_pattern": week_pattern,
                    })
                    continue

                display_name = resolve_course_display_name(course, source)

                if teacher_was_missing:
                    warnings.append(make_missing_teacher_warning(
                        course_id=course["id"],
                        course_name=display_name,
                        instance_id=instance_id,
                        teacher_id=teacher_id,
                    ))

                course_instances.append({
                    "instance_id": instance_id,
                    "course_id": course["id"],
                    "name": display_name,
                    "teacher_id": teacher_id,
                    "teacher_ids": teacher_ids,
                    "teacher_missing": teacher_was_missing,
                    "teacher_is_placeholder": teacher_was_missing or any(
                        _is_teacher_placeholder(tid) for tid in teacher_ids
                    ),
                    "teaching_mode": unit_mode,
                    "lesson_kind": lesson_kind,
                    "group_ids": group_ids,
                    "total_students": total_students,
                    "students_needed": total_students,
                    "requirements": requirements,
                    "needs_software": source.get("needs_software", course.get("needs_software")),
                    "venue_type": venue_type,
                    "needs_physical_room": needs_room,
                    "subgroup_index": subgroup_index,
                    "subgroup_count": subgroup_count,
                    "team_label": team_label,
                    "week_pattern": week_pattern,
                    "weeks": weeks,
                    "duration_slots": duration_slots,
                    "allowed_room_ids": allowed_room_ids,
                    "same_room_as_course_id": same_room_as_course_id,
                    "time_wishes": time_wishes,
                    "time_wish_raw": time_wish_raw,
                })
                created_for_course += 1

        instances_per_course[course["id"]] = created_for_course

    return course_instances, instances_per_course, errors, warnings


def normalize_venue_type(raw: object) -> str:
    """
    Канон: room | online | external | sport | virtual | unspecified.
    НТК / онлайн → online; выезд → external; спортзал → sport.
    """
    if raw is None or raw == "":
        return "unspecified"
    text = str(raw).casefold().strip()
    if text in VENUE_TYPE_ALIASES:
        return VENUE_TYPE_ALIASES[text]
    for alias, canon in VENUE_TYPE_ALIASES.items():
        if alias and alias in text:
            return canon
    return "unspecified"


def resolve_venue_type(
    course: dict,
    source: dict | None = None,
    fixed_entry: dict | None = None,
) -> str:
    """venue_type instance ← source / course / fixed_schedules."""
    source = source or {}
    fixed_entry = fixed_entry or {}
    for raw in (
        source.get("venue_type"),
        course.get("venue_type"),
        fixed_entry.get("venue_type"),
    ):
        if raw is None or raw == "":
            continue
        return normalize_venue_type(raw)
    return "unspecified"


def venue_needs_physical_room(
    venue_type: str,
    *,
    needs_room: object = None,
) -> bool:
    """Нужна ли обычная аудитория из справочника ИЕНИМ."""
    if needs_room is False:
        return False
    if needs_room is True:
        return True
    return normalize_venue_type(venue_type) not in VENUE_TYPES_WITHOUT_ROOM


def course_needs_physical_room(course: dict, fixed_entry: dict | None = None) -> bool:
    """Нужна ли обычная аудитория ИЕНИМ для курса (с учётом fixed_schedules)."""
    fixed_entry = fixed_entry or {}
    if fixed_entry.get("needs_room") is False or course.get("needs_room") is False:
        return False
    if fixed_entry.get("needs_room") is True or course.get("needs_room") is True:
        return True
    return venue_needs_physical_room(resolve_venue_type(course, fixed_entry=fixed_entry))


def virtual_room_prefix(venue_type: str) -> str:
    canon = normalize_venue_type(venue_type)
    return {
        "online": "__ONLINE__",
        "external": "__EXTERNAL__",
        "sport": "__SPORT__",
        "virtual": "__VIRTUAL__",
    }.get(canon, "__VIRTUAL__")


def make_virtual_room(course_id: str, venue_type: str = "virtual") -> dict:
    """Площадка вне справочника ИЕНИМ: без конфликта H-B по обычным аудиториям."""
    canon = normalize_venue_type(venue_type)
    if canon in {"room", "unspecified"}:
        canon = "virtual"
    prefix = virtual_room_prefix(canon)
    return {
        "id": f"{prefix}:{course_id}",
        "capacity": 10**9,
        "is_virtual": True,
        "venue_type": canon,
        "has_chalkboard": True,
        "has_whiteboard": True,
        "has_multimedia_board": True,
        "has_blinds": True,
        "has_screen": True,
        "has_acoustic_system": True,
        "has_board": True,
    }


def ensure_virtual_room(
    rooms: list[dict],
    rooms_by_id: dict[str, dict],
    *,
    course_id: str,
    venue_type: str,
) -> dict:
    """Добавить виртуальную площадку курса в список rooms при отсутствии."""
    virtual = make_virtual_room(course_id, venue_type)
    if virtual["id"] not in rooms_by_id:
        rooms.append(virtual)
        rooms_by_id[virtual["id"]] = virtual
    return rooms_by_id[virtual["id"]]


def resolve_allowed_room_ids(course: dict, source: dict | None = None) -> list[str] | None:
    """Явный whitelist аудиторий; None = без ограничения."""
    source = source or {}
    raw = source.get("allowed_room_ids")
    if raw is None:
        raw = course.get("allowed_room_ids")
    if raw is None or raw == "":
        return None
    if isinstance(raw, (str, int)):
        raw = [raw]
    ids = [
        room_id
        for item in raw
        if (room_id := normalize_room_id(item))
    ]
    return list(dict.fromkeys(ids)) or None


def resolve_same_room_as_course_id(course: dict, source: dict | None = None) -> str | None:
    """Связь «вместе с лекциями» → id курса, чью аудиторию нужно повторить."""
    source = source or {}
    for raw in (
        source.get("same_room_as_course_id"),
        course.get("same_room_as_course_id"),
        source.get("same_room_as"),
        course.get("same_room_as"),
    ):
        if raw is None or raw == "":
            continue
        return str(raw).strip()
    return None


def parse_room_preblocked(raw: object) -> set[tuple]:
    """
    Занятость аудиторий из эталона (режим B парсера).
    Элементы: {slot_id|timeslot_id, room_id} → множество (slot_id, room_id).
    """
    blocked: set[tuple] = set()
    if not raw:
        return blocked
    rows = raw if isinstance(raw, list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        slot = row.get("slot_id", row.get("timeslot_id"))
        room = row.get("room_id")
        if slot is None or room is None or room == "":
            continue
        try:
            slot_id = int(slot)
        except (TypeError, ValueError):
            slot_id = slot
        blocked.add((slot_id, normalize_room_id(room)))
    return blocked


def build_same_room_groups(
    course_instances: list[dict],
    *,
    courses_by_id: dict[str, dict],
) -> tuple[list[list[dict]], list[dict]]:
    """
    Компоненты занятий, которые должны получить одну и ту же физическую аудиторию.
    Ребро: instance.same_room_as_course_id → курс (все его очные instances).
    """
    errors: list[dict] = []
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        root_l, root_r = find(left), find(right)
        if root_l != root_r:
            parent[root_r] = root_l

    known_course_ids = set(courses_by_id) | {inst["course_id"] for inst in course_instances}
    linked_course_ids: set[str] = set()

    for inst in course_instances:
        target = inst.get("same_room_as_course_id")
        if not target:
            continue
        if not inst.get("needs_physical_room", True):
            continue
        if target not in known_course_ids:
            errors.append({
                "code": "SAME_ROOM_UNKNOWN_COURSE",
                "message": (
                    f"Курс '{inst['course_id']}' ссылается на same_room_as_course_id "
                    f"'{target}', которого нет во входе"
                ),
                "course_id": inst["course_id"],
                "entity_ids": [inst["instance_id"]],
                "same_room_as_course_id": target,
            })
            continue
        if target == inst["course_id"]:
            continue
        union(inst["course_id"], target)
        linked_course_ids.add(inst["course_id"])
        linked_course_ids.add(target)

    if errors:
        return [], errors

    groups_by_root: dict[str, list[dict]] = {}
    for inst in course_instances:
        if not inst.get("needs_physical_room", True):
            continue
        if inst["course_id"] not in linked_course_ids:
            continue
        root = find(inst["course_id"])
        groups_by_root.setdefault(root, []).append(inst)

    groups = [group for group in groups_by_root.values() if len(group) >= 2]
    return groups, errors


def add_same_room_constraints(
    model: cp_model.CpModel,
    x: dict,
    *,
    groups: list[list[dict]],
    rooms: list[dict],
    blocks_by_duration: dict[int, dict[int, list[dict]]],
) -> None:
    """Жёстко: все instances группы выбирают один и тот же room_id."""
    physical_rooms = [room for room in rooms if not room.get("is_virtual")]
    for group in groups:
        # None = аудитория недоступна instance (константа 0); иначе LinearExpr
        used: dict[tuple[str, str], object | None] = {}
        for inst in group:
            duration = int(inst.get("duration_slots") or 1)
            start_ids = list((blocks_by_duration.get(duration) or {}).keys())
            for room in physical_rooms:
                vars_for_room = [
                    x[(inst["instance_id"], start_id, room["id"])]
                    for start_id in start_ids
                    if (inst["instance_id"], start_id, room["id"]) in x
                ]
                used[(inst["instance_id"], room["id"])] = (
                    sum(vars_for_room) if vars_for_room else None
                )

        anchor_id = group[0]["instance_id"]
        for inst in group[1:]:
            for room in physical_rooms:
                left = used[(anchor_id, room["id"])]
                right = used[(inst["instance_id"], room["id"])]
                if left is None and right is None:
                    continue
                if left is None:
                    model.Add(right == 0)
                elif right is None:
                    model.Add(left == 0)
                else:
                    model.Add(left == right)


def filter_rooms_by_allowed_ids(
    rooms: list[dict],
    allowed_room_ids: list[str] | None,
    *,
    rooms_by_id: dict[str, dict],
) -> tuple[list[dict], list[str]]:
    """
    Оставить только аудитории из whitelist.
    Возвращает (rooms, unknown_ids).
    """
    if not allowed_room_ids:
        return rooms, []
    allowed_set = {normalize_room_id(room_id) for room_id in allowed_room_ids}
    unknown = sorted(room_id for room_id in allowed_set if room_id not in rooms_by_id)
    filtered = [
        room for room in rooms
        if not room.get("is_virtual") and normalize_room_id(room["id"]) in allowed_set
    ]
    return filtered, unknown


def select_candidate_rooms(
    rooms: list[dict],
    *,
    total_students: int,
    requirements: list[str] | None,
    needs_software: object,
    max_candidate_rooms: int,
) -> list[dict]:
    """
    Сужение домена аудиторий (п.15): только feasible, затем до N ближайших
    по вместимости (сначала те, что не сильно больше нужды).
    """
    feasible = [
        room for room in rooms
        if not room.get("is_virtual")
        and room_is_feasible(
            room,
            total_students=total_students,
            requirements=requirements,
            needs_software=needs_software,
        )
    ]
    if max_candidate_rooms <= 0 or len(feasible) <= max_candidate_rooms:
        return feasible

    def sort_key(room: dict) -> tuple:
        capacity = int(room.get("capacity") or 0)
        overflow = max(0, capacity - total_students)
        under = max(0, total_students - capacity)  # уже отфильтровано, =0
        return (under, overflow, capacity, str(room.get("id")))

    feasible.sort(key=sort_key)
    return feasible[:max_candidate_rooms]


def estimate_decision_var_count(
    course_instances: list[dict],
    *,
    blocks_by_duration: dict[int, dict[int, list[dict]]],
    avg_rooms_per_instance: float,
) -> int:
    """Грубая оценка |x| = sum_inst |starts| × |rooms|."""
    total = 0
    for inst in course_instances:
        duration = int(inst.get("duration_slots") or 1)
        starts = len(blocks_by_duration.get(duration) or {})
        total += starts
    return int(total * max(1.0, avg_rooms_per_instance))


def resolve_solve_strategy(
    config: dict,
    *,
    estimated_vars: int,
) -> str:
    raw = str(config.get("solve_strategy") or "auto").casefold().strip()
    if raw in {"monolithic", "mono", "single"}:
        return "monolithic"
    if raw in {"two_phase", "two-phase", "2phase", "phased"}:
        return "two_phase"
    threshold = int(config.get("var_threshold_two_phase") or 80_000)
    return "two_phase" if estimated_vars >= threshold else "monolithic"


def make_phase1_slot_room(course_id: str) -> dict:
    """Служебная «аудитория» phase1: только выбор слота, без H-B."""
    return {
        "id": f"__SLOT_ONLY__:{course_id}",
        "capacity": 10**9,
        "is_virtual": True,
        "is_phase1_placeholder": True,
        "venue_type": "virtual",
        "has_board": True,
    }


def validate_fixed_schedules(
    fixed_schedules: list[dict] | None,
    *,
    courses: list[dict],
    time_slots: list[dict],
    instances_per_course: dict[str, int],
) -> tuple[dict[str, list[int]], list[dict]]:
    """
    Pre-check fixed_schedules.

    Политика: если число timeslots_ids == числу занятий курса (lessons_per_week
    при duration_slots=1), все перечисленные слоты обязательны (биекция).
    """
    errors: list[dict] = []
    fixed_slots_by_course: dict[str, list[int]] = {}
    slot_ids = {slot["id"] for slot in time_slots}
    courses_by_id = {course["id"]: course for course in courses}

    for entry in fixed_schedules or []:
        course_id = entry.get("course_id")
        raw_slots = entry.get("timeslots_ids") or []
        if not course_id:
            errors.append({
                "code": "FIXED_SCHEDULE_MISSING_COURSE_ID",
                "message": "В fixed_schedules отсутствует course_id",
                "course_id": None,
                "entity_ids": [],
                "timeslots_ids": list(raw_slots),
            })
            continue
        if course_id not in courses_by_id:
            errors.append({
                "code": "FIXED_SCHEDULE_UNKNOWN_COURSE",
                "message": f"fixed_schedules ссылается на неизвестный course_id '{course_id}'",
                "course_id": course_id,
                "entity_ids": [],
                "timeslots_ids": list(raw_slots),
            })
            continue

        invalid = [slot_id for slot_id in raw_slots if slot_id not in slot_ids]
        if invalid:
            errors.append({
                "code": "FIXED_SCHEDULE_INVALID_SLOT",
                "message": (
                    f"Для курса '{course_id}' в fixed_schedules указаны несуществующие "
                    f"слоты {invalid}"
                ),
                "course_id": course_id,
                "entity_ids": [],
                "timeslots_ids": list(raw_slots),
                "invalid_timeslots_ids": invalid,
            })
            continue

        slots = [int(slot_id) for slot_id in raw_slots]
        if len(slots) != len(set(slots)):
            errors.append({
                "code": "FIXED_SCHEDULE_DUPLICATE_SLOTS",
                "message": (
                    f"Для курса '{course_id}' в fixed_schedules слоты повторяются: {slots}"
                ),
                "course_id": course_id,
                "entity_ids": [],
                "timeslots_ids": slots,
            })
            continue

        course = courses_by_id[course_id]
        duration = (
            normalize_duration_slots(course.get("duration_slots"))
            or normalize_duration_slots(entry.get("duration_slots"))
            or 1
        )
        lessons = int(instances_per_course.get(course_id) or 0)
        expected_slots = lessons * duration
        if len(slots) != expected_slots:
            errors.append({
                "code": "FIXED_SCHEDULE_COUNT_MISMATCH",
                "message": (
                    f"Для курса '{course_id}' ожидается {expected_slots} слотов "
                    f"(занятий={lessons}, duration_slots={duration}), "
                    f"в fixed_schedules {len(slots)}: {slots}"
                ),
                "course_id": course_id,
                "entity_ids": [],
                "timeslots_ids": slots,
                "expected_slots": expected_slots,
                "lessons_per_week": lessons,
                "duration_slots": duration,
            })
            continue

        if course_id in fixed_slots_by_course and fixed_slots_by_course[course_id] != slots:
            errors.append({
                "code": "FIXED_SCHEDULE_CONFLICT",
                "message": (
                    f"Для курса '{course_id}' заданы разные fixed_schedules: "
                    f"{fixed_slots_by_course[course_id]} и {slots}"
                ),
                "course_id": course_id,
                "entity_ids": [],
                "timeslots_ids": slots,
            })
            continue

        fixed_slots_by_course[course_id] = slots

    return fixed_slots_by_course, errors


def apply_fixed_schedule_mismatch_policy(
    errors: list[dict],
    *,
    policy: str,
) -> tuple[list[dict], list[dict]]:
    """
    strict — все ошибки fixed_schedules остаются ERROR.
    warn — COUNT_MISMATCH / CONFLICT → warnings, запись не применяется
    (validate уже не добавил её в fixed_slots_by_course).
    """
    policy = str(policy or "strict").casefold()
    if policy != "warn":
        return list(errors), []
    hard: list[dict] = []
    soft: list[dict] = []
    soft_codes = {
        "FIXED_SCHEDULE_COUNT_MISMATCH",
        "FIXED_SCHEDULE_CONFLICT",
    }
    for item in errors:
        if item.get("code") in soft_codes:
            soft.append({
                **item,
                "message": (
                    f"{item.get('message')} — fixed_schedules для курса пропущен "
                    f"(fixed_schedule_mismatch_policy=warn)"
                ),
            })
        else:
            hard.append(item)
    return hard, soft


def soften_infeasible_fixed_rooms(
    course_instances: list[dict],
    wanted_prefs_by_instance: dict[str, dict],
    *,
    rooms_by_id: dict[str, dict],
    policy: str,
) -> list[dict]:
    """
    infeasible_fixed_room_policy=warn: снять невыполнимый fixed_room,
    оставить обычный домен аудиторий + warning.
    """
    if str(policy or "strict").casefold() != "warn":
        return []
    warnings: list[dict] = []
    for inst in course_instances:
        pref = wanted_prefs_by_instance.get(inst["instance_id"]) or {}
        fixed_room = pref.get("fixed_room")
        if not fixed_room:
            continue
        fixed_room = normalize_room_id(fixed_room)
        room = rooms_by_id.get(fixed_room) if fixed_room else None
        ok = (
            room is not None
            and room_is_feasible(
                room,
                total_students=inst["total_students"],
                requirements=inst.get("requirements"),
                needs_software=inst.get("needs_software"),
            )
        )
        if ok:
            continue
        pref["fixed_room"] = None
        pref["fixed_rooms"] = set()
        reason = "not_found" if room is None else "infeasible"
        warnings.append({
            "code": "INFEASIBLE_FIXED_ROOM_IGNORED",
            "message": (
                f"Для курса '{inst.get('name')}' fixed_room '{fixed_room}' "
                f"пропущен ({reason}); ищем любую подходящую аудиторию "
                f"(infeasible_fixed_room_policy=warn)"
            ),
            "course_id": inst.get("course_id"),
            "entity_ids": [inst["instance_id"]],
            "fixed_room": fixed_room,
            "reason": reason,
            "students_needed": inst.get("total_students"),
            "requirements": list(inst.get("requirements") or []),
        })
    return warnings


def drop_unplaceable_instances(
    course_instances: list[dict],
    *,
    rooms: list[dict],
    rooms_by_id: dict[str, dict],
    wanted_prefs_by_instance: dict[str, dict],
    solver_config: dict,
    policy: str,
) -> tuple[list[dict], list[dict]]:
    """
    unplaceable_instance_policy=warn: убрать instances без домена аудиторий
    (типично students_needed > max capacity) с warning, чтобы остальной вход решался.
    """
    if str(policy or "strict").casefold() != "warn":
        return course_instances, []
    kept: list[dict] = []
    warnings: list[dict] = []
    for inst in course_instances:
        pref = wanted_prefs_by_instance.get(inst["instance_id"]) or {
            "fixed_room": None,
            "wanted_slot_ids": set(),
            "extra_requirements": [],
            "preferred_capacity": None,
            "preferred_room_types": [],
        }
        domain, err = _collect_instance_room_domain(
            inst,
            rooms=rooms,
            rooms_by_id=rooms_by_id,
            pref=pref,
            solver_config=solver_config,
        )
        if domain:
            kept.append(inst)
            continue
        err_code = None
        err_message = None
        if isinstance(err, dict):
            first = (err.get("errors") or [{}])[0]
            err_code = first.get("code")
            err_message = first.get("message")
        warnings.append({
            "code": "UNPLACEABLE_INSTANCE_DROPPED",
            "message": (
                err_message
                or (
                    f"Занятие '{inst.get('name')}' ({inst['instance_id']}) "
                    f"пропущено: нет допустимой аудитории"
                )
            ) + " (unplaceable_instance_policy=warn)",
            "course_id": inst.get("course_id"),
            "entity_ids": [inst["instance_id"]],
            "students_needed": inst.get("total_students"),
            "requirements": list(inst.get("requirements") or []),
            "cause_code": err_code,
        })
    return kept, warnings


def build_fixed_room_error(inst: dict, pref: dict, rooms_by_id: dict[str, dict]) -> dict:
    fixed_room = pref.get("fixed_room")
    room = rooms_by_id.get(fixed_room) if fixed_room else None
    if room is None:
        return {
            "status": "ERROR",
            "errors": [{
                "code": "FIXED_ROOM_NOT_FOUND",
                "message": (
                    f"Для курса '{inst['name']}' указана аудитория '{fixed_room}', "
                    f"которой нет в справочнике"
                ),
                "course_id": inst["course_id"],
                "entity_ids": [inst["instance_id"]],
                "teacher_id": inst.get("teacher_id"),
                "fixed_room": fixed_room,
            }],
            "message": f"Аудитория '{fixed_room}' не найдена в справочнике",
        }

    requirements = list(inst.get("requirements") or [])
    return {
        "status": "ERROR",
        "errors": [{
            "code": "FIXED_ROOM_INFEASIBLE",
            "message": (
                f"Для курса '{inst['name']}' аудитория '{fixed_room}' недоступна "
                f"(вместимость {room.get('capacity')}, нужно студентов "
                f"{inst['total_students']}, требования {requirements or '—'})"
            ),
            "course_id": inst["course_id"],
            "entity_ids": [inst["instance_id"]],
            "teacher_id": inst.get("teacher_id"),
            "fixed_room": fixed_room,
            "requirements": requirements,
            "students_needed": inst["total_students"],
            "room_capacity": room.get("capacity"),
        }],
        "message": f"Фиксированная аудитория '{fixed_room}' не подходит для курса '{inst['name']}'",
    }


def build_allowed_rooms_error(
    inst: dict,
    *,
    allowed_room_ids: list[str],
    unknown_ids: list[str],
    candidate_rooms: list[dict],
) -> dict:
    """Пустой домен из-за allowed_room_ids / несовместимости со справочником."""
    if unknown_ids and not candidate_rooms:
        code = "ALLOWED_ROOMS_UNKNOWN"
        message = (
            f"Для курса '{inst['name']}' ни одна из allowed_room_ids {allowed_room_ids} "
            f"не найдена в справочнике (нет: {unknown_ids})"
        )
    elif unknown_ids:
        code = "ALLOWED_ROOMS_INFEASIBLE"
        message = (
            f"Для курса '{inst['name']}' аудитории из allowed_room_ids {allowed_room_ids} "
            f"не дают допустимого размещения (нет в справочнике: {unknown_ids})"
        )
    else:
        code = "ALLOWED_ROOMS_INFEASIBLE"
        message = (
            f"Для курса '{inst['name']}' ни одна аудитория из allowed_room_ids "
            f"{allowed_room_ids} не подходит по вместимости/требованиям"
        )
    return {
        "status": "ERROR",
        "errors": [{
            "code": code,
            "message": message,
            "course_id": inst["course_id"],
            "entity_ids": [inst["instance_id"]],
            "allowed_room_ids": allowed_room_ids,
            "unknown_room_ids": unknown_ids,
            "students_needed": inst.get("students_needed", inst.get("total_students")),
            "requirements": list(inst.get("requirements") or []),
        }],
        "message": message,
    }


def build_no_room_error(inst: dict, rooms: list[dict]) -> dict:
    """ERROR с course_id, требованиями и подсказкой по почти подходящим аудиториям."""
    requirements = list(inst.get("requirements") or [])
    needs_software = inst.get("needs_software")
    capacity_ok = []
    almost = []
    for room in rooms:
        capacity = room_capacity_value(room)
        if capacity is None or capacity < inst["total_students"]:
            continue
        capacity_ok.append(room["id"])
        missing = _missing_requirements_for_room(room, requirements)
        soft_ok = room_meets_software(room, needs_software)
        if missing or not soft_ok:
            almost.append({
                "room_id": room["id"],
                "capacity": room.get("capacity"),
                "missing_requirements": missing,
                "software_ok": soft_ok,
            })

    hint_parts = []
    if not capacity_ok:
        hint_parts.append(
            f"нет аудиторий вместимостью >= {inst['total_students']}"
        )
    elif almost:
        preview = ", ".join(
            f"{item['room_id']} (не хватает: {', '.join(item['missing_requirements']) or 'ПО'})"
            for item in almost[:5]
        )
        hint_parts.append(f"по вместимости подходят, но не по оснащению: {preview}")
    else:
        hint_parts.append("нет аудиторий, удовлетворяющих всем hard-требованиям")

    return {
        "status": "ERROR",
        "errors": [{
            "code": "NO_FEASIBLE_ROOM",
            "message": (
                f"Нет подходящей аудитории для курса '{inst['name']}' "
                f"(нужно студентов: {inst['total_students']}, "
                f"требования: {requirements or '—'}; {'; '.join(hint_parts)})"
            ),
            "course_id": inst["course_id"],
            "entity_ids": [inst["instance_id"]],
            "requirements": requirements,
            "students_needed": inst["total_students"],
            "almost_suitable_rooms": almost[:10],
        }],
        "message": (
            f"Нет подходящей аудитории для курса '{inst['name']}' "
            f"с требованиями {requirements or '—'}"
        ),
    }


def failure_payload(
    *,
    status: str,
    errors: list[dict],
    message: str | None = None,
    warnings: list[dict] | None = None,
    meta: dict | None = None,
    schedule: list | None = None,
) -> dict:
    """Единый формат неуспеха: errors всегда непустой, у каждого есть code."""
    if not errors:
        errors = [{
            "code": status or "ERROR",
            "message": message or "Неизвестная ошибка солвера",
        }]
    for item in errors:
        if "code" not in item:
            item["code"] = status or "ERROR"
        if "message" not in item:
            item["message"] = message or "Ошибка солвера"
    payload: dict = {
        "status": status,
        "errors": errors,
        "warnings": list(warnings or []),
        "message": message or errors[0]["message"],
    }
    if schedule is not None:
        payload["schedule"] = schedule
    if meta is not None:
        payload["meta"] = meta
    return payload


def precheck_placement_domains(
    course_instances: list[dict],
    *,
    rooms: list[dict],
    rooms_by_id: dict[str, dict],
    time_slots: list[dict],
    blocks_by_duration: dict[int, dict[int, list[dict]]],
    fixed_slots_by_course: dict[str, list[int]],
    forbidden_slots_by_instance: dict[str, set],
    wanted_prefs_by_instance: dict[str, dict],
    room_preblocked: set[tuple],
    solver_config: dict,
) -> list[dict]:
    """Pre-check до CP-SAT: у каждого instance есть хотя бы одно размещение."""
    errors: list[dict] = []
    if not time_slots:
        return [{
            "code": "NO_TIME_SLOTS",
            "message": "Во входе нет time_slots — решать нечего",
            "hints": ["Проверьте парсер / сетку аудиторий"],
        }]
    if not course_instances:
        return [{
            "code": "NO_COURSE_INSTANCES",
            "message": "Нет размещаемых занятий после expand",
            "hints": ["Проверьте courses / scope_course_ids / hours→lessons"],
        }]

    for inst in course_instances:
        pref = wanted_prefs_by_instance[inst["instance_id"]]
        domain, domain_error = _collect_instance_room_domain(
            inst,
            rooms=rooms,
            rooms_by_id=rooms_by_id,
            pref=pref,
            solver_config=solver_config,
        )
        if domain_error is not None:
            for item in domain_error.get("errors") or []:
                item.setdefault("hints", [
                    "Ослабьте requirements / students_needed / allowed_room_ids / fixed_room",
                ])
                errors.append(item)
            continue

        assert domain is not None
        blocked = set(forbidden_slots_by_instance.get(inst["instance_id"], set()))
        allowed_slot_ids = None
        if inst["course_id"] in fixed_slots_by_course:
            allowed_slot_ids = set(fixed_slots_by_course[inst["course_id"]])
        duration = int(inst.get("duration_slots") or 1)
        start_blocks = blocks_by_duration.get(duration) or {}
        time_wishes = list(inst.get("time_wishes") or [])
        has_pair = False
        for start_id, block in start_blocks.items():
            block_ids = [slot["id"] for slot in block]
            if any(slot_id in blocked for slot_id in block_ids):
                continue
            if allowed_slot_ids is not None and not set(block_ids).issubset(allowed_slot_ids):
                continue
            if time_wishes and block_violates_hard_time_wishes(block, time_wishes):
                continue
            for room in domain:
                if (
                    not room.get("is_virtual")
                    and room_preblocked
                    and any(
                        (slot_id, normalize_room_id(room["id"])) in room_preblocked
                        for slot_id in block_ids
                    )
                ):
                    continue
                has_pair = True
                break
            if has_pair:
                break

        if has_pair:
            continue

        hints: list[str] = []
        code = "EMPTY_PLACEMENT_DOMAIN"
        if inst["course_id"] in fixed_slots_by_course:
            code = "FIXED_SCHEDULE_NO_DOMAIN"
            hints.append("Снимите или расширьте fixed_schedules")
        if blocked:
            hints.append("Сократите teachers_impossible_slots")
        if inst.get("time_wishes"):
            hints.append("Ослабьте hard time_wishes")
        if inst.get("allowed_room_ids"):
            hints.append("Расширьте allowed_room_ids")
        if not start_blocks:
            code = "DURATION_NO_BLOCK"
            hints.append("Уменьшите duration_slots или разрешите allow_duration_across_lunch")
        if not hints:
            hints.append("Проверьте вместимость аудиторий и requirements")
        errors.append({
            "code": code,
            "message": (
                f"До CP-SAT: у занятия '{inst['name']}' ({inst['instance_id']}) "
                f"нет ни одного допустимого размещения"
            ),
            "course_id": inst["course_id"],
            "entity_ids": [inst["instance_id"]],
            "teacher_id": inst.get("teacher_id"),
            "hints": hints,
        })
    return errors


def diagnose_no_solution(
    course_instances: list[dict],
    *,
    time_slots: list[dict],
    fixed_slots_by_course: dict[str, list[int]],
    forbidden_slots_by_instance: dict[str, set],
    x: dict | None = None,
    solver_status: str | None = None,
    timed_out: bool = False,
) -> list[dict]:
    """errors[] + hints при NO_SOLUTION после CP-SAT."""
    hints: list[str] = []
    hot_teachers: dict[str, int] = {}
    hot_groups: dict[str, int] = {}
    for inst in course_instances:
        for teacher_id in instance_teacher_ids(inst):
            hot_teachers[teacher_id] = hot_teachers.get(teacher_id, 0) + 1
        for group_id in inst.get("group_ids") or []:
            hot_groups[str(group_id)] = hot_groups.get(str(group_id), 0) + 1

    if fixed_slots_by_course:
        hints.append(
            "Есть fixed_schedules — попробуйте временно убрать фиксацию у курсов: "
            + ", ".join(list(fixed_slots_by_course)[:8])
        )
    tight_forbidden = [
        inst["course_id"]
        for inst in course_instances
        if len(forbidden_slots_by_instance.get(inst["instance_id"], set()))
        >= max(1, len(time_slots) // 2)
    ]
    if tight_forbidden:
        hints.append(
            "Много запретов слотов у курсов: "
            + ", ".join(sorted(set(tight_forbidden))[:8])
        )
    top_teachers = sorted(hot_teachers.items(), key=lambda item: -item[1])[:5]
    if top_teachers and top_teachers[0][1] >= 3:
        hints.append(
            "Самые загруженные преподаватели (число занятий): "
            + ", ".join(f"{tid}×{cnt}" for tid, cnt in top_teachers)
        )
    top_groups = sorted(hot_groups.items(), key=lambda item: -item[1])[:5]
    if top_groups and top_groups[0][1] >= 3:
        hints.append(
            "Самые загруженные группы: "
            + ", ".join(f"{gid}×{cnt}" for gid, cnt in top_groups)
        )
    if x is not None:
        orphan = [
            inst["instance_id"]
            for inst in course_instances
            if not any(key[0] == inst["instance_id"] for key in x)
        ]
        if orphan:
            hints.append(
                "У части занятий не было переменных размещения: "
                + ", ".join(orphan[:8])
            )
    hints.append(
        "Ослабьте пересечение week_pattern / duration_slots / same_room_as_course_id"
    )
    hints.append("Увеличьте max_time_in_seconds или включите two_phase/repair")

    code = "SOLVER_TIMEOUT" if timed_out else "NO_SOLUTION"
    message = (
        "Поиск прерван по лимиту времени без допустимого расписания"
        if timed_out
        else "Не удалось подобрать расписание с текущими ограничениями"
    )
    if solver_status:
        message = f"{message} (solver={solver_status})"
    return [{
        "code": code,
        "message": message,
        "hints": hints,
        "entity_ids": [inst["instance_id"] for inst in course_instances[:20]],
        "courses_sample": [inst["course_id"] for inst in course_instances[:20]],
    }]


def collect_unmet_soft_warnings(
    schedule: list[dict],
    *,
    course_instances: list[dict],
    wanted_prefs_by_instance: dict[str, dict],
    solver_config: dict,
) -> list[dict]:
    """Warnings, если решение есть, но soft-пожелания не выполнены."""
    warnings: list[dict] = []
    inst_by_id = {inst["instance_id"]: inst for inst in course_instances}
    late_from = int(solver_config.get("late_slot_from", 5))
    weight_saturday = int(solver_config.get("weight_saturday", 0))
    weight_late = int(solver_config.get("weight_late_slot", 0))
    weight_wanted = int(solver_config.get("weight_wanted_slot", 0))

    for row in schedule:
        inst = inst_by_id.get(row["instance_id"]) or {}
        pref = wanted_prefs_by_instance.get(row["instance_id"]) or {}
        start_id = (row.get("timeslots_ids") or [None])[0]
        wanted = pref.get("wanted_slot_ids") or set()
        if weight_wanted and wanted and start_id not in wanted:
            warnings.append({
                "code": "UNMET_WANTED_SLOT",
                "message": (
                    f"Курс '{row.get('course_name')}' не попал в желаемые слоты "
                    f"преподавателя {sorted(wanted)[:6]}"
                ),
                "course_id": row.get("course_id"),
                "entity_ids": [row["instance_id"]],
                "timeslots_ids": row.get("timeslots_ids"),
                "wanted_timeslots_ids": sorted(wanted),
            })

        for wish in inst.get("time_wishes") or []:
            is_soft = (
                wish.get("strength") == "soft"
                or wish.get("type") == "prefer_slots"
            )
            if not is_soft:
                continue
            fake = {
                "id": start_id,
                "day": row.get("day"),
                "slot_index": row.get("slot_index_start") or row.get("slot_index"),
            }
            if slot_violates_time_wish(fake, wish):
                warnings.append({
                    "code": "UNMET_SOFT_TIME_WISH",
                    "message": (
                        f"Курс '{row.get('course_name')}' не выполнил soft time_wish "
                        f"{wish.get('type')}"
                    ),
                    "course_id": row.get("course_id"),
                    "entity_ids": [row["instance_id"]],
                    "time_wish": wish,
                })

        if weight_saturday and normalize_day_name(row.get("day")) == "суббота":
            warnings.append({
                "code": "SCHEDULED_ON_SATURDAY",
                "message": f"Курс '{row.get('course_name')}' поставлен в субботу",
                "course_id": row.get("course_id"),
                "entity_ids": [row["instance_id"]],
            })
        slot_index = int(row.get("slot_index_end") or row.get("slot_index") or 0)
        if weight_late and late_from > 0 and slot_index >= late_from:
            warnings.append({
                "code": "SCHEDULED_LATE_SLOT",
                "message": (
                    f"Курс '{row.get('course_name')}' на поздней паре "
                    f"(slot_index={slot_index} ≥ {late_from})"
                ),
                "course_id": row.get("course_id"),
                "entity_ids": [row["instance_id"]],
                "slot_index": slot_index,
            })
    return warnings


def build_forbidden_slots_error(
    inst: dict,
    *,
    forbidden_slot_ids: set[int],
    rooms: list[dict],
    time_slots: list[dict],
) -> dict:
    """ERROR: после запретов преподавателя не осталось допустимых слотов/аудиторий."""
    feasible_rooms = [
        room["id"]
        for room in rooms
        if room_is_feasible(
            room,
            total_students=inst["total_students"],
            requirements=inst.get("requirements"),
            needs_software=inst.get("needs_software"),
        )
    ]
    blocked = sorted(forbidden_slot_ids)
    remaining_slots = [
        slot["id"] for slot in time_slots if slot["id"] not in forbidden_slot_ids
    ]
    return {
        "status": "ERROR",
        "errors": [{
            "code": "TEACHER_IMPOSSIBLE_SLOTS",
            "message": (
                f"Для курса '{inst['name']}' (преподаватель {inst.get('teacher_id')}) "
                f"запрещены слоты {blocked}; после запретов нет допустимого размещения "
                f"(свободных слотов: {len(remaining_slots)}, подходящих аудиторий: {len(feasible_rooms)})"
            ),
            "course_id": inst["course_id"],
            "entity_ids": [inst["instance_id"]],
            "teacher_id": inst.get("teacher_id"),
            "forbidden_timeslots_ids": blocked,
            "remaining_timeslots_ids": remaining_slots,
            "feasible_room_ids": feasible_rooms[:20],
        }],
        "message": (
            f"Запреты преподавателя блокируют все слоты для курса '{inst['name']}'"
        ),
    }


def _collect_instance_room_domain(
    inst: dict,
    *,
    rooms: list[dict],
    rooms_by_id: dict[str, dict],
    pref: dict,
    solver_config: dict,
) -> tuple[list[dict] | None, dict | None]:
    """
    Домен аудиторий instance для monolithic/phase2.
    Возвращает (rooms, error_payload_or_None).
    """
    fixed_room = pref.get("fixed_room")
    if fixed_room is not None:
        fixed_room = normalize_room_id(fixed_room)
    allowed_ids = inst.get("allowed_room_ids")

    if not inst.get("needs_physical_room", True):
        virtual = make_virtual_room(
            inst["course_id"],
            inst.get("venue_type") or "virtual",
        )
        room = rooms_by_id.get(virtual["id"]) or virtual
        return [room], None

    if fixed_room:
        if allowed_ids and fixed_room not in {
            normalize_room_id(room_id) for room_id in allowed_ids
        }:
            return None, {
                "status": "ERROR",
                "errors": [{
                    "code": "CONFLICTING_ROOM_CONSTRAINTS",
                    "message": (
                        f"Для курса '{inst['name']}' fixed_room '{fixed_room}' "
                        f"не входит в allowed_room_ids {allowed_ids}"
                    ),
                    "course_id": inst["course_id"],
                    "entity_ids": [inst["instance_id"]],
                    "fixed_room": fixed_room,
                    "allowed_room_ids": allowed_ids,
                }],
                "message": f"Конфликт fixed_room и allowed_room_ids у '{inst['name']}'",
            }
        room = rooms_by_id.get(fixed_room)
        if room is None:
            return None, build_fixed_room_error(inst, pref, rooms_by_id)
        if not room_is_feasible(
            room,
            total_students=inst["total_students"],
            requirements=inst["requirements"],
            needs_software=inst.get("needs_software"),
        ):
            return None, build_fixed_room_error(inst, pref, rooms_by_id)
        return [room], None

    physical = [room for room in rooms if not room.get("is_virtual")]
    allowed_rooms, unknown_allowed = filter_rooms_by_allowed_ids(
        physical,
        allowed_ids,
        rooms_by_id=rooms_by_id,
    )
    if allowed_ids is not None and not allowed_rooms:
        return None, build_allowed_rooms_error(
            inst,
            allowed_room_ids=list(allowed_ids),
            unknown_ids=unknown_allowed,
            candidate_rooms=allowed_rooms,
        )
    allowed_rooms = select_candidate_rooms(
        allowed_rooms,
        total_students=inst["total_students"],
        requirements=inst["requirements"],
        needs_software=inst.get("needs_software"),
        max_candidate_rooms=int(solver_config.get("max_candidate_rooms") or 0),
    )
    if not allowed_rooms:
        return None, build_no_room_error(inst, rooms)
    return allowed_rooms, None


def solve_two_phase(
    *,
    course_instances: list[dict],
    rooms: list[dict],
    rooms_by_id: dict[str, dict],
    time_slots: list[dict],
    fixed_slots_by_course: dict[str, list[int]],
    forbidden_slots_by_instance: dict[str, set],
    wanted_prefs_by_instance: dict[str, dict],
    blocks_by_duration: dict[int, dict[int, list[dict]]],
    covering_by_duration: dict[int, dict[int, list[int]]],
    same_room_groups: list[list[dict]],
    room_preblocked: set[tuple],
    solver_config: dict,
    solver_warnings: list[dict],
) -> str:
    """
    Phase1: слот (+ teacher/group/weeks/duration), без аудиторий ИЕНИМ.
    Phase2: аудитории при фиксированных стартах.
    """
    import time as time_module

    total_limit = float(solver_config["max_time_in_seconds"])
    frac = float(solver_config.get("two_phase_time_fraction") or 0.55)
    frac = min(0.9, max(0.2, frac))
    t1_limit = max(1.0, total_limit * frac)
    t2_limit = max(1.0, total_limit - t1_limit)

    weight_wanted_slot = int(solver_config["weight_wanted_slot"])
    weight_time_wish = int(solver_config.get("weight_time_wish", 8))
    weight_group_gap = int(solver_config.get("weight_group_gap", 5))
    weight_late_slot = int(solver_config.get("weight_late_slot", 2))
    weight_saturday = int(solver_config.get("weight_saturday", 4))
    late_slot_from = int(solver_config.get("late_slot_from", 5))
    weight_preferred_capacity = int(solver_config["weight_preferred_capacity"])
    weight_preferred_room_type = int(solver_config["weight_preferred_room_type"])
    workers = int(solver_config["num_search_workers"])

    # --- Phase 1: starts only ---
    model1 = cp_model.CpModel()
    y: dict[tuple[str, int], object] = {}
    obj1: list = []
    phase1_rooms: dict[str, dict] = {}

    for inst in course_instances:
        pref = wanted_prefs_by_instance[inst["instance_id"]]
        blocked = set(forbidden_slots_by_instance.get(inst["instance_id"], set()))
        allowed_slot_ids = None
        if inst["course_id"] in fixed_slots_by_course:
            allowed_slot_ids = set(fixed_slots_by_course[inst["course_id"]])
        duration = int(inst.get("duration_slots") or 1)
        start_blocks = blocks_by_duration.get(duration) or {}
        time_wishes = list(inst.get("time_wishes") or [])
        wanted_slots = pref.get("wanted_slot_ids") or set()
        placeholder = make_phase1_slot_room(inst["course_id"])
        phase1_rooms[inst["instance_id"]] = placeholder

        for start_id, block in start_blocks.items():
            block_ids = [slot["id"] for slot in block]
            if any(slot_id in blocked for slot_id in block_ids):
                continue
            if allowed_slot_ids is not None and not set(block_ids).issubset(allowed_slot_ids):
                continue
            if time_wishes and block_violates_hard_time_wishes(block, time_wishes):
                continue
            var = model1.NewBoolVar(f"y_{inst['instance_id']}_s{start_id}")
            y[(inst["instance_id"], start_id)] = var
            score = 0
            if start_id in wanted_slots:
                score += weight_wanted_slot
            soft_hits = soft_time_wish_penalty(block, time_wishes) if time_wishes else 0
            if soft_hits:
                score -= weight_time_wish * soft_hits
            late_hits = late_slot_penalty(block, late_from=late_slot_from)
            if late_hits and weight_late_slot:
                score -= weight_late_slot * late_hits
            if weight_saturday and saturday_penalty(block):
                score -= weight_saturday
            if score:
                obj1.append(score * var)

        possible = [
            y[(inst["instance_id"], start_id)]
            for start_id in start_blocks
            if (inst["instance_id"], start_id) in y
        ]
        if not possible:
            return json.dumps(
                failure_payload(
                    status="ERROR",
                    errors=[{
                        "code": "PHASE1_NO_DOMAIN",
                        "message": (
                            f"Phase1: нет допустимого старта для '{inst['name']}' "
                            f"({inst['instance_id']})"
                        ),
                        "course_id": inst["course_id"],
                        "entity_ids": [inst["instance_id"]],
                        "hints": [
                            "Ослабьте fixed_schedules / teachers_impossible_slots / hard time_wishes",
                            "Уменьшите duration_slots или разрешите allow_duration_across_lunch",
                        ],
                    }],
                    warnings=solver_warnings,
                    message=f"Phase1: пустой домен слотов для '{inst['name']}'",
                    meta={"solve_strategy": "two_phase", "phase": 1},
                ),
                ensure_ascii=False,
                indent=2,
            )
        model1.AddExactlyOne(possible)

    # Fixed schedules coverage in phase1
    for course_id, slot_ids in fixed_slots_by_course.items():
        course_insts = [inst for inst in course_instances if inst["course_id"] == course_id]
        for slot_id in slot_ids:
            vars_for_slot = []
            for inst in course_insts:
                duration = int(inst.get("duration_slots") or 1)
                for start_id in (covering_by_duration.get(duration) or {}).get(slot_id, []):
                    key = (inst["instance_id"], start_id)
                    if key in y:
                        vars_for_slot.append(y[key])
            if vars_for_slot:
                model1.Add(sum(vars_for_slot) == 1)

    def phase1_vars_covering(inst: dict, slot_id: int) -> list:
        duration = int(inst.get("duration_slots") or 1)
        found = []
        for start_id in (covering_by_duration.get(duration) or {}).get(slot_id, []):
            key = (inst["instance_id"], start_id)
            if key in y:
                found.append(y[key])
        return found

    # Teacher / group conflicts with weeks
    teacher_ids = sorted({
        tid for inst in course_instances for tid in instance_teacher_ids(inst)
    })
    group_ids = sorted({
        gid for inst in course_instances for gid in (inst.get("group_ids") or [])
    })
    for slot in time_slots:
        for teacher_id in teacher_ids:
            teacher_var_groups = []
            for inst in course_instances:
                if teacher_id not in instance_teacher_ids(inst):
                    continue
                vars_i = phase1_vars_covering(inst, slot["id"])
                if vars_i:
                    teacher_var_groups.append((vars_i, instance_weeks(inst)))
            add_pairwise_week_conflicts(model1, teacher_var_groups)

        for group_id in group_ids:
            group_var_groups = []
            for inst in course_instances:
                if group_id not in (inst.get("group_ids") or []):
                    continue
                vars_i = phase1_vars_covering(inst, slot["id"])
                if vars_i:
                    group_var_groups.append((vars_i, instance_weeks(inst)))
            add_pairwise_week_conflicts(model1, group_var_groups)

    # Packing: физ. занятия в слоте ≤ число физ. аудиторий
    physical_room_n = len([room for room in rooms if not room.get("is_virtual")])
    if physical_room_n > 0:
        for slot in time_slots:
            pack_vars = []
            for inst in course_instances:
                if not inst.get("needs_physical_room", True):
                    continue
                pack_vars.extend(phase1_vars_covering(inst, slot["id"]))
            if pack_vars:
                model1.Add(sum(pack_vars) <= physical_room_n)

    # Gap soft on phase1 via synthetic x mapping
    # Reuse gap helper by adapting: build fake x from y
    x_gap = {}
    for (inst_id, start_id), var in y.items():
        room_id = phase1_rooms[inst_id]["id"]
        x_gap[(inst_id, start_id, room_id)] = var
    gap_rooms = list(phase1_rooms.values())
    obj1.extend(
        add_group_gap_objective_terms(
            model1,
            x_gap,
            course_instances=course_instances,
            time_slots=time_slots,
            rooms=gap_rooms,
            covering_by_duration=covering_by_duration,
            weight=weight_group_gap,
        )
    )
    if obj1:
        model1.Maximize(sum(obj1))

    solver1 = cp_model.CpSolver()
    solver1.parameters.max_time_in_seconds = t1_limit
    solver1.parameters.num_search_workers = workers
    t0 = time_module.time()
    status1 = solver1.Solve(model1)
    phase1_time = round(time_module.time() - t0, 3)

    if status1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        timed_out1 = (
            status1 == cp_model.UNKNOWN
            or phase1_time >= t1_limit * 0.98
        )
        phase1_errors = diagnose_no_solution(
            course_instances,
            time_slots=time_slots,
            fixed_slots_by_course=fixed_slots_by_course,
            forbidden_slots_by_instance=forbidden_slots_by_instance,
            x=None,
            solver_status=solver1.StatusName(status1),
            timed_out=timed_out1,
        )
        phase1_errors[0]["code"] = (
            "SOLVER_TIMEOUT" if timed_out1 else "PHASE1_NO_SOLUTION"
        )
        phase1_errors[0]["message"] = (
            "Phase1 (слоты) не нашла допустимого назначения "
            f"({solver1.StatusName(status1)})"
        )
        phase1_errors[0].setdefault("hints", []).insert(
            0,
            "Phase1 упала до назначения аудиторий — сначала ослабьте слотовые hard-ограничения",
        )
        return json.dumps(
            failure_payload(
                status="NO_SOLUTION",
                errors=phase1_errors,
                warnings=solver_warnings,
                message="Не удалось назначить слоты на phase1",
                meta={
                    "solve_strategy": "two_phase",
                    "phase": 1,
                    "solve_time_sec": phase1_time,
                    "solver_status": solver1.StatusName(status1),
                    "max_time_in_seconds": total_limit,
                    "phase1_time_sec": phase1_time,
                    "variables_phase1": len(y),
                    "timed_out": timed_out1,
                },
            ),
            ensure_ascii=False,
            indent=2,
        )

    assigned_start: dict[str, int] = {}
    for (inst_id, start_id), var in y.items():
        if solver1.Value(var) == 1:
            assigned_start[inst_id] = start_id

    # --- Phase 2: rooms for fixed starts ---
    model2 = cp_model.CpModel()
    z: dict[tuple[str, str], object] = {}
    obj2: list = []
    domain_by_inst: dict[str, list[dict]] = {}

    for inst in course_instances:
        pref = wanted_prefs_by_instance[inst["instance_id"]]
        domain, err = _collect_instance_room_domain(
            inst,
            rooms=rooms,
            rooms_by_id=rooms_by_id,
            pref=pref,
            solver_config=solver_config,
        )
        if err is not None:
            return json.dumps(err, ensure_ascii=False, indent=2)
        assert domain is not None
        start_id = assigned_start[inst["instance_id"]]
        duration = int(inst.get("duration_slots") or 1)
        block = (blocks_by_duration.get(duration) or {})[start_id]
        block_ids = [slot["id"] for slot in block]
        preferred_capacity = pref.get("preferred_capacity")
        preferred_types = pref.get("preferred_room_types") or []
        candidates = []
        for room in domain:
            if (
                not room.get("is_virtual")
                and room_preblocked
                and any(
                    (slot_id, normalize_room_id(room["id"])) in room_preblocked
                    for slot_id in block_ids
                )
            ):
                continue
            if not room.get("is_virtual") and not room_is_feasible(
                room,
                total_students=inst["total_students"],
                requirements=inst["requirements"],
                needs_software=inst.get("needs_software"),
            ):
                continue
            candidates.append(room)
        if not candidates:
            return json.dumps(
                failure_payload(
                    status="ERROR",
                    errors=[{
                        "code": "PHASE2_NO_DOMAIN",
                        "message": (
                            f"Phase2: нет аудитории для '{inst['name']}' "
                            f"в слоте {start_id}"
                        ),
                        "course_id": inst["course_id"],
                        "entity_ids": [inst["instance_id"]],
                        "timeslots_ids": block_ids,
                        "hints": [
                            "Расширьте allowed_room_ids / requirements",
                            "Снимите room_preblocked для этих слотов",
                            "Попробуйте monolithic/repair",
                        ],
                    }],
                    warnings=solver_warnings,
                    message=f"Phase2: пустой домен аудиторий для '{inst['name']}'",
                    meta={
                        "solve_strategy": "two_phase",
                        "phase": 2,
                        "phase1_time_sec": phase1_time,
                    },
                ),
                ensure_ascii=False,
                indent=2,
            )

        domain_by_inst[inst["instance_id"]] = candidates
        vars_room = []
        for room in candidates:
            var = model2.NewBoolVar(
                f"z_{inst['instance_id']}_r{room['id']}"
            )
            z[(inst["instance_id"], room["id"])] = var
            vars_room.append(var)
            score = 0
            if not room.get("is_virtual"):
                if preferred_capacity is not None and room.get("capacity", 0) < preferred_capacity:
                    score -= weight_preferred_capacity
                if preferred_types and not room_matches_preferred_type(room, preferred_types):
                    score -= weight_preferred_room_type
            if score:
                obj2.append(score * var)
        model2.AddExactlyOne(vars_room)

    # Room conflicts on each occupied slot of the fixed blocks
    for slot in time_slots:
        for room in rooms:
            if room.get("is_virtual"):
                continue
            var_groups = []
            for inst in course_instances:
                start_id = assigned_start[inst["instance_id"]]
                duration = int(inst.get("duration_slots") or 1)
                block = (blocks_by_duration.get(duration) or {}).get(start_id) or []
                if slot["id"] not in {s["id"] for s in block}:
                    continue
                key = (inst["instance_id"], room["id"])
                if key in z:
                    var_groups.append(([z[key]], instance_weeks(inst)))
            add_pairwise_week_conflicts(model2, var_groups)

    # same_room on phase2
    physical_rooms = [room for room in rooms if not room.get("is_virtual")]
    for group in same_room_groups:
        used: dict[tuple[str, str], object | None] = {}
        for inst in group:
            for room in physical_rooms:
                key = (inst["instance_id"], room["id"])
                used[(inst["instance_id"], room["id"])] = z[key] if key in z else None
        anchor = group[0]["instance_id"]
        for inst in group[1:]:
            for room in physical_rooms:
                left = used[(anchor, room["id"])]
                right = used[(inst["instance_id"], room["id"])]
                if left is None and right is None:
                    continue
                if left is None:
                    model2.Add(right == 0)
                elif right is None:
                    model2.Add(left == 0)
                else:
                    model2.Add(left == right)

    if obj2:
        model2.Maximize(sum(obj2))

    solver2 = cp_model.CpSolver()
    solver2.parameters.max_time_in_seconds = t2_limit
    solver2.parameters.num_search_workers = workers
    t1 = time_module.time()
    status2 = solver2.Solve(model2)
    phase2_time = round(time_module.time() - t1, 3)

    if status2 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        timed_out2 = (
            status2 == cp_model.UNKNOWN
            or phase2_time >= t2_limit * 0.98
        )
        phase2_errors = diagnose_no_solution(
            course_instances,
            time_slots=time_slots,
            fixed_slots_by_course=fixed_slots_by_course,
            forbidden_slots_by_instance=forbidden_slots_by_instance,
            x=None,
            solver_status=solver2.StatusName(status2),
            timed_out=timed_out2,
        )
        phase2_errors[0]["code"] = (
            "SOLVER_TIMEOUT" if timed_out2 else "PHASE2_NO_SOLUTION"
        )
        phase2_errors[0]["message"] = (
            "Phase2 (аудитории) не нашла назначения при слотах phase1 "
            f"({solver2.StatusName(status2)}); попробуйте repair/monolithic"
        )
        phase2_errors[0].setdefault("hints", []).insert(
            0,
            "Слоты phase1 зафиксированы — конфликт аудиторий/same_room/preblocked",
        )
        return json.dumps(
            failure_payload(
                status="NO_SOLUTION",
                errors=phase2_errors,
                warnings=solver_warnings,
                message="Не удалось назначить аудитории на phase2",
                meta={
                    "solve_strategy": "two_phase",
                    "phase": 2,
                    "solve_time_sec": round(phase1_time + phase2_time, 3),
                    "phase1_time_sec": phase1_time,
                    "phase2_time_sec": phase2_time,
                    "solver_status": solver2.StatusName(status2),
                    "variables_phase1": len(y),
                    "variables_phase2": len(z),
                    "max_time_in_seconds": total_limit,
                    "timed_out": timed_out2,
                },
            ),
            ensure_ascii=False,
            indent=2,
        )

    schedule_result = []
    for inst in course_instances:
        start_id = assigned_start[inst["instance_id"]]
        duration = int(inst.get("duration_slots") or 1)
        block = (blocks_by_duration.get(duration) or {})[start_id]
        chosen_room = None
        for room in domain_by_inst[inst["instance_id"]]:
            key = (inst["instance_id"], room["id"])
            if key in z and solver2.Value(z[key]) == 1:
                chosen_room = room
                break
        if chosen_room is None:
            continue
        start_slot = block[0]
        end_slot = block[-1]
        start_time = str(start_slot.get("time") or "")
        end_time = str(end_slot.get("time") or "")
        if "-" in start_time and "-" in end_time:
            time_span = f"{start_time.split('-', 1)[0]}-{end_time.split('-', 1)[-1]}"
        else:
            time_span = start_time or end_time
        row = {
            "course_id": inst["course_id"],
            "course_name": inst["name"],
            "teacher_id": inst["teacher_id"],
            "teacher_ids": list(inst.get("teacher_ids") or [inst["teacher_id"]]),
            "teacher_missing": bool(inst.get("teacher_missing")),
            "teacher_is_placeholder": bool(inst.get("teacher_is_placeholder")),
            "teaching_mode": inst.get("teaching_mode"),
            "lesson_kind": inst.get("lesson_kind"),
            "students_needed": inst.get("students_needed", inst["total_students"]),
            "group_ids": inst["group_ids"],
            "day": start_slot["day"],
            "slot_index": start_slot["slot_index"],
            "slot_index_start": start_slot["slot_index"],
            "slot_index_end": end_slot["slot_index"],
            "timeslots_ids": [slot["id"] for slot in block],
            "duration_slots": duration,
            "time": time_span,
            "room_id": chosen_room["id"],
            "venue_type": inst.get("venue_type") or (
                chosen_room.get("venue_type") if chosen_room.get("is_virtual") else "room"
            ),
            "needs_physical_room": bool(inst.get("needs_physical_room", True)),
            "requirements": inst["requirements"],
            "instance_id": inst["instance_id"],
            "week_pattern": inst.get("week_pattern") or {"type": "all"},
            "weeks": sorted(instance_weeks(inst)),
        }
        if inst.get("allowed_room_ids") is not None:
            row["allowed_room_ids"] = list(inst["allowed_room_ids"])
        if inst.get("same_room_as_course_id"):
            row["same_room_as_course_id"] = inst["same_room_as_course_id"]
        if inst.get("time_wishes"):
            row["time_wishes"] = list(inst["time_wishes"])
        if inst.get("time_wish_raw"):
            row["time_wish_raw"] = inst["time_wish_raw"]
        if inst.get("subgroup_index") is not None:
            row["subgroup_index"] = inst["subgroup_index"]
        if inst.get("subgroup_count") is not None:
            row["subgroup_count"] = inst["subgroup_count"]
        if inst.get("team_label") is not None:
            row["team_label"] = inst["team_label"]
        schedule_result.append(row)

    soft_warnings = collect_unmet_soft_warnings(
        schedule_result,
        course_instances=course_instances,
        wanted_prefs_by_instance=wanted_prefs_by_instance,
        solver_config=solver_config,
    )
    all_warnings = list(solver_warnings) + soft_warnings
    status_label = "SUCCESS_WITH_WARNINGS" if all_warnings else "SUCCESS"
    return json.dumps({
        "status": status_label,
        "errors": [],
        "warnings": all_warnings,
        "schedule": schedule_result,
        "meta": {
            "solve_strategy": "two_phase",
            "solve_time_sec": round(phase1_time + phase2_time, 3),
            "phase1_time_sec": phase1_time,
            "phase2_time_sec": phase2_time,
            "objective": int(solver2.ObjectiveValue()) if obj2 else (
                int(solver1.ObjectiveValue()) if obj1 else None
            ),
            "lessons_count": len(schedule_result),
            "solver_status": solver2.StatusName(status2),
            "max_time_in_seconds": total_limit,
            "num_search_workers": workers,
            "variables_phase1": len(y),
            "variables_phase2": len(z),
            "max_candidate_rooms": int(solver_config.get("max_candidate_rooms") or 0),
            "missing_teacher_policy": resolve_missing_teacher_policy(solver_config),
            "unmet_soft_count": len(soft_warnings),
        },
    }, ensure_ascii=False, indent=2)


def solve_schedule(input_json_str: str, config: dict | None = None) -> str:
    # 1. Загрузка данных из входного JSON
    data = json.loads(input_json_str)
    solver_config = resolve_solver_config(data, config)
    
    rooms = list(data["rooms"])
    teachers = data["teachers"]
    groups = data["groups"]
    time_slots = data["time_slots"]
    courses = list(data["courses"])
    impossible_restrictions = data.get("teachers_impossible_slots") or []
    wanted_rows = data.get("teachers_wanted_slots") or []
    fixed_schedule_rows = list(data.get("fixed_schedules") or [])
    scope_warnings: list[dict] = []
    # Декомпозиция / срез для масштаба: только указанные course_id
    scope_ids = solver_config.get("scope_course_ids") or data.get("scope_course_ids")
    if scope_ids:
        scope_set = {str(course_id) for course_id in scope_ids}
        courses = [course for course in courses if str(course["id"]) in scope_set]
        # TZ §13.1.F: fixed чужих курсов не должны давать FIXED_SCHEDULE_UNKNOWN_COURSE
        kept_fixed: list[dict] = []
        dropped_fixed_ids: list[str] = []
        for entry in fixed_schedule_rows:
            course_id = entry.get("course_id")
            if course_id is not None and str(course_id) in scope_set:
                kept_fixed.append(entry)
            elif course_id is not None:
                dropped_fixed_ids.append(str(course_id))
            else:
                kept_fixed.append(entry)  # без course_id — пусть validate поймает
        fixed_schedule_rows = kept_fixed
        if dropped_fixed_ids:
            unique_dropped = sorted(set(dropped_fixed_ids))
            scope_warnings.append({
                "code": "SCOPE_DROPPED_FIXED_SCHEDULES",
                "message": (
                    f"scope_course_ids: пропущены fixed_schedules вне среза "
                    f"({len(unique_dropped)} курсов): {', '.join(unique_dropped[:12])}"
                    + ("…" if len(unique_dropped) > 12 else "")
                ),
                "course_ids": unique_dropped[:50],
                "scope_course_ids": sorted(scope_set),
            })
    room_preblocked = parse_room_preblocked(data.get("room_preblocked"))
    rooms_by_id = {str(room["id"]): room for room in rooms}
    courses_by_id = {course["id"]: course for course in courses}
    fixed_entry_by_course = {
        entry["course_id"]: entry
        for entry in fixed_schedule_rows
        if entry.get("course_id")
    }
    
    # Словари для быстрого поиска вместимости и размеров групп
    default_group_size = int(solver_config.get("default_group_size", 30))
    group_sizes = {
        g["id"]: int(g["size"]) if g.get("size") is not None else default_group_size
        for g in groups
    }
    
    # 2. Создание модели CP-SAT
    model = cp_model.CpModel()
    
    # Раскрываем курсы: подгруппы из courses[].instances или legacy lessons_per_week
    semester_weeks = resolve_semester_weeks(data, solver_config)
    (
        course_instances,
        instances_per_course,
        expand_errors,
        expand_warnings,
    ) = expand_course_instances(
        courses,
        group_sizes=group_sizes,
        fixed_entry_by_course=fixed_entry_by_course,
        config=solver_config,
        semester_weeks=semester_weeks,
    )
    solver_warnings: list[dict] = list(scope_warnings) + list(expand_warnings)
    if expand_errors:
        return json.dumps({
            "status": "ERROR",
            "errors": expand_errors,
            "warnings": solver_warnings,
            "message": expand_errors[0]["message"],
        }, ensure_ascii=False, indent=2)

    solver_warnings.extend(collect_unmanaged_wish_warnings(course_instances, courses))

    teacher_validation_errors = validate_instance_teachers(course_instances)
    if teacher_validation_errors:
        return json.dumps({
            "status": "ERROR",
            "errors": teacher_validation_errors,
            "warnings": solver_warnings,
            "message": teacher_validation_errors[0]["message"],
        }, ensure_ascii=False, indent=2)

    fixed_slots_by_course, fixed_schedule_errors = validate_fixed_schedules(
        fixed_schedule_rows,
        courses=courses,
        time_slots=time_slots,
        instances_per_course=instances_per_course,
    )
    fixed_schedule_errors, fixed_schedule_soft = apply_fixed_schedule_mismatch_policy(
        fixed_schedule_errors,
        policy=str(solver_config.get("fixed_schedule_mismatch_policy") or "strict"),
    )
    solver_warnings.extend(fixed_schedule_soft)
    if fixed_schedule_errors:
        return json.dumps({
            "status": "ERROR",
            "errors": fixed_schedule_errors,
            "warnings": solver_warnings,
            "message": fixed_schedule_errors[0]["message"],
        }, ensure_ascii=False, indent=2)

    # Виртуальные площадки для online / external / sport / needs_room=false
    for inst in course_instances:
        if inst.get("needs_physical_room", True):
            continue
        ensure_virtual_room(
            rooms,
            rooms_by_id,
            course_id=inst["course_id"],
            venue_type=inst.get("venue_type") or "virtual",
        )

    forbidden_slots_by_instance = collect_forbidden_slots_by_instance(
        course_instances,
        impossible_restrictions,
    )
    wanted_prefs_by_instance, fixed_room_conflicts = collect_wanted_prefs_by_instance(
        course_instances,
        wanted_rows,
    )
    if fixed_room_conflicts:
        return json.dumps({
            "status": "ERROR",
            "errors": fixed_room_conflicts,
            "warnings": solver_warnings,
            "message": fixed_room_conflicts[0]["message"],
        }, ensure_ascii=False, indent=2)

    # Объединить hard-требования курса с room_requirements из анкеты
    for inst in course_instances:
        pref = wanted_prefs_by_instance[inst["instance_id"]]
        merged = list(dict.fromkeys(
            list(inst["requirements"]) + list(pref.get("extra_requirements") or [])
        ))
        inst["requirements"] = merged

    solver_warnings.extend(
        soften_infeasible_fixed_rooms(
            course_instances,
            wanted_prefs_by_instance,
            rooms_by_id=rooms_by_id,
            policy=str(solver_config.get("infeasible_fixed_room_policy") or "strict"),
        )
    )

    course_instances, dropped_unplaceable = drop_unplaceable_instances(
        course_instances,
        rooms=rooms,
        rooms_by_id=rooms_by_id,
        wanted_prefs_by_instance=wanted_prefs_by_instance,
        solver_config=solver_config,
        policy=str(solver_config.get("unplaceable_instance_policy") or "strict"),
    )
    solver_warnings.extend(dropped_unplaceable)
    if not course_instances:
        return json.dumps(
            failure_payload(
                status="ERROR",
                errors=[{
                    "code": "NO_COURSE_INSTANCES",
                    "message": (
                        "После фильтра unplaceable_instance_policy не осталось "
                        "размещаемых занятий"
                    ),
                    "hints": [
                        "Ослабьте students_needed / requirements",
                        "Или верните unplaceable_instance_policy=strict для диагностики",
                    ],
                }],
                warnings=solver_warnings,
                message="Нет размещаемых занятий после фильтра незакрываемых",
            ),
            ensure_ascii=False,
            indent=2,
        )

    remaining_course_ids = {inst["course_id"] for inst in course_instances}
    fixed_slots_by_course = {
        course_id: slots
        for course_id, slots in fixed_slots_by_course.items()
        if course_id in remaining_course_ids
    }

    same_room_groups, same_room_errors = build_same_room_groups(
        course_instances,
        courses_by_id=courses_by_id,
    )
    if same_room_errors:
        return json.dumps({
            "status": "ERROR",
            "errors": same_room_errors,
            "warnings": solver_warnings,
            "message": same_room_errors[0]["message"],
        }, ensure_ascii=False, indent=2)

    weight_wanted_slot = int(solver_config["weight_wanted_slot"])
    weight_preferred_capacity = int(solver_config["weight_preferred_capacity"])
    weight_preferred_room_type = int(solver_config["weight_preferred_room_type"])
    weight_time_wish = int(solver_config.get("weight_time_wish", 8))
    weight_group_gap = int(solver_config.get("weight_group_gap", 5))
    weight_late_slot = int(solver_config.get("weight_late_slot", 2))
    weight_saturday = int(solver_config.get("weight_saturday", 4))
    late_slot_from = int(solver_config.get("late_slot_from", 5))

    # Блоки непрерывных слотов по duration (п.9)
    durations_used = sorted({
        int(inst.get("duration_slots") or 1) for inst in course_instances
    }) or [1]
    blocks_by_duration: dict[int, dict[int, list[dict]]] = {
        duration: build_duration_blocks(time_slots, duration, solver_config)
        for duration in durations_used
    }
    covering_by_duration: dict[int, dict[int, list[int]]] = {
        duration: index_blocks_by_occupied_slot(blocks)
        for duration, blocks in blocks_by_duration.items()
    }

    precheck_errors = precheck_placement_domains(
        course_instances,
        rooms=rooms,
        rooms_by_id=rooms_by_id,
        time_slots=time_slots,
        blocks_by_duration=blocks_by_duration,
        fixed_slots_by_course=fixed_slots_by_course,
        forbidden_slots_by_instance=forbidden_slots_by_instance,
        wanted_prefs_by_instance=wanted_prefs_by_instance,
        room_preblocked=room_preblocked,
        solver_config=solver_config,
    )
    if precheck_errors:
        return json.dumps(
            failure_payload(
                status="ERROR",
                errors=precheck_errors,
                warnings=solver_warnings,
                message=precheck_errors[0]["message"],
                meta={"precheck": True, "instances_count": len(course_instances)},
            ),
            ensure_ascii=False,
            indent=2,
        )

    max_candidate_rooms = int(solver_config.get("max_candidate_rooms") or 0)
    avg_rooms_guess = (
        float(max_candidate_rooms)
        if max_candidate_rooms > 0
        else float(max(1, len([room for room in rooms if not room.get("is_virtual")])))
    )
    estimated_vars = estimate_decision_var_count(
        course_instances,
        blocks_by_duration=blocks_by_duration,
        avg_rooms_per_instance=avg_rooms_guess,
    )
    solve_strategy = resolve_solve_strategy(
        solver_config,
        estimated_vars=estimated_vars,
    )

    if solve_strategy == "two_phase":
        two_phase_result = solve_two_phase(
            course_instances=course_instances,
            rooms=rooms,
            rooms_by_id=rooms_by_id,
            time_slots=time_slots,
            fixed_slots_by_course=fixed_slots_by_course,
            forbidden_slots_by_instance=forbidden_slots_by_instance,
            wanted_prefs_by_instance=wanted_prefs_by_instance,
            blocks_by_duration=blocks_by_duration,
            covering_by_duration=covering_by_duration,
            same_room_groups=same_room_groups,
            room_preblocked=room_preblocked,
            solver_config=solver_config,
            solver_warnings=solver_warnings,
        )
        parsed_two = json.loads(two_phase_result)
        if parsed_two.get("status") in {"SUCCESS", "SUCCESS_WITH_WARNINGS"}:
            meta = parsed_two.setdefault("meta", {})
            meta["estimated_vars_monolithic"] = estimated_vars
            meta["solve_strategy_selected"] = "two_phase"
            return json.dumps(parsed_two, ensure_ascii=False, indent=2)

        # Repair: fallback на monolithic с остатком времени
        if solver_config.get("repair_on_two_phase_fail", True):
            used = float(
                (parsed_two.get("meta") or {}).get("solve_time_sec")
                or (
                    float((parsed_two.get("meta") or {}).get("phase1_time_sec") or 0)
                    + float((parsed_two.get("meta") or {}).get("phase2_time_sec") or 0)
                )
            )
            remaining = max(
                1.0,
                float(solver_config["max_time_in_seconds"]) - used,
            )
            solver_config = {
                **solver_config,
                "max_time_in_seconds": remaining,
                "solve_strategy": "monolithic",
            }
            solver_warnings = list(solver_warnings) + [{
                "code": "TWO_PHASE_REPAIR_FALLBACK",
                "message": (
                    "two_phase не завершилась успешно "
                    f"({parsed_two.get('status')}); fallback на monolithic, "
                    f"остаток времени {remaining:.1f}s"
                ),
                "phase_status": parsed_two.get("status"),
                "phase_errors": parsed_two.get("errors") or [],
            }]
        else:
            return two_phase_result

    # 3. Переменные: x[(inst, start_slot_id, room)] = блок duration начиная со start
    x = {}
    objective_terms: list = []
    for inst in course_instances:
        pref = wanted_prefs_by_instance[inst["instance_id"]]
        blocked_slots = set(forbidden_slots_by_instance.get(inst["instance_id"], set()))
        allowed_slot_ids = None
        if inst["course_id"] in fixed_slots_by_course:
            allowed_slot_ids = set(fixed_slots_by_course[inst["course_id"]])

        fixed_room = pref.get("fixed_room")
        if fixed_room is not None:
            fixed_room = normalize_room_id(fixed_room)
        allowed_ids = inst.get("allowed_room_ids")

        if not inst["needs_physical_room"]:
            # online/external/sport: только виртуальный пул, не аудитории ИЕНИМ
            virtual = ensure_virtual_room(
                rooms,
                rooms_by_id,
                course_id=inst["course_id"],
                venue_type=inst.get("venue_type") or "virtual",
            )
            allowed_rooms = [virtual]
        elif fixed_room:
            if allowed_ids and fixed_room not in {
                normalize_room_id(room_id) for room_id in allowed_ids
            }:
                return json.dumps({
                    "status": "ERROR",
                    "errors": [{
                        "code": "CONFLICTING_ROOM_CONSTRAINTS",
                        "message": (
                            f"Для курса '{inst['name']}' fixed_room '{fixed_room}' "
                            f"не входит в allowed_room_ids {allowed_ids}"
                        ),
                        "course_id": inst["course_id"],
                        "entity_ids": [inst["instance_id"]],
                        "fixed_room": fixed_room,
                        "allowed_room_ids": allowed_ids,
                    }],
                    "message": (
                        f"Конфликт fixed_room и allowed_room_ids у '{inst['name']}'"
                    ),
                }, ensure_ascii=False, indent=2)
            room = rooms_by_id.get(fixed_room)
            if room is None:
                return json.dumps(
                    build_fixed_room_error(inst, pref, rooms_by_id),
                    ensure_ascii=False,
                    indent=2,
                )
            if not room_is_feasible(
                room,
                total_students=inst["total_students"],
                requirements=inst["requirements"],
                needs_software=inst.get("needs_software"),
            ):
                return json.dumps(
                    build_fixed_room_error(inst, pref, rooms_by_id),
                    ensure_ascii=False,
                    indent=2,
                )
            allowed_rooms = [room]
        else:
            # Только аудитории ИЕНИМ; виртуальный пул — исключительно для D-VIRT.
            physical = [room for room in rooms if not room.get("is_virtual")]
            allowed_rooms, unknown_allowed = filter_rooms_by_allowed_ids(
                physical,
                allowed_ids,
                rooms_by_id=rooms_by_id,
            )
            if allowed_ids is not None and not allowed_rooms:
                return json.dumps(
                    build_allowed_rooms_error(
                        inst,
                        allowed_room_ids=list(allowed_ids),
                        unknown_ids=unknown_allowed,
                        candidate_rooms=allowed_rooms,
                    ),
                    ensure_ascii=False,
                    indent=2,
                )
            # п.15: сужение домена до max_candidate_rooms ближайших по вместимости
            allowed_rooms = select_candidate_rooms(
                allowed_rooms,
                total_students=inst["total_students"],
                requirements=inst["requirements"],
                needs_software=inst.get("needs_software"),
                max_candidate_rooms=int(solver_config.get("max_candidate_rooms") or 0),
            )
            if not allowed_rooms:
                return json.dumps(
                    build_no_room_error(inst, rooms),
                    ensure_ascii=False,
                    indent=2,
                )

        wanted_slots = pref.get("wanted_slot_ids") or set()
        preferred_capacity = pref.get("preferred_capacity")
        preferred_types = pref.get("preferred_room_types") or []
        duration = int(inst.get("duration_slots") or 1)
        start_blocks = blocks_by_duration.get(duration) or {}
        time_wishes = list(inst.get("time_wishes") or [])

        for start_id, block in start_blocks.items():
            block_ids = [slot["id"] for slot in block]
            if any(slot_id in blocked_slots for slot_id in block_ids):
                continue
            if allowed_slot_ids is not None and not set(block_ids).issubset(allowed_slot_ids):
                continue
            if time_wishes and block_violates_hard_time_wishes(block, time_wishes):
                continue
            soft_wish_hits = soft_time_wish_penalty(block, time_wishes) if time_wishes else 0
            for r in allowed_rooms:
                if not r.get("is_virtual") and room_preblocked:
                    room_key = normalize_room_id(r["id"])
                    if any((slot_id, room_key) in room_preblocked for slot_id in block_ids):
                        continue
                if not room_is_feasible(
                    r,
                    total_students=inst["total_students"],
                    requirements=inst["requirements"],
                    needs_software=inst.get("needs_software"),
                ):
                    continue
                var_name = f"x_{inst['instance_id']}_s{start_id}_r{r['id']}"
                var = model.NewBoolVar(var_name)
                x[(inst["instance_id"], start_id, r["id"])] = var

                score = 0
                if start_id in wanted_slots:
                    score += weight_wanted_slot
                if soft_wish_hits:
                    score -= weight_time_wish * soft_wish_hits
                late_hits = late_slot_penalty(block, late_from=late_slot_from)
                if late_hits and weight_late_slot:
                    score -= weight_late_slot * late_hits
                if weight_saturday and saturday_penalty(block):
                    score -= weight_saturday
                if not r.get("is_virtual"):
                    if preferred_capacity is not None and r.get("capacity", 0) < preferred_capacity:
                        score -= weight_preferred_capacity
                    if preferred_types and not room_matches_preferred_type(r, preferred_types):
                        score -= weight_preferred_room_type
                if score:
                    objective_terms.append(score * var)

    # 4. Ограничения (Constraints) — ядро MVP + requirements + impossible + wanted + fixed

    # Ограничение A: каждое занятие ровно один старт+аудитория (блок целиком)
    for inst in course_instances:
        duration = int(inst.get("duration_slots") or 1)
        start_ids = list((blocks_by_duration.get(duration) or {}).keys())
        possible_vars = [
            x[(inst["instance_id"], start_id, r["id"])]
            for start_id in start_ids
            for r in rooms
            if (inst["instance_id"], start_id, r["id"]) in x
        ]
        if not possible_vars:
            pref = wanted_prefs_by_instance[inst["instance_id"]]
            if inst["course_id"] in fixed_slots_by_course:
                error = {
                "status": "ERROR", 
                    "errors": [{
                        "code": "FIXED_SCHEDULE_NO_DOMAIN",
                        "message": (
                            f"Для курса '{inst['name']}' fixed_schedules "
                            f"{fixed_slots_by_course[inst['course_id']]} не оставляют "
                            f"допустимого размещения (duration_slots={duration}, "
                            f"запреты преподавателя или аудитория)"
                        ),
                        "course_id": inst["course_id"],
                        "entity_ids": [inst["instance_id"]],
                        "timeslots_ids": list(fixed_slots_by_course[inst["course_id"]]),
                        "teacher_id": inst.get("teacher_id"),
                        "duration_slots": duration,
                    }],
                    "message": (
                        f"fixed_schedules блокируют размещение курса '{inst['name']}'"
                    ),
                }
            elif not (blocks_by_duration.get(duration) or {}):
                error = {
                    "status": "ERROR",
                    "errors": [{
                        "code": "DURATION_NO_BLOCK",
                        "message": (
                            f"Для курса '{inst['name']}' нет непрерывного блока "
                            f"из {duration} слотов "
                            f"(allow_duration_across_lunch="
                            f"{solver_config.get('allow_duration_across_lunch')})"
                        ),
                        "course_id": inst["course_id"],
                        "entity_ids": [inst["instance_id"]],
                        "duration_slots": duration,
                    }],
                    "message": (
                        f"Нет допустимого блока слотов для '{inst['name']}' "
                        f"(duration_slots={duration})"
                    ),
                }
            elif pref.get("fixed_room"):
                error = build_fixed_room_error(inst, pref, rooms_by_id)
            elif inst.get("allowed_room_ids"):
                allowed_ids = list(inst["allowed_room_ids"])
                filtered, unknown = filter_rooms_by_allowed_ids(
                    [room for room in rooms if not room.get("is_virtual")],
                    allowed_ids,
                    rooms_by_id=rooms_by_id,
                )
                error = build_allowed_rooms_error(
                    inst,
                    allowed_room_ids=allowed_ids,
                    unknown_ids=unknown,
                    candidate_rooms=filtered,
                )
            elif inst.get("time_wishes"):
                error = {
                    "status": "ERROR",
                    "errors": [{
                        "code": "TIME_WISH_NO_DOMAIN",
                        "message": (
                            f"Для курса '{inst['name']}' hard time_wishes "
                            f"{inst.get('time_wishes')} не оставляют допустимого "
                            f"размещения"
                        ),
                        "course_id": inst["course_id"],
                        "entity_ids": [inst["instance_id"]],
                        "time_wishes": list(inst.get("time_wishes") or []),
                        "time_wish_raw": inst.get("time_wish_raw"),
                    }],
                    "message": (
                        f"Пожелания по времени блокируют курс '{inst['name']}'"
                    ),
                }
            else:
                blocked = forbidden_slots_by_instance.get(inst["instance_id"], set())
                has_room = any(
                    room_is_feasible(
                        room,
                        total_students=inst["total_students"],
                        requirements=inst.get("requirements"),
                        needs_software=inst.get("needs_software"),
                    )
                    for room in rooms
                    if not room.get("is_virtual")
                )
                if blocked and has_room:
                    error = build_forbidden_slots_error(
                        inst,
                        forbidden_slot_ids=blocked,
                        rooms=rooms,
                        time_slots=time_slots,
                    )
                else:
                    error = build_no_room_error(inst, rooms)
            return json.dumps(error, ensure_ascii=False, indent=2)
            
        model.AddExactlyOne(possible_vars)

    # «Вместе с лекциями»: одна физическая аудитория на связанную группу курсов
    add_same_room_constraints(
        model,
        x,
        groups=same_room_groups,
        rooms=rooms,
        blocks_by_duration=blocks_by_duration,
    )

    # Fixed schedules: каждый указанный слот занят ровно одним instance курса
    # (для duration>1 одна переменная старта покрывает весь блок).
    for course_id, slot_ids in fixed_slots_by_course.items():
        course_insts = [inst for inst in course_instances if inst["course_id"] == course_id]
        for slot_id in slot_ids:
            vars_for_slot = []
            for inst in course_insts:
                duration = int(inst.get("duration_slots") or 1)
                covering = covering_by_duration.get(duration) or {}
                for start_id in covering.get(slot_id, []):
                    for room in rooms:
                        key = (inst["instance_id"], start_id, room["id"])
                        if key in x:
                            vars_for_slot.append(x[key])
            if not vars_for_slot:
                return json.dumps({
                    "status": "ERROR",
                    "errors": [{
                        "code": "FIXED_SCHEDULE_NO_DOMAIN",
                        "message": (
                            f"Для курса '{course_id}' fixed-слот {slot_id} "
                            f"не имеет допустимых переменных размещения"
                        ),
                        "course_id": course_id,
                        "entity_ids": [inst["instance_id"] for inst in course_insts],
                        "timeslots_ids": list(slot_ids),
                    }],
                    "message": f"Невозможно закрепить слот {slot_id} для курса '{course_id}'",
                }, ensure_ascii=False, indent=2)
            model.Add(sum(vars_for_slot) == 1)

    def placement_vars_covering_slot(inst: dict, slot_id: int, room_id: str | None = None) -> list:
        duration = int(inst.get("duration_slots") or 1)
        covering = covering_by_duration.get(duration) or {}
        vars_found = []
        for start_id in covering.get(slot_id, []):
            if room_id is not None:
                key = (inst["instance_id"], start_id, room_id)
                if key in x:
                    vars_found.append(x[key])
            else:
                for room in rooms:
                    key = (inst["instance_id"], start_id, room["id"])
                    if key in x:
                        vars_found.append(x[key])
        return vars_found

    # Ограничение B: аудитория занята на каждом слоте блока (п.8+9).
    for s in time_slots:
        for r in rooms:
            if r.get("is_virtual"):
                continue
            var_groups = []
            for inst in course_instances:
                vars_for_inst = placement_vars_covering_slot(inst, s["id"], r["id"])
                if vars_for_inst:
                    var_groups.append((vars_for_inst, instance_weeks(inst)))
            add_pairwise_week_conflicts(model, var_groups)

    # Ограничение C: teacher занят на каждом слоте блока.
    teacher_ids_in_model = sorted({
        teacher_id
        for inst in course_instances
        for teacher_id in instance_teacher_ids(inst)
    })
    for s in time_slots:
        for teacher_id in teacher_ids_in_model:
            var_groups = []
            for inst in course_instances:
                if teacher_id not in instance_teacher_ids(inst):
                    continue
                vars_for_inst = placement_vars_covering_slot(inst, s["id"])
                if vars_for_inst:
                    var_groups.append((vars_for_inst, instance_weeks(inst)))
            add_pairwise_week_conflicts(model, var_groups)

    # Ограничение D: группа занята на каждом слоте блока.
    group_ids_in_model = sorted({
        group_id
        for inst in course_instances
        for group_id in (inst.get("group_ids") or [])
    })
    for s in time_slots:
        for group_id in group_ids_in_model:
            var_groups = []
            for inst in course_instances:
                if group_id not in (inst.get("group_ids") or []):
                    continue
                vars_for_inst = placement_vars_covering_slot(inst, s["id"])
                if vars_for_inst:
                    var_groups.append((vars_for_inst, instance_weeks(inst)))
            add_pairwise_week_conflicts(model, var_groups)

    # Soft: окна у групп (п.14)
    objective_terms.extend(
        add_group_gap_objective_terms(
            model,
            x,
            course_instances=course_instances,
            time_slots=time_slots,
            rooms=rooms,
            covering_by_duration=covering_by_duration,
            weight=weight_group_gap,
        )
    )

    if objective_terms:
        model.Maximize(sum(objective_terms))

    # 5. Запуск солвера
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(solver_config["max_time_in_seconds"])
    solver.parameters.num_search_workers = int(solver_config["num_search_workers"])
    
    status = solver.Solve(model)
    
    # 6. Формирование ответа в JSON
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        schedule_result = []
        for inst in course_instances:
            duration = int(inst.get("duration_slots") or 1)
            start_blocks = blocks_by_duration.get(duration) or {}
            for start_id, block in start_blocks.items():
                for r in rooms:
                    key = (inst["instance_id"], start_id, r["id"])
                    if key in x and solver.Value(x[key]) == 1:
                        start_slot = block[0]
                        end_slot = block[-1]
                        start_time = str(start_slot.get("time") or "")
                        end_time = str(end_slot.get("time") or "")
                        if "-" in start_time and "-" in end_time:
                            time_span = f"{start_time.split('-', 1)[0]}-{end_time.split('-', 1)[-1]}"
                        else:
                            time_span = start_time or end_time
                        row = {
                            "course_id": inst["course_id"],
                            "course_name": inst["name"],
                            "teacher_id": inst["teacher_id"],
                            "teacher_ids": list(inst.get("teacher_ids") or (
                                [inst["teacher_id"]] if inst.get("teacher_id") else []
                            )),
                            "teacher_missing": bool(inst.get("teacher_missing")),
                            "teacher_is_placeholder": bool(
                                inst.get("teacher_is_placeholder")
                            ),
                            "teaching_mode": inst.get("teaching_mode"),
                            "lesson_kind": inst.get("lesson_kind"),
                            "students_needed": inst.get("students_needed", inst["total_students"]),
                            "group_ids": inst["group_ids"],
                            "day": start_slot["day"],
                            "slot_index": start_slot["slot_index"],
                            "slot_index_start": start_slot["slot_index"],
                            "slot_index_end": end_slot["slot_index"],
                            "timeslots_ids": [slot["id"] for slot in block],
                            "duration_slots": duration,
                            "time": time_span,
                            "room_id": r["id"],
                            "venue_type": inst.get("venue_type") or (
                                r.get("venue_type") if r.get("is_virtual") else "room"
                            ),
                            "needs_physical_room": bool(
                                inst.get("needs_physical_room", not r.get("is_virtual"))
                            ),
                            "requirements": inst["requirements"],
                            "instance_id": inst["instance_id"],
                            "week_pattern": inst.get("week_pattern") or {"type": "all"},
                            "weeks": sorted(instance_weeks(inst)),
                        }
                        if inst.get("allowed_room_ids") is not None:
                            row["allowed_room_ids"] = list(inst["allowed_room_ids"])
                        if inst.get("same_room_as_course_id"):
                            row["same_room_as_course_id"] = inst["same_room_as_course_id"]
                        if inst.get("time_wishes"):
                            row["time_wishes"] = list(inst["time_wishes"])
                        if inst.get("time_wish_raw"):
                            row["time_wish_raw"] = inst["time_wish_raw"]
                        if inst.get("subgroup_index") is not None:
                            row["subgroup_index"] = inst["subgroup_index"]
                        if inst.get("subgroup_count") is not None:
                            row["subgroup_count"] = inst["subgroup_count"]
                        if inst.get("team_label") is not None:
                            row["team_label"] = inst["team_label"]
                        schedule_result.append(row)

        objective_value = None
        if objective_terms:
            objective_value = int(solver.ObjectiveValue())

        soft_warnings = collect_unmet_soft_warnings(
            schedule_result,
            course_instances=course_instances,
            wanted_prefs_by_instance=wanted_prefs_by_instance,
            solver_config=solver_config,
        )
        all_warnings = list(solver_warnings) + soft_warnings
        status_label = "SUCCESS_WITH_WARNINGS" if all_warnings else "SUCCESS"
        return json.dumps({
            "status": status_label,
            "errors": [],
            "warnings": all_warnings,
            "schedule": schedule_result,
            "meta": {
                "solve_time_sec": round(solver.WallTime(), 3),
                "objective": objective_value,
                "lessons_count": len(schedule_result),
                "solver_status": solver.StatusName(status),
                "max_time_in_seconds": float(solver_config["max_time_in_seconds"]),
                "num_search_workers": int(solver_config["num_search_workers"]),
                "missing_teacher_policy": resolve_missing_teacher_policy(solver_config),
                "soft_weights": {
                    "wanted_slot": weight_wanted_slot,
                    "preferred_capacity": weight_preferred_capacity,
                    "preferred_room_type": weight_preferred_room_type,
                    "time_wish": weight_time_wish,
                    "group_gap": weight_group_gap,
                    "late_slot": weight_late_slot,
                    "saturday": weight_saturday,
                    "late_slot_from": late_slot_from,
                },
                "solve_strategy": "monolithic",
                "estimated_vars_monolithic": estimated_vars,
                "variables_created": len(x),
                "max_candidate_rooms": int(solver_config.get("max_candidate_rooms") or 0),
                "instances_count": len(course_instances),
                "unmet_soft_count": len(soft_warnings),
            },
        }, ensure_ascii=False, indent=2)

    timed_out = (
        status == cp_model.UNKNOWN
        or (
            solver.WallTime() >= float(solver_config["max_time_in_seconds"]) * 0.98
            and status not in (cp_model.OPTIMAL, cp_model.FEASIBLE)
        )
    )
    no_sol_errors = diagnose_no_solution(
        course_instances,
        time_slots=time_slots,
        fixed_slots_by_course=fixed_slots_by_course,
        forbidden_slots_by_instance=forbidden_slots_by_instance,
        x=x,
        solver_status=solver.StatusName(status),
        timed_out=timed_out,
    )
    return json.dumps(
        failure_payload(
            status="NO_SOLUTION",
            errors=no_sol_errors,
            warnings=solver_warnings,
            message=no_sol_errors[0]["message"],
            meta={
                "solve_time_sec": round(solver.WallTime(), 3),
                "objective": None,
                "lessons_count": 0,
                "solver_status": solver.StatusName(status),
                "max_time_in_seconds": float(solver_config["max_time_in_seconds"]),
                "num_search_workers": int(solver_config["num_search_workers"]),
                "missing_teacher_policy": resolve_missing_teacher_policy(solver_config),
                "solve_strategy": "monolithic",
                "estimated_vars_monolithic": estimated_vars,
                "variables_created": len(x),
                "timed_out": timed_out,
            },
        ),
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    data = prepare_parser_data(load_data())
    output_json = solve_schedule(json.dumps(data, ensure_ascii=False))
    print(output_json)
