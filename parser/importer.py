import json
import re
from os import PathLike

import pandas as pd

from pathlib import Path


class Importer:
    rooms_file = "table2.xlsx"
    rooms_sheet = "Аудитории"
    courses_file = "table.xlsx"
    course_sheets = ["ХИМИКИ", "ФИНЗ", "ФИНЗ Магистры", "ЭБМ", "Тургенева 4 по выбору", "Тургенева 4"]
    days = ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА"]
    semester_weeks = 17
    hours_per_pair = 2
    feature_columns = ["has_chalkboard", "has_whiteboard", "has_multimedia_board",
                       "has_blinds", "has_screen", "has_acoustic_system"]
    room_renames = {"Ауд.": "id", "Вм-ть": "capacity", "меловая": "has_chalkboard",
                    "маркерная": "has_whiteboard", "мультимедиа": "has_multimedia_board",
                    "жалюзи": "has_blinds", "экран": "has_screen", "акустич. система": "has_acoustic_system"}
    dropped_room_columns = ["Кому принадлежит", "С кем договариваться", "Примечание"]
    teacher_columns = {"лекция": "ФИО лектора",
                       "практика": "ФИО преподавателя на практики, лаборатории",
                       "лабораторная": "ФИО преподавателя на практики, лаборатории"}
    hours_columns = {"лекция": "Лекции", "практика": "Практ. занятия", "лабораторная": "Лаб. занятия"}
    group_column = "Номер группы"
    discipline_column = "Дисциплины"
    projector_column = "Нужен ли проектор на практики, лаборатории"
    multimedia_column = "Нужна ли мультимедиа на лекции?"
    board_column = "Какая нужна доска на практики, лаборатории: меловая, маркерная, любая"
    board_keywords = {"любая": "board", "меловая": "chalkboard", "маркерная": "whiteboard"}
    group_size_range = 30

    def __init__(
            self,
            rooms_file: str | PathLike = rooms_file,
            rooms_sheet: str = rooms_sheet,
            courses_file: str | PathLike = courses_file,
            course_sheets: list[str] | None = None,
            days: list[str] | None = None,
            semester_weeks: int = semester_weeks,
            save_path: str | PathLike | None = None,
    ):
        self.rooms_file = rooms_file
        self.rooms_sheet = rooms_sheet
        self.courses_file = courses_file
        self.course_sheets = course_sheets if course_sheets is not None else list(self.course_sheets)
        self.days = days if days is not None else list(self.days)
        self.semester_weeks = semester_weeks
        self.save_path = save_path if save_path is not None else Path.cwd() / 'data.json'

        self._teachers: dict[str, dict] = {}
        self._groups: dict[str, dict] = {}
        self._course_count = 0

    def parse_from_excel(self) -> dict:
        rooms_df = pd.read_excel(self.rooms_file, sheet_name=self.rooms_sheet, header=[0, 2])
        return {
            "rooms": self._parse_rooms(rooms_df),
            "time_slots": self._parse_time_slots(rooms_df),
            "courses": self._parse_courses(),
            "teachers": list(self._teachers.values()),
            "groups": list(self._groups.values()),

            "teachers_impossible_slots": [
                {"teacher_id": "Улитко М.В.", "timeslots_ids": [1, 2, 3]},
                {"teacher_id": "Хацко С.Л.", "timeslots_ids": [4, 5, 6]},
            ],
            "teachers_unwanted_slots": [
                {"teacher_id": "Улитко М.В.", "timeslots_ids": [10]},
                {"teacher_id": "Хацко С.Л.", "timeslots_ids": [1]},
            ],
            "fixed_schedules": [
                {
                    "course_id": "c3",
                    "timeslots_ids": [1, 2]
                }
            ]
        }

    def save_to_json(self, data: dict) -> None:
        with open(self.save_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)

    def _parse_time_slots(self, rooms: pd.DataFrame) -> list[dict]:
        slots = []
        for day in self.days:
            for slot_index, time in enumerate(rooms[day].columns, start=1):
                slots.append({"id": len(slots) + 1, "day": day.capitalize(), "slot_index": slot_index, "time": time})
        return slots

    def _parse_rooms(self, rooms: pd.DataFrame) -> list[dict]:
        rooms = rooms.drop(self.days + ["Вид"] + self.dropped_room_columns, axis=1, level=0)
        rooms.columns = [top if "Unnamed" in str(bottom) else bottom for top, bottom in rooms.columns]
        rooms = rooms.dropna(subset=["Ауд.", "Вм-ть"])
        rooms = rooms.rename(columns=self.room_renames)
        rooms[self.feature_columns] = rooms[self.feature_columns] == "+"
        capacity = pd.to_numeric(rooms["capacity"].astype(str).str.extract(r"(\d+)", expand=False), errors="coerce")
        rooms = rooms[capacity.notna()].copy()
        rooms["capacity"] = capacity.dropna().astype(int).values
        return rooms.to_dict(orient="records")

    def _parse_courses(self) -> list[dict]:
        courses = []
        for sheet_name in self.course_sheets:
            df = pd.read_excel(self.courses_file, sheet_name=sheet_name)
            df[self.discipline_column] = df[self.discipline_column].ffill()
            df = df.dropna(subset=[self.group_column])
            for _, row in df.iterrows():
                courses.extend(self._parse_row(row))
        return courses

    def _parse_row(self, row: pd.Series) -> list[dict]:
        courses = []
        for lesson_type in self.hours_columns:
            hours = self._parse_hours(row[self.hours_columns[lesson_type]])
            if hours is None:
                continue
            course = self._build_course(row, lesson_type, hours)
            courses.append(course)
            self._register_teachers_and_groups(course)
        return courses

    def _parse_hours(self, raw_value: object) -> float | None:
        if pd.isna(raw_value):
            return None
        numbers = re.findall(r"\d+", str(raw_value))
        return float(max(map(int, numbers))) if numbers else float(self.hours_per_pair)

    def _build_course(self, row: pd.Series, lesson_type: str, hours: float) -> dict:
        group_ids = [group for group in re.split(r"[\s\n]+", str(row[self.group_column])) if group]
        self._course_count += 1
        return {
            "id": f"c{self._course_count}",
            "name": f"{row[self.discipline_column]} ({lesson_type})",
            "teacher_id": self._parse_teacher(row[self.teacher_columns[lesson_type]]),
            "group_ids": group_ids,
            "lessons_per_week": round(hours / (self.hours_per_pair * self.semester_weeks)),
            "requirements": self._parse_requirements(row, lesson_type)
        }

    def _parse_teacher(self, raw_value: object) -> str | None:
        if pd.isna(raw_value):
            return None
        names = [name.strip() for name in re.split(r"[;,\n]", str(raw_value)) if name.strip() and name.lower() != "nan"]
        return names[0] if names else None

    def _parse_requirements(self, row: pd.Series, lesson_type: str) -> list[str]:
        requirements = []
        if lesson_type == "лекция":
            multimedia = str(row[self.multimedia_column]).lower()
            if "да" in multimedia or "нуж" in multimedia:
                requirements.append("multimedia_board")
            return requirements
        for keyword, requirement in self.board_keywords.items():
            if keyword in str(row[self.board_column]).lower():
                requirements.append(requirement)
        projector = str(row[self.projector_column]).lower()
        if "да" in projector or "нуж" in projector:
            requirements.append("screen")
        return requirements

    def _register_teachers_and_groups(self, course: dict) -> None:
        if course["teacher_id"]:
            self._teachers.setdefault(course["teacher_id"], {"id": course["teacher_id"]})
        for group_id in course["group_ids"]:
            self._groups.setdefault(group_id, {"id": group_id, "size": int(self.group_size_range)})


def run(*args, **kwargs) -> None:
    importer = Importer(*args, **kwargs)
    data = importer.parse_from_excel()
    importer.save_to_json(data)


if __name__ == '__main__':
    run()
