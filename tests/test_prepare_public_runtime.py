import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import prepare_public_runtime as runtime


class PreservePublicRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.dest=self.root/'public'
        self.source.mkdir();self.dest.mkdir()
        self.put(self.source/'submission-manifest.json',dict(release_version='new',sources=1,files={}))
        (self.dest/'app.py').write_bytes(b'verified old app')
        self.put(self.dest/'submission-manifest.json',dict(release_version='old',sources=1,files={
            'app.py':hashlib.sha256(b'verified old app').hexdigest(), 'wheels/not-copied.whl':'0'*64}))
        self.put(self.dest/'gongmudam-runtime.json',dict(source_manifest_sha256=self.digest(self.dest/'submission-manifest.json')))
        self.put(self.dest/'public-demo.json',dict(mode='public-synthetic-demo',private_data_isolated=True))
        (self.dest/'data').mkdir();(self.dest/'data/user.db').write_bytes(b'preserve data')

    def put(self,path,value):path.write_text(json.dumps(value),encoding='utf-8')
    def digest(self,path):return hashlib.sha256(path.read_bytes()).hexdigest()
    def prepare(self):
        with patch.object(runtime,'SOURCE',self.source),patch.object(runtime,'DEST',self.dest):return runtime.prepare()

    def test_source_release_change_does_not_block_verified_existing_public_app(self):
        before={p.relative_to(self.dest).as_posix():p.read_bytes() for p in self.dest.rglob('*') if p.is_file()}
        with patch.object(runtime.subprocess,'run',side_effect=AssertionError('No reinstall')):
            result=self.prepare()
        self.assertEqual(result['status'],'preserved')
        self.assertTrue(result['source_update_available'])
        self.assertEqual(result['version'],'old')
        self.assertEqual(before,{p.relative_to(self.dest).as_posix():p.read_bytes() for p in self.dest.rglob('*') if p.is_file()})

    def test_tampered_managed_file_is_rejected_even_if_source_version_matches(self):
        (self.source/'submission-manifest.json').write_bytes((self.dest/'submission-manifest.json').read_bytes())
        (self.dest/'app.py').write_bytes(b'changed')
        with self.assertRaises(RuntimeError):self.prepare()

    def test_marker_is_checked_against_runtime_not_new_development_manifest(self):
        self.put(self.dest/'gongmudam-runtime.json',dict(source_manifest_sha256=self.digest(self.source/'submission-manifest.json')))
        with self.assertRaises(RuntimeError):self.prepare()

    def test_private_or_interrupted_runtime_is_rejected(self):
        for content in ({'mode':'local','private_data_isolated':True}, {'mode':'public-synthetic-demo','private_data_isolated':False}):
            self.put(self.dest/'public-demo.json',content)
            with self.assertRaises(RuntimeError):self.prepare()
        self.put(self.dest/'public-demo.json',dict(mode='public-synthetic-demo',private_data_isolated=True))
        (self.dest/'data/gongmudam-upgrade.lock').touch()
        with self.assertRaises(RuntimeError):self.prepare()

    def test_managed_path_cannot_escape_runtime(self):
        (self.root/'outside.py').write_bytes(b'verified old app')
        self.put(self.dest/'submission-manifest.json',dict(release_version='old',sources=1,files={
            '../outside.py':hashlib.sha256(b'verified old app').hexdigest()}))
        self.put(self.dest/'gongmudam-runtime.json',dict(source_manifest_sha256=self.digest(self.dest/'submission-manifest.json')))
        with self.assertRaises(RuntimeError):self.prepare()
