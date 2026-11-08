import json
import math
from pathlib import Path

from ortools.sat.python import cp_model

DEFAULT_DATA_PATH = Path(__file__).resolve().parent / "parser" / "data.json"


def load_data(path: str | Path = DEFAULT_DATA_PATH) -> dict:
    """Загрузить JSON, сформированный парсером."""
    with Path(path).open(encoding="utf-8") as file:
        return json.load(file)


def prepare_parser_data(data: dict) -> dict:
    """Привести данные парсера к схеме, которую ожидает solve_schedule."""
    courses = []
    for course in data["courses"]:
        hours = course.get("hours_per_semester") or 0
        courses.append({
            **course,
            "lessons_per_week": max(1, math.ceil(hours / 32)),
        })
    return {**data, "courses": courses}


def solve_schedule(input_json_str: str) -> str:
    # 1. Загрузка данных из входного JSON
    data = json.loads(input_json_str)
    
    rooms = data["rooms"]
    teachers = data["teachers"]
    groups = data["groups"]
    time_slots = data["time_slots"]
    courses = data["courses"]
    
    # Словари для быстрого поиска вместимости и размеров групп
    group_sizes = {g["id"]: g["size"] for g in groups}
    
    # 2. Создание модели CP-SAT
    model = cp_model.CpModel()
    
    # Раскрываем курсы на отдельные занятия (экземпляры) в зависимости от lessons_per_week
    course_instances = []
    for c in courses:
        total_students = sum(group_sizes.get(gid, 0) for gid in c["group_ids"])
        for inst_idx in range(c["lessons_per_week"]):
            course_instances.append({
                "instance_id": f"{c['id']}_inst_{inst_idx}",
                "course_id": c["id"],
                "name": c["name"],
                "teacher_id": c["teacher_id"],
                "group_ids": c["group_ids"],
                "total_students": total_students
            })
            
    # 3. Переменные решения
    # x[instance_id, slot_id, room_id] = 1, если занятие проходит в этом слоте и аудитории
    x = {}
    for inst in course_instances:
        for s in time_slots:
            for r in rooms:
                if r["capacity"] >= inst["total_students"]:
                    var_name = f"x_{inst['instance_id']}_s{s['id']}_r{r['id']}"
                    x[(inst["instance_id"], s["id"], r["id"])] = model.NewBoolVar(var_name)

    # 4. Ограничения (Constraints)

    # Ограничение A: Каждая пара должна состояться ровно один раз в каком-то слоте и аудитории
    for inst in course_instances:
        possible_vars = [
            x[(inst["instance_id"], s["id"], r["id"])]
            for s in time_slots for r in rooms
            if (inst["instance_id"], s["id"], r["id"]) in x
        ]
        if not possible_vars:
            return json.dumps({
                "status": "ERROR", 
                "message": f"Нет подходящей по вместимости аудитории для курса '{inst['name']}'"
            }, ensure_ascii=False)
            
        model.AddExactlyOne(possible_vars)

    # Ограничение B: Занятость аудитории (не более 1 занятия в аудитории в 1 таймслот)
    for s in time_slots:
        for r in rooms:
            vars_in_room_slot = [
                x[(inst["instance_id"], s["id"], r["id"])]
                for inst in course_instances
                if (inst["instance_id"], s["id"], r["id"]) in x
            ]
            if vars_in_room_slot:
                model.Add(sum(vars_in_room_slot) <= 1)

    # Ограничение C: Занятость преподавателя (не более 1 занятия у препода в 1 таймслот)
    for s in time_slots:
        for t in teachers:
            vars_for_teacher = [
                x[(inst["instance_id"], s["id"], r["id"])]
                for inst in course_instances if inst["teacher_id"] == t["id"]
                for r in rooms
                if (inst["instance_id"], s["id"], r["id"]) in x
            ]
            if vars_for_teacher:
                model.Add(sum(vars_for_teacher) <= 1)

    # Ограничение D: Занятость группы (не более 1 пары у группы в 1 таймслот)
    for s in time_slots:
        for g in groups:
            vars_for_group = [
                x[(inst["instance_id"], s["id"], r["id"])]
                for inst in course_instances if g["id"] in inst["group_ids"]
                for r in rooms
                if (inst["instance_id"], s["id"], r["id"]) in x
            ]
            if vars_for_group:
                model.Add(sum(vars_for_group) <= 1)

    # 5. Запуск Солвера
    solver = cp_model.CpSolver()
    # Установка лимита времени (например, 10 секунд для MVP)
    solver.parameters.max_time_in_seconds = 10.0
    
    status = solver.Solve(model)
    
    # 6. Формирование ответа в JSON
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        schedule_result = []
        for inst in course_instances:
            for s in time_slots:
                for r in rooms:
                    key = (inst["instance_id"], s["id"], r["id"])
                    if key in x and solver.Value(x[key]) == 1:
                        schedule_result.append({
                            "course_id": inst["course_id"],
                            "course_name": inst["name"],
                            "teacher_id": inst["teacher_id"],
                            "group_ids": inst["group_ids"],
                            "day": s["day"],
                            "slot_index": s["slot_index"],
                            "time": s["time"],
                            "room_id": r["id"]
                        })
                        
        return json.dumps({
            "status": "SUCCESS",
            "schedule": schedule_result
        }, ensure_ascii=False, indent=2)
    else:
        return json.dumps({
            "status": "NO_SOLUTION",
            "message": "Не удалось подобрать расписание с текущими ограничениями"
        }, ensure_ascii=False)


if __name__ == "__main__":
    data = prepare_parser_data(load_data())
    output_json = solve_schedule(json.dumps(data, ensure_ascii=False))
    print(output_json)