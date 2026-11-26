"""Excel-экспорт: человекочитаемые листы сводки/непоставленных/замечаний."""

from openpyxl import load_workbook

from exporter import export_result


def test_export_creates_human_readable_sheets(tmp_path, sample_result_with_warnings):
    source = {
        "groups": [{"id": "G1", "size": 25}, {"id": "G2", "size": 25}],
        "time_slots": [
            {"id": 1, "day": "Понедельник", "slot_index": 1, "time": "08:30-10:00"},
        ],
        "courses": [
            {"id": "c2", "discipline": "Иностранный язык", "lesson_type": "практика"},
            {"id": "c4", "discipline": "Русский язык", "lesson_type": "лекция"},
        ],
        "config": {"semester_weeks": 16},
    }
    target = tmp_path / "schedule.xlsx"
    export_result(sample_result_with_warnings, target, source)
    assert target.exists()

    workbook = load_workbook(target)
    assert workbook.sheetnames[:4] == ["Сводка", "Расписание", "Непоставленные", "Замечания"]

    summary = workbook["Сводка"]
    assert "Итог" in str(summary["A1"].value)

    unplaced = workbook["Непоставленные"]
    headers = [cell.value for cell in unplaced[1]]
    assert headers == ["Занятие", "Группы", "Студентов", "Почему не встало", "Что проверить"]
    assert "Русский язык" in str(unplaced["A2"].value)
    assert "330" in str(unplaced["D2"].value)
    # без машинных кодов в пользовательских колонках
    for column in ("A", "D", "E"):
        assert "UNPLACEABLE" not in str(unplaced[f"{column}2"].value or "")

    remarks = workbook["Замечания"]
    remark_headers = [cell.value for cell in remarks[1]]
    assert "Тип замечания" in remark_headers
    assert "Код" not in remark_headers
    blob = " ".join(
        str(cell.value or "")
        for row in remarks.iter_rows(min_row=2, max_row=10, max_col=4)
        for cell in row
    )
    assert "суббот" in blob.casefold()
    assert "SCHEDULED_ON_SATURDAY" not in blob
