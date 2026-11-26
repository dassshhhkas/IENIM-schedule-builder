"""Классификация warnings солвера."""

from mvp_1 import classify_warning_kind, partition_warnings


def test_classify_unplaced_vs_soft():
    assert classify_warning_kind({"code": "UNPLACEABLE_INSTANCE_DROPPED"}) == "unplaced"
    assert classify_warning_kind({"code": "SCHEDULED_ON_SATURDAY"}) == "soft"
    assert classify_warning_kind({"code": "UNMET_SOFT_EQUIPMENT"}) == "soft"
    assert classify_warning_kind({"code": "SOME_UNKNOWN"}) == "other"


def test_partition_warnings_groups():
    warnings = [
        {"code": "UNPLACEABLE_INSTANCE_DROPPED"},
        {"code": "UNPLACEABLE_INSTANCE_DROPPED"},
        {"code": "SCHEDULED_LATE_SLOT"},
        {"code": "CUSTOM"},
    ]
    groups = partition_warnings(warnings)
    assert len(groups["unplaced"]) == 2
    assert len(groups["soft"]) == 1
    assert len(groups["other"]) == 1
