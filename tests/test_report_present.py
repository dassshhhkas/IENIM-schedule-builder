"""Человекочитаемые формулировки отчёта."""

from app.report_present import (
    build_presentation,
    classify_user_category,
    humanize_soft_text,
    humanize_unplaced_reason,
    present_item,
)


def test_classify_user_categories():
    assert classify_user_category({"code": "UNPLACEABLE_INSTANCE_DROPPED"}) == "unplaced"
    assert classify_user_category({"code": "SCHEDULED_LATE_SLOT"}) == "late"
    assert classify_user_category({"code": "SCHEDULED_ON_SATURDAY"}) == "saturday"
    assert classify_user_category({"code": "UNMANAGED_TIME_WISH"}) == "raw_wish"


def test_humanize_unplaced_large_group():
    reason, advice = humanize_unplaced_reason(
        {
            "cause_code": "NO_FEASIBLE_ROOM",
            "students_needed": 330,
            "requirements": [],
            "message": "Нет подходящей аудитории",
        }
    )
    assert "330" in reason
    assert "вместительн" in advice.casefold() or "подгрупп" in advice.casefold()


def test_humanize_unplaced_slot_conflict():
    reason, _advice = humanize_unplaced_reason(
        {
            "cause_code": "NO_FEASIBLE_SLOT_OR_ROOM",
            "message": "не удалось поставить при текущих ограничениях",
        }
    )
    assert "время" in reason.casefold()
    assert "аудитор" in reason.casefold()


def test_humanize_soft_has_no_machine_codes():
    text = humanize_soft_text(
        {
            "code": "SCHEDULED_ON_SATURDAY",
            "name": "Иностранный язык (практика)",
            "message": "Курс x поставлен в субботу",
        }
    )
    assert "SCHEDULED" not in text
    assert "суббот" in text.casefold()
    assert "Иностранный язык" in text


def test_humanize_unmanaged_wish_readable():
    text = humanize_soft_text(
        {
            "code": "UNMANAGED_TIME_WISH",
            "course_id": "c6",
            "name": "Общая химия (лекция)",
            "time_wish_raw": "по ситуации",
            "reason": "no_rule",
        }
    )
    assert "по ситуации" in text
    assert "reason=" not in text


def test_build_presentation_structure(sample_result_with_warnings):
    presentation = build_presentation(sample_result_with_warnings)
    assert presentation["counts"]["unplaced"] == 1
    assert presentation["counts"]["saturday"] == 1
    assert presentation["counts"]["raw_wish"] == 1
    assert "непоставлен" in presentation["status_human"].casefold()
    unplaced = presentation["unplaced_rows"][0]
    assert unplaced["lesson"] == "Русский язык (лекция)"
    assert "330" in unplaced["text"]
    assert "UNPLACEABLE" not in unplaced["text"]
    remark = next(
        row for row in presentation["remark_rows"] if row["category"] == "saturday"
    )
    assert "суббот" in remark["text"].casefold()


def test_present_item_unplaced_fields():
    row = present_item(
        {
            "code": "UNPLACEABLE_INSTANCE_DROPPED",
            "name": "Математика (практика)",
            "group_ids": ["A", "B", "C", "D", "E"],
            "students_needed": 30,
            "requirements": ["screen", "board"],
            "cause_code": "NO_FEASIBLE_ROOM",
            "message": "по вместимости подходят, но не по оснащению",
        }
    )
    assert row["category"] == "unplaced"
    assert "и ещё 1" in row["groups"]
    assert "экран" in row["requirements"] or "доска" in row["text"].casefold()
