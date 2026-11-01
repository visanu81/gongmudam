"""Fixes ported from the teammate branch (2026-11-01): local boundary, issuance numbers, AI off."""
import os
import unittest
from datetime import date
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import knowledge, llm, main
from app.knowledge_supplement import without_document_numbers


class LocalBoundaryTest(unittest.TestCase):
    """A browser on this PC reaches the server from 127.0.0.1; only its own screen may use it."""

    def client(self):
        return TestClient(main.app, base_url='http://127.0.0.1:8787', client=('127.0.0.1', 50000))

    def test_own_screen_is_allowed(self):
        self.assertEqual(self.client().get('/api/documents').status_code, 200)
        response = self.client().post('/api/ask', json={'query': '연가 일수', 'use_ai': False},
                                      headers={'Origin': 'http://127.0.0.1:8787'})
        self.assertEqual(response.status_code, 200)

    def test_rebound_host_is_rejected(self):
        response = self.client().get('/api/documents', headers={'Host': 'evil.example'})
        self.assertEqual(response.status_code, 400)

    def test_cross_site_change_is_rejected(self):
        for headers in ({'Origin': 'http://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}):
            with self.subTest(headers=headers):
                response = self.client().post('/api/ask', json={'query': '연가', 'use_ai': False}, headers=headers)
                self.assertEqual(response.status_code, 403)

    def test_public_demo_keeps_its_own_policy(self):
        main.app.state.public_demo = True
        try:
            response = self.client().get('/api/documents', headers={'Host': 'gongmudam.example.dev'})
            self.assertNotEqual(response.status_code, 400)
        finally:
            del main.app.state.public_demo


class DocumentNumberTest(unittest.TestCase):
    def test_issuance_number_is_not_a_year(self):
        self.assertNotIn('2025', without_document_numbers('인사혁신처예규 제2025-3호에 따른 연가'))
        self.assertIn('2024년', without_document_numbers('예규 제2025-3호, 2024년 사건'))
        query = '인사혁신처예규 제2025-3호에 따른 국가공무원 연가 일수는?'
        found = knowledge.retrieve(query, None, date(2026, 11, 1))
        self.assertTrue(found['hits'])
        # The reviewed conclusion still applies; the number is not a personal case.
        from app import answer_tree
        tree = answer_tree.build(query, knowledge.answer(query, found, use_ai=False))
        self.assertEqual(tree.get('rule_id'), 'service-rules:national-annual')


class AiOffTest(unittest.TestCase):
    def test_request_with_ai_off_never_builds_a_model_provider(self):
        profile = {'provider': 'openai_compatible', 'base_url': 'http://127.0.0.1:1/v1', 'model': 'x'}
        with llm.inference_policy(True):
            self.assertIsInstance(llm.get_provider(profile), llm.OfflineProvider)
            with self.assertRaises(llm.LLMError):
                llm.OpenAICompatibleProvider(profile).chat([{'role': 'user', 'content': 'x'}])
        self.assertNotIsInstance(llm.get_provider(profile), llm.OfflineProvider)

    def test_runtime_switch_turns_every_model_call_off(self):
        with patch.dict(os.environ, {'GONGMUDAM_NO_LLM': '1'}):
            self.assertTrue(llm.disabled())
            # 업무자료 정리 calls Ollama directly; that path is closed too.
            from app import folder_ai
            with patch.object(folder_ai.httpx, 'post', side_effect=AssertionError('model called')):
                with self.assertRaises(llm.LLMError):
                    folder_ai.call_model({'base_url': 'http://127.0.0.1:11434/v1', 'model': 'x'}, [])
