import re
from pathlib import Path


class Entities:
    data_dir = Path(__file__).resolve().parent.parent / "tables"
    config_file = Path(__file__).resolve().parent.parent / "config.json"
    rooms_file = data_dir / "table2.xlsx"
    rooms_sheet = "Аудитории"
    courses_file = data_dir / "table.xlsx"
    desires_file = data_dir / "table3.xlsx"
    pe_sheet = "Физ.культура"
    pe_institute = "ИЕНиМ"
    course_sheets = ["ХИМИКИ", "ФИНЗ", "ФИНЗ Магистры", "ЭБМ", "Тургенева 4 по выбору", "Тургенева 4"]
    days = ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА"]
    default_group_size = 30
    fixed_course_names = {"Прикладная физическая культура (практика)"}

    feature_columns = ["has_chalkboard", "has_whiteboard", "has_multimedia_board",
                       "has_blinds", "has_screen", "has_acoustic_system"]
    room_renames = {"Ауд.": "id", "Вид": "type", "Вм-ть": "capacity",
                    "меловая": "has_chalkboard",
                    "маркерная": "has_whiteboard", "мультимедиа": "has_multimedia_board",
                    "жалюзи": "has_blinds", "экран": "has_screen", "акустич. система": "has_acoustic_system"}
    dropped_room_columns = ["Кому принадлежит", "С кем договариваться", "Примечание"]
    teacher_columns = {"лекция": "ФИО лектора", "практика": "ФИО преподавателя на практики, лаборатории",
                       "лабораторная": "ФИО преподавателя на практики, лаборатории"}
    hours_columns = {"лекция": "Лекции", "практика": "Практ. занятия", "лабораторная": "Лаб. занятия"}
    group_column = "Номер группы"
    discipline_column = "Дисциплины"
    students_column = "Число студентов"
    projector_column = "Нужен ли проектор на практики, лаборатории"
    multimedia_column = "Нужна ли мультимедиа на лекции?"
    board_column = "Какая нужна доска на практики, лаборатории: меловая, маркерная, любая"
    software_column = "ПО на практики, лаборатории"
    location_column = "Где проводятся практики, лаборатории?"
    ntk_column = "НТК"
    delivery_model_column = "Модель реализации"
    time_wish_column = ("Пожелания по времени пар (дни недели, утро/вечер, "
                        "середина дня, ограничения по кол-ву пар в день "
                        "по медицинским показаниям)")
    comments_column = "Комментарий, особенности дисциплины"
    room_requirement_labels = {
        "любая доска": "board", "меловая доска": "chalkboard",
        "маркерная доска": "whiteboard", "мультимедиа доска": "multimedia_board",
        "экран": "screen", "жалюзи": "blinds", "акустическая система": "acoustic_system",
    }
    room_ref_pattern = re.compile(
        r"(?<!\d)\d{3}(?:/\d{1,2})?(?:\s?[а-яё](?![а-яё]))?(?!\d)", re.IGNORECASE)
    same_room_pattern = re.compile(
        r"(?:вместе\s+с\s+лекц\w*|там\s+же[,\s]*где\s+и\s+лекц\w*|"
        r"как\s+и\s+лекц\w*|где\s+и\s+лекц\w*|как\s+лекц\w*)", re.IGNORECASE)
    generic_location_pattern = re.compile(
        r"^\s*(?:любая|в\s+|аудитория|аудиторно|ауд\b|обычн|онлайн|online|"
        r"нет|не\s+проводится|уточняется|больш|класс|кабинет|комп|ивц|"
        r"ит-центр|информационн|тургенева|куйбышева|литер|корпус|этаж|"
        r"\d+\s*этаж|отдельн|на\s|лабораторн|практик|лекци)", re.IGNORECASE)
    # Canonical header -> accepted variants. Variants that differ only by case,
    # whitespace or "ё" are matched by _normalize_header without an explicit entry.
    header_aliases = {
        "Курс": ("Курс обучения",),
        "Номер группы": ("№ группы", "Группа"),
        "Число студентов": ("Количество студентов", "Численность студентов"),
        "Дисциплины": ("Дисциплина", "Наименование дисциплины"),
        "Лекции": ("Лекционные занятия", "Лекции, ч"),
        "Практ. занятия": ("Практические занятия", "Практ. занятия, ч"),
        "Лаб. занятия": ("Лабораторные занятия", "Лаб. занятия, ч"),
        "Зачет / экзамен": ("зачет /экзамен", "Зачёт/экзамен",
                            "Отчетное мероприятие: Зачет / экзамен"),
        "ФИО лектора": ("Лектор",),
        "ФИО преподавателя на практики, лаборатории": (
            "ФИО преподавателя на практики/лаборатории",
            "ФИО преподавателя на практические занятия, лаборатории"),
        "Нужна ли мультимедиа на лекции?": ("Нужна ли мультимедиа на лекции",),
        "Нужен ли проектор на практики, лаборатории": (
            "Нужен ли проектор на практики, лаборатории?",),
        "Какая нужна доска на практики, лаборатории: меловая, маркерная, любая": (
            "Какая нужна доска на практики, лаборатории: меловая, маркерная или любая",),
        "Кол-во подгрупп на практич и лаб. занятия": (
            "Кол-во подгрупп на практические и лабораторные занятия",),
    }
    subgroup_column = "Кол-во подгрупп на практич и лаб. занятия"
    # Session / report columns are isolated from weekly courses (п.13).
    session_field_markers = (
        ("teacher_name", ("принимающего отчетное",)),
        ("time_window_raw", ("время начала",)),
        ("consultation_raw", ("консультация",)),
        ("free_days_min", ("свободных дней",)),
        ("room_requirement_raw", ("какая нужна аудитория",)),
        ("scope_raw", ("особенности проведения",)),
        ("date_windows_raw", ("поставить отчетные",)),
        ("restrictions_raw", ("ограничения по датам",)),
        ("note_raw", ("дополнительные особенности", "примечание:")),
        ("report_format", ("вид отчетного",)),
        ("report_type", ("зачет / экзамен", "зачет /экзамен", "отчетное мероприятие")),
    )
    teacher_segment_pattern = re.compile(
        r"[,;\n]+|\s+или\s+|\s*\+\s*|(?<![А-Яа-яЁё])/(?![А-Яа-яЁё])")
    teacher_name_pattern = re.compile(
        r"(?:"
        r"[А-ЯЁA-Z][а-яёa-z-]+"
        r"(?:"
        r"\s+[А-ЯЁA-Z]\.(?:\s*[А-ЯЁA-Z]\.?(?![а-яёa-z]))?"
        r"|\s+[А-ЯЁA-Z]\s?[А-ЯЁA-Z](?![а-яёa-z])"
        r")"
        r"|"
        r"[А-ЯЁA-Z]\.(?:\s*[А-ЯЁA-Z]\.)?\s*[А-ЯЁA-Z][а-яёa-z-]+"
        r")")
    latin_name_letters = str.maketrans(
        {"A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К",
         "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х"})
    initials_first_pattern = re.compile(
        r"^([А-ЯЁA-Z]\.)\s*([А-ЯЁA-Z]\.)?\s*([А-ЯЁA-Z][а-яёa-z-]+)$")
    dotless_initials_pattern = re.compile(
        r"^([А-ЯЁA-Z][а-яёa-z-]+)\s+([А-ЯЁA-Z])\s?([А-ЯЁA-Z])$")
    teacher_full_name_pattern = re.compile(
        r"[А-ЯЁ][а-яё-]+\s+[А-ЯЁ][а-яё-]+(?:\s+[А-ЯЁ][а-яё-]+)?")
    team_marker_pattern = re.compile(
        r"(?P<count>\d+)?\s*(?P<kind>команд\w*|подгрупп\w*|подгр\w*|п/гр\w*|групп\w*)",
        re.IGNORECASE)
    parenthesized_count_pattern = re.compile(r"\(\s*(\d+)\s*\)")
    subgroup_type_pattern = re.compile(r"\b(лаб\w*|практ\w*|пр\.)", re.IGNORECASE)

    # --- Пункт 9: тип площадки ------------------------------------------------
    venue_online_pattern = re.compile(
        r"(?:^|[^\w])(?:онлайн|online|дистанционн\w*|в\s+онлайн[-\s]?формате)(?:[^\w]|$)")
    venue_room_pattern = re.compile(
        r"аудитор|ауд\b|класс|кабинет|лаборатор|очно|ивц|ит-центр|"
        r"этаж|корпус|доск|проектор|любая|больш|обычн|тургенева|куйбышева|литер")
    venue_campus_pattern = re.compile(r"тургенева|куйбышева|литер")
    venue_external_pattern = re.compile(
        r"\b(?:имм\s+уро\s+ран|уро\s+ран|униим|ран)\b|"
        r"\b(?:ооо|ао|пао|зао)\b|на\s+предприятии|в\s+организации|обсерватори")
    venue_comment_external_pattern = re.compile(
        r"занятия\s+(?:проводятся|проходят)\s+в\s+"
        r"(?:имм\s+уро\s+ран|униим|ран|ооо|ао|пао|зао|организации|институте)")
    venue_no_room_pattern = re.compile(r"^\s*(?:нет|не\s+требуется|не\s+проводится)\s*$")

    # --- Пункт 10: пожелания по времени --------------------------------------
    day_patterns = (
        ("ПОНЕДЕЛЬНИК", re.compile(r"\b(?:понедельник\w*|понед\w*|пн)\b", re.IGNORECASE)),
        ("ВТОРНИК", re.compile(r"\b(?:вторник\w*|вт)\b", re.IGNORECASE)),
        ("СРЕДА", re.compile(r"\b(?:сред[аыуе]\w*|ср)\b", re.IGNORECASE)),
        ("ЧЕТВЕРГ", re.compile(r"\b(?:четверг\w*|четвер\w*|чт)\b", re.IGNORECASE)),
        ("ПЯТНИЦА", re.compile(r"\b(?:пятниц\w*|пятн\w*|пт)\b", re.IGNORECASE)),
        ("СУББОТА", re.compile(r"\b(?:суббот\w*|суб\w*|сб)\b", re.IGNORECASE)),
    )
    pair_word_values = {
        "перв": 1, "втор": 2, "трет": 3, "четверт": 4, "пят": 5, "шест": 6,
    }
    pair_count_word_values = {
        "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6,
    }
    pair_range_pattern = re.compile(
        r"(?<![\d,.])(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?"
        r"\s*(?:-?(?:й|я|ю|ой|ий|ая|ую))?\s*пар(?:а|ы|у|ам|ами|е)?\b",
        re.IGNORECASE)
    pair_word_pattern = re.compile(
        r"\b(перв|втор|трет|четверт|пят|шест)\w*\s+пар(?:а|ы|у|ам|ами|е)?\b",
        re.IGNORECASE)
    pair_count_word_pattern = re.compile(
        r"\b(?:первые|первых)?\s*(два|две|три|четыре|пять|шесть)\s+"
        r"пар(?:а|ы|у|ам|ами|е)?\b", re.IGNORECASE)
    pair_bound_pattern = re.compile(
        r"\b(?P<prep>не\s+раньше|не\s+ранее|не\s+позже|не\s+позднее|"
        r"начиная\s+со?|после|со?|до)\s+"
        r"(?:(?P<num>\d{1,2})|(?P<word>перв\w*|втор\w*|трет\w*|"
        r"четверт\w*|пят\w*|шест\w*))\s+пар(?:а|ы|у|ам|ами|е)?\b",
        re.IGNORECASE)
    time_clause_pattern = re.compile(
        r"\b(?P<prep>не\s+раньше|не\s+ранее|не\s+позже|не\s+позднее|"
        r"начиная\s+со?|после|со?|до)\s+"
        r"(?P<hour>\d{1,2})(?:[:.](?P<minute>\d{2})|-(?P<minute2>\d{2}))",
        re.IGNORECASE)
    max_pairs_day_pattern = re.compile(
        r"\b(?:не\s+более|не\s+больше|максимум|макс\.?)\s+"
        r"(\d{1,2})\s+пар(?:ы)?\s+в\s+день\b", re.IGNORECASE)
    day_part_patterns = (
        ("morning", re.compile(
            r"\bутр\w*|перв(?:ая|ой|ую)?\s+половин\w*\s+(?:дня|день)",
            re.IGNORECASE)),
        ("afternoon", re.compile(
            r"втор(?:ая|ой|ую)?\s+половин\w*\s+(?:дня|день)|"
            r"после\s+обеда|середин\w*\s+(?:дня|день)|"
            r"\bднем\b", re.IGNORECASE)),
        ("evening", re.compile(r"\bвечер\w*", re.IGNORECASE)),
    )
    wish_negation_pattern = re.compile(
        r"\bне\b|нельзя|нежелат|исключ|кроме|запрещ", re.IGNORECASE)
    wish_soft_pattern = re.compile(
        r"по\s+возможности|желательно|лучше|предпочтительн\w*",
        re.IGNORECASE)
    wish_positive_pattern = re.compile(
        r"\b(?:по)?ставить\b|\bставим\b|\bжелательно\b|\bлучше\b|"
        r"\bпредпочтительн\w*|\bможно\b", re.IGNORECASE)
    wish_segment_pattern = re.compile(r"[;\n]+|(?<=\.)\s+(?=[А-ЯЁA-Z0-9])")

    # --- Пункт 11: комментарии -----------------------------------------------
    comment_online_pattern = re.compile(
        r"\bонлайн\b|\bonline\b|в\s+контур\b|"
        r"дистанционн\w*\s+(?:формат\w*|обучен\w*|занят\w*|курс\w*|"
        r"проведен\w*|режим\w*)", re.IGNORECASE)
    comment_duration_hours_pattern = re.compile(
        r"(\d+(?:[.,]\d+)?)\s*(?:ак\.?\s*)?час\w*")
    comment_duration_double_pattern = re.compile(
        r"сдвоен\w*|пар\w*\s+подряд|подряд\s+пар\w*|без\s+окна")
    comment_duration_half_pattern = re.compile(
        r"полтор\w*\s+пар\w*|1[.,]5\s+пар\w*")
    comment_duration_pairs_pattern = re.compile(
        r"(?:по\s+)?(две|три|четыре|пять|шесть|\d+)\s+пар\w*\s+подряд")
    comment_period_pattern = re.compile(
        r"\bс\s+(\d{1,2}\.\d{1,2}\.\d{2,4})\s+по\s+"
        r"(\d{1,2}\.\d{1,2}\.\d{2,4})")
    comment_week_range_patterns = (
        re.compile(r"\bс\s+(\d{1,2})\s+по\s+(\d{1,2})\s+недел"),
        re.compile(r"\b(\d{1,2})\s*[-–]\s*(\d{1,2})\s+недел"),
    )
    comment_week_chain_pattern = re.compile(
        r"\bс\s+(\d{1,2})\s+по\s+(\d{1,2})(?=\s*(?:,|и|недел))",
        re.IGNORECASE)
    comment_week_list_pattern = re.compile(
        r"\bнедели\s+([\d,\s\-–и]+)", re.IGNORECASE)
    comment_semester_half_pattern = re.compile(
        r"(перв|втор)\w*\s+половин\w*\s+семестра")
