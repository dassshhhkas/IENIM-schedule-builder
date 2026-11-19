import json
from os import PathLike
from pathlib import Path

import pandas as pd

from parser.common.core import ParserConfigMixin, ParserValidationError
from parser.parsers.course_model import CourseModelMixin
from parser.parsers.courses import CoursesParserMixin
from parser.entities.table_entities import Entities
from parser.parsers.links import CourseLinksMixin
from parser.parsers.physical_education import PhysicalEducationMixin
from parser.parsers.rooms import RoomsParserMixin
from parser.parsers.teachers import TeachersParserMixin
from parser.parsers.wishes import WishesParserMixin


class Importer(
        ParserConfigMixin,
        RoomsParserMixin,
        CoursesParserMixin,
        TeachersParserMixin,
        WishesParserMixin,
        CourseModelMixin,
        CourseLinksMixin,
        PhysicalEducationMixin):
    """Coordinate Excel parsing and convert source tables into solver data."""

    def __init__(
            self,
            rooms_file: str | PathLike = Entities.rooms_file,
            rooms_sheet: str = Entities.rooms_sheet,
            courses_file: str | PathLike = Entities.courses_file,
            course_sheets: list[str] | None = None,
            days: list[str] | None = None,
            save_path: str | PathLike | None = None,
            desires_file: str | PathLike | None = Entities.desires_file,
            fixed_course_names: set[str] | None = None,
            default_group_size: int = Entities.default_group_size,
            pe_sheet: str | None = Entities.pe_sheet,
            pe_institute: str = Entities.pe_institute,
            config: dict | str | PathLike | None = None,
            parse_room_occupancy: bool = False
    ):
        super().__init__()
        self.rooms_file = rooms_file
        self.rooms_sheet = rooms_sheet
        self.courses_file = courses_file
        self.desires_file = desires_file
        self.pe_sheet = pe_sheet
        self.pe_institute = pe_institute
        self.course_sheets = list(course_sheets) if course_sheets is not None else Entities.course_sheets
        self.days = list(days) if days is not None else Entities.days
        self.save_path = Path(save_path) if save_path is not None else \
            Path(__file__).resolve().parent.parent / "data.json"
        self.fixed_course_names = set(fixed_course_names) \
            if fixed_course_names is not None else Entities.fixed_course_names
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

    def parse_from_excel(self) -> dict:
        self._warnings = []
        self._teachers = {}
        self._groups = {}
        self._course_count = 0
        self._session_count = 0
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
        self._expand_whole_cohort_pe_groups(courses)

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
        fixed_events = self._build_fixed_schedule_events(courses, fixed)
        return {
            "rooms": rooms,
            "teachers": list(self._teachers.values()),
            "groups": list(self._groups.values()),
            "courses": courses,
            "time_slots": self._time_slots,
            "teachers_impossible_slots": impossible,
            "teachers_wanted_slots": wanted,
            "fixed_schedules": fixed,
            "fixed_schedule_events": fixed_events,
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
        if type(missing).__name__ == "bool_" and bool(missing):
            return None
        if hasattr(value, "item"):
            try:
                return value.item()
            except (ValueError, TypeError):
                pass
        return value
