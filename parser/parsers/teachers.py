import re

import pandas as pd

from parser.common.core import ParserValidationError
from parser.entities.table_entities import Entities


class TeachersParserMixin:
    def __init__(self):
        super().__init__()
        self._teachers: dict[str, dict] = {}
        self._warnings: list[str] = []

    surname_endings = (
        "ов", "ев", "ёв", "ин", "ын", "ский", "цкий", "ской", "цкой", "ий",
        "ая", "яя", "ой", "ова", "ева", "ёва", "ина", "ына", "ко", "ук",
        "юк", "ич", "енко", "чук", "як", "ец", "дзе", "швили", "ян", "янц",
    )

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
        segments = [segment.strip() for segment in Entities.teacher_segment_pattern.split(text)
                    if segment.strip()]
        specs = []
        for segment in segments:
            names = Entities.teacher_name_pattern.findall(segment)
            if not names:
                names = Entities.teacher_full_name_pattern.findall(segment)
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
        for match in Entities.team_marker_pattern.finditer(segment):
            if match.group("count"):
                return {"count": int(match.group("count")),
                        "label": re.sub(r"\s+", " ", match.group(0)).strip()}
        match = Entities.parenthesized_count_pattern.search(segment)
        if match:
            return {"count": int(match.group(1)), "label": match.group(0).strip()}
        return None

    @classmethod
    def _normalize_teacher_name(cls, name: str) -> str:
        value = re.sub(r"\s+", " ", str(name)).strip(" ,;:-")
        value = value.translate(Entities.latin_name_letters)
        value = re.sub(r"([А-ЯЁA-Z]\.)\s+(?=[А-ЯЁA-Z]\.)", r"\1", value)
        match = Entities.initials_first_pattern.match(value)
        if match:
            first, second, surname = match.groups()
            value = f"{surname} {first}{second or ''}"
        match = Entities.dotless_initials_pattern.match(value)
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
