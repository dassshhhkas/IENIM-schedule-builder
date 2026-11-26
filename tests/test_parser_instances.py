"""Автонарезка подгрупп и sport/PE флаги парсера."""

from parser.importer import Importer


def _teacher_meta(name: str = "Иванов И.И.") -> dict:
    return {
        "raw": name,
        "specs": [{"name": name, "team_count": None, "team_label": None, "team_index": None}],
        "cell_hint": 1,
        "cell_label": None,
        "unresolved": [],
    }


def test_practice_without_subgroup_count_splits_by_group():
    importer = Importer()
    specs = _teacher_meta()["specs"]
    meta = _teacher_meta()
    instances, count = importer._build_course_instances(
        "c100",
        "Иностранный язык (практика)",
        "практика",
        specs,
        meta,
        column_count=1,
        group_ids=["G1", "G2", "G3"],
        requirements=[],
        sheet_name="Тургенева 4",
    )
    assert count == 3
    assert len(instances) == 3
    assert [inst["group_ids"] for inst in instances] == [["G1"], ["G2"], ["G3"]]
    assert all(inst["lesson_kind"] == "practice_subgroup" for inst in instances)
    assert any("автонарезка" in warning for warning in importer._warnings)


def test_lecture_with_many_groups_stays_one_instance():
    importer = Importer()
    specs = _teacher_meta()["specs"]
    meta = _teacher_meta()
    instances, count = importer._build_course_instances(
        "c101",
        "Математика (лекция)",
        "лекция",
        specs,
        meta,
        column_count=1,
        group_ids=["G1", "G2", "G3"],
        requirements=[],
        sheet_name="ХИМИКИ",
    )
    assert count == 1
    assert len(instances) == 1
    assert instances[0]["group_ids"] == ["G1", "G2", "G3"]
    assert instances[0]["lesson_kind"] == "lecture_stream"


def test_explicit_subgroup_count_keeps_shared_groups():
    importer = Importer()
    specs = _teacher_meta()["specs"]
    meta = _teacher_meta()
    instances, count = importer._build_course_instances(
        "c102",
        "Иностранный язык (практика)",
        "практика",
        specs,
        meta,
        column_count=2,
        group_ids=["G1", "G2"],
        requirements=[],
        sheet_name="ХИМИКИ",
    )
    assert count == 2
    assert len(instances) == 2
    assert instances[0]["group_ids"] == ["G1", "G2"]
    assert instances[1]["group_ids"] == ["G1", "G2"]


def test_finalize_assigns_students_per_group_after_split():
    importer = Importer()
    importer._groups = {
        "G1": {"id": "G1", "size": 24},
        "G2": {"id": "G2", "size": 28},
    }
    course = {
        "id": "c200",
        "discipline": "Иностранный язык",
        "lesson_type": "практика",
        "group_ids": ["G1", "G2"],
        "teacher_ids": ["Иванов И.И."],
        "subgroup_count": 1,
        "venue_type": "room",
        "instances": [
            {
                "id": "c200_i1",
                "teacher_ids": ["Иванов И.И."],
                "group_ids": ["G1", "G2"],
                "requirements": [],
                "venue_type": "room",
            }
        ],
    }
    importer._finalize_course_instances([course])
    assert len(course["instances"]) == 2
    assert course["subgroup_count"] == 2
    by_group = {inst["group_ids"][0]: inst["students_needed"] for inst in course["instances"]}
    assert by_group == {"G1": 24, "G2": 28}


def test_sport_course_gets_needs_physical_room_false():
    importer = Importer()
    importer._groups = {"G1": {"id": "G1", "size": 20}}
    # минимальный путь: finalize на уже собранном sport-курсе
    course = {
        "id": "c_pe",
        "discipline": "Прикладная физическая культура",
        "lesson_type": "практика",
        "group_ids": ["G1"],
        "teacher_ids": [],
        "subgroup_count": 1,
        "venue_type": "sport",
        "allowed_room_ids": ["304"],
        "instances": [
            {
                "id": "c_pe_i1",
                "teacher_ids": [],
                "group_ids": ["G1"],
                "requirements": ["screen"],
                "venue_type": "sport",
                "allowed_room_ids": ["304"],
            }
        ],
    }
    importer._finalize_course_instances([course])
    assert course["needs_physical_room"] is False
    assert course["allowed_room_ids"] == []
    assert course["instances"][0]["needs_physical_room"] is False
    assert course["instances"][0]["allowed_room_ids"] == []
    assert course["instances"][0]["venue_type"] == "sport"
