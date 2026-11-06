import json
import re
from pathlib import Path
from os import PathLike

import pandas as pd


class Importer:
    """Read the course load, room catalog and teacher preferences from XLSX."""

    data_dir = Path.cwd() / "tables"
    rooms_file = data_dir / "table2.xlsx"
    rooms_sheet = "Аудитории"
    courses_file = data_dir / "table.xlsx"
    desires_file = data_dir / "table3.xlsx"
    course_sheets = ["ХИМИКИ", "ФИНЗ", "ФИНЗ Магистры", "ЭБМ", "Тургенева 4 по выбору", "Тургенева 4"]
    days = ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА"]
    group_size = 30
    fixed_course_names = {"Прикладная физическая культура (практика)"}

    feature_columns = ["has_chalkboard", "has_whiteboard", "has_multimedia_board",
                       "has_blinds", "has_screen", "has_acoustic_system"]
    room_renames = {"Ауд.": "id", "Вм-ть": "capacity", "меловая": "has_chalkboard",
                    "маркерная": "has_whiteboard", "мультимедиа": "has_multimedia_board",
                    "жалюзи": "has_blinds", "экран": "has_screen", "акустич. система": "has_acoustic_system"}
    dropped_room_columns = ["Кому принадлежит", "С кем договариваться", "Примечание"]
    teacher_columns = {"лекция": "ФИО лектора", "практика": "ФИО преподавателя на практики, лаборатории",
                       "лабораторная": "ФИО преподавателя на практики, лаборатории"}
    hours_columns = {"лекция": "Лекции", "практика": "Практ. занятия", "лабораторная": "Лаб. занятия"}
    group_column = "Номер группы"
    discipline_column = "Дисциплины"
    projector_column = "Нужен ли проектор на практики, лаборатории"
    multimedia_column = "Нужна ли мультимедиа на лекции?"
    board_column = "Какая нужна доска на практики, лаборатории: меловая, маркерная, любая"
    board_keywords = {"любая": "board", "меловая": "chalkboard", "маркерная": "whiteboard"}

    def __init__(self, rooms_file: str | PathLike = rooms_file, rooms_sheet: str = rooms_sheet,
                 courses_file: str | PathLike = courses_file, course_sheets: list[str] | None = None,
                 days: list[str] | None = None, save_path: str | PathLike | None = None,
                 desires_file: str | PathLike | None = desires_file, fixed_course_names: set[str] | None = None):
        self.rooms_file = rooms_file
        self.rooms_sheet = rooms_sheet
        self.courses_file = courses_file
        self.desires_file = desires_file
        self.course_sheets = list(course_sheets) if course_sheets is not None else list(type(self).course_sheets)
        self.days = list(days) if days is not None else list(type(self).days)
        self.save_path = Path(save_path) if save_path is not None else Path.cwd() / "data.json"
        self.fixed_course_names = set(fixed_course_names) \
            if fixed_course_names is not None \
            else set(type(self).fixed_course_names)
        self._teachers: dict[str, dict] = {}
        self._groups: dict[str, dict] = {}
        self._course_count = 0
        self._time_slots: list[dict] = []

    def parse_from_excel(self) -> dict:
        rooms_df = pd.read_excel(self.rooms_file, sheet_name=self.rooms_sheet, header=[0, 2])
        rooms = self._parse_rooms(rooms_df)
        self._time_slots = self._parse_time_slots(rooms_df)
        courses = self._parse_courses()
        impossible, wanted = ([], [])
        if self.desires_file is not None:
            desires_df = pd.read_excel(self.desires_file)
            impossible, wanted = self._parse_teachers_desires(desires_df)
        fixed = self._generate_fixed_schedules(courses)
        for course in courses:
            course.pop("_course_number", None)
        return {
            "rooms": rooms,
            "teachers": list(self._teachers.values()),
            "groups": list(self._groups.values()),
            "courses": courses,
            "time_slots": self._time_slots,
            "teachers_impossible_slots": impossible,
            "teachers_wanted_slots": wanted,
            "fixed_schedules": fixed,
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

    def _parse_rooms(self, rooms: pd.DataFrame) -> list[dict]:
        rooms = rooms.drop(self.days + ["Вид"] + self.dropped_room_columns, axis=1, level=0)
        rooms.columns = [top if "Unnamed" in str(bottom) else bottom for top, bottom in rooms.columns]
        rooms = rooms.dropna(subset=["Ауд.", "Вм-ть"]).rename(columns=self.room_renames)
        for column in self.feature_columns:
            if column not in rooms:
                rooms[column] = False
            else:
                rooms[column] = rooms[column].fillna("").astype(str).str.strip().eq("+")
        rooms["id"] = rooms["id"].astype(str).str.strip()
        capacity = pd.to_numeric(rooms["capacity"].astype(str).str.extract(r"(\d+)", expand=False), errors="coerce")
        rooms = rooms[capacity.notna()].copy()
        rooms["capacity"] = capacity.loc[rooms.index].astype(int)
        rooms["has_board"] = rooms["has_chalkboard"] | rooms["has_whiteboard"] | rooms["has_multimedia_board"]
        return rooms.to_dict(orient="records")

    def _parse_courses(self) -> list[dict]:
        courses = []
        for sheet_name in self.course_sheets:
            df = pd.read_excel(self.courses_file, sheet_name=sheet_name)
            if self.discipline_column not in df or self.group_column not in df:
                raise ValueError(f"Лист {sheet_name!r}: отсутствует колонка дисциплины или группы")
            df[self.discipline_column] = df[self.discipline_column].ffill()
            for _, row in df.dropna(subset=[self.group_column]).iterrows():
                courses.extend(self._parse_row(row))
        return courses

    def _parse_row(self, row: pd.Series) -> list[dict]:
        result = []
        for lesson_type, column in self.hours_columns.items():
            hours = self._parse_hours(row.get(column))
            if hours is None:
                continue
            course = self._build_course(row, lesson_type, hours)
            result.append(course)
            self._register_teachers_and_groups(course)
        return result

    @staticmethod
    def _parse_hours(raw_value: object) -> float | None:
        if pd.isna(raw_value):
            return None
        numbers = re.findall(r"\d+(?:[.,]\d+)?", str(raw_value))
        return float(numbers[-1].replace(",", ".")) if numbers else 2.0

    def _build_course(self, row: pd.Series, lesson_type: str, hours: float) -> dict:
        group_ids = [x for x in re.split(r"[\s,;\n]+", str(row[self.group_column]).strip()) if x]
        self._course_count += 1
        name = f"{row[self.discipline_column]} ({lesson_type})"
        return {"id": f"c{self._course_count}", "name": name,
                "teacher_id": self._parse_teacher(row.get(self.teacher_columns[lesson_type])),
                "group_ids": group_ids,
                "hours_per_semester": hours,
                "requirements": self._parse_requirements(row, lesson_type),
                "_course_number": row.get("Курс")}

    @staticmethod
    def _split_teacher_names(raw_value: object) -> list[str]:
        if pd.isna(raw_value):
            return []
        # Some source cells contain several instructors separated only by
        # whitespace, e.g. "Кочетова Н.А.        Белова К.Г.".
        value = re.sub(
            r"(?<=[А-ЯЁ]\.)\s+(?=[А-ЯЁ][а-яё-]+\s+[А-ЯЁ]\.[А-ЯЁ]\.)",
            "\n",
            str(raw_value).strip(),
        )
        names = [name.strip() for name in re.split(r"[;,\n]+", value)
                 if name.strip() and name.strip().lower() != "nan"]
        return names

    @classmethod
    def _parse_teacher(cls, raw_value: object) -> str | None:
        names = cls._split_teacher_names(raw_value)
        return names[0] if names else None

    def _parse_requirements(self, row: pd.Series, lesson_type: str) -> list[str]:
        requirements = []
        if lesson_type == "лекция":
            value = str(row.get(self.multimedia_column, "")).lower()
            if "да" in value or "нуж" in value:
                requirements.append("multimedia_board")
            return requirements
        board = str(row.get(self.board_column, "")).lower()
        for keyword, requirement in self.board_keywords.items():
            if keyword in board:
                requirements.append(requirement)
                if keyword == "любая":
                    break
        projector = str(row.get(self.projector_column, "")).lower()
        if "да" in projector or "нуж" in projector:
            requirements.append("screen")
        return requirements

    def _register_teachers_and_groups(self, course: dict) -> None:
        teacher = course["teacher_id"]
        if teacher:
            self._teachers.setdefault(teacher, {"id": teacher})
        for group_id in course["group_ids"]:
            self._groups.setdefault(group_id, {"id": group_id, "size": 30})

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
                if digits and (day, int(digits.group())) in slots:
                    selected.add(slots[(day, int(digits.group()))])
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
            for teacher in teachers:
                impossible.append({"teacher_id": teacher, "course_name": course_name,
                                   "group_ids": group_ids, "timeslots_ids": blocked,
                                   "comments": row.get("Другие комментарии")})
                wanted.append({"teacher_id": teacher, "course_name": course_name, "group_ids": group_ids,
                               "fixed_room": row.get("Аудитория"), "room_type": row.get("Вид аудитории"),
                               "capacity": row.get("Вместимость"),
                               "room_requirements": [str(c).split(" / ")[-1] for c in room_cols
                                                     if pd.notna(row.get(c)) and str(row.get(c)).strip().lower() not in {"", "false", "нет"}],
                               "timeslots_ids": preferred, "comments": row.get("Другие комментарии")})
                self._teachers.setdefault(teacher, {"id": teacher})
        return impossible, wanted

    def _generate_fixed_schedules(self, courses: list[dict]) -> list[dict]:
        """Apply the incoming project's explicit fixed PE slots by study year."""
        slots_by_course = {1: [12, 22], 2: [19, 29], 3: [40, 1]}
        fixed = []
        for course in courses:
            if course["name"] not in self.fixed_course_names:
                continue
            try:
                course_number = int(course["_course_number"])
            except (TypeError, ValueError):
                continue
            slot_ids = slots_by_course.get(course_number)
            if slot_ids:
                fixed.append({"course_id": course["id"], "timeslots_ids": slot_ids})
        return fixed


def run(*args, **kwargs) -> None:
    importer = Importer(*args, **kwargs)
    importer.save_to_json(importer.parse_from_excel())


if __name__ == "__main__":
    run()
