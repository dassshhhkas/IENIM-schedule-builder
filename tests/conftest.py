"""Общие фикстуры для тестов."""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def tiny_schedule_data() -> dict:
    return {
        "rooms": [
            {
                "id": "101",
                "capacity": 30,
                "has_board": True,
                "has_screen": False,
                "type": "м",
            }
        ],
        "teachers": [{"id": "Иванов И.И."}],
        "groups": [{"id": "G1", "size": 25}],
        "time_slots": [
            {"id": 1, "day": "понедельник", "slot_index": 1, "time": "08:30-10:00"},
            {"id": 2, "day": "понедельник", "slot_index": 2, "time": "10:15-11:45"},
        ],
        "courses": [
            {
                "id": "c1",
                "discipline": "Математика",
                "lesson_type": "практика",
                "teacher_ids": ["Иванов И.И."],
                "group_ids": ["G1"],
                "lessons_per_week": 1,
                "week_pattern": "weekly",
                "duration_slots": 1,
                "requirements": [],
                "venue_type": "room",
                "instances": [
                    {
                        "id": "c1_i1",
                        "course_id": "c1",
                        "name": "Математика (практика)",
                        "lesson_type": "практика",
                        "lesson_kind": "single",
                        "teacher_ids": ["Иванов И.И."],
                        "group_ids": ["G1"],
                        "students_needed": 25,
                        "subgroup_index": 1,
                        "subgroup_count": 1,
                        "requirements": [],
                        "venue_type": "room",
                        "lessons_per_week": 1,
                        "week_pattern": "weekly",
                        "duration_slots": 1,
                    }
                ],
            }
        ],
    }


@pytest.fixture
def solver_config() -> dict:
    return {
        "max_time_in_seconds": 5,
        "solve_strategy": "monolithic",
        "num_search_workers": 1,
        "unplaceable_instance_policy": "warn",
    }


@pytest.fixture
def sample_result_with_warnings() -> dict:
    return {
        "status": "SUCCESS_WITH_WARNINGS",
        "errors": [],
        "schedule": [
            {
                "instance_id": "c2_i1",
                "course_id": "c2",
                "course_name": "Иностранный язык (практика)",
                "name": "Иностранный язык (практика)",
                "group_ids": ["G1"],
                "room_id": "101",
                "timeslots_ids": [1],
                "day": "понедельник",
                "slot_index_start": 1,
                "weeks": list(range(1, 17)),
            }
        ],
        "warnings": [
            {
                "code": "UNPLACEABLE_INSTANCE_DROPPED",
                "name": "Русский язык (лекция)",
                "course_id": "c4",
                "group_ids": ["G1", "G2"],
                "students_needed": 330,
                "requirements": [],
                "cause_code": "NO_FEASIBLE_ROOM",
                "message": "Нет подходящей аудитории",
                "entity_ids": ["c4_i1"],
            },
            {
                "code": "SCHEDULED_ON_SATURDAY",
                "course_id": "c2",
                "message": "Курс 'Иностранный язык (практика)' поставлен в субботу",
                "entity_ids": ["c2_i1"],
            },
            {
                "code": "UNMANAGED_TIME_WISH",
                "course_id": "c6",
                "time_wish_raw": "по ситуации",
                "reason": "no_rule",
                "message": "Неформализованное пожелание",
                "entity_ids": [],
            },
        ],
        "warning_groups": {
            "unplaced": [
                {
                    "code": "UNPLACEABLE_INSTANCE_DROPPED",
                    "name": "Русский язык (лекция)",
                    "course_id": "c4",
                    "group_ids": ["G1", "G2"],
                    "students_needed": 330,
                    "requirements": [],
                    "cause_code": "NO_FEASIBLE_ROOM",
                    "message": "Нет подходящей аудитории",
                    "entity_ids": ["c4_i1"],
                }
            ],
            "soft": [
                {
                    "code": "SCHEDULED_ON_SATURDAY",
                    "course_id": "c2",
                    "message": "Курс 'Иностранный язык (практика)' поставлен в субботу",
                    "entity_ids": ["c2_i1"],
                },
                {
                    "code": "UNMANAGED_TIME_WISH",
                    "course_id": "c6",
                    "time_wish_raw": "по ситуации",
                    "reason": "no_rule",
                    "message": "Неформализованное пожелание",
                    "entity_ids": [],
                },
            ],
            "other": [],
        },
        "unplaced": [],
        "meta": {"solve_time_sec": 1.5, "solve_strategy": "monolithic"},
    }


@pytest.fixture
def dumps():
    return lambda obj: json.dumps(obj, ensure_ascii=False)
