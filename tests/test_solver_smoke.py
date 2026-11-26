"""Минимальный end-to-end прогон солвера на синтетике."""

import json

from mvp_1 import normalize_duration_slots, normalize_week_pattern, solve_schedule


def test_normalize_week_pattern_weekly_alias():
    assert normalize_week_pattern("weekly")["type"] == "all"
    assert normalize_week_pattern("all")["type"] == "all"
    assert normalize_week_pattern("odd")["type"] == "odd"


def test_normalize_duration_slots_ceil():
    assert normalize_duration_slots(1) == 1
    assert normalize_duration_slots(1.0) == 1
    assert normalize_duration_slots(1.5) == 2
    assert normalize_duration_slots("1.5") == 2


def test_monolithic_smoke_places_one_lesson(tiny_schedule_data, solver_config, dumps):
    result = json.loads(solve_schedule(dumps(tiny_schedule_data), solver_config))
    assert str(result["status"]).startswith("SUCCESS")
    assert len(result["schedule"]) == 1
    assert result["schedule"][0]["room_id"] == "101"
    assert result["schedule"][0]["timeslots_ids"]
    assert result.get("errors") == []


def test_screen_requirement_does_not_block_placement(tiny_schedule_data, solver_config, dumps):
    course = tiny_schedule_data["courses"][0]
    course["requirements"] = ["screen"]
    course["instances"][0]["requirements"] = ["screen"]
    # аудитория типа «м» — soft proxy для screen, hard не блокирует
    result = json.loads(solve_schedule(dumps(tiny_schedule_data), solver_config))
    assert str(result["status"]).startswith("SUCCESS")
    assert len(result["schedule"]) == 1


def test_overbook_allows_students_within_120_percent(tiny_schedule_data, solver_config, dumps):
    tiny_schedule_data["rooms"][0]["capacity"] = 100
    tiny_schedule_data["groups"][0]["size"] = 120
    tiny_schedule_data["courses"][0]["instances"][0]["students_needed"] = 120
    result = json.loads(solve_schedule(dumps(tiny_schedule_data), solver_config))
    assert str(result["status"]).startswith("SUCCESS")
    assert len(result["schedule"]) == 1


def test_overbook_rejects_above_120_percent(tiny_schedule_data, solver_config, dumps):
    tiny_schedule_data["rooms"][0]["capacity"] = 100
    tiny_schedule_data["groups"][0]["size"] = 121
    tiny_schedule_data["courses"][0]["instances"][0]["students_needed"] = 121
    result = json.loads(solve_schedule(dumps(tiny_schedule_data), solver_config))
    # warn-policy: либо ERROR без schedule, либо SUCCESS с unplaced
    schedule = result.get("schedule") or []
    unplaced = result.get("unplaced") or []
    assert len(schedule) == 0
    assert unplaced or result.get("status") in {"ERROR", "NO_SOLUTION", "SUCCESS_WITH_WARNINGS"}


def test_sport_venue_uses_virtual_room(tiny_schedule_data, solver_config, dumps):
    course = tiny_schedule_data["courses"][0]
    course["venue_type"] = "sport"
    course["needs_physical_room"] = False
    course["instances"][0]["venue_type"] = "sport"
    course["instances"][0]["needs_physical_room"] = False
    result = json.loads(solve_schedule(dumps(tiny_schedule_data), solver_config))
    assert str(result["status"]).startswith("SUCCESS")
    assert len(result["schedule"]) == 1
    room_id = str(result["schedule"][0]["room_id"])
    assert room_id.startswith("__SPORT__") or room_id == "Спортзал"
