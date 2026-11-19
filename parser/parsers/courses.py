import math
import re

import pandas as pd

from parser.entities.table_entities import Entities


class CoursesParserMixin:
    def __init__(self):
        super().__init__()
        self._course_count = 0
        self._session_count = 0
        self._skipped_hours: dict[tuple[str, str, str], int] = {}
        self._biweekly_counter = 0
        self._warnings: list[str] = []

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
                if Entities.discipline_column not in df or Entities.group_column not in df:
                    raise ValueError(f"Лист {sheet_name!r}: отсутствует колонка дисциплины или группы")
                df[Entities.discipline_column] = df[Entities.discipline_column].ffill()
                session_columns = self._session_columns(df) if session_enabled else {}
                for _, row in df.dropna(subset=[Entities.group_column]).iterrows():
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
        counts = self._parse_students_count(row.get(Entities.students_column))
        result = []
        for lesson_type, column in Entities.hours_columns.items():
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
            for field, markers in Entities.session_field_markers:
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
            texts = [self._text_cell(row.get(column))
                     for column in field_columns]
            texts = [text for text in texts if text]
            if texts:
                values[field] = " | ".join(texts)
        date_windows = []
        for column in columns.get("date_windows_raw", []):
            text = self._text_cell(row.get(column))
            if not text:
                continue
            periods = Entities.comment_period_pattern.findall(text)
            parsed = False
            for start, end in periods:
                start_iso = self._iso_date(start)
                end_iso = self._iso_date(end)
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

        raw_groups = row.get(Entities.group_column)
        group_ids = [] if pd.isna(raw_groups) else [
            group for group in re.split(r"[\s,;\n]+", str(raw_groups).strip()) if group]
        free_days_value = values.get("free_days_min")
        free_days_match = re.search(r"\d+", free_days_value or "")
        self._session_count += 1
        return {
            "id": f"s{self._session_count}",
            "sheet": sheet_name,
            "course_ids": list(course_ids),
            "discipline": self._clean_discipline(
                row.get(Entities.discipline_column)) or None,
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
            type_match = Entities.subgroup_type_pattern.search(line)
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
