"""Локальный веб-интерфейс: загрузка Excel → расписание → скачивание."""

from __future__ import annotations

import traceback
from pathlib import Path

import streamlit as st

from app.pipeline import run_pipeline
from app.report_present import build_presentation

st.set_page_config(
    page_title="Конструктор расписания ИЕНИМ",
    layout="centered",
)

st.title("Конструктор расписания ИЕНИМ")
st.caption("Загрузите три Excel-файла, дождитесь расчёта и скачайте готовое расписание.")

with st.form("schedule_form"):
    st.subheader("Входные файлы")
    courses_file = st.file_uploader(
        "Нагрузка (курсы и группы)",
        type=["xlsx"],
        help="Обычно table.xlsx",
        key="courses",
    )
    rooms_file = st.file_uploader(
        "Аудитории и сетка слотов",
        type=["xlsx"],
        help="Обычно table2.xlsx",
        key="rooms",
    )
    desires_file = st.file_uploader(
        "Анкета преподавателей",
        type=["xlsx"],
        help="Обычно table3.xlsx",
        key="desires",
    )

    with st.expander("Параметры расчёта", expanded=False):
        max_time = st.number_input(
            "Лимит времени солвера, секунд",
            min_value=30,
            max_value=3600,
            value=900,
            step=30,
        )
        strategy = st.selectbox(
            "Стратегия",
            options=["two_phase", "auto", "monolithic"],
            index=0,
            help="Для полного набора лучше two_phase",
        )
        parse_room_occupancy = st.checkbox(
            "Учитывать занятость аудиторий из справочника",
            value=False,
        )

    submitted = st.form_submit_button("Собрать расписание", type="primary", use_container_width=True)

if submitted:
    missing = [
        label
        for label, f in (
            ("нагрузка", courses_file),
            ("аудитории", rooms_file),
            ("анкета", desires_file),
        )
        if f is None
    ]
    if missing:
        st.error("Загрузите все три файла: " + ", ".join(missing))
    else:
        status_box = st.empty()
        progress = st.progress(0, text="Подготовка…")

        def on_status(message: str) -> None:
            status_box.info(message)
            lower = message.casefold()
            if "парсинг excel" in lower:
                progress.progress(10, text=message)
            elif "парсинг готов" in lower:
                progress.progress(25, text=message)
            elif "экспорт" in lower:
                progress.progress(85, text=message)
            elif "готово" in lower:
                progress.progress(100, text=message)
            else:
                progress.progress(55, text=message)

        try:
            outcome = run_pipeline(
                courses_bytes=courses_file.getvalue(),
                rooms_bytes=rooms_file.getvalue(),
                desires_bytes=desires_file.getvalue(),
                courses_name=courses_file.name or "table.xlsx",
                rooms_name=rooms_file.name or "table2.xlsx",
                desires_name=desires_file.name or "table3.xlsx",
                max_time=float(max_time),
                strategy=strategy,
                parse_room_occupancy=parse_room_occupancy,
                on_status=on_status,
            )
            st.session_state["last_run"] = outcome
        except Exception as exc:  # noqa: BLE001 — показать пользователю
            progress.empty()
            status_box.empty()
            st.error(f"Не удалось выполнить расчёт: {exc}")
            with st.expander("Технические подробности"):
                st.code(traceback.format_exc())
            st.stop()

        progress.progress(100, text="Готово")
        status_box.empty()

if "last_run" in st.session_state:
    outcome = st.session_state["last_run"]
    meta = outcome["meta"]
    result = outcome.get("result") or {}
    presentation = build_presentation(result)

    status_human = presentation["status_human"]
    unplaced_n = len(presentation["unplaced_rows"])
    soft_n = len(presentation["remark_rows"])

    if str(meta.get("status") or "").startswith("SUCCESS"):
        st.success(status_human)
    elif meta.get("status") == "NO_SOLUTION":
        st.warning(status_human)
    else:
        st.error(status_human)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Поставлено", meta.get("lessons", len(result.get("schedule") or [])))
    c2.metric("Не поставлено", unplaced_n)
    c3.metric("Замечаний", soft_n)
    c4.metric("Время, с", meta.get("solve_time_sec", "—"))

    if presentation["counts"]:
        st.subheader("По типам")
        for key in presentation["category_order"]:
            count = presentation["counts"].get(key) or 0
            if not count:
                continue
            title = presentation["category_titles"][key]
            hint = presentation["category_hints"][key]
            rows = presentation["by_category"].get(key) or []
            with st.expander(f"{title} — {count}", expanded=(key == "unplaced" and count > 0)):
                st.caption(hint)
                if key == "unplaced":
                    st.dataframe(
                        [
                            {
                                "Занятие": row["lesson"],
                                "Группы": row["groups"],
                                "Студентов": row["students"],
                                "Почему": row["text"],
                                "Что проверить": row["advice"],
                            }
                            for row in rows[:300]
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                    if len(rows) > 300:
                        st.caption(f"Показаны первые 300 из {len(rows)}. Полный список — в Excel.")
                else:
                    st.dataframe(
                        [
                            {
                                "Занятие": row["lesson"],
                                "Группы": row["groups"],
                                "Подробности": row["text"],
                            }
                            for row in rows[:300]
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                    if len(rows) > 300:
                        st.caption(f"Показаны первые 300 из {len(rows)}. Полный список — в Excel.")

    schedule_path = Path(outcome["schedule_path"])
    result_path = Path(outcome["result_path"])

    st.subheader("Скачать результат")
    d1, d2 = st.columns(2)
    if schedule_path.exists():
        d1.download_button(
            "Расписание Excel",
            data=schedule_path.read_bytes(),
            file_name="schedule.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    if result_path.exists():
        d2.download_button(
            "Технический JSON (для разработчиков)",
            data=result_path.read_bytes(),
            file_name="result.json",
            mime="application/json",
            use_container_width=True,
        )

    st.caption(
        "В Excel: листы «Сводка», «Расписание», «Непоставленные», «Замечания». "
        f"Копия прогона: {meta['paths']['run_dir']}"
    )
