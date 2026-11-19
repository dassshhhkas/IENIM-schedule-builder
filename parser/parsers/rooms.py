import re

import pandas as pd

from parser.common.core import ParserValidationError
from parser.entities.table_entities import Entities


class RoomsParserMixin:
    def __init__(self):
        super().__init__()
        self._room_ids: dict[str, str] = {}
        self._header_lookup: dict[str, str] = {}
        self._time_slots: list[dict] = []
        self._warnings: list[str] = []

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
        rooms = rooms.drop(self.days + Entities.dropped_room_columns, axis=1, level=0)
        rooms.columns = [top if "Unnamed" in str(bottom) else bottom for top, bottom in rooms.columns]
        rooms = rooms.dropna(subset=["Ауд."]).rename(columns=Entities.room_renames)
        rooms["id"] = rooms["id"].map(self._normalize_room_id)
        rooms = rooms[rooms["id"].notna() & ~rooms["id"].astype(str).eq("")]
        # The sheet contains one empty duplicate row (e.g. room 369); keep the
        # richest row per id so the solver never sees two rooms with one id.
        rooms = rooms.assign(_filled=rooms.notna().sum(axis=1))
        rooms = rooms.sort_values("_filled", ascending=False).drop_duplicates("id", keep="first")
        for column in Entities.feature_columns:
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
            record.update({column: bool(row.get(column, False)) for column in Entities.feature_columns})
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
        for canonical, variants in Entities.header_aliases.items():
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
