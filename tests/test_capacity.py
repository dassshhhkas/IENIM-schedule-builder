"""Hard-вместимость с запасом +20%."""

from mvp_1 import (
    effective_room_capacity,
    room_fits_students,
    room_is_feasible,
    resolve_capacity_overbook_factor,
)


def test_default_overbook_factor_is_1_2():
    assert resolve_capacity_overbook_factor() == 1.2
    assert resolve_capacity_overbook_factor({}) == 1.2


def test_effective_capacity_adds_20_percent():
    assert effective_room_capacity(100) == 120
    assert effective_room_capacity(100, overbook_factor=1.2) == 120
    assert effective_room_capacity(50, overbook_factor=1.2) == 60


def test_room_fits_students_boundary():
    assert room_fits_students(100, 120) is True
    assert room_fits_students(100, 121) is False
    assert room_fits_students(100, 100) is True
    assert room_fits_students(None, 10) is False


def test_room_is_feasible_uses_overbook():
    room = {"id": "1", "capacity": 100, "has_board": True}
    assert room_is_feasible(room, total_students=120, requirements=["board"]) is True
    assert room_is_feasible(room, total_students=121, requirements=["board"]) is False
