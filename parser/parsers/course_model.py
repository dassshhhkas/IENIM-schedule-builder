import math
import re

import pandas as pd

from parser.common.core import ParserValidationError
from parser.entities.table_entities import Entities


class CourseModelMixin:
    def __init__(self):
        super().__init__()
        self._course_count = 0
        self._groups: dict[str, dict] = {}
        self._group_sizes: dict[str, int] = {}
        self._group_size_sources: dict[str, str] = {}
        self._room_ids: dict[str, str] = {}
        self._teachers: dict[str, dict] = {}
        self._warnings: list[str] = []

    def _build_course(self, row: pd.Series, lesson_type: str, hours: float,
                      sheet_name: str) -> dict:
        group_ids = [x for x in re.split(r"[\s,;\n]+", str(row[Entities.group_column]).strip()) if x]
        self._course_count += 1
        course_id = f"c{self._course_count}"
        discipline = self._clean_discipline(row[Entities.discipline_column])
        name = f"{discipline} ({lesson_type})"
        specs, teacher_meta = self._parse_teacher_cell(
            row.get(Entities.teacher_columns[lesson_type]))
        if teacher_meta["unparsed"]:
            self._warnings.append(
                f"Лист {sheet_name!r}, {course_id}: не удалось выделить ФИО "
                f"из {teacher_meta['raw']!r}")
        for fragment in teacher_meta["unresolved"]:
            self._warnings.append(
                f"Лист {sheet_name!r}, {course_id}: неразобранный фрагмент ФИО {fragment!r}")
        subgroups = self._parse_subgroup_counts(
            row.get(Entities.subgroup_column))
        if subgroups["unparsed"]:
            self._warnings.append(
                f"Лист {sheet_name!r}, {course_id}: не удалось разобрать "
                f"«{Entities.subgroup_column}»: {subgroups['raw']!r}")
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
        column_count = self._subgroup_count_for_lesson(
            subgroups, lesson_type)
        requirements, software_raw = self._parse_requirements(row, lesson_type)
        location = self._parse_location(row.get(Entities.location_column))
        ntk_raw = self._text_cell(row.get(Entities.ntk_column))
        delivery_raw = self._text_cell(row.get(Entities.delivery_model_column))
        time_wish_raw = self._text_cell(row.get(Entities.time_wish_column))
        comments_raw = self._text_cell(row.get(Entities.comments_column))
        venue_type = (
            "sport" if name in self.fixed_course_names else self._classify_venue(
                ntk_raw, delivery_raw, location["location_raw"],
                comments_raw, location["allowed_room_ids"], course_id
            )
        )
        # A PE course uses its preassigned sport slots and does not consume an
        # IENIM classroom or classroom equipment from the regular room catalog.
        if venue_type == "sport":
            requirements = []
            software_raw = None
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
        teacher_ids = self._unique_names(
            [spec["name"] for spec in specs])
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
            teacher_ids = self._unique_names(
                [spec["name"] for spec in specs])
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
            teacher_ids = self._unique_names(
                [spec["name"] for spec in assignment])
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
            value = str(row.get(Entities.multimedia_column, "")).lower()
            if self._is_positive(value):
                self._add_requirement(requirements, "multimedia_board")
            if "доск" in value:
                self._add_board_requirement(value, requirements)
        else:
            self._add_board_requirement(str(row.get(Entities.board_column, "")), requirements)
            projector = row.get(Entities.projector_column)
            if self._is_positive(projector):
                self._add_requirement(requirements, "screen")
            raw_software = row.get(Entities.software_column)
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
        self._requirements_from_location(row.get(Entities.location_column), requirements)
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
        for match in Entities.room_ref_pattern.finditer(text):
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
        has_same_room = bool(Entities.same_room_pattern.search(text))
        if not allowed and not has_same_room and not unknown \
                and not Entities.generic_location_pattern.search(text):
            self._warn_once(f"Место проведения {text!r} не распознано; сохранён location_raw")
        return result

    @staticmethod
    def _text_cell(value: object) -> str | None:
        if pd.isna(value):
            return None
        text = re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()
        if not text or text.lower() == "nan":
            return None
        return text

    def _classify_venue(
            self,
            ntk: str | None,
            delivery: str | None,
            location: str | None,
            comments: str | None,
            allowed_room_ids: list[str],
            course_id: str
    ) -> str:
        """Return room/online/external/unspecified for one course row (п.9)."""
        ntk_key = self._name_key(ntk or "")
        delivery_key = self._name_key(delivery or "")
        location_key = self._name_key(location or "")
        comments_key = self._name_key(comments or "")

        if "онлайн" in ntk_key:
            return "online"
        if "исключительно эо" in delivery_key:
            return "online"
        if location_key and Entities.venue_online_pattern.search(location_key) \
                and not Entities.venue_room_pattern.search(location_key):
            return "online"
        if location_key and Entities.venue_external_pattern.search(location_key) \
                and not Entities.venue_campus_pattern.search(location_key):
            return "external"
        if not location_key and comments_key \
                and Entities.venue_comment_external_pattern.search(comments_key):
            return "external"
        if allowed_room_ids:
            return "room"
        if location_key and Entities.same_room_pattern.search(location_key):
            return "room"
        if location_key and Entities.venue_room_pattern.search(location_key):
            return "room"
        if location_key and Entities.room_ref_pattern.search(location_key):
            return "room"
        if location_key and Entities.venue_no_room_pattern.search(location_key):
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

    @staticmethod
    def _comment_duration_slots(text_key: str) -> float | None:
        if Entities.comment_duration_half_pattern.search(text_key):
            return 1.5
        hours = Entities.comment_duration_hours_pattern.search(text_key)
        if hours:
            value = float(hours.group(1).replace(",", "."))
            slots = value / 2
            if slots >= 1:
                return slots
        pairs = Entities.comment_duration_pairs_pattern.search(text_key)
        if pairs:
            word = pairs.group(1)
            return float(Entities.pair_count_word_values.get(word, 0) or word)
        if Entities.comment_duration_double_pattern.search(text_key):
            return 2.0
        return None

    @staticmethod
    def _comment_week_ranges(text_key: str) -> list[list[int]]:
        ranges: list[list[int]] = []
        if "недел" in text_key:
            for start, end in Entities.comment_week_chain_pattern.findall(text_key):
                ranges.append([int(start), int(end)])
        for pattern in Entities.comment_week_range_patterns:
            for start, end in pattern.findall(text_key):
                ranges.append([int(start), int(end)])
        listed = Entities.comment_week_list_pattern.search(text_key)
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
        for segment in Entities.wish_segment_pattern.split(raw):
            text = re.sub(r"\s+", " ", segment).strip(" .;,")
            if not text:
                continue
            text_key = self._name_key(text)
            hint = {
                "scope": self._comment_scope(text_key),
                "online": bool(Entities.comment_online_pattern.search(text_key)),
                "duration_slots": self._comment_duration_slots(text_key),
                "period_start": None,
                "period_end": None,
                "week_ranges": self._comment_week_ranges(text_key),
                "semester_half": None,
                "source": text,
            }
            period = Entities.comment_period_pattern.search(text_key)
            if period:
                hint["period_start"] = self._iso_date(period.group(1))
                hint["period_end"] = self._iso_date(period.group(2))
            half = Entities.comment_semester_half_pattern.search(text_key)
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

    def _warn_comment_venue_conflict(
            self, course_id: str, lesson_type: str, venue_type: str, hints: list[dict]
    ) -> None:
        if venue_type == "online":
            return
        for hint in hints:
            if hint["online"] and hint["scope"] in {"all", lesson_type}:
                self._warn_once(
                    f"venue_conflict: курс {course_id}: комментарий говорит об "
                    f"онлайн-формате, но venue_type={venue_type}")

    def _register_teachers_and_groups(self, course: dict, counts: list[int] | None, sheet_name: str) -> None:
        teacher_ids = list(course.get("teacher_ids") or [])
        for instance in course.get("instances") or []:
            teacher_ids.extend(instance.get("teacher_ids") or [])
        for teacher in self._unique_names(teacher_ids):
            self._teachers.setdefault(teacher, {"id": teacher})
        observations = self._group_size_observations(
            course["group_ids"], counts)
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
                    f"Группа {group_id}: не удалось определить «{Entities.students_column}»{where}; "
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
        if (
                subgroup_count > 1
                and course.get("group_ids")
                and all(
            set(instance.get("group_ids") or []) == set(course["group_ids"])
            for instance in instances
        )
        ):
            self._warnings.append(
                f"Курс {course['id']}: состав групп по подгруппам не задан; "
                "каждый instance резервирует все group_ids курса. "
                "Для параллельного расписания нужна привязка подгрупп к группам."
            )
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
