import argparse
import json
import math
import re
from pathlib import Path
from os import PathLike

import pandas as pd


class ParserValidationError(ValueError):
    """Raised when parser output cannot be handed to the solver."""


DEFAULT_PARSER_CONFIG = {
    "hours": {
        "unit_hours": 32,
        "below_16_policy": "biweekly",
        "biweekly_start": "odd",
        "exact": {
            "16": {"lessons_per_week": 1, "week_pattern": "biweekly"},
            "32": {"lessons_per_week": 1, "week_pattern": "weekly"},
            "48": {"lessons_per_week": 2, "week_pattern": "weekly"},
            "64": {"lessons_per_week": 2, "week_pattern": "weekly"},
            "96": {"lessons_per_week": 3, "week_pattern": "weekly"},
            "108": {"lessons_per_week": 4, "week_pattern": "weekly"},
        },
        "ranges": [
            {"min": 17, "max": 31, "lessons_per_week": 1, "week_pattern": "weekly"},
            {"min": 33, "max": 47, "lessons_per_week": 2, "week_pattern": "weekly"},
            {"min": 49, "max": 63, "lessons_per_week": 2, "week_pattern": "weekly"},
            {"min": 65, "max": 95, "lessons_per_week": 3, "week_pattern": "weekly"},
            {"min": 97, "max": 128, "lessons_per_week": 4, "week_pattern": "weekly"},
        ],
        "long_lab": {"use_comment_hint": True, "default_duration_slots": 1},
    },
    "missing_teacher": {
        "policy": "soft",
        "placeholder": "UNKNOWN:{course_id}",
        "whitelist": {
            "venue_types": ["online", "external"],
            "course_names": ["Прикладная физическая культура (практика)"],
            "lesson_types": [],
        },
    },
    "pair_grid": {"unsupported_pair_policy": "warn"},
    "session": {"enabled": True},
}


class Importer:
    """Read the course load, room catalog and teacher preferences from XLSX."""

    data_dir = Path(__file__).resolve().parent / "tables"
    config_file = Path(__file__).resolve().parent / "config.json"
    rooms_file = data_dir / "table2.xlsx"
    rooms_sheet = "Аудитории"
    courses_file = data_dir / "table.xlsx"
    desires_file = data_dir / "table3.xlsx"
    pe_sheet = "Физ.культура"
    pe_institute = "ИЕНиМ"
    course_sheets = ["ХИМИКИ", "ФИНЗ", "ФИНЗ Магистры", "ЭБМ", "Тургенева 4 по выбору", "Тургенева 4"]
    days = ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА"]
    default_group_size = 30
    fixed_course_names = {"Прикладная физическая культура (практика)"}

    feature_columns = ["has_chalkboard", "has_whiteboard", "has_multimedia_board",
                       "has_blinds", "has_screen", "has_acoustic_system"]
    room_renames = {"Ауд.": "id", "Вид": "type", "Вм-ть": "capacity",
                    "меловая": "has_chalkboard",
                    "маркерная": "has_whiteboard", "мультимедиа": "has_multimedia_board",
                    "жалюзи": "has_blinds", "экран": "has_screen", "акустич. система": "has_acoustic_system"}
    dropped_room_columns = ["Кому принадлежит", "С кем договариваться", "Примечание"]
    teacher_columns = {"лекция": "ФИО лектора", "практика": "ФИО преподавателя на практики, лаборатории",
                       "лабораторная": "ФИО преподавателя на практики, лаборатории"}
    hours_columns = {"лекция": "Лекции", "практика": "Практ. занятия", "лабораторная": "Лаб. занятия"}
    group_column = "Номер группы"
    discipline_column = "Дисциплины"
    students_column = "Число студентов"
    projector_column = "Нужен ли проектор на практики, лаборатории"
    multimedia_column = "Нужна ли мультимедиа на лекции?"
    board_column = "Какая нужна доска на практики, лаборатории: меловая, маркерная, любая"
    software_column = "ПО на практики, лаборатории"
    location_column = "Где проводятся практики, лаборатории?"
    ntk_column = "НТК"
    delivery_model_column = "Модель реализации"
    time_wish_column = ("Пожелания по времени пар (дни недели, утро/вечер, "
                        "середина дня, ограничения по кол-ву пар в день "
                        "по медицинским показаниям)")
    comments_column = "Комментарий, особенности дисциплины"
    room_requirement_labels = {
        "любая доска": "board", "меловая доска": "chalkboard",
        "маркерная доска": "whiteboard", "мультимедиа доска": "multimedia_board",
        "экран": "screen", "жалюзи": "blinds", "акустическая система": "acoustic_system",
    }
    room_ref_pattern = re.compile(
        r"(?<!\d)\d{3}(?:/\d{1,2})?(?:\s?[а-яё](?![а-яё]))?(?!\d)", re.IGNORECASE)
    same_room_pattern = re.compile(
        r"(?:вместе\s+с\s+лекц\w*|там\s+же[,\s]*где\s+и\s+лекц\w*|"
        r"как\s+и\s+лекц\w*|где\s+и\s+лекц\w*|как\s+лекц\w*)", re.IGNORECASE)
    generic_location_pattern = re.compile(
        r"^\s*(?:любая|в\s+|аудитория|аудиторно|ауд\b|обычн|онлайн|online|"
        r"нет|не\s+проводится|уточняется|больш|класс|кабинет|комп|ивц|"
        r"ит-центр|информационн|тургенева|куйбышева|литер|корпус|этаж|"
        r"\d+\s*этаж|отдельн|на\s|лабораторн|практик|лекци)", re.IGNORECASE)
    # Canonical header -> accepted variants. Variants that differ only by case,
    # whitespace or "ё" are matched by _normalize_header without an explicit entry.
    header_aliases = {
        "Курс": ("Курс обучения",),
        "Номер группы": ("№ группы", "Группа"),
        "Число студентов": ("Количество студентов", "Численность студентов"),
        "Дисциплины": ("Дисциплина", "Наименование дисциплины"),
        "Лекции": ("Лекционные занятия", "Лекции, ч"),
        "Практ. занятия": ("Практические занятия", "Практ. занятия, ч"),
        "Лаб. занятия": ("Лабораторные занятия", "Лаб. занятия, ч"),
        "Зачет / экзамен": ("зачет /экзамен", "Зачёт/экзамен",
                            "Отчетное мероприятие: Зачет / экзамен"),
        "ФИО лектора": ("Лектор",),
        "ФИО преподавателя на практики, лаборатории": (
            "ФИО преподавателя на практики/лаборатории",
            "ФИО преподавателя на практические занятия, лаборатории"),
        "Нужна ли мультимедиа на лекции?": ("Нужна ли мультимедиа на лекции",),
        "Нужен ли проектор на практики, лаборатории": (
            "Нужен ли проектор на практики, лаборатории?",),
        "Какая нужна доска на практики, лаборатории: меловая, маркерная, любая": (
            "Какая нужна доска на практики, лаборатории: меловая, маркерная или любая",),
        "Кол-во подгрупп на практич и лаб. занятия": (
            "Кол-во подгрупп на практические и лабораторные занятия",),
    }
    subgroup_column = "Кол-во подгрупп на практич и лаб. занятия"
    # Session / report columns are isolated from weekly courses (п.13).
    session_field_markers = (
        ("teacher_name", ("принимающего отчетное",)),
        ("time_window_raw", ("время начала",)),
        ("consultation_raw", ("консультация",)),
        ("free_days_min", ("свободных дней",)),
        ("room_requirement_raw", ("какая нужна аудитория",)),
        ("scope_raw", ("особенности проведения",)),
        ("date_windows_raw", ("поставить отчетные",)),
        ("restrictions_raw", ("ограничения по датам",)),
        ("note_raw", ("дополнительные особенности", "примечание:")),
        ("report_format", ("вид отчетного",)),
        ("report_type", ("зачет / экзамен", "зачет /экзамен", "отчетное мероприятие")),
    )
    teacher_segment_pattern = re.compile(
        r"[,;\n]+|\s+или\s+|\s*\+\s*|(?<![А-Яа-яЁё])/(?![А-Яа-яЁё])")
    teacher_name_pattern = re.compile(
        r"(?:"
        r"[А-ЯЁA-Z][а-яёa-z-]+"
        r"(?:"
        r"\s+[А-ЯЁA-Z]\.(?:\s*[А-ЯЁA-Z]\.?(?![а-яёa-z]))?"
        r"|\s+[А-ЯЁA-Z]\s?[А-ЯЁA-Z](?![а-яёa-z])"
        r")"
        r"|"
        r"[А-ЯЁA-Z]\.(?:\s*[А-ЯЁA-Z]\.)?\s*[А-ЯЁA-Z][а-яёa-z-]+"
        r")")
    latin_name_letters = str.maketrans(
        {"A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К",
         "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х"})
    initials_first_pattern = re.compile(
        r"^([А-ЯЁA-Z]\.)\s*([А-ЯЁA-Z]\.)?\s*([А-ЯЁA-Z][а-яёa-z-]+)$")
    dotless_initials_pattern = re.compile(
        r"^([А-ЯЁA-Z][а-яёa-z-]+)\s+([А-ЯЁA-Z])\s?([А-ЯЁA-Z])$")
    teacher_full_name_pattern = re.compile(
        r"[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+)?")
    team_marker_pattern = re.compile(
        r"(?P<count>\d+)?\s*(?P<kind>команд\w*|подгрупп\w*|подгр\w*|п/гр\w*|групп\w*)",
        re.IGNORECASE)
    parenthesized_count_pattern = re.compile(r"\(\s*(\d+)\s*\)")
    subgroup_type_pattern = re.compile(r"\b(лаб\w*|практ\w*|пр\.)", re.IGNORECASE)

    # --- Пункт 9: тип площадки ------------------------------------------------
    venue_online_pattern = re.compile(
        r"(?:^|[^\w])(?:онлайн|online|дистанционн\w*|в\s+онлайн[-\s]?формате)(?:[^\w]|$)")
    venue_room_pattern = re.compile(
        r"аудитор|ауд\b|класс|кабинет|лаборатор|очно|ивц|ит-центр|"
        r"этаж|корпус|доск|проектор|любая|больш|обычн|тургенева|куйбышева|литер")
    venue_campus_pattern = re.compile(r"тургенева|куйбышева|литер")
    venue_external_pattern = re.compile(
        r"\b(?:имм\s+уро\s+ран|уро\s+ран|униим|ран)\b|"
        r"\b(?:ооо|ао|пао|зао)\b|на\s+предприятии|в\s+организации|обсерватори")
    venue_comment_external_pattern = re.compile(
        r"занятия\s+(?:проводятся|проходят)\s+в\s+"
        r"(?:имм\s+уро\s+ран|униим|ран|ооо|ао|пао|зао|организации|институте)")
    venue_no_room_pattern = re.compile(r"^\s*(?:нет|не\s+требуется|не\s+проводится)\s*$")

    # --- Пункт 10: пожелания по времени --------------------------------------
    day_patterns = (
        ("ПОНЕДЕЛЬНИК", re.compile(r"\b(?:понедельник\w*|понед\w*|пн)\b", re.IGNORECASE)),
        ("ВТОРНИК", re.compile(r"\b(?:вторник\w*|вт)\b", re.IGNORECASE)),
        ("СРЕДА", re.compile(r"\b(?:сред[аыуе]\w*|ср)\b", re.IGNORECASE)),
        ("ЧЕТВЕРГ", re.compile(r"\b(?:четверг\w*|четвер\w*|чт)\b", re.IGNORECASE)),
        ("ПЯТНИЦА", re.compile(r"\b(?:пятниц\w*|пятн\w*|пт)\b", re.IGNORECASE)),
        ("СУББОТА", re.compile(r"\b(?:суббот\w*|суб\w*|сб)\b", re.IGNORECASE)),
    )
    pair_word_values = {
        "перв": 1, "втор": 2, "трет": 3, "четверт": 4, "пят": 5, "шест": 6,
    }
    pair_count_word_values = {
        "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6,
    }
    pair_range_pattern = re.compile(
        r"(?<![\d,.])(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?"
        r"\s*(?:-?(?:й|я|ю|ой|ий|ая|ую))?\s*пар(?:а|ы|у|ам|ами|е)?\b",
        re.IGNORECASE)
    pair_word_pattern = re.compile(
        r"\b(перв|втор|трет|четверт|пят|шест)\w*\s+пар(?:а|ы|у|ам|ами|е)?\b",
        re.IGNORECASE)
    pair_count_word_pattern = re.compile(
        r"\b(?:первые|первых)?\s*(два|две|три|четыре|пять|шесть)\s+"
        r"пар(?:а|ы|у|ам|ами|е)?\b", re.IGNORECASE)
    pair_bound_pattern = re.compile(
        r"\b(?P<prep>не\s+раньше|не\s+ранее|не\s+позже|не\s+позднее|"
        r"начиная\s+со?|после|со?|до)\s+"
        r"(?:(?P<num>\d{1,2})|(?P<word>перв\w*|втор\w*|трет\w*|"
        r"четверт\w*|пят\w*|шест\w*))\s+пар(?:а|ы|у|ам|ами|е)?\b",
        re.IGNORECASE)
    time_clause_pattern = re.compile(
        r"\b(?P<prep>не\s+раньше|не\s+ранее|не\s+позже|не\s+позднее|"
        r"начиная\s+со?|после|со?|до)\s+"
        r"(?P<hour>\d{1,2})(?:[:.](?P<minute>\d{2})|-(?P<minute2>\d{2}))",
        re.IGNORECASE)
    max_pairs_day_pattern = re.compile(
        r"\b(?:не\s+более|не\s+больше|максимум|макс\.?)\s+"
        r"(\d{1,2})\s+пар(?:ы)?\s+в\s+день\b", re.IGNORECASE)
    day_part_patterns = (
        ("morning", re.compile(
            r"\bутр\w*|перв(?:ая|ой|ую)?\s+половин\w*\s+(?:дня|день)",
            re.IGNORECASE)),
        ("afternoon", re.compile(
            r"втор(?:ая|ой|ую)?\s+половин\w*\s+(?:дня|день)|"
            r"после\s+обеда|середин\w*\s+(?:дня|день)|"
            r"\bднем\b", re.IGNORECASE)),
        ("evening", re.compile(r"\bвечер\w*", re.IGNORECASE)),
    )
    wish_negation_pattern = re.compile(
        r"\bне\b|нельзя|нежелат|исключ|кроме|запрещ", re.IGNORECASE)
    wish_soft_pattern = re.compile(
        r"по\s+возможности|желательно|лучше|предпочтительн\w*",
        re.IGNORECASE)
    wish_positive_pattern = re.compile(
        r"\b(?:по)?ставить\b|\bставим\b|\bжелательно\b|\bлучше\b|"
        r"\bпредпочтительн\w*|\bможно\b", re.IGNORECASE)
    wish_segment_pattern = re.compile(r"[;\n]+|(?<=\.)\s+(?=[А-ЯЁA-Z0-9])")

    # --- Пункт 11: комментарии -----------------------------------------------
    comment_online_pattern = re.compile(
        r"\bонлайн\b|\bonline\b|в\s+контур\b|"
        r"дистанционн\w*\s+(?:формат\w*|обучен\w*|занят\w*|курс\w*|"
        r"проведен\w*|режим\w*)", re.IGNORECASE)
    comment_duration_hours_pattern = re.compile(
        r"(\d+(?:[.,]\d+)?)\s*(?:ак\.?\s*)?час\w*")
    comment_duration_double_pattern = re.compile(
        r"сдвоен\w*|пар\w*\s+подряд|подряд\s+пар\w*|без\s+окна")
    comment_duration_half_pattern = re.compile(
        r"полтор\w*\s+пар\w*|1[.,]5\s+пар\w*")
    comment_duration_pairs_pattern = re.compile(
        r"(?:по\s+)?(две|три|четыре|пять|шесть|\d+)\s+пар\w*\s+подряд")
    comment_period_pattern = re.compile(
        r"\bс\s+(\d{1,2}\.\d{1,2}\.\d{2,4})\s+по\s+"
        r"(\d{1,2}\.\d{1,2}\.\d{2,4})")
    comment_week_range_patterns = (
        re.compile(r"\bс\s+(\d{1,2})\s+по\s+(\d{1,2})\s+недел"),
        re.compile(r"\b(\d{1,2})\s*[-–]\s*(\d{1,2})\s+недел"),
    )
    comment_week_chain_pattern = re.compile(
        r"\bс\s+(\d{1,2})\s+по\s+(\d{1,2})(?=\s*(?:,|и|недел))",
        re.IGNORECASE)
    comment_week_list_pattern = re.compile(
        r"\bнедели\s+([\d,\s\-–и]+)", re.IGNORECASE)
    comment_semester_half_pattern = re.compile(
        r"(перв|втор)\w*\s+половин\w*\s+семестра")

    def __init__(self, rooms_file: str | PathLike = rooms_file, rooms_sheet: str = rooms_sheet,
                 courses_file: str | PathLike = courses_file, course_sheets: list[str] | None = None,
                 days: list[str] | None = None, save_path: str | PathLike | None = None,
                 desires_file: str | PathLike | None = desires_file, fixed_course_names: set[str] | None = None,
                 default_group_size: int = default_group_size,
                 pe_sheet: str | None = pe_sheet, pe_institute: str = pe_institute,
                 config: dict | str | PathLike | None = None,
                 parse_room_occupancy: bool = False):
        self.rooms_file = rooms_file
        self.rooms_sheet = rooms_sheet
        self.courses_file = courses_file
        self.desires_file = desires_file
        self.pe_sheet = pe_sheet
        self.pe_institute = pe_institute
        self.course_sheets = list(course_sheets) if course_sheets is not None else list(type(self).course_sheets)
        self.days = list(days) if days is not None else list(type(self).days)
        self.save_path = Path(save_path) if save_path is not None \
            else Path(__file__).resolve().parent / "data.json"
        self.fixed_course_names = set(fixed_course_names) \
            if fixed_course_names is not None \
            else set(type(self).fixed_course_names)
        self.default_group_size = int(default_group_size)
        self.config = self._load_config(config)
        self.parse_room_occupancy = bool(parse_room_occupancy)
        self._teachers: dict[str, dict] = {}
        self._groups: dict[str, dict] = {}
        self._course_count = 0
        self._time_slots: list[dict] = []
        self._warnings: list[str] = []
        self._group_sizes: dict[str, int] = {}
        self._group_size_sources: dict[str, str] = {}
        self._room_ids: dict[str, str] = {}
        self._pe_slots: dict[int, list[int]] = {}
        self._header_lookup = self._build_header_lookup()
        self._skipped_hours: dict[tuple[str, str, str], int] = {}
        self._biweekly_counter = 0
        self._session_count = 0

    @classmethod
    def _load_config(cls, config: dict | str | PathLike | None) -> dict:
        """Load parser config.json and deep-merge it over the built-in defaults."""
        user_config: dict = {}
        if config is None:
            path = Path(cls.config_file)
            if path.exists():
                with path.open(encoding="utf-8") as file:
                    user_config = json.load(file)
        elif isinstance(config, dict):
            user_config = config
        else:
            with Path(config).open(encoding="utf-8") as file:
                user_config = json.load(file)
        return cls._deep_merge(DEFAULT_PARSER_CONFIG, user_config)

    @classmethod
    def _deep_merge(cls, base: dict, override: dict) -> dict:
        result = {key: cls._deep_merge(value, {}) if isinstance(value, dict) else value
                  for key, value in base.items()}
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = cls._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def parse_from_excel(self) -> dict:
        self._warnings = []
        self._group_sizes = {}
        self._group_size_sources = {}
        self._skipped_hours = {}
        self._biweekly_counter = 0
        self._session_count = 0
        rooms_df = pd.read_excel(self.rooms_file, sheet_name=self.rooms_sheet, header=[0, 2])
        rooms = self._parse_rooms(rooms_df)
        self._time_slots = self._parse_time_slots(rooms_df)
        room_preblocked = self._parse_room_occupancy(rooms_df, rooms)
        courses, session_requests = self._parse_courses()
        impossible, wanted = ([], [])
        if self.desires_file is not None:
            desires_df = pd.read_excel(self.desires_file)
            impossible, wanted = self._parse_teachers_desires(desires_df)
        self._pe_slots = self._parse_pe_slots()
        fixed = self._generate_fixed_schedules(courses)
        self._validate_fixed_schedules(courses, fixed)
        for course in courses:
            course.pop("_course_number", None)
        self._finalize_group_sizes()
        self._finalize_teacher_ids(courses, impossible, wanted)
        self._link_desires_to_courses(courses, impossible, wanted)
        self._apply_missing_teacher_policy(courses)
        self._finalize_time_wishes(courses)
        self._resolve_same_room_links(courses)
        self._finalize_course_instances(courses)
        return {
            "rooms": rooms,
            "teachers": list(self._teachers.values()),
            "groups": list(self._groups.values()),
            "courses": courses,
            "time_slots": self._time_slots,
            "teachers_impossible_slots": impossible,
            "teachers_wanted_slots": wanted,
            "fixed_schedules": fixed,
            "room_preblocked": room_preblocked,
            "ignored": {"session_requests": session_requests},
            "warnings": self._warnings,
        }

    def save_to_json(self, data: dict) -> None:
        self.save_path.parent.mkdir(parents=True, exist_ok=True)
        with self.save_path.open("w", encoding="utf-8") as file:
            json.dump(self._json_safe(data), file, indent=2, ensure_ascii=False, allow_nan=False)

    @classmethod
    def _json_safe(cls, value):
        """Convert pandas/numpy missing values into standards-compliant JSON nulls."""
        if isinstance(value, dict):
            return {key: cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._json_safe(item) for item in value]
        try:
            missing = pd.isna(value)
        except (TypeError, ValueError):
            return value
        if isinstance(missing, bool) and missing:
            return None
        # numpy.bool_ is not a Python bool.
        if type(missing).__name__ == "bool_" and bool(missing):
            return None
        if hasattr(value, "item"):
            try:
                return value.item()
            except (ValueError, TypeError):
                pass
        return value

    def _parse_time_slots(self, rooms: pd.DataFrame) -> list[dict]:
        slots = []
        for day in self.days:
            for slot_index, time in enumerate(rooms[day].columns, start=1):
                slots.append({"id": len(slots) + 1, "day": day.capitalize(),
                              "slot_index": slot_index, "time": str(time)})
        return slots

    def _room_id_column(self, rooms_df: pd.DataFrame):
        for column in rooms_df.columns:
            top = column[0] if isinstance(column, tuple) else column
            if self._name_key(top).rstrip(".") in {"ауд", "аудитория"}:
                return column
        return None

    def _parse_room_occupancy(self, rooms_df: pd.DataFrame,
                              rooms: list[dict]) -> list[dict]:
        """Read the reference timetable from the room sheet (п.15, opt-in)."""
        if not self.parse_room_occupancy:
            return []
        id_column = self._room_id_column(rooms_df)
        if id_column is None:
            raise ParserValidationError(
                f"Лист {self.rooms_sheet!r}: не найдена колонка «Ауд.»")
        room_ids = {room["id"] for room in rooms}
        slot_lookup = {(slot["day"].upper(), slot["slot_index"]): slot["id"]
                       for slot in self._time_slots}
        result: list[dict] = []
        seen: set[tuple[int, str]] = set()
        unknown_rooms: set[str] = set()
        unknown_cells: set[tuple[str, str]] = set()
        for _, row in rooms_df.iterrows():
            room_id = self._normalize_room_id(row.get(id_column))
            if not room_id:
                continue
            if room_id not in room_ids:
                unknown_rooms.add(room_id)
                continue
            for day in self.days:
                for slot_index, time in enumerate(rooms_df[day].columns, start=1):
                    value = row.get((day, time))
                    if pd.isna(value) or not str(value).strip() \
                            or str(value).strip().lower() == "nan":
                        continue
                    slot_id = slot_lookup.get((day.upper(), slot_index))
                    if slot_id is None:
                        unknown_cells.add((day, str(time)))
                        continue
                    key = (slot_id, room_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    result.append({"slot_id": slot_id, "room_id": room_id})
        if unknown_rooms:
            self._warn_once(
                f"Аудитории: занятость ссылается на отсутствующие аудитории "
                f"{sorted(unknown_rooms)!r}; записи пропущены")
        if unknown_cells:
            self._warn_once(
                f"Аудитории: занятость в неизвестных слотах {sorted(unknown_cells)!r}; "
                f"записи пропущены")
        return result

    def _parse_rooms(self, rooms: pd.DataFrame) -> list[dict]:
        rooms = rooms.drop(self.days + self.dropped_room_columns, axis=1, level=0)
        rooms.columns = [top if "Unnamed" in str(bottom) else bottom for top, bottom in rooms.columns]
        rooms = rooms.dropna(subset=["Ауд."]).rename(columns=self.room_renames)
        rooms["id"] = rooms["id"].map(self._normalize_room_id)
        rooms = rooms[rooms["id"].notna() & ~rooms["id"].astype(str).eq("")]
        # The sheet contains one empty duplicate row (e.g. room 369); keep the
        # richest row per id so the solver never sees two rooms with one id.
        rooms = rooms.assign(_filled=rooms.notna().sum(axis=1))
        rooms = rooms.sort_values("_filled", ascending=False).drop_duplicates("id", keep="first")
        for column in self.feature_columns:
            if column not in rooms:
                rooms[column] = False
            else:
                rooms[column] = rooms[column].fillna("").astype(str).str.strip().eq("+")
        capacity = pd.to_numeric(
            rooms["capacity"].astype(str).str.extract(r"(\d+)", expand=False), errors="coerce")
        missing_capacity = int(capacity.isna().sum())
        if missing_capacity:
            self._warnings.append(
                f"Аудитории: у {missing_capacity} из {len(rooms)} не указана «Вм-ть»; "
                f"capacity оставлен null")
        records = []
        for _, row in rooms.iterrows():
            record = {"id": row["id"], "type": self._normalize_room_type(row.get("type")),
                      "capacity": None if pd.isna(capacity.loc[row.name])
                      else int(capacity.loc[row.name])}
            record.update({column: bool(row.get(column, False)) for column in self.feature_columns})
            record["has_board"] = (record["has_chalkboard"] or record["has_whiteboard"]
                                   or record["has_multimedia_board"])
            records.append(record)
        self._room_ids = {record["id"]: record["id"] for record in records}
        return records

    @staticmethod
    def _normalize_room_id(value: object) -> str | None:
        if pd.isna(value):
            return None
        text = str(value).replace("\xa0", " ").strip()
        if not text or text.lower() == "nan":
            return None
        text = re.sub(r"^(\d+)\.0$", r"\1", text)
        return re.sub(r"\s+", "", text)

    def _normalize_room_type(self, value: object) -> str | None:
        """Normalize the raw "Вид" value without interpreting its meaning."""
        if pd.isna(value):
            return None
        text = str(value).replace("\xa0", " ").strip().lower()
        if not text or text == "nan":
            return None
        text = re.sub(r"[\s.]+", " ", text).strip()
        mapping = {"м": "м", "м лаб": "м лаб", "лаб": "лаб", "к": "к",
                   "ивц": "ИВЦ", "лмб": "ЛМБ"}
        if text in mapping:
            return mapping[text]
        self._warnings.append(f"Аудитория: неизвестное значение «Вид» {value!r}")
        return None

    @staticmethod
    def _normalize_header(value: object) -> str:
        """Build a case/spacing-insensitive key for header alias lookup."""
        text = str(value).replace("\xa0", " ").replace("ё", "е").replace("Ё", "Е")
        text = re.sub(r"\s+", " ", text).strip().lower()
        return re.sub(r"\s*/\s*", " / ", text)

    @classmethod
    def _build_header_lookup(cls) -> dict[str, str]:
        lookup = {}
        for canonical, variants in cls.header_aliases.items():
            for variant in (canonical, *variants):
                lookup[cls._normalize_header(variant)] = canonical
        return lookup

    def _normalize_headers(self, df: pd.DataFrame) -> pd.DataFrame:
        renamed = {}
        for column in df.columns:
            canonical = self._header_lookup.get(self._normalize_header(column))
            if canonical is not None:
                renamed[column] = canonical
        return df.rename(columns=renamed)

    def _parse_courses(self) -> tuple[list[dict], list[dict]]:
        courses: list[dict] = []
        session_requests: list[dict] = []
        seen_sessions: set[tuple] = set()
        session_enabled = bool(self.config.get("session", {}).get("enabled", True))
        with pd.ExcelFile(self.courses_file) as workbook:
            sheet_names = list(workbook.sheet_names)
            for sheet_name in sheet_names:
                if sheet_name not in self.course_sheets:
                    self._warnings.append(
                        f"Лист {sheet_name!r} не входит в список поддерживаемых и пропущен")
            for sheet_name in self.course_sheets:
                if sheet_name not in sheet_names:
                    self._warnings.append(f"Лист {sheet_name!r} отсутствует в файле и пропущен")
                    continue
                df = pd.read_excel(workbook, sheet_name=sheet_name)
                df = self._normalize_headers(df)
                if self.discipline_column not in df or self.group_column not in df:
                    raise ValueError(f"Лист {sheet_name!r}: отсутствует колонка дисциплины или группы")
                df[self.discipline_column] = df[self.discipline_column].ffill()
                session_columns = self._session_columns(df) if session_enabled else {}
                for _, row in df.dropna(subset=[self.group_column]).iterrows():
                    row_courses, session = self._parse_row(row, sheet_name, session_columns)
                    courses.extend(row_courses)
                    if session is None:
                        continue
                    key = (session["sheet"], session["discipline"],
                           tuple(session["group_ids"]), session["report_type"],
                           session["teacher_name"], session["report_format"],
                           session["time_window_raw"], session["consultation_raw"],
                           session["free_days_min"], session["room_requirement_raw"],
                           session["scope_raw"],
                           tuple((window["start"], window["end"], window["raw"])
                                 for window in session["date_windows"]),
                           session["restrictions_raw"], session["note_raw"])
                    if key in seen_sessions:
                        continue
                    seen_sessions.add(key)
                    session_requests.append(session)
        self._flush_hours_warnings()
        return courses, session_requests

    def _parse_row(self, row: pd.Series, sheet_name: str,
                   session_columns: dict | None = None) -> tuple[list[dict], dict | None]:
        counts = self._parse_students_count(row.get(self.students_column))
        result = []
        for lesson_type, column in self.hours_columns.items():
            hours = self._parse_hours(row.get(column))
            if hours is None:
                self._count_skipped_hours(sheet_name, column, "empty")
                continue
            if hours <= 0:
                self._count_skipped_hours(sheet_name, column, "zero")
                continue
            course = self._build_course(row, lesson_type, hours, sheet_name)
            result.append(course)
            self._register_teachers_and_groups(course, counts, sheet_name)
        session = self._extract_session_request(
            row, sheet_name, session_columns or {}, [course["id"] for course in result])
        return result, session

    def _count_skipped_hours(self, sheet_name: str, column: str, kind: str) -> None:
        key = (sheet_name, column, kind)
        self._skipped_hours[key] = self._skipped_hours.get(key, 0) + 1

    def _flush_hours_warnings(self) -> None:
        for (sheet_name, column, kind), count in sorted(self._skipped_hours.items()):
            if not count:
                continue
            reason = "пусто" if kind == "empty" else "= 0"
            self._warnings.append(
                f"Лист {sheet_name!r}: «{column}» {reason} в {count} строках — "
                f"курсы не созданы")

    def _session_columns(self, df: pd.DataFrame) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        for column in df.columns:
            key = self._name_key(column)
            for field, markers in self.session_field_markers:
                if any(marker in key for marker in markers):
                    mapping.setdefault(field, []).append(column)
                    break
        # "Зачет / экзамен" exists on every course sheet as a grading column.
        # A sheet is session-aware only when it also carries extended report fields.
        extended = {"teacher_name", "time_window_raw", "consultation_raw",
                    "free_days_min", "room_requirement_raw", "scope_raw",
                    "date_windows_raw", "restrictions_raw", "note_raw",
                    "report_format"}
        if not extended.intersection(mapping):
            return {}
        return mapping

    def _extract_session_request(self, row: pd.Series, sheet_name: str,
                                 columns: dict[str, list[str]],
                                 course_ids: list[str]) -> dict | None:
        """Isolate session / report data so it never becomes a weekly course (п.13)."""
        if not columns:
            return None
        values: dict[str, str] = {}
        for field, field_columns in columns.items():
            if field == "date_windows_raw":
                continue
            texts = [self._text_cell(row.get(column)) for column in field_columns]
            texts = [text for text in texts if text]
            if texts:
                values[field] = " | ".join(texts)
        date_windows = []
        for column in columns.get("date_windows_raw", []):
            text = self._text_cell(row.get(column))
            if not text:
                continue
            periods = self.comment_period_pattern.findall(text)
            parsed = False
            for start, end in periods:
                start_iso, end_iso = self._iso_date(start), self._iso_date(end)
                if start_iso and end_iso:
                    date_windows.append(
                        {"start": start_iso, "end": end_iso, "raw": text})
                    parsed = True
            if not parsed:
                dates = [self._iso_date(value) for value in
                         re.findall(r"\d{1,2}\.\d{1,2}\.\d{2,4}", text)]
                dates = [value for value in dates if value]
                if dates:
                    date_windows.append(
                        {"start": dates[0], "end": dates[-1], "raw": text})
                else:
                    date_windows.append({"start": None, "end": None, "raw": text})
        if not values and not date_windows:
            return None

        raw_groups = row.get(self.group_column)
        group_ids = [] if pd.isna(raw_groups) else [
            group for group in re.split(r"[\s,;\n]+", str(raw_groups).strip()) if group]
        free_days_value = values.get("free_days_min")
        free_days_match = re.search(r"\d+", free_days_value or "")
        self._session_count += 1
        return {
            "id": f"s{self._session_count}",
            "sheet": sheet_name,
            "course_ids": list(course_ids),
            "discipline": self._clean_discipline(row.get(self.discipline_column)) or None,
            "group_ids": group_ids,
            "report_type": values.get("report_type"),
            "teacher_name": values.get("teacher_name"),
            "report_format": values.get("report_format"),
            "time_window_raw": values.get("time_window_raw"),
            "consultation_raw": values.get("consultation_raw"),
            "free_days_min": int(free_days_match.group()) if free_days_match else None,
            "room_requirement_raw": values.get("room_requirement_raw"),
            "scope_raw": values.get("scope_raw"),
            "date_windows": date_windows,
            "restrictions_raw": values.get("restrictions_raw"),
            "note_raw": values.get("note_raw"),
        }

    @staticmethod
    def _parse_hours(raw_value: object) -> float | None:
        if pd.isna(raw_value):
            return None
        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool):
            return float(raw_value)
        text = str(raw_value).strip()
        if not text or text.lower() in {"nan", "-", "—"}:
            return None
        numbers = re.findall(r"\d+(?:[.,]\d+)?", text)
        return float(numbers[-1].replace(",", ".")) if numbers else None

    def _resolve_hours(self, hours: float, lesson_type: str,
                       hints: list[dict]) -> dict:
        """Map semester hours to lessons_per_week / week_pattern (п.16)."""
        config = self.config.get("hours", {})
        exact = {float(key): value
                 for key, value in (config.get("exact") or {}).items()}
        rule = exact.get(float(hours))
        if rule is None and 0 < hours < 16:
            rule = {"lessons_per_week": 1,
                    "week_pattern": config.get("below_16_policy", "biweekly")}
        if rule is None:
            for item in config.get("ranges") or []:
                if float(item.get("min", 0)) <= hours <= float(item.get("max", 0)):
                    rule = item
                    break
        if rule is None:
            unit = float(config.get("unit_hours", 32) or 32)
            rule = {"lessons_per_week": max(1, math.ceil(hours / unit)),
                    "week_pattern": "weekly"}

        lessons_per_week = max(1, int(rule.get("lessons_per_week") or 1))
        pattern = str(rule.get("week_pattern") or "weekly").lower()
        if pattern == "biweekly":
            start = str(config.get("biweekly_start", "odd")).lower()
            first, second = ("even", "odd") if start == "even" else ("odd", "even")
            pattern = first if self._biweekly_counter % 2 == 0 else second
            self._biweekly_counter += 1
        elif pattern not in {"weekly", "odd", "even"}:
            pattern = "weekly"
        return {
            "lessons_per_week": lessons_per_week,
            "week_pattern": pattern,
            "duration_slots": self._resolve_duration_slots(lesson_type, hints),
        }

    def _resolve_duration_slots(self, lesson_type: str, hints: list[dict]) -> float:
        config = self.config.get("hours", {}).get("long_lab", {})
        default = float(config.get("default_duration_slots", 1) or 1)
        if lesson_type != "лабораторная" or not config.get("use_comment_hint", True):
            return default
        durations = [float(hint["duration_slots"]) for hint in hints
                     if hint.get("duration_slots") is not None]
        return max(durations) if durations else default

    @staticmethod
    def _parse_students_count(raw_value: object) -> list[int] | None:
        """Parse a fully numeric "Число студентов" cell; ignore text like "2 полусеместр"."""
        if pd.isna(raw_value):
            return None
        parts = [part for part in re.split(r"[\s,;]+", str(raw_value).strip()) if part]
        if not parts or not all(re.fullmatch(r"\d+(?:[.,]\d+)?", part) for part in parts):
            return None
        values = [int(float(part.replace(",", "."))) for part in parts]
        values = [value for value in values if value > 0]
        return values or None

    @staticmethod
    def _group_size_observations(group_ids: list[str], counts: list[int] | None) -> dict[str, int]:
        """Distribute the row's student count across its groups (documented in TZ)."""
        if not counts:
            return {}
        if len(counts) > 1 and len(counts) == len(group_ids):
            return dict(zip(group_ids, counts))
        if len(counts) == 1:
            per_group = math.ceil(counts[0] / max(1, len(group_ids)))
            return {group_id: per_group for group_id in group_ids}
        size = max(counts)
        return {group_id: size for group_id in group_ids}

    @classmethod
    def _parse_subgroup_counts(cls, raw_value: object) -> dict:
        """Parse the subgroup column into practice/laboratory counts."""
        result = {"practice": None, "laboratory": None, "raw": None,
                  "ambiguous": False, "zero": False, "unparsed": False, "extra": []}
        if pd.isna(raw_value):
            return result
        text = str(raw_value).strip()
        if not text or text.lower() == "nan":
            return result
        result["raw"] = text
        typed = {"practice": [], "laboratory": []}
        unlabeled = []
        extra = []
        zero = False
        for line in re.split(r"[\n;]+", text):
            line = re.sub(r"\s+", " ", line.replace("\xa0", " ")).strip()
            if not line:
                continue
            match = re.match(r"(\d+)", line)
            if not match:
                extra.append(line)
                continue
            count = int(match.group(1))
            if count == 0:
                zero = True
                continue
            suffix = line[match.end():].strip()
            type_match = cls.subgroup_type_pattern.search(line)
            if type_match:
                key = "laboratory" if type_match.group(1).lower().startswith("лаб") else "practice"
                typed[key].append(count)
            else:
                has_label = bool(re.search(r"[А-Яа-яЁё]", suffix)) and "?" not in suffix
                unlabeled.append((count, has_label))
        result["zero"] = zero
        practice = typed["practice"][0] if typed["practice"] else None
        laboratory = typed["laboratory"][0] if typed["laboratory"] else None
        if len(typed["practice"]) > 1 or len(typed["laboratory"]) > 1:
            result["ambiguous"] = True
        if practice is not None or laboratory is not None:
            remaining = [count for count, _ in unlabeled]
            if practice is None and remaining:
                practice = remaining.pop(0)
            if laboratory is None and remaining:
                laboratory = remaining.pop(0)
            if remaining:
                result["extra"].append(", ".join(str(count) for count in remaining))
        elif unlabeled:
            counts = [count for count, _ in unlabeled]
            labelled = [flag for _, flag in unlabeled]
            if len(counts) == 1:
                practice = laboratory = counts[0]
            elif all(labelled):
                total = sum(counts)
                practice = laboratory = total
            elif len(set(counts)) == 1:
                practice = laboratory = counts[0]
            else:
                practice, laboratory = counts[0], counts[-1]
                result["ambiguous"] = True
            if any(labelled) and not all(labelled):
                result["ambiguous"] = True
        elif extra:
            result["unparsed"] = True
        if extra:
            result["extra"].extend(extra)
        if practice is None and laboratory is not None:
            result["ambiguous"] = True
        if laboratory is None and practice is not None:
            result["ambiguous"] = True
        result["practice"] = practice
        result["laboratory"] = laboratory
        if not practice and not laboratory and not zero:
            result["unparsed"] = True
        return result

    @staticmethod
    def _subgroup_count_for_lesson(subgroups: dict, lesson_type: str) -> int:
        if lesson_type == "лекция":
            return 1
        key = "laboratory" if lesson_type == "лабораторная" else "practice"
        return int(subgroups.get(key) or 1)

    @classmethod
    def _parse_teacher_cell(cls, raw_value: object) -> tuple[list[dict], dict]:
        """Extract all teacher names and their team/subgroup markers from a cell."""
        meta = {"cell_hint": None, "cell_label": None, "unparsed": False,
                "unresolved": [], "raw": None}
        if pd.isna(raw_value):
            return [], meta
        text = str(raw_value).strip()
        if not text or text.lower() == "nan":
            return [], meta
        meta["raw"] = text
        text = re.sub(r"\s+\.", ".", text)
        global_marker = None
        match = re.search(
            r"по\s+одной\s+(?:подгруппе|команде|группе)\s+каждому", text, re.IGNORECASE)
        if match:
            global_marker = (1, re.sub(r"\s+", " ", match.group(0)).strip())
        else:
            match = re.search(
                r"у\s+каждого\s+по\s+(\d+)\s+(?:групп\w*|команд\w*|подгрупп\w*)",
                text, re.IGNORECASE)
            if match:
                global_marker = (int(match.group(1)), re.sub(r"\s+", " ", match.group(0)).strip())
        segments = [segment.strip() for segment in cls.teacher_segment_pattern.split(text)
                    if segment.strip()]
        specs = []
        for segment in segments:
            names = cls.teacher_name_pattern.findall(segment)
            if not names:
                names = cls.teacher_full_name_pattern.findall(segment)
            marker = cls._find_team_marker(segment)
            if not names:
                if marker and marker["count"]:
                    if meta["cell_hint"] is None:
                        meta["cell_hint"] = marker["count"]
                        meta["cell_label"] = marker["label"]
                elif re.search(r"кто-?то|обсужда|кафедр|колес|вакант|нет\s+преподават",
                               segment, re.IGNORECASE):
                    meta["unresolved"].append(segment)
                continue
            start = len(specs)
            for name in names:
                specs.append({"name": cls._normalize_teacher_name(name),
                              "team_label": None, "team_count": None})
            if marker and marker["count"]:
                for spec in specs[start:]:
                    spec["team_label"] = marker["label"]
                    spec["team_count"] = marker["count"]
        if global_marker:
            for spec in specs:
                spec["team_label"] = global_marker[1]
                spec["team_count"] = global_marker[0]
        if not specs:
            meta["unparsed"] = True
        return specs, meta

    @classmethod
    def _find_team_marker(cls, segment: str) -> dict | None:
        for match in cls.team_marker_pattern.finditer(segment):
            if match.group("count"):
                return {"count": int(match.group("count")),
                        "label": re.sub(r"\s+", " ", match.group(0)).strip()}
        match = cls.parenthesized_count_pattern.search(segment)
        if match:
            return {"count": int(match.group(1)), "label": match.group(0).strip()}
        return None

    @classmethod
    def _normalize_teacher_name(cls, name: str) -> str:
        value = re.sub(r"\s+", " ", str(name)).strip(" ,;:-")
        value = value.translate(cls.latin_name_letters)
        value = re.sub(r"([А-ЯЁA-Z]\.)\s+(?=[А-ЯЁA-Z]\.)", r"\1", value)
        match = cls.initials_first_pattern.match(value)
        if match:
            first, second, surname = match.groups()
            value = f"{surname} {first}{second or ''}"
        match = cls.dotless_initials_pattern.match(value)
        if match:
            surname, first, second = match.groups()
            value = f"{surname} {first}.{second}."
        return value

    @classmethod
    def _split_teacher_names(cls, raw_value: object) -> list[str]:
        specs, _ = cls._parse_teacher_cell(raw_value)
        return [spec["name"] for spec in specs]

    @classmethod
    def _parse_teacher(cls, raw_value: object) -> str | None:
        names = cls._split_teacher_names(raw_value)
        return names[0] if names else None

    @staticmethod
    def _unique_names(names: list[str]) -> list[str]:
        return list(dict.fromkeys(name for name in names if name))

    @staticmethod
    def _name_key(value: str) -> str:
        """Case/ё-insensitive comparison key for names and disciplines."""
        text = str(value).replace("\xa0", " ").replace("ё", "е").replace("Ё", "Е")
        return re.sub(r"\s+", " ", text).strip().lower()

    surname_endings = (
        "ов", "ев", "ёв", "ин", "ын", "ский", "цкий", "ской", "цкой", "ий",
        "ая", "яя", "ой", "ова", "ева", "ёва", "ина", "ына", "ко", "ук",
        "юк", "ич", "енко", "чук", "як", "ец", "дзе", "швили", "ян", "янц",
    )

    @classmethod
    def _looks_like_surname(cls, token: str) -> bool:
        text = cls._name_key(token)
        return any(text.endswith(ending) for ending in cls.surname_endings)

    @classmethod
    def _parse_person_name(cls, name: str) -> tuple[str, tuple[str, ...]] | None:
        """Split a normalized teacher name into (surname, initials)."""
        value = cls._normalize_teacher_name(name)
        value = re.sub(r"\s+", " ", value).strip(" ,;:-")
        if not value:
            return None
        match = re.fullmatch(
            r"([А-ЯЁA-Z][а-яёa-z-]+)\s+([А-ЯЁA-Z])\.\s*(?:([А-ЯЁA-Z])\.?)?", value)
        if match:
            surname, first, second = match.groups()
            initials = (first,) + ((second,) if second else ())
            return surname, initials
        match = re.fullmatch(
            r"([А-ЯЁA-Z][а-яёa-z-]+)\s+([А-ЯЁA-Z][а-яёa-z-]+)"
            r"(?:\s+([А-ЯЁA-Z][а-яёa-z-]+))?", value)
        if not match:
            return None
        first, second, third = match.groups()
        if third:
            if cls._looks_like_surname(third) and not cls._looks_like_surname(first):
                surname, given, patronymic = third, first, second
            else:
                surname, given, patronymic = first, second, third
            return surname, (given[0], patronymic[0])
        if cls._looks_like_surname(second) and not cls._looks_like_surname(first):
            surname, given = second, first
        else:
            surname, given = first, second
        return surname, (given[0],)

    @staticmethod
    def _format_teacher_id(surname: str, initials: tuple[str, ...]) -> str:
        return f"{surname} {''.join(f'{letter}.' for letter in initials)}".strip()

    def _finalize_teacher_ids(self, courses: list[dict], impossible: list[dict],
                              wanted: list[dict]) -> None:
        """Collapse all raw name spellings into canonical "Фамилия И.О." ids."""
        raw_names = list(self._teachers)
        parsed = {}
        for name in raw_names:
            person = self._parse_person_name(name)
            if person is None:
                self._warnings.append(
                    f"ФИО {name!r}: не удалось выделить фамилию и инициалы; "
                    f"id оставлен без изменений")
                continue
            parsed[name] = person
        by_surname: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {}
        for name, (surname, initials) in parsed.items():
            by_surname.setdefault(self._name_key(surname), []).append((name, surname, initials))
        mapping: dict[str, str] = {}
        for items in by_surname.values():
            signatures: dict[tuple[str, ...], list[tuple[str, str]]] = {}
            for name, surname, initials in items:
                signatures.setdefault(initials, []).append((name, surname))
            merged: dict[tuple[str, ...], tuple[str, ...]] = {
                initials: initials for initials in signatures}
            for initials in signatures:
                if len(initials) != 1:
                    continue
                candidates = [other for other in signatures
                              if len(other) > 1 and other[:1] == initials[:1]]
                if len(candidates) == 1:
                    merged[initials] = candidates[0]
                elif len(candidates) > 1:
                    variant = ', '.join(
                        self._format_teacher_id(signatures[other][0][1], other)
                        for other in candidates)
                    self._warnings.append(
                        f"ФИО: {self._format_teacher_id(items[0][1], initials)!r} "
                        f"неоднозначно — подходят {variant}; id не объединён")
            for initials, variants in signatures.items():
                target = merged[initials]
                target_surname = signatures[target][0][1]
                canonical_id = self._format_teacher_id(target_surname, target)
                for name, _ in variants:
                    mapping[name] = canonical_id
                if target != initials:
                    sources = ', '.join(repr(name) for name, _ in variants)
                    self._warnings.append(
                        f"ФИО: варианты {sources} объединены в {canonical_id!r}")

        def rewrite(name: str) -> str:
            return mapping.get(name, name)

        for course in courses:
            course["teacher_ids"] = self._unique_names(
                [rewrite(name) for name in course.get("teacher_ids") or []])
            for instance in course.get("instances") or []:
                instance["teacher_ids"] = self._unique_names(
                    [rewrite(name) for name in instance.get("teacher_ids") or []])
        for entry in impossible + wanted:
            entry["teacher_id"] = rewrite(entry.get("teacher_id"))

        self._teachers = {}
        for name in raw_names:
            canonical_id = mapping.get(name, name)
            self._teachers.setdefault(canonical_id, {"id": canonical_id})

    @staticmethod
    def _course_label(course: dict) -> str:
        """Reconstruct the display name without storing it in the course."""
        discipline = course.get("discipline") or ""
        lesson_type = course.get("lesson_type") or ""
        if discipline and lesson_type:
            return f"{discipline} ({lesson_type})"
        return discipline or lesson_type

    def _missing_teacher_whitelisted(self, course: dict, whitelist: dict) -> bool:
        venue_types = set(whitelist.get("venue_types") or [])
        course_names = set(whitelist.get("course_names") or [])
        lesson_types = set(whitelist.get("lesson_types") or [])
        return (course.get("venue_type") in venue_types
                or self._course_label(course) in course_names
                or course.get("lesson_type") in lesson_types)

    def _apply_missing_teacher_policy(self, courses: list[dict]) -> None:
        """Apply soft/strict handling for courses without a teacher (п.17)."""
        config = self.config.get("missing_teacher", {})
        policy = str(config.get("policy") or "soft").lower()
        whitelist = config.get("whitelist") or {}
        missing = [course for course in courses
                   if not self._course_teacher_ids(course)
                   and not self._missing_teacher_whitelisted(course, whitelist)]
        if not missing:
            return
        if policy == "strict":
            details = "; ".join(
                f"{course['id']} ({self._course_label(course)!r}, "
                f"venue_type={course.get('venue_type')})"
                for course in missing)
            raise ParserValidationError(
                f"Курсы без преподавателя ({len(missing)}): {details}")
        template = config.get("placeholder") or "UNKNOWN:{course_id}"
        for course in missing:
            placeholder = template.format(course_id=course["id"])
            course["teacher_ids"] = [placeholder]
            for instance in course.get("instances") or []:
                instance["teacher_ids"] = [placeholder]
            self._teachers.setdefault(placeholder, {"id": placeholder})
            self._warnings.append(
                f"Курс {course['id']} ({self._course_label(course)!r}): "
                f"нет преподавателя; назначен {placeholder}")

    # --- Пункт 10: разбор пожеланий по времени -------------------------------

    def _wish_slot_ids(self, days: list[str] | None,
                       pairs: set[int] | list[int] | range) -> list[int]:
        day_set = {day.upper() for day in days} if days else None
        pair_set = set(pairs)
        return [slot["id"] for slot in self._time_slots
                if (day_set is None or slot["day"].upper() in day_set)
                and slot["slot_index"] in pair_set]

    def _pair_start_minutes(self) -> dict[int, int]:
        starts: dict[int, int] = {}
        for slot in self._time_slots:
            match = re.match(r"(\d{1,2}):(\d{2})", str(slot["time"]))
            if match:
                starts.setdefault(slot["slot_index"],
                                  int(match.group(1)) * 60 + int(match.group(2)))
        return starts

    def _pair_from_minutes(self, minutes: int, mode: str) -> int | None:
        ordered = sorted(self._pair_start_minutes().items())
        if mode == "ge":
            return next((index for index, start in ordered if start >= minutes), None)
        if mode == "gt":
            return next((index for index, start in ordered if start > minutes), None)
        if mode == "le":
            return next((index for index, start in reversed(ordered) if start <= minutes), None)
        if mode == "lt":
            return next((index for index, start in reversed(ordered) if start < minutes), None)
        return None

    def _wish_pair_value(self, match: re.Match) -> int | None:
        if "num" in match.groupdict() and match.group("num"):
            return int(match.group("num"))
        if "word" in match.groupdict() and match.group("word"):
            word = match.group("word")
            for prefix, value in self.pair_word_values.items():
                if word.startswith(prefix):
                    return value
            return None
        groups = match.groups()
        for value in groups:
            if value and value.isdigit():
                return int(value)
        for value in groups:
            if value:
                for prefix, number in self.pair_word_values.items():
                    if str(value).startswith(prefix):
                        return number
        return None

    def _wish_day_hits(self, text: str) -> list[dict]:
        hits: list[dict] = []
        for day, pattern in self.day_patterns:
            for match in pattern.finditer(text):
                hits.append({"day": day, "start": match.start(), "end": match.end()})
        hits.sort(key=lambda item: (item["start"], item["end"]))
        unique: list[dict] = []
        for hit in hits:
            if unique and hit["start"] == unique[-1]["start"]:
                continue
            unique.append(hit)
        return unique

    def _wish_days_for_clause(self, hits: list[dict], text: str,
                              previous_end: int, start: int, end: int) -> list[dict]:
        chunk_start = self._wish_chunk_start(text, start)
        boundary = max(previous_end, chunk_start)
        before = [hit for hit in hits
                  if boundary <= hit["end"] <= start and start - hit["end"] <= 60]
        if before:
            return before
        after = [hit for hit in hits
                 if hit["start"] >= end and hit["start"] - end <= 16
                 and re.fullmatch(r"\s*(?:(?:в|во|по|каждый|каждую)\s*)?\s*",
                                  text[end:hit["start"]], re.IGNORECASE)]
        return after

    @staticmethod
    def _wish_chunk_start(text: str, position: int) -> int:
        start = 0
        for separator in re.finditer(r"[,;]", text[:position]):
            start = separator.end()
        return start

    @staticmethod
    def _wish_is_continuation(chunk: str) -> bool:
        """True for a bare day/pair list that continues the previous clause."""
        head = chunk.strip().lower()
        if re.match(
                r"^\(?\s*(?:в|во|и)?\s*(?:пн|вт|ср|чт|пт|сб|"
                r"понедельник|вторник|сред|четверг|пятниц|суббот)",
                head):
            return True
        return bool(re.match(r"^\(?\s*\d{1,2}\s*(?:[-–и,]\s*\d{1,2}\s*)?"
                             r"(?:-?(?:я|й|ю|ой|ий|ая|ую))?\s*(?:пар|$)", head))

    def _wish_chunk_polarity(self, text: str, position: int,
                             segment_default: bool) -> bool:
        """Polarity of the comma-separated clause containing ``position``."""
        chunk_start = self._wish_chunk_start(text, position)
        chunk_end = len(text)
        separator = re.search(r"[,;]", text[position:])
        if separator:
            chunk_end = position + separator.start()
        prefix = text[chunk_start:position]
        chunk = text[chunk_start:chunk_end]

        last_negation = -1
        for match in self.wish_negation_pattern.finditer(prefix):
            last_negation = match.start()
        last_positive = -1
        for match in self.wish_positive_pattern.finditer(prefix):
            before = prefix[max(0, match.start() - 10):match.start()]
            if re.search(r"(?:^|\s)(?:не|нельзя)\s*$", before, re.IGNORECASE):
                continue
            last_positive = match.start()

        if last_negation < 0 and last_positive < 0:
            return segment_default if self._wish_is_continuation(chunk) else False
        return last_positive <= last_negation

    def _wish_segment_polarity(self, text: str) -> bool | None:
        has_negation = bool(self.wish_negation_pattern.search(text))
        positive = False
        for match in self.wish_positive_pattern.finditer(text):
            before = text[max(0, match.start() - 10):match.start()]
            if not re.search(r"(?:^|\s)(?:не|нельзя)\s*$", before, re.IGNORECASE):
                positive = True
                break
        if has_negation and positive:
            return None
        return has_negation

    @staticmethod
    def _wish_is_frequency(text: str, match: re.Match) -> bool:
        after = text[match.end():match.end() + 24]
        before = text[max(0, match.start() - 8):match.start()]
        if re.match(r"\s*(?:(?:в|через)\s+недел\w*|еженедельн|раз\s+в|"
                    r"подряд|сдвоен)", after, re.IGNORECASE):
            return True
        if re.search(r"\bпо\s*$", before, re.IGNORECASE):
            return True
        return False

    def _resolve_wish_teacher(self, raw_name: str,
                              course_teacher_ids: list[str]) -> str | None:
        normalized = self._normalize_teacher_name(raw_name)
        person = self._parse_person_name(normalized)
        if person is None:
            return None
        surname, initials = person
        exact = self._format_teacher_id(surname, initials)
        if exact in course_teacher_ids:
            return exact
        matches = []
        for teacher_id in course_teacher_ids:
            candidate = self._parse_person_name(teacher_id)
            if candidate is None:
                continue
            if self._name_key(candidate[0]) == self._name_key(surname) \
                    and candidate[1][:1] == initials[:1]:
                matches.append(teacher_id)
        return matches[0] if len(matches) == 1 else exact

    def _group_wish_teachers(self, segment: str) -> list[tuple[list[str], str]]:
        matches = list(self.teacher_name_pattern.finditer(segment))
        if not matches:
            return [([], segment)]
        groups: list[tuple[list[str], str]] = []
        names = [matches[0].group(0)]
        group_start = 0
        previous_end = matches[0].end()
        for match in matches[1:]:
            between = segment[previous_end:match.start()]
            if re.fullmatch(r"\s*(?:,|и|,?\s*и)\s*", between):
                names.append(match.group(0))
            else:
                groups.append((names, segment[group_start:match.start()]))
                names = [match.group(0)]
                group_start = match.start()
            previous_end = match.end()
        groups.append((names, segment[group_start:]))
        return groups

    def _wish_rule(self, fields: dict, scope: str, teacher_id: str | None,
                   soft: bool, source: str) -> dict:
        return {
            "scope": scope,
            "teacher_id": teacher_id,
            "soft": soft,
            "forbidden_days": list(fields["forbidden_days"]),
            "forbidden_slot_ids": sorted(fields["forbidden_slot_ids"]),
            "min_pair_index": fields["min_pair_index"],
            "max_pair_index": fields["max_pair_index"],
            "day_part": fields["day_part"],
            "max_pairs_per_day": fields["max_pairs_per_day"],
            "source": source,
        }

    def _parse_wish_fields(self, text: str, negative: bool) -> tuple[dict, list[str]]:
        fields = {
            "forbidden_days": [],
            "forbidden_slot_ids": set(),
            "min_pair_index": None,
            "max_pair_index": None,
            "day_part": None,
            "max_pairs_per_day": None,
            "_any_positive": False,
        }
        reasons: list[str] = []
        max_pair = max((slot["slot_index"] for slot in self._time_slots), default=6)
        clauses: list[dict] = []

        def add(kind: str, match: re.Match, priority: int, **extra) -> None:
            clauses.append({"kind": kind, "start": match.start(), "end": match.end(),
                            "match": match, "priority": priority, **extra})

        for match in self.max_pairs_day_pattern.finditer(text):
            add("max_pairs", match, 0)
        for match in self.pair_bound_pattern.finditer(text):
            add("pair_bound", match, 0)
        for match in self.time_clause_pattern.finditer(text):
            add("time", match, 0)
        for match in self.pair_count_word_pattern.finditer(text):
            add("pair_range", match, 1)
        for match in self.pair_range_pattern.finditer(text):
            add("pair_range", match, 1)
        for match in self.pair_word_pattern.finditer(text):
            add("pair_range", match, 1)
        for part, pattern in self.day_part_patterns:
            for match in pattern.finditer(text):
                add("day_part", match, 2, part=part)

        clauses.sort(key=lambda item: (item["start"], item["priority"]))
        chosen: list[dict] = []
        occupied: list[tuple[int, int]] = []
        for clause in clauses:
            overlaps = any(not (clause["end"] <= start or clause["start"] >= end)
                           for start, end in occupied)
            if clause["priority"] > 0 and overlaps:
                continue
            chosen.append(clause)
            occupied.append((clause["start"], clause["end"]))

        day_hits = self._wish_day_hits(text)
        used_days: set[int] = set()
        used_day_names: set[str] = set()
        previous_end = 0
        day_parts: list[str] = []

        def forbid(pairs: list[int] | range | set[int], days: list[str] | None) -> None:
            fields["forbidden_slot_ids"].update(self._wish_slot_ids(days, pairs))

        for clause in chosen:
            match = clause["match"]
            clause_negative = self._wish_chunk_polarity(text, clause["start"], negative)
            if not clause_negative:
                fields["_any_positive"] = True
            context = self._wish_days_for_clause(
                day_hits, text, previous_end, clause["start"], clause["end"])
            days = [hit["day"] for hit in context]
            for hit in context:
                used_days.add(id(hit))
                used_day_names.add(hit["day"])
            previous_end = max([clause["end"]] + [hit["end"] for hit in context])

            if clause["kind"] == "max_pairs":
                value = int(match.group(1))
                if days:
                    reasons.append("day_specific_max_pairs")
                else:
                    current = fields["max_pairs_per_day"]
                    fields["max_pairs_per_day"] = value if current is None \
                        else min(current, value)
                continue

            if clause["kind"] == "pair_bound":
                prep = match.group("prep")
                value = self._wish_pair_value(match)
                if value is None:
                    reasons.append("invalid_pair")
                    continue
                lexical_min = prep in {"не раньше", "не ранее"}
                lexical_max = prep in {"не позже", "не позднее"}
                if lexical_min:
                    if days:
                        reasons.append("preferred_day_pair")
                    else:
                        fields["min_pair_index"] = max(
                            fields["min_pair_index"] or 1, value)
                elif lexical_max:
                    if days:
                        reasons.append("preferred_day_pair")
                    else:
                        fields["max_pair_index"] = min(
                            fields["max_pair_index"] or max_pair, value)
                elif "после" in prep:
                    target = value + 1
                    if clause_negative:
                        forbid(range(max(1, target), max_pair + 1), days or None)
                    elif days:
                        reasons.append("preferred_day_pair")
                    else:
                        fields["min_pair_index"] = max(
                            fields["min_pair_index"] or 1, target)
                elif "до" in prep:
                    if clause_negative:
                        forbid(range(1, value + 1), days or None)
                    elif days:
                        reasons.append("preferred_day_pair")
                    else:
                        fields["max_pair_index"] = min(
                            fields["max_pair_index"] or max_pair, value)
                else:  # "с" / "начиная с"
                    if clause_negative:
                        forbid(range(value, max_pair + 1), days or None)
                    elif days:
                        reasons.append("preferred_day_pair")
                    else:
                        fields["min_pair_index"] = max(
                            fields["min_pair_index"] or 1, value)
                continue

            if clause["kind"] == "time":
                hour = int(match.group("hour"))
                minute = int(match.group("minute") or match.group("minute2"))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    reasons.append("invalid_time")
                    continue
                minutes = hour * 60 + minute
                prep = match.group("prep")
                lexical_min = prep in {"не раньше", "не ранее"}
                lexical_max = prep in {"не позже", "не позднее"}
                if lexical_min or prep == "с" and not clause_negative \
                        or prep == "начиная с" and not clause_negative:
                    target = self._pair_from_minutes(minutes, "ge")
                    if target is None:
                        reasons.append("time_outside_grid")
                    elif days:
                        reasons.append("preferred_day_slot")
                    else:
                        fields["min_pair_index"] = max(
                            fields["min_pair_index"] or 1, target)
                elif lexical_max or prep == "до" and not clause_negative:
                    target = self._pair_from_minutes(minutes, "le")
                    if target is None:
                        reasons.append("time_outside_grid")
                    elif days:
                        reasons.append("preferred_day_slot")
                    else:
                        fields["max_pair_index"] = min(
                            fields["max_pair_index"] or max_pair, target)
                elif prep == "после":
                    target = self._pair_from_minutes(minutes, "gt")
                    if target is None:
                        reasons.append("time_outside_grid")
                    elif clause_negative:
                        forbid(range(target, max_pair + 1), days or None)
                    elif days:
                        reasons.append("preferred_day_slot")
                    else:
                        fields["min_pair_index"] = max(
                            fields["min_pair_index"] or 1, target)
                elif prep in {"с", "начиная с"}:
                    target = self._pair_from_minutes(minutes, "ge")
                    if target is None:
                        reasons.append("time_outside_grid")
                    elif clause_negative:
                        forbid(range(target, max_pair + 1), days or None)
                    elif days:
                        reasons.append("preferred_day_slot")
                    else:
                        fields["min_pair_index"] = max(
                            fields["min_pair_index"] or 1, target)
                else:  # "до"
                    target = self._pair_from_minutes(minutes, "le")
                    if target is None:
                        reasons.append("time_outside_grid")
                    elif clause_negative:
                        forbid(range(1, target + 1), days or None)
                    elif days:
                        reasons.append("preferred_day_slot")
                    else:
                        fields["max_pair_index"] = min(
                            fields["max_pair_index"] or max_pair, target)
                continue

            if clause["kind"] == "pair_range":
                if self._wish_is_frequency(text, match):
                    continue
                if match.re is self.pair_count_word_pattern:
                    word = match.group(1)
                    value = self.pair_count_word_values.get(word)
                    if value is None:
                        reasons.append("invalid_pair")
                        continue
                    low, high = 1, value
                elif match.re is self.pair_word_pattern:
                    value = self._wish_pair_value(match)
                    if value is None:
                        reasons.append("invalid_pair")
                        continue
                    low = high = value
                else:
                    low = int(match.group(1))
                    high = int(match.group(2) or low)
                low = max(1, min(low, max_pair))
                high = max(low, min(high, max_pair))
                if clause_negative:
                    forbid(range(low, high + 1), days or None)
                elif days:
                    reasons.append("preferred_day_slot")
                else:
                    fields["min_pair_index"] = max(
                        fields["min_pair_index"] or 1, low)
                    fields["max_pair_index"] = min(
                        fields["max_pair_index"] or max_pair, high)
                continue

            if clause["kind"] == "day_part":
                part = clause["part"]
                ranges = {"morning": range(1, 4), "afternoon": range(4, max_pair + 1),
                          "evening": range(5, max_pair + 1)}
                if clause_negative:
                    forbid(ranges[part], days or None)
                elif days:
                    reasons.append("preferred_day")
                    day_parts.append(part)
                else:
                    day_parts.append(part)

        for hit in day_hits:
            if id(hit) in used_days:
                continue
            if self._wish_chunk_polarity(text, hit["start"], negative):
                if hit["day"] not in fields["forbidden_days"]:
                    fields["forbidden_days"].append(hit["day"])
            else:
                fields["_any_positive"] = True
                reasons.append("preferred_day")

        if day_parts:
            unique_parts = list(dict.fromkeys(day_parts))
            if len(unique_parts) > 1:
                reasons.append("ambiguous_day_part")
            else:
                fields["day_part"] = unique_parts[0]

        if fields["day_part"]:
            part_ranges = {"morning": (1, 3),
                           "afternoon": (4, max_pair),
                           "evening": (5, max_pair)}
            part_min, part_max = part_ranges[fields["day_part"]]
            if (fields["min_pair_index"] and fields["min_pair_index"] > part_max) \
                    or (fields["max_pair_index"] and fields["max_pair_index"] < part_min):
                reasons.append("empty_day_part")
                fields["day_part"] = None
                fields["min_pair_index"] = None
                fields["max_pair_index"] = None

        if fields["min_pair_index"] and fields["max_pair_index"] \
                and fields["min_pair_index"] > fields["max_pair_index"]:
            reasons.append("empty_pair_range")
            fields["min_pair_index"] = None
            fields["max_pair_index"] = None
        if len(set(fields["forbidden_days"])) >= len(self.days):
            reasons.append("all_days_forbidden")
            fields["forbidden_days"] = []
        if len(fields["forbidden_slot_ids"]) >= len(self._time_slots):
            reasons.append("all_slots_forbidden")
            fields["forbidden_slot_ids"] = set()
        return fields, reasons

    def _add_unmanaged_wish(self, course_id: str, text: str, reason: str,
                            unmanaged: list[dict]) -> None:
        item = {"text": text, "reason": reason}
        if item not in unmanaged:
            unmanaged.append(item)
        self._warn_once(
            f"unmanaged_wish: курс {course_id}: {text!r} (причина: {reason})")

    def _parse_wish_segment(self, course: dict, text: str, names: list[str],
                            rules: list[dict], unmanaged: list[dict]) -> None:
        polarity = self._wish_segment_polarity(text)
        segment_default = bool(polarity)
        fields, reasons = self._parse_wish_fields(text, segment_default)
        any_positive = fields.pop("_any_positive", False)
        soft = bool(self.wish_soft_pattern.search(text)) or any_positive \
            or polarity is not True
        has_fields = bool(fields["forbidden_days"] or fields["forbidden_slot_ids"]
                          or fields["min_pair_index"] or fields["max_pair_index"]
                          or fields["day_part"] or fields["max_pairs_per_day"])
        for reason in reasons:
            self._add_unmanaged_wish(course["id"], text, reason, unmanaged)
        if not has_fields:
            if not reasons:
                self._add_unmanaged_wish(course["id"], text, "no_rule", unmanaged)
            return

        course_teacher_ids = list(course.get("teacher_ids") or [])
        if not names:
            rules.append(self._wish_rule(fields, "course", None, soft, text))
            return

        matched: list[str] = []
        foreign: list[str] = []
        for name in names:
            teacher_id = self._resolve_wish_teacher(name, course_teacher_ids)
            if teacher_id is None:
                foreign.append(name)
            elif teacher_id in course_teacher_ids:
                if teacher_id not in matched:
                    matched.append(teacher_id)
            else:
                foreign.append(teacher_id)
        if matched:
            for teacher_id in matched:
                rules.append(self._wish_rule(fields, "teacher", teacher_id,
                                             soft, text))
        if foreign:
            self._add_unmanaged_wish(
                course["id"], text, f"foreign_teacher={foreign!r}", unmanaged)
        elif not matched:
            self._add_unmanaged_wish(course["id"], text, "teacher_not_found", unmanaged)

    def _finalize_time_wishes(self, courses: list[dict]) -> None:
        for course in courses:
            raw = course.get("time_wish_raw")
            rules: list[dict] = []
            unmanaged: list[dict] = []
            if raw:
                for segment in self.wish_segment_pattern.split(raw):
                    segment = re.sub(r"\s+", " ", segment).strip(" .;,")
                    if not segment:
                        continue
                    for names, group_text in self._group_wish_teachers(segment):
                        group_text = group_text.strip(" .;,")
                        if not group_text:
                            continue
                        group_names = [self._normalize_teacher_name(name)
                                       for name in names]
                        self._parse_wish_segment(course, group_text, group_names,
                                                 rules, unmanaged)
            course["time_wish_rules"] = rules
            course["time_wish_unmanaged"] = unmanaged
            for instance in course.get("instances") or []:
                teacher_ids = set(instance.get("teacher_ids") or [])
                instance["time_wish_rules"] = [
                    rule for rule in rules
                    if rule["scope"] == "course" or rule["teacher_id"] in teacher_ids]
                instance["time_wish_unmanaged"] = list(unmanaged)

    def _build_course(self, row: pd.Series, lesson_type: str, hours: float,
                      sheet_name: str) -> dict:
        group_ids = [x for x in re.split(r"[\s,;\n]+", str(row[self.group_column]).strip()) if x]
        self._course_count += 1
        course_id = f"c{self._course_count}"
        discipline = self._clean_discipline(row[self.discipline_column])
        name = f"{discipline} ({lesson_type})"
        specs, teacher_meta = self._parse_teacher_cell(row.get(self.teacher_columns[lesson_type]))
        if teacher_meta["unparsed"]:
            self._warnings.append(
                f"Лист {sheet_name!r}, {course_id}: не удалось выделить ФИО "
                f"из {teacher_meta['raw']!r}")
        for fragment in teacher_meta["unresolved"]:
            self._warnings.append(
                f"Лист {sheet_name!r}, {course_id}: неразобранный фрагмент ФИО {fragment!r}")
        subgroups = self._parse_subgroup_counts(row.get(self.subgroup_column))
        if subgroups["unparsed"]:
            self._warnings.append(
                f"Лист {sheet_name!r}, {course_id}: не удалось разобрать "
                f"«{self.subgroup_column}»: {subgroups['raw']!r}")
        if subgroups["ambiguous"]:
            self._warnings.append(
                f"Лист {sheet_name!r}, {course_id}: неоднозначные подгруппы "
                f"{subgroups['raw']!r}; принято practice={subgroups['practice']}, "
                f"laboratory={subgroups['laboratory']}")
        if subgroups["zero"]:
            self._warnings.append(
                f"Лист {sheet_name!r}, {course_id}: 0 подгрупп в {subgroups['raw']!r}; "
                f"трактуем как 1")
        if subgroups["extra"]:
            self._warnings.append(
                f"Лист {sheet_name!r}, {course_id}: лишний текст в подгруппах "
                f"{subgroups['extra']!r}")
        column_count = self._subgroup_count_for_lesson(subgroups, lesson_type)
        requirements, software_raw = self._parse_requirements(row, lesson_type)
        location = self._parse_location(row.get(self.location_column))
        ntk_raw = self._text_cell(row.get(self.ntk_column))
        delivery_raw = self._text_cell(row.get(self.delivery_model_column))
        time_wish_raw = self._text_cell(row.get(self.time_wish_column))
        comments_raw = self._text_cell(row.get(self.comments_column))
        venue_type = self._classify_venue(
            ntk_raw, delivery_raw, location["location_raw"],
            comments_raw, location["allowed_room_ids"], course_id)
        comment_hints = self._parse_comments_hints(comments_raw)
        instance_hints = self._filter_comment_hints(comment_hints, lesson_type)
        self._warn_comment_venue_conflict(
            course_id, lesson_type, venue_type, comment_hints)
        hours_rule = self._resolve_hours(hours, lesson_type, instance_hints)
        instances, subgroup_count = self._build_course_instances(
            course_id, name, lesson_type, specs, teacher_meta, column_count,
            group_ids, requirements, sheet_name)
        for instance in instances:
            instance["requirements"] = list(requirements)
            instance["needs_software"] = bool(software_raw)
            instance["software_raw"] = software_raw
            instance["location_raw"] = location["location_raw"]
            instance["allowed_room_ids"] = list(location["allowed_room_ids"])
            instance["same_room_as_course_id"] = None
            instance["same_room_as_instance_ids"] = []
            instance["venue_type"] = venue_type
            instance["time_wish_raw"] = time_wish_raw
            instance["time_wish_rules"] = []
            instance["time_wish_unmanaged"] = []
            instance["comments_raw"] = comments_raw
            instance["comments_hints"] = [dict(hint) for hint in instance_hints]
            instance["lessons_per_week"] = hours_rule["lessons_per_week"]
            instance["week_pattern"] = hours_rule["week_pattern"]
            instance["duration_slots"] = hours_rule["duration_slots"]
        teacher_ids = self._unique_names([spec["name"] for spec in specs])
        return {"id": course_id,
                "discipline": discipline,
                "lesson_type": lesson_type,
                "teacher_ids": teacher_ids,
                "group_ids": group_ids,
                "lessons_per_week": hours_rule["lessons_per_week"],
                "week_pattern": hours_rule["week_pattern"],
                "duration_slots": hours_rule["duration_slots"],
                "requirements": requirements,
                "needs_software": bool(software_raw),
                "software_raw": software_raw,
                "location_raw": location["location_raw"],
                "allowed_room_ids": location["allowed_room_ids"],
                "venue_type": venue_type,
                "time_wish_raw": time_wish_raw,
                "time_wish_rules": [],
                "time_wish_unmanaged": [],
                "comments_raw": comments_raw,
                "comments_hints": comment_hints,
                "same_room_as_course_id": None,
                "students_needed": None,
                "subgroup_count": subgroup_count,
                "subgroup_column_count": column_count,
                "subgroup_raw": subgroups["raw"],
                "instances": instances,
                "_course_number": row.get("Курс")}

    def _build_course_instances(self, course_id: str, name: str, lesson_type: str,
                                specs: list[dict], teacher_meta: dict, column_count: int,
                                group_ids: list[str], requirements: list[str],
                                sheet_name: str) -> tuple[list[dict], int]:
        teacher_count = len(specs)
        cell_hint = teacher_meta["cell_hint"] or 1
        has_team_marker = any(spec["team_count"] for spec in specs)
        expanded = []
        if has_team_marker:
            for spec in specs:
                count = spec["team_count"] or 1
                for team_index in range(1, count + 1):
                    expanded.append({**spec, "team_index": team_index})
        split_requested = len(expanded) > 1 or cell_hint > 1 or \
            (lesson_type != "лекция" and column_count > 1)
        if not split_requested:
            teacher_ids = self._unique_names([spec["name"] for spec in specs])
            if lesson_type == "лекция":
                lesson_kind = "lecture_stream"
            elif len(teacher_ids) > 1:
                lesson_kind = "co_taught"
                self._warnings.append(
                    f"Лист {sheet_name!r}, {course_id}: несколько преподавателей без "
                    f"маркера подгрупп/команд — создан один co_taught instance")
            else:
                lesson_kind = "single"
            instance = self._make_instance(
                course_id, name, lesson_type, lesson_kind, teacher_ids, group_ids,
                requirements, 1, 1, team_label=teacher_meta["cell_label"])
            return [instance], 1

        subgroup_count = max(1, column_count, cell_hint, len(expanded), teacher_count)
        if has_team_marker and column_count > 1 and len(expanded) != column_count:
            self._warnings.append(
                f"Лист {sheet_name!r}, {course_id}: маркеры команд дают "
                f"{len(expanded)} подгрупп, колонка — {column_count}; "
                f"принято {subgroup_count}")
        assignments = [[entry] for entry in expanded]
        if expanded and len(assignments) < subgroup_count:
            if assignments:
                self._warnings.append(
                    f"Лист {sheet_name!r}, {course_id}: маркеров хватает на "
                    f"{len(assignments)} из {subgroup_count} подгрупп; "
                    f"остальные заполнены циклически")
            if specs:
                index = 0
                while len(assignments) < subgroup_count:
                    spec = specs[index % len(specs)]
                    assignments.append([{**spec, "team_label": None,
                                         "team_count": None, "team_index": None}])
                    index += 1
            else:
                while len(assignments) < subgroup_count:
                    assignments.append([])
        if not expanded:
            if teacher_count == 0:
                assignments = [[] for _ in range(subgroup_count)]
                self._warnings.append(
                    f"Лист {sheet_name!r}, {course_id}: у подгрупп нет преподавателей")
            elif teacher_count >= subgroup_count:
                assignments = []
                for index in range(subgroup_count):
                    start = index * teacher_count // subgroup_count
                    end = (index + 1) * teacher_count // subgroup_count
                    assignments.append(specs[start:end])
            else:
                assignments = [[specs[index % teacher_count]]
                               for index in range(subgroup_count)]
                self._warnings.append(
                    f"Лист {sheet_name!r}, {course_id}: преподавателей ({teacher_count}) "
                    f"меньше, чем подгрупп ({subgroup_count}); назначены циклически")
        if lesson_type == "лекция":
            lesson_kind = "lecture_team"
        elif lesson_type == "практика":
            lesson_kind = "practice_subgroup"
        else:
            lesson_kind = "lab_subgroup"
        instances = []
        for index, assignment in enumerate(assignments[:subgroup_count], start=1):
            teacher_ids = self._unique_names([spec["name"] for spec in assignment])
            labels = [spec["team_label"] for spec in assignment if spec["team_label"]]
            if len(set(labels)) > 1:
                self._warnings.append(
                    f"Лист {sheet_name!r}, {course_id}: в instance {index} "
                    f"несколько маркеров команд: {labels!r}")
            team_label = labels[0] if labels else teacher_meta["cell_label"]
            single = assignment[0] if len(assignment) == 1 else None
            instances.append(self._make_instance(
                course_id, name, lesson_type, lesson_kind, teacher_ids, group_ids,
                requirements, index, subgroup_count,
                team_label=team_label,
                team_count=single["team_count"] if single else None,
                team_index=single.get("team_index") if single else None))
        return instances, subgroup_count

    @staticmethod
    def _make_instance(course_id: str, name: str, lesson_type: str, lesson_kind: str,
                       teacher_ids: list[str], group_ids: list[str],
                       requirements: list[str], subgroup_index: int, subgroup_count: int,
                       team_label: str | None = None, team_count: int | None = None,
                       team_index: int | None = None) -> dict:
        suffix = ""
        if subgroup_count > 1:
            if team_label:
                suffix = f", {team_label}"
                if team_index:
                    suffix += f" {team_index}"
            else:
                suffix = f", подгруппа {subgroup_index}/{subgroup_count}"
        return {"id": f"{course_id}_i{subgroup_index}",
                "course_id": course_id,
                "name": f"{name}{suffix}",
                "lesson_type": lesson_type,
                "lesson_kind": lesson_kind,
                "teacher_ids": teacher_ids,
                "group_ids": list(group_ids),
                "students_needed": None,
                "subgroup_index": subgroup_index,
                "subgroup_count": subgroup_count,
                "team_label": team_label,
                "team_count": team_count,
                "team_index": team_index,
                "requirements": list(requirements)}

    @staticmethod
    def _clean_discipline(value: object) -> str:
        if pd.isna(value):
            return ""
        text = str(value).replace("\xa0", " ")
        text = re.sub(r"[\t\r\n]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _normalize_discipline(cls, value: object) -> str:
        text = cls._clean_discipline(value)
        text = text.replace("ё", "е").replace("Ё", "Е").lower()
        text = re.sub(r"\(\s*(?:лекция|практика|лабораторная)\s*\)\s*$", "", text)
        text = re.sub(r"\s*[-–—]\s*", "-", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip(" .;:-")

    @staticmethod
    def _add_requirement(requirements: list[str], code: str) -> None:
        if code and code not in requirements:
            requirements.append(code)

    def _warn_once(self, message: str) -> None:
        if message not in self._warnings:
            self._warnings.append(message)

    def _warn_unsupported_pair(self, day: str, pair_number: int) -> None:
        message = f"{pair_number}-я пара игнорируется: слот отсутствует в сетке"
        policy = str(self.config.get("pair_grid", {}).get(
            "unsupported_pair_policy", "warn")).lower()
        if policy == "error":
            raise ParserValidationError(f"Анкета: {day}, {message}")
        self._warn_once(message)

    def _add_board_requirement(self, text: str, requirements: list[str]) -> None:
        text = str(text).lower()
        if "мелов" in text:
            self._add_requirement(requirements, "chalkboard")
        elif "маркер" in text:
            self._add_requirement(requirements, "whiteboard")
        elif "мультимедиа" in text and "доск" in text:
            self._add_requirement(requirements, "multimedia_board")
        elif "любая" in text or "доск" in text:
            self._add_requirement(requirements, "board")

    def _requirements_from_location(self, raw_value: object,
                                    requirements: list[str]) -> None:
        if pd.isna(raw_value):
            return
        text = self._name_key(str(raw_value))
        if not text:
            return
        if ("комп" in text and ("класс" in text or "компьютер" in text)) or "ивц" in text:
            self._add_requirement(requirements, "computer_class")
        if "проектор" in text:
            self._add_requirement(requirements, "screen")
        if "меловая" in text:
            self._add_requirement(requirements, "chalkboard")
        elif "маркерная" in text:
            self._add_requirement(requirements, "whiteboard")
        if "доск" in text and not any(
                code in requirements for code in
                ("board", "chalkboard", "whiteboard", "multimedia_board")):
            self._add_requirement(requirements, "board")
        if "интернет" in text:
            self._add_requirement(requirements, "internet")

    @staticmethod
    def _is_positive(value: object) -> bool:
        text = str(value).lower()
        if re.search(r"\bне\s+(?:нуж\w*|требу\w*)", text):
            return False
        return "да" in text or "нуж" in text

    def _parse_requirements(self, row: pd.Series, lesson_type: str) -> tuple[list[str], str | None]:
        requirements: list[str] = []
        software_raw = None
        if lesson_type == "лекция":
            value = str(row.get(self.multimedia_column, "")).lower()
            if self._is_positive(value):
                self._add_requirement(requirements, "multimedia_board")
            if "доск" in value:
                self._add_board_requirement(value, requirements)
        else:
            self._add_board_requirement(str(row.get(self.board_column, "")), requirements)
            projector = row.get(self.projector_column)
            if self._is_positive(projector):
                self._add_requirement(requirements, "screen")
            raw_software = row.get(self.software_column)
            if not pd.isna(raw_software):
                text = re.sub(r"\s+", " ", str(raw_software).replace("\xa0", " ")).strip()
                if text and text.lower() not in {"nan", "нет", "no", "-"}:
                    software_raw = text
                    self._add_requirement(requirements, "software")
                    low = text.lower()
                    if ("комп" in low and ("класс" in low or "компьютер" in low)) \
                            or "ивц" in low:
                        self._add_requirement(requirements, "computer_class")
                    if "интернет" in low:
                        self._add_requirement(requirements, "internet")
        self._requirements_from_location(row.get(self.location_column), requirements)
        return requirements, software_raw

    def _parse_location(self, raw_value: object) -> dict:
        """Extract room ids and keep the raw location for the solver fallback."""
        result = {"location_raw": None, "allowed_room_ids": [],
                  "same_room_as_course_id": None}
        if pd.isna(raw_value):
            return result
        text = re.sub(r"\s+", " ", str(raw_value).replace("\xa0", " ")).strip()
        if not text or text.lower() == "nan":
            return result
        result["location_raw"] = text
        allowed: list[str] = []
        unknown: list[str] = []
        for match in self.room_ref_pattern.finditer(text):
            room = self._normalize_room_id(match.group(0))
            if not room:
                continue
            if room not in self._room_ids and room[-1].isalpha() \
                    and room[:-1] in self._room_ids:
                # "418 и 422": the conjunction was read as a room letter.
                room = room[:-1]
            canonical = self._room_ids.get(room)
            if canonical is not None:
                if canonical not in allowed:
                    allowed.append(canonical)
            else:
                unknown.append(room)
        result["allowed_room_ids"] = allowed
        if unknown:
            self._warn_once(
                f"Место проведения {text!r}: аудитории {unknown!r} отсутствуют "
                f"в справочнике; сохранён location_raw")
        has_same_room = bool(self.same_room_pattern.search(text))
        if not allowed and not has_same_room and not unknown \
                and not self.generic_location_pattern.search(text):
            self._warn_once(
                f"Место проведения {text!r} не распознано; сохранён location_raw")
        return result

    @staticmethod
    def _text_cell(value: object) -> str | None:
        if pd.isna(value):
            return None
        text = re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()
        if not text or text.lower() == "nan":
            return None
        return text

    def _classify_venue(self, ntk: str | None, delivery: str | None,
                        location: str | None, comments: str | None,
                        allowed_room_ids: list[str], course_id: str) -> str:
        """Return room/online/external/unspecified for one course row (п.9)."""
        ntk_key = self._name_key(ntk or "")
        delivery_key = self._name_key(delivery or "")
        location_key = self._name_key(location or "")
        comments_key = self._name_key(comments or "")

        if "онлайн" in ntk_key:
            return "online"
        if "исключительно эо" in delivery_key:
            return "online"
        if location_key and self.venue_online_pattern.search(location_key) \
                and not self.venue_room_pattern.search(location_key):
            return "online"
        if location_key and self.venue_external_pattern.search(location_key) \
                and not self.venue_campus_pattern.search(location_key):
            return "external"
        if not location_key and comments_key \
                and self.venue_comment_external_pattern.search(comments_key):
            return "external"
        if allowed_room_ids:
            return "room"
        if location_key and self.same_room_pattern.search(location_key):
            return "room"
        if location_key and self.venue_room_pattern.search(location_key):
            return "room"
        if location_key and self.room_ref_pattern.search(location_key):
            return "room"
        if location_key and self.venue_no_room_pattern.search(location_key):
            return "unspecified"
        if ntk_key.strip() == "нк":
            self._warn_once(
                f"Курс {course_id}: НТК='НК' не интерпретирован; "
                f"venue_type=unspecified")
            return "unspecified"
        if location_key:
            self._warn_once(
                f"Курс {course_id}: место {location!r} не распознано; "
                f"venue_type=unspecified")
            return "unspecified"
        return "room"

    @staticmethod
    def _comment_scope(text_key: str) -> str:
        has_lecture = "лекц" in text_key
        has_practice = "практик" in text_key or re.search(r"\bпракт\b", text_key)
        has_lab = "лаборатор" in text_key
        if has_lab and not has_lecture and not has_practice:
            return "лабораторная"
        if has_practice and not has_lecture and not has_lab:
            return "практика"
        if has_lecture and not has_practice and not has_lab:
            return "лекция"
        return "all"

    @staticmethod
    def _iso_date(value: str) -> str | None:
        parts = value.split(".")
        if len(parts) != 3:
            return None
        try:
            day, month, year = (int(part) for part in parts)
        except ValueError:
            return None
        if len(parts[2]) == 2:
            year += 2000
        if not (1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2100):
            return None
        return f"{year:04d}-{month:02d}-{day:02d}"

    def _comment_duration_slots(self, text_key: str) -> float | None:
        if self.comment_duration_half_pattern.search(text_key):
            return 1.5
        hours = self.comment_duration_hours_pattern.search(text_key)
        if hours:
            value = float(hours.group(1).replace(",", "."))
            slots = value / 2
            if slots >= 1:
                return slots
        pairs = self.comment_duration_pairs_pattern.search(text_key)
        if pairs:
            word = pairs.group(1)
            return float(self.pair_count_word_values.get(word, 0) or word)
        if self.comment_duration_double_pattern.search(text_key):
            return 2.0
        return None

    def _comment_week_ranges(self, text_key: str) -> list[list[int]]:
        ranges: list[list[int]] = []
        if "недел" in text_key:
            for start, end in self.comment_week_chain_pattern.findall(text_key):
                ranges.append([int(start), int(end)])
        for pattern in self.comment_week_range_patterns:
            for start, end in pattern.findall(text_key):
                ranges.append([int(start), int(end)])
        listed = self.comment_week_list_pattern.search(text_key)
        if listed:
            for token in re.split(r"[,;]+|\bи\b", listed.group(1)):
                token = token.strip()
                if not token:
                    continue
                match = re.fullmatch(r"(\d{1,2})\s*[-–]\s*(\d{1,2})", token)
                if match:
                    ranges.append([int(match.group(1)), int(match.group(2))])
                    continue
                match = re.fullmatch(r"(\d{1,2})", token)
                if match:
                    value = int(match.group(1))
                    ranges.append([value, value])
        unique: list[list[int]] = []
        for item in sorted(ranges):
            if item not in unique:
                unique.append(item)
        return unique

    def _parse_comments_hints(self, raw: str | None) -> list[dict]:
        """Extract duration/week/online hints from the comments column (п.11)."""
        if not raw:
            return []
        hints: list[dict] = []
        for segment in self.wish_segment_pattern.split(raw):
            text = re.sub(r"\s+", " ", segment).strip(" .;,")
            if not text:
                continue
            text_key = self._name_key(text)
            hint = {
                "scope": self._comment_scope(text_key),
                "online": bool(self.comment_online_pattern.search(text_key)),
                "duration_slots": self._comment_duration_slots(text_key),
                "period_start": None,
                "period_end": None,
                "week_ranges": self._comment_week_ranges(text_key),
                "semester_half": None,
                "source": text,
            }
            period = self.comment_period_pattern.search(text_key)
            if period:
                hint["period_start"] = self._iso_date(period.group(1))
                hint["period_end"] = self._iso_date(period.group(2))
            half = self.comment_semester_half_pattern.search(text_key)
            if half:
                hint["semester_half"] = 1 if half.group(1) == "перв" else 2
            if not any((hint["online"], hint["duration_slots"] is not None,
                        hint["period_start"], hint["week_ranges"],
                        hint["semester_half"])):
                continue
            hints.append(hint)
            if hint["period_start"] and hint["period_end"]:
                self._warn_once(
                    f"comments_hint: {text!r}: период "
                    f"{hint['period_start']}..{hint['period_end']}; "
                    f"недельная сетка не меняется")
            if hint["duration_slots"] is not None and hint["duration_slots"] != 1:
                self._warn_once(
                    f"comments_hint: {text!r}: duration_slots="
                    f"{hint['duration_slots']:g}")
            if hint["week_ranges"]:
                self._warn_once(
                    f"comments_hint: {text!r}: недели {hint['week_ranges']!r}")
        return hints

    @staticmethod
    def _filter_comment_hints(hints: list[dict], lesson_type: str) -> list[dict]:
        return [dict(hint) for hint in hints
                if hint["scope"] == "all" or hint["scope"] == lesson_type]

    def _warn_comment_venue_conflict(self, course_id: str, lesson_type: str,
                                     venue_type: str, hints: list[dict]) -> None:
        if venue_type == "online":
            return
        for hint in hints:
            if hint["online"] and hint["scope"] in {"all", lesson_type}:
                self._warn_once(
                    f"venue_conflict: курс {course_id}: комментарий говорит об "
                    f"онлайн-формате, но venue_type={venue_type}")

    def _register_teachers_and_groups(self, course: dict, counts: list[int] | None,
                                      sheet_name: str) -> None:
        teacher_ids = list(course.get("teacher_ids") or [])
        for instance in course.get("instances") or []:
            teacher_ids.extend(instance.get("teacher_ids") or [])
        for teacher in self._unique_names(teacher_ids):
            self._teachers.setdefault(teacher, {"id": teacher})
        observations = self._group_size_observations(course["group_ids"], counts)
        for group_id in course["group_ids"]:
            self._groups.setdefault(group_id, {"id": group_id, "size": None})
            self._group_size_sources.setdefault(group_id, sheet_name)
            size = observations.get(group_id)
            if size is not None:
                self._group_sizes[group_id] = max(self._group_sizes.get(group_id, 0), size)

    def _finalize_group_sizes(self) -> None:
        for group_id, group in self._groups.items():
            size = self._group_sizes.get(group_id)
            if size is None:
                size = self.default_group_size
                sheet_name = self._group_size_sources.get(group_id)
                where = f" (лист {sheet_name!r})" if sheet_name else ""
                self._warnings.append(
                    f"Группа {group_id}: не удалось определить «{self.students_column}»{where}; "
                    f"использован default_group_size={self.default_group_size}")
            group["size"] = size

    def _finalize_course_instances(self, courses: list[dict]) -> None:
        for course in courses:
            total = sum(self._groups[group_id]["size"]
                        for group_id in course["group_ids"] if group_id in self._groups)
            course["students_needed"] = total
            subgroup_count = max(1, int(course.get("subgroup_count") or 1))
            instances = course.get("instances") or []
            if len(instances) != subgroup_count:
                self._warnings.append(
                    f"Курс {course['id']}: создано {len(instances)} instances, "
                    f"ожидалось {subgroup_count}")
            per_instance = max(1, math.ceil(total / subgroup_count))
            for index, instance in enumerate(instances, start=1):
                instance["students_needed"] = per_instance
                instance["subgroup_index"] = index
                instance["subgroup_count"] = subgroup_count
            self._validate_course_instances(course)

    def _validate_course_instances(self, course: dict) -> None:
        problems = []
        instances = course.get("instances") or []
        subgroup_count = int(course.get("subgroup_count") or 1)
        if not instances:
            problems.append("нет instances")
        if len(instances) != subgroup_count:
            problems.append("количество instances не совпадает с subgroup_count")
        indices = [instance.get("subgroup_index") for instance in instances]
        if sorted(indices) != list(range(1, len(instances) + 1)):
            problems.append(f"некорректные subgroup_index: {indices!r}")
        for instance in instances:
            for teacher_id in instance.get("teacher_ids") or []:
                if teacher_id not in self._teachers:
                    problems.append(f"teacher_id {teacher_id!r} отсутствует в teachers")
            needed = instance.get("students_needed")
            if needed is None or needed < 1:
                problems.append(f"{instance.get('id')}: students_needed < 1")
        for problem in problems:
            self._warnings.append(f"Курс {course['id']}: {problem}")

    @staticmethod
    def _normalize_group_key(value: object) -> str:
        return re.sub(r"\s+", "", str(value)).upper()

    @classmethod
    def _course_group_keys(cls, course: dict) -> set[str]:
        return {cls._normalize_group_key(group) for group in course.get("group_ids") or []}

    @staticmethod
    def _course_teacher_ids(course: dict) -> set[str]:
        teacher_ids = set(course.get("teacher_ids") or [])
        for instance in course.get("instances") or []:
            teacher_ids.update(instance.get("teacher_ids") or [])
        return teacher_ids

    @classmethod
    def _desire_instance_ids(cls, course: dict, teacher_id: str) -> list[str]:
        instances = course.get("instances") or []
        matched = [instance["id"] for instance in instances
                   if teacher_id in (instance.get("teacher_ids") or [])]
        return matched or [instance["id"] for instance in instances]

    def _match_desire(self, entry: dict, index: dict) -> dict:
        course_name = str(entry.get("course_name") or "")
        match = re.search(r"\((лекция|практика|лабораторная)\)\s*$",
                          course_name, re.IGNORECASE)
        lesson_type = match.group(1).lower() if match else ""
        discipline_key = self._normalize_discipline(course_name)
        teacher_id = entry.get("teacher_id")
        group_keys = {self._normalize_group_key(group)
                      for group in entry.get("group_ids") or []}
        pool = list(index.get((lesson_type, discipline_key), []))
        teacher_pool = [course for course in pool
                        if teacher_id in self._course_teacher_ids(course)]
        group_pool = [course for course in teacher_pool
                      if self._course_group_keys(course) & group_keys]

        def describe(courses: list[dict]) -> list[str]:
            return [course["id"] for course in courses]

        def instance_ids(courses: list[dict]) -> list[str]:
            ids = []
            for course in courses:
                for instance_id in self._desire_instance_ids(course, teacher_id):
                    if instance_id not in ids:
                        ids.append(instance_id)
            return ids

        if len(group_pool) == 1:
            course = group_pool[0]
            return {"course_id": course["id"], "course_ids": [course["id"]],
                    "instance_ids": self._desire_instance_ids(course, teacher_id),
                    "match_type": "exact"}
        if len(group_pool) > 1:
            self._warnings.append(
                f"Анкета: {teacher_id!r}, {course_name!r}, группы "
                f"{entry.get('group_ids')!r}: несколько курсов {describe(group_pool)!r}; "
                f"course_id не задан")
            return {"course_id": None, "course_ids": describe(group_pool),
                    "instance_ids": instance_ids(group_pool),
                    "match_type": "ambiguous"}
        if teacher_pool:
            self._warnings.append(
                f"Анкета: {teacher_id!r}, {course_name!r}, группы "
                f"{entry.get('group_ids')!r}: преподаватель и дисциплина совпали, "
                f"но группы не пересеклись ({describe(teacher_pool)!r})")
            return {"course_id": None, "course_ids": describe(teacher_pool),
                    "instance_ids": instance_ids(teacher_pool),
                    "match_type": "no_group_overlap"}
        self._warnings.append(
            f"Анкета: {teacher_id!r}, {course_name!r}, группы "
            f"{entry.get('group_ids')!r}: курс не найден; используются поля fallback")
        return {"course_id": None, "course_ids": [], "instance_ids": [],
                "match_type": "none"}

    def _link_desires_to_courses(self, courses: list[dict], impossible: list[dict],
                                 wanted: list[dict]) -> None:
        index: dict[tuple[str, str], list[dict]] = {}
        for course in courses:
            discipline = course.get("discipline") or self._course_label(course)
            key = (course.get("lesson_type", ""), self._normalize_discipline(discipline))
            index.setdefault(key, []).append(course)
        cache: dict[tuple, dict] = {}
        for entry in impossible + wanted:
            cache_key = (entry.get("teacher_id"), entry.get("course_name"),
                         tuple(entry.get("group_ids") or []))
            if cache_key not in cache:
                cache[cache_key] = self._match_desire(entry, index)
            link = cache[cache_key]
            entry["course_id"] = link["course_id"]
            entry["course_ids"] = list(link["course_ids"])
            entry["instance_ids"] = list(link["instance_ids"])
            entry["match_type"] = link["match_type"]

    def _resolve_same_room_links(self, courses: list[dict]) -> None:
        lectures: dict[str, list[dict]] = {}
        for course in courses:
            if course.get("lesson_type") != "лекция":
                continue
            discipline = course.get("discipline") or self._course_label(course)
            lectures.setdefault(self._normalize_discipline(discipline), []).append(course)
        for course in courses:
            if course.get("lesson_type") == "лекция":
                continue
            raw = course.get("location_raw")
            if not raw or not self.same_room_pattern.search(str(raw)):
                continue
            discipline = course.get("discipline") or self._course_label(course)
            discipline_key = self._normalize_discipline(discipline)
            group_keys = self._course_group_keys(course)
            best: list[dict] = []
            best_score = 0
            for lecture in lectures.get(discipline_key, []):
                score = len(group_keys & self._course_group_keys(lecture))
                if score > best_score:
                    best, best_score = [lecture], score
                elif score == best_score and score > 0:
                    best.append(lecture)
            if best_score <= 0:
                self._warnings.append(
                    f"Курс {course['id']}: «вместе с лекциями», но лекция по "
                    f"дисциплине {discipline!r} и группам не найдена; "
                    f"same_room_as_course_id=null")
                continue
            if len(best) > 1:
                self._warnings.append(
                    f"Курс {course['id']}: «вместе с лекциями» — несколько лекционных "
                    f"курсов {[lecture['id'] for lecture in best]!r}; связь не задана")
                continue
            lecture = best[0]
            lecture_instances = lecture.get("instances") or []
            instance_ids = [instance["id"] for instance in lecture_instances]
            overlapping = [
                instance["id"] for instance in lecture_instances
                if group_keys & self._course_group_keys(instance)]
            if overlapping:
                instance_ids = overlapping
            if len(instance_ids) > 1:
                self._warnings.append(
                    f"Курс {course['id']}: «вместе с лекциями» — несколько лекционных "
                    f"instances {instance_ids!r}; связь задана со всеми")
            course["same_room_as_course_id"] = lecture["id"]
            for instance in course.get("instances") or []:
                instance["same_room_as_course_id"] = lecture["id"]
                instance["same_room_as_instance_ids"] = list(instance_ids)

    def _parse_teachers_desires(self, df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
        slots = {(slot["day"].lower(), slot["slot_index"]): slot["id"] for slot in self._time_slots}
        cannot_cols = [c for c in df.columns if "Не могу" in str(c)]
        want_cols = [c for c in df.columns if "Хочу" in str(c)]
        room_cols = [c for c in df.columns if "Что должно быть в аудитории" in str(c)]

        def selected_slots(row: pd.Series, columns: list[str], prefix: str) -> list[int]:
            selected = set()
            for column in columns:
                value = row.get(column)
                if pd.isna(value) or value is False or str(value).strip().lower() in {"", "false", "нет", "0"}:
                    continue
                parts = [part.strip() for part in str(column).replace(prefix, "", 1).split("/")]
                if len(parts) < 2:
                    continue
                day = parts[0].replace("во ", "").replace("в ", "").strip().lower()
                digits = re.search(r"\d+", parts[1])
                if not digits:
                    continue
                pair_number = int(digits.group())
                slot_id = slots.get((day, pair_number))
                if slot_id is not None:
                    selected.add(slot_id)
                else:
                    self._warn_unsupported_pair(day, pair_number)
            return sorted(selected)

        impossible, wanted = [], []
        for _, row in df.iterrows():
            teachers = self._split_teacher_names(row.get("ФИО"))
            if not teachers:
                continue
            course = str(row.get("Какую дисциплину вы ведете?", "")).strip()
            lesson_type = str(row.get("Тип дисциплины", "")).strip().lower()
            course_name = f"{course} ({lesson_type})" if course else ""
            raw_groups = str(row.get("Укажите группы, у которых вы ведете эту дисциплину", ""))
            group_ids = [group.strip() for group in raw_groups.split(",") if group.strip() and group.lower() != "nan"]
            blocked = selected_slots(row, cannot_cols, "Не могу")
            preferred = selected_slots(row, want_cols, "Хочу")
            raw_room = row.get("Аудитория")
            fixed_room = None
            if pd.notna(raw_room) and str(raw_room).strip():
                raw_text = re.sub(r"\s+", " ", str(raw_room).replace("\xa0", " ")).strip()
                normalized = self._normalize_room_id(raw_text)
                if normalized in self._room_ids:
                    fixed_room = self._room_ids[normalized]
                else:
                    fixed_room = raw_text
                    self._warnings.append(
                        f"Анкета: аудитория {raw_text!r} отсутствует в справочнике; "
                        f"fixed_room сохранён как есть")
            raw_type = row.get("Вид аудитории")
            if pd.isna(raw_type) or str(raw_type).strip().lower() in {
                    "", "nan", "без разницы", "любая", "нет"}:
                room_type = None
            else:
                room_type = self._normalize_room_type(raw_type)
            room_requirements = []
            for column in room_cols:
                value = row.get(column)
                if pd.isna(value) or str(value).strip().lower() in {"", "false", "нет"}:
                    continue
                label = str(column).split(" / ")[-1]
                code = self.room_requirement_labels.get(self._name_key(label))
                if code is None:
                    code = self._name_key(label)
                    self._warnings.append(
                        f"Анкета: неизвестное требование к аудитории {label!r}")
                self._add_requirement(room_requirements, code)
            capacity_raw = row.get("Вместимость")
            capacity = None
            if pd.notna(capacity_raw):
                digits = re.search(r"\d+", str(capacity_raw))
                capacity = int(digits.group()) if digits else None
            for teacher in teachers:
                impossible.append({"teacher_id": teacher, "course_name": course_name,
                                   "group_ids": group_ids, "timeslots_ids": blocked,
                                   "comments": row.get("Другие комментарии")})
                wanted.append({"teacher_id": teacher, "course_name": course_name, "group_ids": group_ids,
                               "fixed_room": fixed_room, "room_type": room_type,
                               "capacity": capacity,
                               "room_requirements": list(room_requirements),
                               "timeslots_ids": preferred, "comments": row.get("Другие комментарии")})
                self._teachers.setdefault(teacher, {"id": teacher})
        return impossible, wanted

    def _parse_pe_slots(self) -> dict[int, list[int]]:
        """Read the IENIM column of the PE sheet and map it to real timeslot ids."""
        if self.pe_sheet is None:
            return {}
        try:
            df = pd.read_excel(self.courses_file, sheet_name=self.pe_sheet, header=None)
        except Exception as error:
            raise ParserValidationError(
                f"Лист {self.pe_sheet!r} недоступен: {error}") from error

        header_row = None
        for row_index in range(min(30, len(df))):
            values = {self._name_key(value) for value in df.iloc[row_index].tolist()
                      if not pd.isna(value)}
            if "день недели" in values and "пара" in values:
                header_row = row_index
                break
        if header_row is None:
            raise ParserValidationError(
                f"Лист {self.pe_sheet!r}: не найдена строка с «День недели» и «Пара»")

        target = self._name_key(self.pe_institute)
        institute_column = None
        institute_row = None
        for row_index in range(header_row, min(header_row + 4, len(df))):
            for column_index, value in enumerate(df.iloc[row_index].tolist()):
                if not pd.isna(value) and self._name_key(value) == target:
                    institute_column = column_index
                    institute_row = row_index
                    break
            if institute_column is not None:
                break
        if institute_column is None:
            raise ParserValidationError(
                f"Лист {self.pe_sheet!r}: не найдена колонка института "
                f"{self.pe_institute!r}")

        day_lookup = {self._name_key(day): day for day in self.days}
        slot_lookup = {(slot["day"].upper(), slot["slot_index"]): slot["id"]
                       for slot in self._time_slots}
        slots: dict[int, list[int]] = {}
        current_day = None
        data_start = (institute_row if institute_row is not None else header_row) + 1
        for row_index in range(data_start, len(df)):
            day_value = df.iat[row_index, 0]
            if pd.notna(day_value) and str(day_value).strip():
                day_key = self._name_key(day_value)
                if day_key not in day_lookup:
                    raise ParserValidationError(
                        f"Лист {self.pe_sheet!r}, строка {row_index + 1}: "
                        f"неизвестный день недели {day_value!r}")
                current_day = day_lookup[day_key]

            year_value = df.iat[row_index, institute_column]
            if pd.isna(year_value) or str(year_value).strip().lower() in {"", "nan"}:
                continue
            if current_day is None:
                raise ParserValidationError(
                    f"Лист {self.pe_sheet!r}, строка {row_index + 1}: "
                    f"год обучения указан без дня недели")

            pair_value = df.iat[row_index, 1]
            try:
                pair_number = int(float(str(pair_value).strip()))
                if not float(str(pair_value).strip()).is_integer():
                    raise ValueError
            except (TypeError, ValueError):
                raise ParserValidationError(
                    f"Лист {self.pe_sheet!r}, строка {row_index + 1}: "
                    f"некорректный номер пары {pair_value!r}") from None
            slot_id = slot_lookup.get((current_day.upper(), pair_number))
            if slot_id is None:
                raise ParserValidationError(
                    f"Лист {self.pe_sheet!r}, строка {row_index + 1}: "
                    f"пара {pair_number} для {current_day} отсутствует в time_slots")

            try:
                year_value_float = float(str(year_value).strip())
                if not year_value_float.is_integer():
                    raise ValueError
                year = int(year_value_float)
            except (TypeError, ValueError):
                raise ParserValidationError(
                    f"Лист {self.pe_sheet!r}, строка {row_index + 1}: "
                    f"некорректный год обучения {year_value!r}") from None
            if not 1 <= year <= 6:
                raise ParserValidationError(
                    f"Лист {self.pe_sheet!r}, строка {row_index + 1}: "
                    f"год обучения {year} вне диапазона 1..6")
            year_slots = slots.setdefault(year, [])
            if slot_id in year_slots:
                raise ParserValidationError(
                    f"Лист {self.pe_sheet!r}: дубликат слота {slot_id} "
                    f"для {year} курса")
            year_slots.append(slot_id)

        if not slots:
            raise ParserValidationError(
                f"Лист {self.pe_sheet!r}: для {self.pe_institute!r} не найдено "
                f"ни одной пары")
        for year, year_slots in slots.items():
            slots[year] = sorted(year_slots)
        return slots

    @staticmethod
    def _fixed_course_year(course: dict) -> int:
        raw_value = course.get("_course_number")
        try:
            if pd.isna(raw_value):
                raise ValueError
            value = float(str(raw_value).strip())
            if not value.is_integer():
                raise ValueError
            return int(value)
        except (TypeError, ValueError):
            raise ParserValidationError(
                f"fixed_schedules: курс {course.get('id')!r} "
                f"({Importer._course_label(course)!r}): не удалось определить год обучения "
                f"из {raw_value!r}") from None

    def _generate_fixed_schedules(self, courses: list[dict]) -> list[dict]:
        """Apply the explicit PE slots from the PE sheet by study year (п.12)."""
        if self.pe_sheet is None:
            return []
        fixed = []
        for course in courses:
            if self._course_label(course) not in self.fixed_course_names:
                continue
            year = self._fixed_course_year(course)
            slot_ids = self._pe_slots.get(year)
            if not slot_ids:
                raise ParserValidationError(
                    f"fixed_schedules: курс {course['id']!r} "
                    f"({self._course_label(course)!r}, {year} курс): "
                    f"на листе {self.pe_sheet!r} нет слотов для этого года")
            fixed.append({"course_id": course["id"],
                          "timeslots_ids": list(slot_ids)})
        return fixed

    def _validate_fixed_schedules(self, courses: list[dict],
                                  fixed: list[dict]) -> None:
        """Fail before the solver if the time grid or fixed slots are inconsistent."""
        known: dict[int, dict] = {}
        grid: set[tuple[str, int]] = set()
        for slot in self._time_slots:
            slot_id = slot.get("id")
            if isinstance(slot_id, bool) or not isinstance(slot_id, int):
                raise ParserValidationError(
                    f"time_slots: некорректный id {slot_id!r}")
            if slot_id in known:
                raise ParserValidationError(
                    f"time_slots: дубликат id {slot_id}")
            day = str(slot.get("day", "")).upper()
            if day not in self.days:
                raise ParserValidationError(
                    f"time_slots: id {slot_id}: неизвестный день {slot.get('day')!r}")
            pair_index = slot.get("slot_index")
            if isinstance(pair_index, bool) or not isinstance(pair_index, int):
                raise ParserValidationError(
                    f"time_slots: id {slot_id}: некорректный номер пары "
                    f"{pair_index!r}")
            if (day, pair_index) in grid:
                raise ParserValidationError(
                    f"time_slots: дубликат ячейки {day}, пара {pair_index}")
            grid.add((day, pair_index))
            known[slot_id] = slot
        if not known:
            raise ParserValidationError("time_slots пуст")
        if sorted(known) != list(range(1, len(known) + 1)):
            raise ParserValidationError(
                f"time_slots: id должны идти подряд 1..{len(known)}")

        if self.pe_sheet is None:
            return

        course_by_id = {course["id"]: course for course in courses}
        expected = {course["id"] for course in courses
                    if self._course_label(course) in self.fixed_course_names}
        seen: set[str] = set()
        for entry in fixed:
            course_id = entry.get("course_id")
            if course_id not in course_by_id:
                raise ParserValidationError(
                    f"fixed_schedules: неизвестный course_id {course_id!r}")
            if course_id in seen:
                raise ParserValidationError(
                    f"fixed_schedules: дубликат course_id {course_id!r}")
            seen.add(course_id)
            course = course_by_id[course_id]
            if self._course_label(course) not in self.fixed_course_names:
                raise ParserValidationError(
                    f"fixed_schedules: курс {course_id!r} "
                    f"({self._course_label(course)!r}) не является фиксируемым")
            slot_ids = entry.get("timeslots_ids")
            if not isinstance(slot_ids, list) or not slot_ids:
                raise ParserValidationError(
                    f"fixed_schedules: курс {course_id!r}: пустой timeslots_ids")
            if len(slot_ids) != len(set(slot_ids)):
                raise ParserValidationError(
                    f"fixed_schedules: курс {course_id!r}: дубликаты "
                    f"timeslots_ids {slot_ids!r}")
            for slot_id in slot_ids:
                if isinstance(slot_id, bool) or not isinstance(slot_id, int):
                    raise ParserValidationError(
                        f"fixed_schedules: курс {course_id!r}: "
                        f"timeslot id {slot_id!r} не является целым числом")
                if slot_id not in known:
                    year = course.get("_course_number")
                    raise ParserValidationError(
                        f"fixed_schedules: курс {course_id!r} "
                        f"({self._course_label(course)!r}, {year} курс) ссылается на "
                        f"несуществующий timeslot id={slot_id}; "
                        f"допустимые id: 1..{len(known)}")

        missing = sorted(expected - seen)
        if missing:
            raise ParserValidationError(
                f"fixed_schedules: нет записей для фиксируемых курсов {missing!r}")
        extra = sorted(seen - expected)
        if extra:
            raise ParserValidationError(
                f"fixed_schedules: лишние записи для курсов {extra!r}")


def build_arg_parser() -> argparse.ArgumentParser:
    """Describe the parser CLI. Defaults point at parser/tables, not the cwd."""
    data_dir = Path(__file__).resolve().parent / "tables"
    parser = argparse.ArgumentParser(
        prog="python -m parser.importer",
        description="Собрать JSON для солвера из Excel-файлов нагрузки, аудиторий и анкеты.")
    parser.add_argument(
        "--courses", dest="courses_file", type=Path, default=data_dir / "table.xlsx",
        help="Excel с нагрузкой (по умолчанию parser/tables/table.xlsx)")
    parser.add_argument(
        "--rooms", "--reference", dest="rooms_file", type=Path,
        default=data_dir / "table2.xlsx",
        help="Excel с каталогом аудиторий, сеткой слотов и эталонной занятостью "
             "(по умолчанию parser/tables/table2.xlsx)")
    parser.add_argument(
        "--desires", dest="desires_file", type=Path,
        default=data_dir / "table3.xlsx",
        help="Excel с анкетой преподавателей (по умолчанию parser/tables/table3.xlsx)")
    parser.add_argument(
        "--config", dest="config_file", type=Path, default=None,
        help="JSON-конфиг парсера (по умолчанию parser/config.json)")
    parser.add_argument(
        "--save", dest="save_path", type=Path,
        default=Path(__file__).resolve().parent / "data.json",
        help="Куда сохранить итоговый JSON (по умолчанию parser/data.json)")
    parser.add_argument(
        "--parse-room-occupancy", action="store_true",
        help="Читать эталонную занятость из листа «Аудитории» в room_preblocked")
    parser.add_argument(
        "--rooms-sheet", default=Importer.rooms_sheet,
        help=f"Имя листа аудиторий (по умолчанию {Importer.rooms_sheet!r})")
    parser.add_argument(
        "--pe-sheet", default=Importer.pe_sheet,
        help=f"Имя листа физкультуры (по умолчанию {Importer.pe_sheet!r})")
    return parser


def run(*args, **kwargs) -> None:
    if args or kwargs:
        importer = Importer(*args, **kwargs)
    else:
        options = build_arg_parser().parse_args()
        importer = Importer(
            rooms_file=options.rooms_file,
            rooms_sheet=options.rooms_sheet,
            courses_file=options.courses_file,
            desires_file=options.desires_file,
            save_path=options.save_path,
            config=options.config_file,
            parse_room_occupancy=options.parse_room_occupancy,
            pe_sheet=options.pe_sheet,
        )
    importer.save_to_json(importer.parse_from_excel())


if __name__ == "__main__":
    run()
