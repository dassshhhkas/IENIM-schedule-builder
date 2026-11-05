import json
import re

import numpy as np
import pandas as pd

class Importer:
    def __init__(self):
        self._teachers = pd.DataFrame()
        self._groups = pd.DataFrame()
        self.fixed_courses = ['Прикладная физическая культура (практика)']
        self._fixed_schedules = pd.DataFrame()
        self._time_slots = self._generate_time_slots()

    def parse_from_excel(self, rooms_io: str = 'table2.xlsx', rooms_sheet_name: str = 'Аудитории', courses_io: str = 'table.xlsx',
                         courses_sheets=None) -> dict:
        if courses_sheets is None:
            courses_sheets = ['ХИМИКИ', 'ФИНЗ', 'ФИНЗ Магистры', 'ЭБМ', 'Тургенева 4 по выбору', 'Тургенева 4']
        return {
            "rooms": self._parse_rooms(pd.read_excel(io=rooms_io, sheet_name=rooms_sheet_name, header=[0, 2])),
            "courses": self._parse_courses(courses_io, courses_sheets),
            "teachers": self._teachers.to_dict(orient='records'),
            "groups": self._groups.to_dict(orient='records'),
            "fixed_schedules": self._fixed_schedules.to_dict(orient='records'),
            "time_slots": self._time_slots,


            "teachers_impossible_slots": [
                {"teacher_id": "Улитко М.В.", "timeslots_ids": [1, 2, 3]},
                {"teacher_id": "Хацко С.Л.", "timeslots_ids": [4, 5, 6]},
            ],
            "teachers_unwanted_slots": [
                {"teacher_id": "Улитко М.В.", "timeslots_ids": [10]},
                {"teacher_id": "Хацко С.Л.", "timeslots_ids": [1]},
            ],
        }

    @staticmethod
    def _parse_rooms(rooms: pd.DataFrame):
        rooms = rooms.drop(['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА', 'Кому принадлежит',
                            'С кем договариваться', 'Примечание', 'Вид'], axis=1, level=0)
        flat_cols = []
        for top, bottom in rooms.columns:
            if 'Unnamed:' in str(bottom):
                flat_cols.append(top)
            else:
                flat_cols.append(bottom)

        rooms.columns = flat_cols
        rooms = rooms.dropna(subset=['Ауд.'])
        rooms = rooms.rename(
            columns={'Ауд.': 'id', 'Вм-ть': 'capacity', 'меловая': 'has_chalkboard', 'маркерная': 'has_whiteboard',
                     'мультимедиа': 'has_multimedia_board', 'жалюзи': 'has_blinds', 'экран': 'has_screen',
                     'акустич. система': 'has_acoustic_system'})
        rooms[['has_chalkboard', 'has_whiteboard', 'has_multimedia_board', 'has_blinds', 'has_screen',
               'has_acoustic_system']] = rooms[
                                             ['has_chalkboard', 'has_whiteboard', 'has_multimedia_board', 'has_blinds',
                                              'has_screen', 'has_acoustic_system']] == "+"
        return rooms.to_dict(orient='records')

    def _parse_courses(self, excel_path, sheet_names):
        df = pd.DataFrame()
        for sheet_name in sheet_names:
            df = pd.concat([df, self._parse_courses_page(pd.read_excel(io=excel_path, sheet_name=sheet_name))])

        df['id'] = range(len(df))

        self._teachers = pd.concat([self._teachers, df['teacher_id'].explode().drop_duplicates().dropna()])
        self._teachers = self._teachers.rename(columns={'teacher_id': 'id'})

        self._groups = pd.concat([self._groups, df['group_ids'].explode().drop_duplicates().dropna()])
        self._groups = self._groups.rename(columns={'group_ids': 'id'})
        self._groups['size'] = np.random.randint(25, 34, size=len(self._groups))
        # так то в табличке есть столбец "число студентов", но он пустой :(

        self._fixed_schedules = self._generate_fixed_schedules(df[['id', 'name', 'course']])

        df = df.drop(['course'], axis=1)
        return df.to_dict(orient='records')

    def _generate_fixed_schedules(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df[df['name'].isin(self.fixed_courses)]
        print(df)
        def _get_pe(course): # можно заменить на честный парсинг из таблицы, но пока так
            if course == 1:
                return [12, 22]
            elif course == 2:
                return [19, 29]
            elif course == 3:
                return [40, 1]
            else:
                return []
        df['timeslots_ids'] = df['course'].apply(_get_pe)
        df = df.rename(columns={'id': 'course_id'})
        return df[['course_id', 'timeslots_ids']]



    @staticmethod
    def _parse_courses_page(courses: pd.DataFrame):
        courses[['Лекции', 'Практ. занятия', 'Лаб. занятия']] = courses[['Лекции', 'Практ. занятия', 'Лаб. занятия']].replace(r'^\s*$', np.nan, regex=True)
        courses['Дисциплины'] = courses['Дисциплины'].ffill()
        courses = courses[['Курс', 'Номер группы', 'Дисциплины', 'Лекции', 'Практ. занятия', 'Лаб. занятия', 'ФИО лектора',
                           'ФИО преподавателя на практики, лаборатории', 'Нужна ли мультимедиа на лекции?',
                           'Нужен ли проектор на практики, лаборатории', 'Какая нужна доска на практики, лаборатории: меловая, маркерная, любая']].dropna(subset=['Номер группы'])

        def _build_non_lecture_reqs(row):
            reqs = []
            proj = row['Нужен ли проектор на практики, лаборатории']
            if pd.notna(proj) and ('да' in str(proj).lower() or 'нуж' in str(proj).lower()):
                reqs.append('screen')
            board = row['Какая нужна доска на практики, лаборатории: меловая, маркерная, любая']
            if pd.isna(board) or str(board).strip() == '':
                return reqs
            lower = str(board).lower()
            if 'любая' in lower:
                reqs.append('board')
                return reqs
            if 'меловая' in lower:
                reqs.append('chalkboard')
            if 'маркерная' in lower:
                reqs.append('whiteboard')
            return reqs

        def _build_lecture_reqs(x):
            return ['multimedia_board'] if ('да' in str(x).lower() or 'нуж' in str(x).lower()) else []

        lectures = pd.DataFrame({
            'course': courses['Курс'],
            'group_ids': courses['Номер группы'].apply(lambda x: [s for s in re.split(r'[\s\n]+', str(x)) if s]),
            'name': courses['Дисциплины'] + ' (лекция)',
            'academic_hour_per_semester': courses['Лекции'],
            # если будет единый формат этого столбца, можно немного упростить
            # 'teacher_id': courses['ФИО лектора'].apply(lambda x: str(x).split('\n')),
            'teacher_id': courses['ФИО лектора'].apply(
                lambda x: [
                    name.strip()
                    for name in re.split(r'[;,\n]', str(x))
                    if name.strip() and name.lower() != 'nan'
                ]
            ),
            'requirements': (courses['Нужна ли мультимедиа на лекции?'].fillna('').apply(_build_lecture_reqs))
        })
        lectures = lectures.dropna(subset=['academic_hour_per_semester'])

        practices = pd.DataFrame({
            'course': courses['Курс'],
            'group_ids': courses['Номер группы'].apply(lambda x: [s for s in re.split(r'[\s\n]+', str(x)) if s]),
            'name': courses['Дисциплины'] + ' (практика)',
            'academic_hour_per_semester': courses['Практ. занятия'],
            # 'teacher_id': courses['ФИО преподавателя на практики, лаборатории'].apply(lambda x: str(x).split('\n')),
            'teacher_id': courses['ФИО преподавателя на практики, лаборатории'].apply(
                lambda x: [
                    name.strip()
                    for name in re.split(r'[;,\n]', str(x))
                    if name.strip() and name.lower() != 'nan'
                ]
            ),
            'requirements': (courses.apply(_build_non_lecture_reqs, axis=1))
        })
        practices = practices.dropna(subset=['academic_hour_per_semester'])

        labs = pd.DataFrame({
            'course': courses['Курс'],
            'group_ids': courses['Номер группы'].apply(lambda x: [s for s in re.split(r'[\s\n]+', str(x)) if s]),
            'name': courses['Дисциплины'] + ' (лабораторная)',
            'academic_hour_per_semester': courses['Лаб. занятия'],
            # 'teacher_id': courses['ФИО преподавателя на практики, лаборатории'].apply(lambda x: str(x).split('\n')),
            'teacher_id': courses['ФИО преподавателя на практики, лаборатории'].apply(
                lambda x: [
                    name.strip()
                    for name in re.split(r'[;,\n]', str(x))
                    if name.strip() and name.lower() != 'nan'
                ]
            ),
            'requirements': courses.apply(_build_non_lecture_reqs, axis=1),
        })
        labs = labs.dropna(subset=['academic_hour_per_semester'])

        return pd.concat([lectures, practices, labs], ignore_index=True)

    @staticmethod
    def _generate_time_slots(week_days=None, slots_per_day=None):
        if slots_per_day is None:
            slots_per_day = ['09:00-10:30', '10:40-12:10', '12:50-14:20', '14:30-16:00', '16:10-17:40', '17:50-19:20',
                             '19:30-21:00']
        if week_days is None:
            week_days = ['ПОНЕДЕЛЬНИК', 'ВТОРНИК', 'СРЕДА', 'ЧЕТВЕРГ', 'ПЯТНИЦА', 'СУББОТА']
        slots = []
        slot_id = 1

        for day in week_days:
            for slot_index, time in enumerate(slots_per_day):
                slots.append({
                    "id": slot_id,
                    "day": day,
                    "slot_index": slot_index + 1,
                    "time": time
                })
                slot_id += 1

        return slots


i = Importer()
with open('data.json', 'w') as f:
    f.write(json.dumps(i.parse_from_excel(), indent=2, ensure_ascii=False))

