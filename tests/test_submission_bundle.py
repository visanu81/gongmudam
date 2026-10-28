import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('submission_bundle', Path(__file__).resolve().parents[1] / 'tools/build_submission_bundle.py')
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class SubmissionBundleTest(unittest.TestCase):
    def fixture(self, root):
        paths = ['service/app/main.py', 'service/submission-manifest.json',
                 'desktop/data/agencies-v1.sqlite', 'integration/__init__.py', 'integration/application.py',
                 'tools/run_local_app.py', 'tools/build_submission_bundle.py',
                 'tools/prepare_public_runtime.py', 'tools/upgrade_public_runtime.py',
                 'desktop/tests/test_agency_directory.py',
                 'tests/test_integration.py', 'tests/test_local_run.py', 'tests/test_submission_bundle.py',
                 'tests/service-bridge.test.mjs', 'tests/window-resize.test.mjs', 'tests/deployment-context.test.mjs', 'tests/home-agenda.test.mjs', 'tests/quote-strip.test.mjs', 'tests/service-entry.test.mjs', 'tests/service-navigation.test.mjs', 'tests/embedded-affiliation.test.mjs',
                 'docs/LOCAL-AI-v71-20261025.txt', 'docs/SUBMISSION-v72-START.txt', 'docs/SUBMISSION-v72-VALIDATION.txt']
        paths += ['desktop/' + name for name in bundle.DESKTOP]
        for name in paths:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('public fixture', encoding='utf-8')
        (root / 'desktop/assets').mkdir()
        manifest = {'release_version': 'v72', 'sources': 36,
                    'files': {'app/main.py': hashlib.sha256((root / 'service/app/main.py').read_bytes()).hexdigest()}}
        (root / 'service/submission-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        return manifest

    def test_bundle_excludes_live_data_and_secrets_and_provides_b_desktop_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            self.fixture(root)
            for name in ['service/config.json', 'service/data/folders.db', '.local-runtime/private.db', '.env']:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('PRIVATE', encoding='utf-8')
            target, archive = Path(tmp) / 'package', Path(tmp) / 'package.zip'
            with patch.object(bundle, 'ROOT', root):
                result = bundle.build(target, archive)
            self.assertTrue((target / '1_설치.bat').is_file())
            self.assertIn('run_local_app.py', (target / 'run.bat').read_text())
            manifest = json.loads((target / 'gongmudam-manifest.json').read_text(encoding='utf-8'))
            for relative_name in ('desktop/tests/test_agency_directory.py', 'tests/embedded-affiliation.test.mjs'):
                packaged = target / relative_name
                self.assertTrue(packaged.is_file())
                self.assertEqual(manifest['files'][relative_name], hashlib.sha256(packaged.read_bytes()).hexdigest())
            self.assertFalse((target / 'service/config.json').exists())
            self.assertFalse((target / 'service/data').exists())
            with zipfile.ZipFile(archive) as contents:
                self.assertIsNone(contents.testzip())
                self.assertFalse(any(n.endswith('/config.json') or '/.local-runtime/' in n for n in contents.namelist()))
            self.assertEqual(result['sha256'], bundle.sha(archive))

    def test_private_manifest_entry_and_existing_destination_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            manifest = self.fixture(root)
            manifest['files']['data/folders.db'] = 'not-even-read'
            (root / 'service/submission-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            with patch.object(bundle, 'ROOT', root):
                with self.assertRaisesRegex(ValueError, 'Private runtime'):
                    bundle.build(Path(tmp) / 'package')
                with self.assertRaisesRegex(ValueError, 'existing files'):
                    bundle.build(root)

    def test_external_service_root_supplies_staged_content_and_keeps_safeguards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            manifest = self.fixture(root)
            staged = Path(tmp) / 'staged-service'
            staged_app = staged / 'app/main.py'
            staged_app.parent.mkdir(parents=True)
            staged_app.write_text('reviewed staged service', encoding='utf-8')
            manifest['files']['app/main.py'] = hashlib.sha256(staged_app.read_bytes()).hexdigest()
            staged_manifest = staged / 'submission-manifest.json'
            staged_manifest.write_text(json.dumps(manifest), encoding='utf-8')
            for name in ('config.json', 'data/private.db'):
                private = staged / name
                private.parent.mkdir(parents=True, exist_ok=True)
                private.write_text('PRIVATE', encoding='utf-8')

            target = Path(tmp) / 'package'
            with patch.object(bundle, 'ROOT', root):
                bundle.build(target, service_root=staged)

            self.assertEqual((target / 'service/app/main.py').read_text(encoding='utf-8'), 'reviewed staged service')
            self.assertEqual((target / 'service/submission-manifest.json').read_text(encoding='utf-8'), staged_manifest.read_text(encoding='utf-8'))
            self.assertFalse((target / 'service/config.json').exists())
            self.assertFalse((target / 'service/data').exists())

            manifest['files']['app/main.py'] = '0' * 64
            staged_manifest.write_text(json.dumps(manifest), encoding='utf-8')
            with patch.object(bundle, 'ROOT', root), self.assertRaisesRegex(ValueError, 'Service hash mismatch'):
                bundle.build(Path(tmp) / 'hash-mismatch', service_root=staged)

            manifest['files']['app/main.py'] = hashlib.sha256(staged_app.read_bytes()).hexdigest()
            manifest['files']['data/private.db'] = 'unread'
            staged_manifest.write_text(json.dumps(manifest), encoding='utf-8')
            with patch.object(bundle, 'ROOT', root), self.assertRaisesRegex(ValueError, 'Private runtime'):
                bundle.build(Path(tmp) / 'private-entry', service_root=staged)

    def test_manifest_path_cannot_escape_or_point_at_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('../secret', 'C:/secret', '', '/etc/file', 'a\\b'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    bundle.relative(Path(tmp), name)

    def test_release_uses_its_own_first_run_guide_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            manifest = self.fixture(root)
            manifest['release_version'] = 'v73'
            (root / 'service/submission-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            for suffix in ('START', 'VALIDATION'):
                (root / f'docs/SUBMISSION-v73-{suffix}.txt').write_text('v73 ' + suffix, encoding='utf-8')
            with patch.object(bundle, 'ROOT', root):
                bundle.build(Path(tmp) / 'package')
            self.assertEqual((Path(tmp) / 'package/처음읽기.txt').read_text(encoding='utf-8'), 'v73 START')
            self.assertTrue((Path(tmp) / 'package/docs/SUBMISSION-v73-VALIDATION.txt').is_file())

    def test_release_evidence_includes_jpeg_formats_with_managed_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            self.fixture(root)
            evidence = root / 'docs/evidence/v72'
            evidence.mkdir(parents=True)
            image_bytes = {
                'folder-picker.jpg': b'jpeg evidence one',
                'folder-picker.jpeg': b'jpeg evidence two',
                'folder-picker-initial.jpg': b'development capture',
            }
            for name, data in image_bytes.items():
                (evidence / name).write_bytes(data)
            (evidence / 'private.db').write_bytes(b'private data')
            (evidence / 'unrelated.exe').write_bytes(b'unrelated binary')
            target, archive = Path(tmp) / 'package', Path(tmp) / 'package.zip'
            with patch.object(bundle, 'ROOT', root):
                bundle.build(target, archive)

            manifest = json.loads((target / 'gongmudam-manifest.json').read_text(encoding='utf-8'))
            for name in ('folder-picker.jpg', 'folder-picker.jpeg'):
                relative_name = f'docs/evidence/v72/{name}'
                packaged = target / relative_name
                self.assertEqual(packaged.read_bytes(), image_bytes[name])
                self.assertEqual(manifest['files'][relative_name], hashlib.sha256(image_bytes[name]).hexdigest())
            self.assertFalse((target / 'docs/evidence/v72/folder-picker-initial.jpg').exists())
            self.assertFalse((target / 'docs/evidence/v72/private.db').exists())
            self.assertFalse((target / 'docs/evidence/v72/unrelated.exe').exists())
            with zipfile.ZipFile(archive) as contents:
                names = set(contents.namelist())
                for name in ('folder-picker.jpg', 'folder-picker.jpeg'):
                    relative_name = f'공무담/docs/evidence/v72/{name}'
                    self.assertIn(relative_name, names)
                    self.assertEqual(contents.read(relative_name), image_bytes[name])
                self.assertNotIn('공무담/docs/evidence/v72/folder-picker-initial.jpg', names)
                self.assertNotIn('공무담/docs/evidence/v72/private.db', names)
                self.assertNotIn('공무담/docs/evidence/v72/unrelated.exe', names)


if __name__ == '__main__':
    unittest.main()
