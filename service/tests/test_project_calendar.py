"""Dates in a 업무자료 정리 answer become calendar candidates the user confirms, linked to the project."""
from datetime import date
from pathlib import Path
from unittest.mock import patch
import json, tempfile, unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import adhoc, calendar_api, folder_projects as projects, folders, project_calendar, store, travel_api

ANSWER = '''일정과 할 일 · 원문 발췌
날짜나 완료 여부를 추정하지 않았습니다.
일정·기한
- 합성_교육취합보고.hwpx: 교육일시: 11. 13.(목) 14:00 [1]
- 합성_교육취합보고.hwpx: 재요청 기한: 11. 7.까지 회신 [2]
- 안내.txt: 행사 기간 2026. 12. 30.(수) ~ 1. 2.(토) [3]
- 안내.txt: 신청 2027년 1월 20일 마감 [4]
- 예산.hwpx: 1. ~ 3. 생략 4. 시설비 [5]
- 예산.hwpx: 금액 1,200,000원, 비율 3.5, 2026. 2. 30. [6]
- 메모.txt: 11/28 보고 [7]
할 일
- 회계과 재요청'''


class CandidatesTest(unittest.TestCase):
    def test_dates_with_and_without_a_year(self):
        found = project_calendar.candidates(ANSWER, date(2026, 11, 3), '교육 준비')
        self.assertEqual([(c['start'], c['end'], c['year_written'], c['kind']) for c in found], [
            ('2026-11-13', '2026-11-13', False, 'event'),
            ('2026-11-07', '2026-11-07', False, 'deadline'),
            # The year is written once on the start; the range crosses into the next year.
            ('2026-12-30', '2027-01-02', True, 'event'),
            ('2027-01-20', '2027-01-20', True, 'deadline'),
            ('2026-11-28', '2026-11-28', False, 'event'),
        ])
        first = found[0]
        self.assertEqual(first['title'], '교육 준비 · 교육일시: 11. 13.(목) 14:00')
        self.assertEqual((first['source'], first['line']), ('합성_교육취합보고.hwpx', '교육일시: 11. 13.(목) 14:00'))

    def test_numbering_amounts_and_impossible_dates_are_not_dates(self):
        for line in ('1. ~ 3. 생략 4. 시설비', '금액 1,200,000원, 비율 3.5', '2026. 2. 30. 마감', '13. 40. 항목'):
            with self.subTest(line=line):
                self.assertEqual(project_calendar.candidates(line, date(2026, 11, 3)), [])


class CalendarLinkTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); root = Path(self.temp.name)
        # The calendar lists every kind of work; none of it may come from the real data folder.
        for target, name in ((folders, 'folders.db'), (calendar_api, 'calendar.db'), (travel_api, 'travel.db'), (adhoc, 'adhoc.db')):
            p = patch.object(target, 'DB_PATH', root / name); p.start(); self.addCleanup(p.stop)
        old = (store.DATA, store.LIBRARY, store.DB_PATH, store._conn)
        if store._conn: store._conn.close()
        store._conn, store.DATA, store.LIBRARY, store.DB_PATH = None, root, root / 'library', root / 'seomu.db'
        def restore():
            if store._conn: store._conn.close()
            store.DATA, store.LIBRARY, store.DB_PATH, store._conn = old
        self.addCleanup(restore)
        store.conn(); travel_api.initialize(); adhoc.initialize(); folders.initialize(); projects.initialize()
        app = FastAPI(); app.include_router(projects.router); app.include_router(calendar_api.router)
        self.client = TestClient(app)
        self.pid = self.client.post('/api/folder-projects', json={'name': '교육 준비'}).json()['id']
        with projects.db() as c:
            for mid, role in (('q', 'user'), ('a', 'assistant')):
                projects.put(c, 'project_messages', dict(id=mid, project_id=self.pid, role=role, content=ANSWER if role == 'assistant' else '일정 알려줘',
                                                         status='completed', created_at='2026-11-03T00:00:00+00:00'))

    def test_answer_dates_register_as_project_linked_events(self):
        found = self.client.get(f'/api/folder-projects/{self.pid}/messages/a/calendar').json()['candidates']
        self.assertEqual(len(found), 5)
        self.assertEqual(self.client.get(f'/api/folder-projects/{self.pid}/messages/q/calendar').status_code, 422)
        # What the screen sends after the user checks the date: an all-day event linked to the project.
        item = found[1]
        r = self.client.post('/api/calendar/events', json=dict(title=item['title'], start=item['start'], end='2026-11-08', all_day=True,
                                                             kind=item['kind'], notes='업무자료 정리 · 교육 준비', work_kind='project', work_id=self.pid))
        self.assertEqual(r.status_code, 201, r.text)
        event = r.json()['event']
        self.assertEqual((event['work_kind'], event['work_id'], event['kind']), ('project', self.pid, 'deadline'))
        options = self.client.get('/api/calendar/work-options').json()['items']
        self.assertIn(dict(kind='project', id=self.pid, title='교육 준비', href=f'folders.html#project={self.pid}'), options)
        self.assertEqual(self.client.post('/api/calendar/events', json=dict(title='x', start='2026-11-07', end='2026-11-08', all_day=True,
                                                                           work_kind='project', work_id='missing')).status_code, 422)


if __name__ == '__main__':
    unittest.main()
