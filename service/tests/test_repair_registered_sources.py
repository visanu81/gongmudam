"""Safety tests for repairing the five bundled national-service registrations."""
import json
import gc
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from tools import repair_registered_sources as repair


class RepairRegisteredSourcesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(gc.collect)
        self.tmp = Path(self.temp.name)
        self.db = self.tmp / 'folders.db'
        self._create_db(self.db)

    @staticmethod
    def _create_db(path):
        with closing(sqlite3.connect(path)) as c:
            with c:
                c.executescript('''
                CREATE TABLE libraries(id TEXT PRIMARY KEY, version INTEGER, payload TEXT);
                CREATE TABLE knowledge_sources(
                    id TEXT PRIMARY KEY, library_id TEXT, file_id TEXT, enabled INTEGER,
                    payload TEXT, UNIQUE(library_id, file_id));
                CREATE TABLE work_experiences(id TEXT PRIMARY KEY, library_id TEXT, payload BLOB);
                CREATE TABLE project_messages(id TEXT PRIMARY KEY, payload BLOB);
            ''')
                c.execute('INSERT INTO libraries VALUES(?,?,?)',
                          ('existing-library', 7, '{"owner":"user","preserve":"exact"}'))
                c.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?)',
                          ('existing-source', 'existing-library', 'existing-file', 1,
                           '{"user_payload":"keep exactly"}'))
                c.execute('INSERT INTO work_experiences VALUES(?,?,?)',
                          ('experience-1', 'existing-library', sqlite3.Binary(b'\x00experience\xffpayload')))
                c.execute('INSERT INTO project_messages VALUES(?,?)',
                          ('message-1', sqlite3.Binary(b'\x00project\x80message\xff')))

    @staticmethod
    def _snapshot(path):
        with closing(sqlite3.connect(path)) as c:
            tables = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            return {name: c.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
                    for name in tables}

    @staticmethod
    def _copy_bundle(destination):
        source_root = repair.ROOT
        (destination / 'submission-data').mkdir(parents=True)
        shutil.copy2(source_root / 'submission-data/knowledge.json',
                     destination / 'submission-data/knowledge.json')
        bundle = json.loads((destination / 'submission-data/knowledge.json').read_text(encoding='utf-8'))
        for source in bundle['sources']:
            if source['id'].startswith('public-v70-'):
                src = source_root / source['asset']
                dst = destination / source['asset']
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        return bundle

    def test_dry_run_reports_five_missing_sources_without_changes_or_backup(self):
        before = self._snapshot(self.db)
        result = repair.repair(repair.ROOT, db_path=self.db)
        self.assertFalse(result['applied'])
        self.assertEqual(len(result['would_add']), 5)
        self.assertEqual(result['added'], [])
        self.assertIsNone(result['backup'])
        self.assertEqual(self._snapshot(self.db), before)
        self.assertFalse((self.tmp / 'knowledge-repair-backups').exists())

    def test_apply_adds_five_sources_preserving_existing_rows_and_tables(self):
        before = self._snapshot(self.db)
        result = repair.repair(repair.ROOT, db_path=self.db, apply=True)
        self.assertEqual(len(result['added']), 5)
        self.assertEqual(result['added'], result['would_add'])
        self.assertTrue(result['business_rows_preserved'])
        self.assertTrue(Path(result['backup']).is_file())
        after = self._snapshot(self.db)
        self.assertEqual(set(after), set(before))
        for table in ('work_experiences', 'project_messages'):
            self.assertEqual(after[table], before[table])
        self.assertEqual(after['libraries'][0], before['libraries'][0])
        self.assertIn('national-service-v70', [row[0] for row in after['libraries']])
        self.assertEqual(len(after['knowledge_sources']), len(before['knowledge_sources']) + 5)
        self.assertIn(before['knowledge_sources'][0], after['knowledge_sources'])

    def test_second_apply_is_idempotent(self):
        first = repair.repair(repair.ROOT, db_path=self.db, apply=True)
        self.assertEqual(len(first['added']), 5)
        before = self._snapshot(self.db)
        second = repair.repair(repair.ROOT, db_path=self.db, apply=True)
        self.assertEqual(second['would_add'], [])
        self.assertEqual(second['added'], [])
        self.assertEqual(self._snapshot(self.db), before)

    def test_disabled_existing_source_stays_disabled(self):
        source = repair.selected_sources(repair.ROOT)[0]
        payload = {k: v for k, v in source.items() if k not in {'asset', 'enabled'}}
        with closing(sqlite3.connect(self.db)) as c:
            with c:
                c.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?)',
                          (source['id'], source['library_id'], source['file_id'], 0,
                           json.dumps(payload, ensure_ascii=False)))
        result = repair.repair(repair.ROOT, db_path=self.db, apply=True)
        self.assertEqual(len(result['added']), 4)
        self.assertEqual(result['preserved_disabled'], [source['id']])
        with closing(sqlite3.connect(self.db)) as c:
            self.assertEqual(c.execute('SELECT enabled FROM knowledge_sources WHERE id=?',
                                       (source['id'],)).fetchone()[0], 0)

    def test_file_id_conflict_refuses_atomically(self):
        source = repair.selected_sources(repair.ROOT)[0]
        with closing(sqlite3.connect(self.db)) as c:
            with c:
                c.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?)',
                          ('someone-elses-id', source['library_id'], source['file_id'], 1, '{}'))
        before = self._snapshot(self.db)
        with self.assertRaisesRegex(ValueError, 'Another registration owns this file'):
            repair.repair(repair.ROOT, db_path=self.db, apply=True)
        self.assertEqual(self._snapshot(self.db), before)

    def test_wrong_digest_and_corrupt_asset_are_rejected_in_temporary_bundle_copies(self):
        for damage in ('digest', 'asset'):
            with self.subTest(damage=damage):
                copy_root = self.tmp / ('bundle-' + damage)
                bundle = self._copy_bundle(copy_root)
                source = next(s for s in bundle['sources'] if s['id'].startswith('public-v70-'))
                if damage == 'digest':
                    source['sha256'] = '0' * 64
                    (copy_root / 'submission-data/knowledge.json').write_text(
                        json.dumps(bundle, ensure_ascii=False), encoding='utf-8')
                else:
                    asset = copy_root / source['asset']
                    asset.write_bytes(asset.read_bytes() + b' tampered')
                with self.assertRaises(ValueError):
                    repair.selected_sources(copy_root)

    def test_missing_database_is_not_created(self):
        missing = self.tmp / 'missing.db'
        with self.assertRaisesRegex(ValueError, 'Existing database is required'):
            repair.repair(repair.ROOT, db_path=missing, apply=True)
        self.assertFalse(missing.exists())


if __name__ == '__main__':
    unittest.main()
