"""internet / screen не hard-kill; soft-штраф и proxy."""

from mvp_1 import (
    _missing_requirements_for_room,
    room_meets_requirements,
    room_satisfies_soft_equipment,
    soft_equipment_penalty,
)


def test_internet_and_screen_do_not_hard_block():
    room = {"id": "1", "capacity": 30, "has_board": True, "type": "лаб"}
    assert room_meets_requirements(room, ["internet"]) is True
    assert room_meets_requirements(room, ["screen"]) is True
    assert room_meets_requirements(room, ["board", "screen", "internet"]) is True


def test_hard_board_still_required():
    room = {"id": "1", "capacity": 30, "type": "лаб"}
    assert room_meets_requirements(room, ["board"]) is False


def test_computer_class_still_hard():
    assert room_meets_requirements({"id": "1", "type": "лаб"}, ["computer_class"]) is False
    assert room_meets_requirements({"id": "2", "type": "к"}, ["computer_class"]) is True
    assert room_meets_requirements({"id": "3", "type": "ИВЦ"}, ["computer_class"]) is True


def test_screen_proxy_from_room_type_m():
    assert room_satisfies_soft_equipment({"type": "м"}, "screen") is True
    assert room_satisfies_soft_equipment({"type": "лаб"}, "screen") is False
    assert room_satisfies_soft_equipment({"has_screen": True}, "screen") is True
    assert room_satisfies_soft_equipment({"has_multimedia_board": True}, "screen") is True


def test_internet_proxy_from_computer_class():
    assert room_satisfies_soft_equipment({"type": "к"}, "internet") is True
    assert room_satisfies_soft_equipment({"type": "лаб"}, "internet") is False
    assert room_satisfies_soft_equipment({"has_wifi": True}, "internet") is True


def test_soft_equipment_penalty_for_screen():
    plain = {"id": "1", "type": "лаб"}
    with_screen = {"id": "2", "has_screen": True}
    assert soft_equipment_penalty(plain, ["screen"], weight_screen=3) == 3
    assert soft_equipment_penalty(with_screen, ["screen"], weight_screen=3) == 0
    assert soft_equipment_penalty(plain, ["internet"], weight_screen=3) == 0


def test_missing_requirements_skips_soft_codes():
    room = {"id": "1", "has_board": True}
    missing = _missing_requirements_for_room(room, ["board", "screen", "internet", "software"])
    assert missing == []
