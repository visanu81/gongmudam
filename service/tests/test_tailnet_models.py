"""A model on another of the user's PCs over Tailscale counts as local; other hosts stay external."""
import unittest
from unittest.mock import MagicMock, patch

from app import config, knowledge, llm, local_ai, model_status


class TailnetModelTest(unittest.TestCase):
    def test_tailnet_and_loopback_hosts_are_private(self):
        for host in ('127.0.0.1', 'localhost', '::1', '100.88.175.64', '100.64.0.1', 'rtx.tail1234.ts.net'):
            with self.subTest(host=host):
                self.assertTrue(local_ai.private_model_host(host))
        for host in ('100.128.0.1', '192.168.0.5', '203.0.113.5', 'api.example.com', None, ''):
            with self.subTest(host=host):
                self.assertFalse(local_ai.private_model_host(host))

    def answer_mode(self, base_url):
        profile = dict(provider='openai_compatible', base_url=base_url, model='qwen3.5:9b', _name='rtx')
        hit = dict(id='lib:1', text='제15조(연가일수) 연가는 재직기간에 따라 정한다.', title='합성', loc='제15조',
                   source_id='lib', kind='regulation', score=1.0, limited=False, official=None)
        provider = MagicMock(available=True)
        with patch.object(config, 'active_profile', return_value=profile), patch.object(llm, 'get_provider', return_value=provider), \
             patch.object(knowledge, '_model_evidence', return_value=[dict(id='lib:1', quote='연가는 재직기간에 따라 정한다.')]) as chosen:
            reply = knowledge.answer('연가 며칠', dict(hits=[hit], experiences=[], excluded=[], intent=None), use_ai=True)
        return reply['mode'], chosen.called

    def test_answers_use_a_tailnet_model_but_not_an_external_one(self):
        self.assertEqual(self.answer_mode('http://100.88.175.64:11434/v1'), ('source_llm', True))
        self.assertEqual(self.answer_mode('http://203.0.113.5:11434/v1'), ('source_search', False))

    def test_model_status_checks_a_tailnet_model_as_local(self):
        kind, target = model_status._target(dict(provider='openai_compatible', base_url='http://100.88.175.64:11434/v1'), 'qwen3.5:9b')
        self.assertEqual((kind, target), ('local', 'http://100.88.175.64:11434/v1/models'))
        self.assertEqual(model_status._target(dict(provider='openai_compatible', base_url='http://203.0.113.5/v1'), 'm')[0], 'external')


if __name__ == '__main__':
    unittest.main()
