import importlib.util
import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from integration.application import (EmbeddedPages, PublicModelBudget, desktop_asset,
                                     service_version, validate_public_config)


class AssetBoundaryTests(unittest.TestCase):
    def test_frontend_files_allowed_but_database_python_and_traversal_are_not(self):
        self.assertIsNotNone(desktop_asset('index.html'))
        self.assertIsNotNone(desktop_asset('assets/seomu-otter-v1.png'))
        for name in ('data/agencies-v1.sqlite', 'server.py', '../service/config.json'):
            self.assertIsNone(desktop_asset(name), name)


class ServiceVersionTests(unittest.TestCase):
    def test_reads_release_version_from_selected_service_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = Path(tmp)
            (service / 'submission-manifest.json').write_text(
                json.dumps({'release_version': 'v70'}), encoding='utf-8')
            self.assertEqual(service_version(service), 'v70')

    def test_missing_empty_or_non_string_release_version_fails_clearly(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = Path(tmp)
            with self.assertRaisesRegex(RuntimeError, 'submission manifest'):
                service_version(service)
            for value in ('', 70, None):
                (service / 'submission-manifest.json').write_text(
                    json.dumps({'release_version': value}), encoding='utf-8')
                with self.assertRaisesRegex(RuntimeError, 'release_version'):
                    service_version(service)


class EmbedTests(unittest.TestCase):
    def test_cached_legacy_html_cannot_bypass_the_current_entry_adapter(self):
        from fastapi.staticfiles import StaticFiles
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'index.html').write_text('<html><head></head><body>OLD</body></html>',encoding='utf-8')
            static=StaticFiles(directory=tmp)
            old=TestClient(static).get('/index.html')
            response=TestClient(EmbeddedPages(static)).get('/index.html',headers={'If-None-Match':old.headers['etag']})
            self.assertEqual(response.status_code,200)
            self.assertIn(b'/desktop/service-entry.js',response.content)
            self.assertEqual(response.headers.get('cache-control'),'no-store')
            self.assertNotIn('etag',response.headers)

    def client(self, media, data, csp=True):
        async def app(scope, receive, send):
            headers = [(b'content-type', media), (b'content-length', str(len(data)).encode())]
            if csp: headers.append((b'content-security-policy', b"frame-ancestors 'none'; default-src 'self'"))
            await send({'type': 'http.response.start', 'status': 200, 'headers': headers})
            await send({'type': 'http.response.body', 'body': data[:3], 'more_body': True})
            await send({'type': 'http.response.body', 'body': data[3:]})
        return TestClient(EmbeddedPages(app))

    def test_html_adapter_injected_once_and_same_origin_framing_allowed(self):
        result = self.client(b'text/html', b'<html><head></head><body>OK</body></html>').get('/index.html')
        self.assertEqual(result.content.count(b'/desktop/embedded.js'), 1)
        self.assertEqual(result.content.count(b'/desktop/service-entry.js'), 1)
        self.assertLess(result.content.index(b'/desktop/service-entry.js'), result.content.index(b'</head>'))
        self.assertNotIn('content-length', result.headers)
        self.assertIn("frame-ancestors 'self'", result.headers['Content-Security-Policy'])

    def test_download_bytes_and_content_length_are_preserved(self):
        data = b'%PDF\x00\x01\x02binary'
        result = self.client(b'application/pdf', data).get('/api/file')
        self.assertEqual(result.content, data)
        self.assertEqual(result.headers['content-length'], str(len(data)))

    def test_desktop_does_not_receive_embedded_adapter(self):
        result = self.client(b'text/html', b'<head></head>').get('/desktop/')
        self.assertNotIn(b'embedded.js', result.content)

    def test_toolbox_allows_blob_previews_and_wasm_without_general_eval(self):
        policy = self.client(b'text/html', b'<head></head>').get('/toolbox.html').headers['Content-Security-Policy']
        self.assertIn("img-src 'self' data: blob:", policy)
        self.assertIn("script-src 'self' 'wasm-unsafe-eval'", policy)
        self.assertNotIn("'unsafe-eval'", policy)


class RuntimePreservationTests(unittest.TestCase):
    def builder(self):
        path = Path(__file__).resolve().parents[1] / 'tools/prepare_public_runtime.py'
        spec = importlib.util.spec_from_file_location('runtime_builder', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def test_existing_runtime_without_matching_marker_is_never_overwritten(self):
        module = self.builder()
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / 'runtime'; destination.mkdir()
            original = destination / 'work.txt'; original.write_text('saved work')
            with patch.object(module, 'DEST', destination):
                with self.assertRaises(RuntimeError): module.prepare()
            self.assertEqual(original.read_text(), 'saved work')

    def test_new_runtime_metadata_uses_manifest_release_and_source_count(self):
        module = self.builder()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source'
            destination = Path(tmp) / 'runtime'
            (source / 'tools').mkdir(parents=True)
            (source / 'tools/restore_submission.py').write_text('', encoding='utf-8')
            (source / 'config.example.json').write_text('{}', encoding='utf-8')
            manifest = {'release_version': 'v70', 'sources': 36, 'files': {
                name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                for name in ('tools/restore_submission.py', 'config.example.json')}}
            (source / 'submission-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            with patch.object(module, 'SOURCE', source), patch.object(module, 'DEST', destination), \
                 patch.object(module.subprocess, 'run'):
                result = module.prepare()
            definition = json.loads((destination / 'public-demo.json').read_text(encoding='utf-8'))
            self.assertEqual(result['public_sources'], 36)
            self.assertEqual(definition['created_from'], 'verified v70 public sources; no private databases')


class ModelBudgetTests(unittest.TestCase):
    def test_new_model_check_routes_share_the_same_budget(self):
        async def app(scope, receive, send):
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'OK'})
        client = TestClient(PublicModelBudget(app, limit=1))
        self.assertEqual(client.post('/api/workspace/model-check').status_code, 200)
        self.assertEqual(client.post('/api/settings/llm/test').status_code, 429)
        self.assertEqual(client.get('/api/workspace/model-status').status_code, 200)

    def test_questions_sent_without_ai_do_not_use_the_shared_budget(self):
        seen = []
        async def app(scope, receive, send):
            seen.append((await receive()).get('body'))
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'OK'})
        client = TestClient(PublicModelBudget(app, limit=1))
        for _ in range(3):
            self.assertEqual(client.post('/api/ask', json={'query': 'q', 'use_ai': False}).status_code, 200)
        self.assertIn(b'"use_ai"', seen[0])  # The app still reads the whole request.
        self.assertEqual(client.post('/api/ask', json={'query': 'q', 'use_ai': True}).status_code, 200)
        self.assertEqual(client.post('/api/ask', json={'query': 'q'}).status_code, 429)
        self.assertEqual(client.post('/api/ask', content=b'not json').status_code, 429)
        self.assertEqual(client.post('/api/ask', json={'query': 'q', 'use_ai': False}).status_code, 200)

    def test_limits_come_from_environment_with_pc_defaults(self):
        from integration.application import public_limit
        with patch.dict('os.environ', {}, clear=False):
            os.environ.pop('GONGMUDAM_PUBLIC_HOURLY', None)
            self.assertEqual(public_limit('GONGMUDAM_PUBLIC_HOURLY', 30), 30)
        for value, expected in (('120', 120), ('0', 30), ('abc', 30), ('99999', 30)):
            with patch.dict('os.environ', {'GONGMUDAM_PUBLIC_HOURLY': value}):
                self.assertEqual(public_limit('GONGMUDAM_PUBLIC_HOURLY', 30), expected)


class PublicConfigTests(unittest.TestCase):
    def test_selection_counter_allowed_but_other_changes_still_checked(self):
        original = {'llm': {'active': 'local_gemma', 'profiles': {'local_gemma': {}, 'local_llama': {}}}}
        changed = copy.deepcopy(original)
        changed['llm'].update(active='local_llama', _selection_revision=1)
        seen = []
        validate_public_config(changed, original, original, lambda value, baseline: seen.append((value, baseline)))
        self.assertNotIn('_selection_revision', seen[0][0]['llm'])
        self.assertEqual(seen[0][0]['llm']['active'], 'local_llama')
        changed['llm']['_selection_revision'] = 20
        with self.assertRaises(ValueError): validate_public_config(changed, original, original, lambda *_: None)


if __name__ == '__main__':
    unittest.main()
