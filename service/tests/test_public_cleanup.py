"""Visitor material on the shared demo is removed after an hour; the demo's own material stays."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import json, os, tempfile, unittest

from app import calendar_api, folder_projects as projects, folders, public_cleanup


class PublicCleanupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.patch = patch.object(folders, 'DB_PATH', self.root / 'folders.db'); self.patch.start()
        self.calendar = patch.object(calendar_api, 'DB_PATH', self.root / 'calendar.db'); self.calendar.start()
        folders.initialize(); projects.initialize()
        self.sandbox = self.root / 'synthetic-folders'; (self.sandbox / '추가회신').mkdir(parents=True); (self.sandbox / 'uploads').mkdir()
        self.now = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
        self.project('demo', self.now - timedelta(days=1)); self.event('demo-event', self.now - timedelta(days=1))
        (self.sandbox / '추가회신' / '시연 회신.txt').write_text('[합성] 기본 시연 자료', encoding='utf-8')
        self.age(self.sandbox / '추가회신' / '시연 회신.txt', hours=5)
        self.kept = public_cleanup.snapshot(self.sandbox)

    def tearDown(self):
        self.calendar.stop(); self.patch.stop(); self.temp.cleanup()

    def project(self, pid, created, job='completed'):
        with projects.db() as c:
            projects.put(c, 'folder_projects', dict(id=pid, name=pid, created_at=created.isoformat(), updated_at=created.isoformat(), library_ids=[]))
            projects.put(c, 'project_files', dict(id=pid + '-f', project_id=pid, name='a.txt', status='ready'))
            projects.put(c, 'project_jobs', dict(id=pid + '-j', project_id=pid, status=job, created_at=created.isoformat()))
            c.execute('INSERT INTO project_units VALUES(?,?,?,?)', (pid + '-f', 1, '1행', '내용'))

    def event(self, key, created):
        calendar_api.initialize()
        with calendar_api.db() as c:
            c.execute('INSERT INTO calendar_events VALUES(?,?,?,0)', (key, 1, '{}'))
            c.execute('INSERT INTO calendar_history(event_id,kind,created_at) VALUES(?,?,?)', (key, '일정 등록', created.isoformat()))

    def message(self, mid, pid, created):
        with projects.db() as c:
            projects.put(c, 'project_messages', dict(id=mid, project_id=pid, role='user', content='질문', status='completed', created_at=created.isoformat()))

    def age(self, path, hours):
        stamp = (self.now - timedelta(hours=hours)).timestamp(); os.utime(path, (stamp, stamp))

    def ids(self, table):
        with projects.db() as c:
            return {r[0] for r in c.execute(f'SELECT id FROM {table}')}

    def test_visitor_material_older_than_an_hour_is_removed(self):
        self.project('old', self.now - timedelta(hours=2)); self.message('old-q', 'demo', self.now - timedelta(hours=2))
        self.project('new', self.now - timedelta(minutes=10)); self.message('new-q', 'demo', self.now - timedelta(minutes=10))
        self.project('busy', self.now - timedelta(hours=2), job='running')
        with folders.db() as c:
            for key, hours in (('lib-old', 2), ('lib-new', 0.2)):
                at = (self.now - timedelta(hours=hours)).isoformat()
                c.execute('INSERT INTO libraries VALUES(?,?,?)', (key, 1, json.dumps({'id': key, 'name': key, 'history': [{'at': at}]})))
        old_upload = self.sandbox / 'uploads' / ('a' * 32); old_upload.mkdir(); self.age(old_upload, 2)
        new_upload = self.sandbox / 'uploads' / ('b' * 32); new_upload.mkdir(); self.age(new_upload, 0.2)
        self.event('event-old', self.now - timedelta(hours=2)); self.event('event-new', self.now - timedelta(minutes=10))
        visitor = self.sandbox / '추가회신' / '공개_연락.txt'; visitor.write_text('[합성] 방문자 자료', encoding='utf-8'); self.age(visitor, 2)

        removed = public_cleanup.sweep(self.kept, self.sandbox, now=self.now)

        self.assertEqual(removed, dict(projects=1, messages=1, libraries=1, events=1, uploads=1, files=1))
        self.assertEqual(self.ids('folder_projects'), {'demo', 'new', 'busy'})
        self.assertEqual(self.ids('project_messages'), {'new-q'})
        self.assertNotIn('old-f', self.ids('project_files'))
        with projects.db() as c:
            self.assertEqual({r[0] for r in c.execute('SELECT file_id FROM project_units')}, {'demo-f', 'new-f', 'busy-f'})
        with folders.db() as c:
            self.assertEqual({r[0] for r in c.execute('SELECT id FROM libraries')}, {'lib-new'})
        with calendar_api.db() as c:
            self.assertEqual({r[0] for r in c.execute('SELECT id FROM calendar_events')}, {'demo-event', 'event-new'})
            self.assertEqual({r[0] for r in c.execute('SELECT event_id FROM calendar_history')}, {'demo-event', 'event-new'})
        self.assertFalse(old_upload.exists()); self.assertTrue(new_upload.exists())
        self.assertFalse(visitor.exists()); self.assertTrue((self.sandbox / '추가회신' / '시연 회신.txt').exists())


if __name__ == '__main__':
    unittest.main()
