import re

import pandas as pd

from parser.entities.table_entities import Entities


class CourseLinksMixin:
    def __init__(self):
        super().__init__()
        self._room_ids: dict[str, str] = {}
        self._teachers: dict[str, dict] = {}
        self._time_slots: list[dict] = []
        self._warnings: list[str] = []

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

    def _link_desires_to_courses(self, courses: list[dict], impossible: list[dict], wanted: list[dict]) -> None:
        index: dict[tuple[str, str], list[dict]] = {}
        for course in courses:
            discipline = course.get("discipline") or self._course_label(course)
            key = (course.get("lesson_type", ""),
                   self._normalize_discipline(discipline))
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
            lectures.setdefault(
                self._normalize_discipline(discipline), []).append(course)
        for course in courses:
            if course.get("lesson_type") == "лекция":
                continue
            raw = course.get("location_raw")
            if not raw or not Entities.same_room_pattern.search(str(raw)):
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
                code = Entities.room_requirement_labels.get(
                    self._name_key(label))
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
