import argparse
from pathlib import Path

from parser.entities.table_entities import Entities
from parser.importer import Importer


def build_arg_parser() -> argparse.ArgumentParser:
    """Describe the parser CLI. Defaults point at parser/tables, not the cwd."""
    data_dir = Path(__file__).resolve().parent / "tables"
    parser = argparse.ArgumentParser(
        prog="python -m parser.importer",
        description="Собрать JSON для солвера из Excel-файлов нагрузки, аудиторий и анкеты.")
    parser.add_argument(
        "--courses", dest="courses_file", type=Path, default=data_dir / "table.xlsx",
        help="Excel с нагрузкой (по умолчанию parser/tables/table.xlsx)")
    parser.add_argument(
        "--rooms", "--reference", dest="rooms_file", type=Path,
        default=data_dir / "table2.xlsx",
        help="Excel с каталогом аудиторий, сеткой слотов и эталонной занятостью "
             "(по умолчанию parser/tables/table2.xlsx)")
    parser.add_argument(
        "--desires", dest="desires_file", type=Path,
        default=data_dir / "table3.xlsx",
        help="Excel с анкетой преподавателей (по умолчанию parser/tables/table3.xlsx)")
    parser.add_argument(
        "--config", dest="config_file", type=Path, default=None,
        help="JSON-конфиг парсера (по умолчанию parser/config.json)")
    parser.add_argument(
        "--save", dest="save_path", type=Path,
        default=Path(__file__).resolve().parent / "data.json",
        help="Куда сохранить итоговый JSON (по умолчанию parser/data.json)")
    parser.add_argument(
        "--parse-room-occupancy", action="store_true",
        help="Читать эталонную занятость из листа «Аудитории» в room_preblocked")
    parser.add_argument(
        "--rooms-sheet", default=Entities.rooms_sheet,
        help=f"Имя листа аудиторий (по умолчанию {Entities.rooms_sheet!r})")
    parser.add_argument(
        "--pe-sheet", default=Entities.pe_sheet,
        help=f"Имя листа физкультуры (по умолчанию {Entities.pe_sheet!r})")
    return parser


def run(*args, **kwargs) -> None:
    if args or kwargs:
        importer = Importer(*args, **kwargs)
    else:
        options = build_arg_parser().parse_args()
        importer = Importer(
            rooms_file=options.rooms_file,
            rooms_sheet=options.rooms_sheet,
            courses_file=options.courses_file,
            desires_file=options.desires_file,
            save_path=options.save_path,
            config=options.config_file,
            parse_room_occupancy=options.parse_room_occupancy,
            pe_sheet=options.pe_sheet,
        )
    importer.save_to_json(importer.parse_from_excel())


if __name__ == "__main__":
    run()
