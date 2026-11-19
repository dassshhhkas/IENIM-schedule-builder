import re

from parser.entities.table_entities import Entities


class WishesParserMixin:
    def __init__(self):
        super().__init__()
        self._time_slots: list[dict] = []
        self._warnings: list[str] = []

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
            for prefix, value in Entities.pair_word_values.items():
                if word.startswith(prefix):
                    return value
            return None
        groups = match.groups()
        for value in groups:
            if value and value.isdigit():
                return int(value)
        for value in groups:
            if value:
                for prefix, number in Entities.pair_word_values.items():
                    if str(value).startswith(prefix):
                        return number
        return None

    def _wish_day_hits(self, text: str) -> list[dict]:
        hits: list[dict] = []
        for day, pattern in Entities.day_patterns:
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
        for match in Entities.wish_negation_pattern.finditer(prefix):
            last_negation = match.start()
        last_positive = -1
        for match in Entities.wish_positive_pattern.finditer(prefix):
            before = prefix[max(0, match.start() - 10):match.start()]
            if re.search(r"(?:^|\s)(?:не|нельзя)\s*$", before, re.IGNORECASE):
                continue
            last_positive = match.start()

        if last_negation < 0 and last_positive < 0:
            return segment_default if self._wish_is_continuation(chunk) else False
        return last_positive <= last_negation

    def _wish_segment_polarity(self, text: str) -> bool | None:
        has_negation = bool(Entities.wish_negation_pattern.search(text))
        positive = False
        for match in Entities.wish_positive_pattern.finditer(text):
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
        matches = list(Entities.teacher_name_pattern.finditer(segment))
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

        for match in Entities.max_pairs_day_pattern.finditer(text):
            add("max_pairs", match, 0)
        for match in Entities.pair_bound_pattern.finditer(text):
            add("pair_bound", match, 0)
        for match in Entities.time_clause_pattern.finditer(text):
            add("time", match, 0)
        for match in Entities.pair_count_word_pattern.finditer(text):
            add("pair_range", match, 1)
        for match in Entities.pair_range_pattern.finditer(text):
            add("pair_range", match, 1)
        for match in Entities.pair_word_pattern.finditer(text):
            add("pair_range", match, 1)
        for part, pattern in Entities.day_part_patterns:
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
                        fields["min_pair_index"] = max(fields["min_pair_index"] or 1, target)
                elif "до" in prep:
                    if clause_negative:
                        forbid(range(1, value + 1), days or None)
                    elif days:
                        reasons.append("preferred_day_pair")
                    else:
                        fields["max_pair_index"] = min(fields["max_pair_index"] or max_pair, value)
                else:  # "с" / "начиная с"
                    if clause_negative:
                        forbid(range(value, max_pair + 1), days or None)
                    elif days:
                        reasons.append("preferred_day_pair")
                    else:
                        fields["min_pair_index"] = max(fields["min_pair_index"] or 1, value)
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
                        fields["min_pair_index"] = max(fields["min_pair_index"] or 1, target)
                elif lexical_max or prep == "до" and not clause_negative:
                    target = self._pair_from_minutes(minutes, "le")
                    if target is None:
                        reasons.append("time_outside_grid")
                    elif days:
                        reasons.append("preferred_day_slot")
                    else:
                        fields["max_pair_index"] = min(fields["max_pair_index"] or max_pair, target)
                elif prep == "после":
                    target = self._pair_from_minutes(minutes, "gt")
                    if target is None:
                        reasons.append("time_outside_grid")
                    elif clause_negative:
                        forbid(range(target, max_pair + 1), days or None)
                    elif days:
                        reasons.append("preferred_day_slot")
                    else:
                        fields["min_pair_index"] = max(fields["min_pair_index"] or 1, target)
                elif prep in {"с", "начиная с"}:
                    target = self._pair_from_minutes(minutes, "ge")
                    if target is None:
                        reasons.append("time_outside_grid")
                    elif clause_negative:
                        forbid(range(target, max_pair + 1), days or None)
                    elif days:
                        reasons.append("preferred_day_slot")
                    else:
                        fields["min_pair_index"] = max(fields["min_pair_index"] or 1, target)
                else:  # "до"
                    target = self._pair_from_minutes(minutes, "le")
                    if target is None:
                        reasons.append("time_outside_grid")
                    elif clause_negative:
                        forbid(range(1, target + 1), days or None)
                    elif days:
                        reasons.append("preferred_day_slot")
                    else:
                        fields["max_pair_index"] = min(fields["max_pair_index"] or max_pair, target)
                continue

            if clause["kind"] == "pair_range":
                if self._wish_is_frequency(text, match):
                    continue
                if match.re is Entities.pair_count_word_pattern:
                    word = match.group(1)
                    value = Entities.pair_count_word_values.get(word)
                    if value is None:
                        reasons.append("invalid_pair")
                        continue
                    low, high = 1, value
                elif match.re is Entities.pair_word_pattern:
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
                    fields["min_pair_index"] = max(fields["min_pair_index"] or 1, low)
                    fields["max_pair_index"] = min(fields["max_pair_index"] or max_pair, high)
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
        soft = bool(Entities.wish_soft_pattern.search(text)) or any_positive \
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
                for segment in Entities.wish_segment_pattern.split(raw):
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
