"""Оркестрация: Excel → парсер → солвер → Excel/JSON в папке прогона."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from exporter import export_result
from mvp_1 import solve_schedule
from parser.importer import Importer

StatusCb = Callable[[str], None]


def _status(cb: StatusCb | None, message: str) -> None:
    if cb:
        cb(message)


def new_run_dir(base: Path | None = None) -> Path:
    root = base or (ROOT / "runs")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = root / stamp
    (path / "inputs").mkdir(parents=True, exist_ok=True)
    return path


def save_upload(target: Path, data: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def run_pipeline(
    *,
    courses_bytes: bytes,
    rooms_bytes: bytes,
    desires_bytes: bytes,
    courses_name: str = "table.xlsx",
    rooms_name: str = "table2.xlsx",
    desires_name: str = "table3.xlsx",
    max_time: float = 900.0,
    strategy: str = "two_phase",
    parse_room_occupancy: bool = False,
    run_dir: Path | None = None,
    on_status: StatusCb | None = None,
) -> dict[str, Any]:
    """Полный прогон в отдельной папке runs/<id>/."""
    run_path = run_dir or new_run_dir()
    inputs = run_path / "inputs"

    courses_path = save_upload(inputs / Path(courses_name).name, courses_bytes)
    rooms_path = save_upload(inputs / Path(rooms_name).name, rooms_bytes)
    desires_path = save_upload(inputs / Path(desires_name).name, desires_bytes)

    data_path = run_path / "data.json"
    schedule_path = run_path / "schedule.xlsx"
    result_path = run_path / "result.json"
    meta_path = run_path / "meta.json"
    config_path = ROOT / "parser" / "config.json"

    _status(on_status, "Парсинг Excel…")
    importer = Importer(
        courses_file=courses_path,
        rooms_file=rooms_path,
        desires_file=desires_path,
        save_path=data_path,
        config=config_path if config_path.exists() else None,
        parse_room_occupancy=parse_room_occupancy,
    )
    data = importer.parse_from_excel()
    importer.save_to_json(data)

    course_count = len(data.get("courses") or [])
    instance_count = sum(len(c.get("instances") or []) for c in (data.get("courses") or []))
    _status(
        on_status,
        f"Парсинг готов: {course_count} курсов, {instance_count} занятий. Запуск солвера…",
    )

    solver_config = {
        "max_time_in_seconds": float(max_time),
        "solve_strategy": strategy,
    }
    result = json.loads(solve_schedule(json.dumps(data, ensure_ascii=False), solver_config))
    result["reserved_events"] = list(data.get("fixed_schedule_events") or [])

    _status(on_status, "Экспорт Excel…")
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    export_result(result, schedule_path, data)

    result_meta = result.get("meta") or {}
    groups = result.get("warning_groups") or {}
    meta = {
        "run_id": run_path.name,
        "status": result.get("status"),
        "lessons": len(result.get("schedule") or []),
        "warnings": len(result.get("warnings") or []),
        "unplaced": len(groups.get("unplaced") or result.get("unplaced") or []),
        "soft_remarks": len(groups.get("soft") or []),
        "errors": len(result.get("errors") or []),
        "solve_time_sec": result_meta.get("solve_time_sec"),
        "strategy": result_meta.get("solve_strategy") or strategy,
        "courses": course_count,
        "instances": instance_count,
        "paths": {
            "run_dir": str(run_path),
            "schedule_xlsx": str(schedule_path),
            "result_json": str(result_path),
            "data_json": str(data_path),
        },
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _status(on_status, f"Готово: {meta['status']}")
    return {
        "meta": meta,
        "result": result,
        "run_dir": run_path,
        "schedule_path": schedule_path,
        "result_path": result_path,
        "data_path": data_path,
    }
