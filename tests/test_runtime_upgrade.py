import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


path = Path(__file__).resolve().parents[1] / 'tools/upgrade_public_runtime.py'
spec = importlib.util.spec_from_file_location('runtime_upgrade', path)
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class RuntimeUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.target = self.root / 'source', self.root / 'runtime'
        self.first = {'id': 'original', 'library_id': 'law', 'file_id': 'file-1', 'sha256': 'a' * 64}
        self.extra = {'id': 'added', 'library_id': 'new-laws', 'file_id': 'file-2', 'sha256': 'b' * 64}
        for root, version, sources in ((self.target, 'v69', [self.first]), (self.source, 'v70', [self.first, self.extra])):
            (root / 'data').mkdir(parents=True)
            write(root / 'submission-data/knowledge.json', {'sources': sources})
            (root / 'app').mkdir()
            (root / 'app/main.py').write_text(version)
            if version == 'v70':
                (root / 'app/added.py').write_text('new feature')
            files = {p.relative_to(root).as_posix(): upgrade.digest(p) for p in root.rglob('*') if p.is_file()}
            write(root / 'submission-manifest.json', {'release_version': version, 'sources': len(sources), 'files': files})
        write(self.target / 'gongmudam-runtime.json', {'source_manifest_sha256': upgrade.digest(self.target / 'submission-manifest.json')})
        write(self.target / 'data/submission-installation.json', {'root': str(self.target), 'bundle_sha256': upgrade.digest(self.target / 'submission-data/knowledge.json'), 'sources': 1})
        with upgrade.database(self.target / 'data/folders.db') as c:
            c.executescript('CREATE TABLE libraries(id TEXT PRIMARY KEY,version INTEGER,payload TEXT);'
                            'CREATE TABLE knowledge_sources(id TEXT PRIMARY KEY,library_id TEXT,file_id TEXT,enabled INTEGER,payload TEXT,UNIQUE(library_id,file_id));')
            c.execute('INSERT INTO libraries VALUES(?,?,?)', ('law', 7, '{"confirmed":"user choice"}'))
            c.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?)', ('original', 'law', 'file-1', 0, json.dumps(self.first)))
        (self.target / 'output').mkdir()
        (self.target / 'output/evidence.pdf').write_bytes(b'attachment unchanged')
        (self.target / 'config.json').write_text('model setting unchanged')

    def rows(self):
        return ([('added', 'new-laws', 'file-2', 1, json.dumps(self.extra))],
                [('new-laws', 1, '{"new":"library"}')])

    def test_upgrade_appends_without_changing_existing_rows_settings_or_attachments(self):
        with upgrade.database(self.target / 'data/folders.db') as c:
            old_sources = c.execute('SELECT * FROM knowledge_sources').fetchall()
            old_libraries = c.execute('SELECT * FROM libraries').fetchall()
        with patch.object(upgrade, 'addition_rows', return_value=self.rows()):
            result = upgrade.upgrade(self.source, self.target, self.root / 'backups')
        self.assertEqual(result['sources_added'], 1)
        self.assertEqual((self.target / 'app/main.py').read_text(), 'v70')
        with upgrade.database(self.target / 'data/folders.db') as c:
            self.assertEqual(c.execute("SELECT * FROM knowledge_sources WHERE id='original'").fetchall(), old_sources)
            self.assertEqual(c.execute("SELECT * FROM libraries WHERE id='law'").fetchall(), old_libraries)
            self.assertEqual(c.execute('SELECT count(*) FROM knowledge_sources').fetchone()[0], 2)
        self.assertEqual((self.target / 'config.json').read_text(), 'model setting unchanged')
        self.assertEqual((self.target / 'output/evidence.pdf').read_bytes(), b'attachment unchanged')
        self.assertTrue((Path(result['backup']) / 'data/folders.db').is_file())
        self.assertEqual(upgrade.upgrade(self.source, self.target, self.root / 'backups')['status'], 'already_current')

    def test_manifest_only_release_change_updates_version_and_runtime_marker(self):
        import shutil

        shutil.rmtree(self.source)
        shutil.copytree(self.target, self.source)
        manifest = upgrade.read(self.source / 'submission-manifest.json')
        manifest['release_version'] = 'v73'
        write(self.source / 'submission-manifest.json', manifest)
        with upgrade.database(self.target / 'data/folders.db') as c:
            old_sources = c.execute('SELECT * FROM knowledge_sources').fetchall()
            old_libraries = c.execute('SELECT * FROM libraries').fetchall()
        result = upgrade.upgrade(self.source, self.target, self.root / 'backups')
        manifest_sha = upgrade.digest(self.source / 'submission-manifest.json')
        self.assertEqual(result['status'], 'upgraded')
        self.assertEqual(result['from'], 'v69'); self.assertEqual(result['to'], 'v73')
        self.assertEqual(result['files_updated'], 0); self.assertEqual(result['sources_added'], 0)
        self.assertEqual(upgrade.digest(self.target / 'submission-manifest.json'), manifest_sha)
        self.assertEqual(upgrade.read(self.target / 'gongmudam-runtime.json')['source_manifest_sha256'], manifest_sha)
        with upgrade.database(self.target / 'data/folders.db') as c:
            self.assertEqual(c.execute('SELECT * FROM knowledge_sources').fetchall(), old_sources)
            self.assertEqual(c.execute('SELECT * FROM libraries').fetchall(), old_libraries)
        self.assertEqual((self.target / 'config.json').read_text(), 'model setting unchanged')
        self.assertEqual((self.target / 'output/evidence.pdf').read_bytes(), b'attachment unchanged')
        self.assertEqual(upgrade.upgrade(self.source, self.target, self.root / 'backups')['status'], 'already_current')

    def test_modified_managed_file_is_rejected_before_writing(self):
        (self.target / 'app/main.py').write_text('local edit')
        with self.assertRaisesRegex(ValueError, 'Managed file was changed'):
            upgrade.upgrade(self.source, self.target, self.root / 'backups')
        self.assertEqual((self.target / 'app/main.py').read_text(), 'local edit')

    def test_changed_or_missing_registered_source_is_rejected(self):
        with upgrade.database(self.target / 'data/folders.db') as c:
            c.execute("DELETE FROM knowledge_sources WHERE id='original'")
        with self.assertRaisesRegex(ValueError, 'changed or was removed'):
            upgrade.plan(self.source, self.target)

    def test_failure_after_copy_and_db_write_rolls_back_all_written_state(self):
        native = upgrade.owned
        fail_once = True

        def fail_marker(root, name):
            nonlocal fail_once
            if root == self.target and name == 'data/submission-installation.json' and fail_once:
                # This is reached during backup too; fail only after v70 files land.
                if (self.target / 'app/main.py').read_text() == 'v70':
                    fail_once = False
                    raise OSError('synthetic marker failure')
            return native(root, name)

        with patch.object(upgrade, 'addition_rows', return_value=self.rows()), patch.object(upgrade, 'owned', side_effect=fail_marker):
            with self.assertRaisesRegex(OSError, 'synthetic marker failure'):
                upgrade.upgrade(self.source, self.target, self.root / 'backups')
        self.assertEqual((self.target / 'app/main.py').read_text(), 'v69')
        self.assertFalse((self.target / 'app/added.py').exists())
        with upgrade.database(self.target / 'data/folders.db') as c:
            self.assertEqual(c.execute('SELECT count(*) FROM knowledge_sources').fetchone()[0], 1)
        self.assertEqual(upgrade.plan(self.source, self.target)['to'], 'v70')
        self.assertFalse((self.target / 'data/gongmudam-upgrade.lock').exists())


if __name__ == '__main__':
    unittest.main()
