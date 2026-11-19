import pandas as pd

from parser.common.core import ParserValidationError


class PhysicalEducationMixin:
    def __init__(self):
        super().__init__()
        self._pe_slots: dict[int, list[int]] = {}
        self._time_slots: list[dict] = []
        self._groups: dict[str, dict] = {}
        self._group_sizes: dict[str, int] = {}
        self._group_size_sources: dict[str, str] = {}
        self._warnings: list[str] = []

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
            values = {self._name_key(value)
                      for value in df.iloc[row_index].tolist()
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
                if not pd.isna(value) and \
                        self._name_key(value) == target:
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

    @classmethod
    def _fixed_course_year(cls, course: dict) -> int:
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
                f"({cls._course_label(course)!r}): не удалось определить год обучения "
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

    def _build_fixed_schedule_events(self, courses: list[dict], fixed: list[dict]) -> list[dict]:
        """Materialize imported PE slots as displayable, group-blocking events."""
        courses_by_id = {course["id"]: course for course in courses}
        events = []
        for fixed_entry in fixed:
            course = courses_by_id[fixed_entry["course_id"]]
            pattern = str(course.get("week_pattern") or "weekly").casefold()
            if pattern == "odd":
                weeks = list(range(1, 17, 2))
            elif pattern == "even":
                weeks = list(range(2, 17, 2))
            else:
                weeks = list(range(1, 17))
            for slot_id in fixed_entry["timeslots_ids"]:
                events.append({
                    "course_id": course["id"],
                    "course_name": self._course_label(course),
                    "lesson_type": course["lesson_type"],
                    "teacher_ids": list(course.get("teacher_ids") or []),
                    "group_ids": list(course.get("group_ids") or []),
                    "timeslots_ids": [int(slot_id)],
                    "weeks": weeks,
                    "duration_slots": 1,
                    "venue_type": "sport",
                    "room_id": "Спортзал",
                    "is_preassigned": True,
                })
        return events

    def _expand_whole_cohort_pe_groups(self, courses: list[dict]) -> None:
        """Resolve the PE workbook's `все` marker to real groups in that year."""
        pe_courses = [
            course for course in courses
            if self._course_label(course) in self.fixed_course_names
               and any(self._normalize_group_key(group) in {"ВСЕ", "ALL"}
                       for group in (course.get("group_ids") or []))
        ]
        for pe_course in pe_courses:
            year = self._fixed_course_year(pe_course)
            sentinels = [
                group for group in (pe_course.get("group_ids") or [])
                if self._normalize_group_key(group) in {"ВСЕ", "ALL"}
            ]
            groups_for_year: list[str] = []
            for course in courses:
                if course is pe_course or \
                        self._course_label(course) in self.fixed_course_names:
                    continue
                try:
                    course_year = self._fixed_course_year(course)
                except ParserValidationError:
                    continue
                if course_year == year:
                    for group_id in course.get("group_ids") or []:
                        if self._normalize_group_key(group_id) not in {"ВСЕ", "ALL"} \
                                and group_id not in groups_for_year:
                            groups_for_year.append(group_id)
            if not groups_for_year:
                self._warnings.append(
                    f"Курс {pe_course['id']}: маркер группы «все» для физкультуры "
                    f"не удалось раскрыть для {year} курса; проверьте список групп"
                )
                continue
            pe_course["group_ids"] = groups_for_year
            for instance in pe_course.get("instances") or []:
                instance["group_ids"] = list(groups_for_year)
            for sentinel in sentinels:
                self._groups.pop(sentinel, None)
                self._group_sizes.pop(sentinel, None)
                self._group_size_sources.pop(sentinel, None)
            self._warnings.append(
                f"Курс {pe_course['id']}: физкультура закреплена за {year} курсом "
                f"({len(groups_for_year)} учебных групп)"
            )

    def _validate_fixed_schedules(self, courses: list[dict], fixed: list[dict]) -> None:
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
