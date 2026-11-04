import pandas as pd

class Importer:
    def __init__(self):
        pass

    def parse_from_excel(self, rooms_io = 'table2.xlsx', rooms_sheet_name = 'Аудитории') -> dict:
        # пока заглушка, формат (надеюсь) не поменяется, а вот объемы да
        return {
            "rooms": [
                {"id": "466", "capacity": 48,
                 "has_chalkboard": True, "has_whiteboard": True, "has_multimedia_board": False,
                 "has_blinds": True, "has_screen": False, "has_acoustic_system": False},
                {"id": "474", "capacity": 20,
                 "has_chalkboard": True, "has_whiteboard": True, "has_multimedia_board": False,
                 "has_blinds": True, "has_screen": False, "has_acoustic_system": False},
                {"id": "513", "capacity": 48,
                 "has_chalkboard": True, "has_whiteboard": True, "has_multimedia_board": False,
                 "has_blinds": True, "has_screen": False, "has_acoustic_system": False}
            ],
            "teachers": [
                {"id": "Улитко М.В."},
                {"id": "Хацко С.Л."}
            ],
            "teachers_impossible_slots": [
                {"teacher_id": "Улитко М.В.", "timeslots_ids": [1, 2, 3]},
                {"teacher_id": "Хацко С.Л.", "timeslots_ids": [4, 5, 6]},
            ],
            "teachers_unwanted_slots": [
                {"teacher_id": "Улитко М.В.", "timeslots_ids": [10]},
                {"teacher_id": "Хацко С.Л.", "timeslots_ids": [1]},
            ],
            "groups": [
                {"id": "МБ1", "size": 25},
                {"id": "МБ2", "size": 22}
            ],
            "time_slots": [
                {"id": 1, "day": "Пятница", "slot_index": 1, "time": "09:00-10:35"},
                {"id": 2, "day": "Пятница", "slot_index": 2, "time": "10:50-12:25"}
            ],
            "courses": [
                {
                    "id": "c1",
                    "name": "Физика (поток)",
                    "teacher_id": "Улитко М.В.",
                    "group_ids": ["МБ1", "МБ2"],
                    "lessons_per_week": 1,
                    "requirements": ["chalkboard", "whiteboard", "multimedia_board", "blinds", "screen", "acoustic_system"]
                },
                {
                    "id": "c2",
                    "name": "Химия",
                    "teacher_id": "Хацко С.Л.",
                    "group_ids": ["МБ1"],
                    "lessons_per_week": 1,
                    "requirements": ["acoustic_system"]
                },
                {
                    "id": "c3",
                    "name": "Прикладная физическая культура",
                    "teacher_id": "",
                    "group_ids": ["МБ1", "МБ2", "МБ3"],
                    "lessons_per_week": 2,
                    "requirements": []
                }
            ],
            "fixed_schedules": [
                {
                    "course_id": "c3",
                    "timeslots_ids": [1, 2]
                }
            ]
        }
        return {
            "rooms": self.parse_rooms(pd.read_excel(io=rooms_io, sheet_name=rooms_sheet_name, header=[0, 2]))
        }

    @staticmethod
    def parse_rooms(rooms: pd.DataFrame):
        rooms = rooms.drop(['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'Кому принадлежит',
                            'С кем договариваться', 'Примечание', 'Вид'], axis=1, level=0)
        flat_cols = []
        for top, bottom in rooms.columns:
            if 'Unnamed:' in str(bottom):
                flat_cols.append(top)
            else:
                flat_cols.append(bottom)

        rooms.columns = flat_cols
        rooms = rooms.rename(
            columns={'Ауд.': 'id', 'Вм-ть': 'capacity', 'меловая': 'has_chalkboard', 'маркерная': 'has_whiteboard',
                     'мультимедиа': 'has_multimedia_board', 'жалюзи': 'has_blinds', 'экран': 'has_screen',
                     'акустич. система': 'has_acoustic_system'})
        rooms[['has_chalkboard', 'has_whiteboard', 'has_multimedia_board', 'has_blinds', 'has_screen',
               'has_acoustic_system']] = rooms[
                                             ['has_chalkboard', 'has_whiteboard', 'has_multimedia_board', 'has_blinds',
                                              'has_screen', 'has_acoustic_system']] == "+"
        return rooms.to_dict(orient='records')


    def parse_courses(self, courses: pd.DataFrame):
        pass






i = Importer()
print(i.parse_from_excel())

