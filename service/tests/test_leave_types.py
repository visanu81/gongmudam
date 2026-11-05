"""Which kinds of leave exist is answered from 복무규정 at once, without AI; situations keep their own guidance."""
import json
import unittest
from unittest.mock import patch

from app import knowledge, leave_types, llm, main, office_knowledge as office
from tools.prepare_advance_pack import build

CASES = (
    ('휴가종류는 뭐가있냐', 'both', '휴가 네 가지', ('연가, 병가, 공가, 특별휴가', '제14조', '제6조', '조례')),
    ('휴가 종류 알려줘', 'both', '휴가 네 가지', ('연가, 병가, 공가, 특별휴가',)),
    ('휴가에는 어떤 종류가 있나요?', 'both', '휴가 네 가지', ('네 가지',)),
    ('연가 말고 무슨 휴가가 있어?', 'both', '휴가 네 가지', ('특별휴가',)),
    ('특별휴가 종류 알려줘', 'both', '특별휴가 세부 종류', ('가족돌봄', '장기재직')),
    ('국가공무원 휴가 종류는?', 'national', '휴가 네 가지', ('연 60일', '제19조', '장기재직')),
    ('지방공무원 휴가 종류는?', 'local', '휴가 네 가지', ('연 60일', '제7조의6', '조례')),
    ('휴가 종류\n업무환경: 경기도 소속 지방공무원', 'local', '휴가 네 가지', ('지방공무원 휴가는',)),
    ('휴가 종류\n업무환경: 국가공무원', 'national', '휴가 네 가지', ('국가공무원 휴가는',)),
)


class LeaveTypesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((office.LEAVE_TYPES_BASE / 'manifest.json').read_text(encoding='utf-8'))
        cls.sources = [dict(id=r['id'], title=r['title'] + ' ' + r['article'], enabled=True, current=True,
                            sha256=r['sha256'], effective_date=r['effective_date'], kind=r['kind'], institution=r['institution'],
                            limited=False, library_id=r['collection'], file_id=r['id'], units=r['units'], official=r) for r in cls.manifest]

    def ask(self, query):
        with patch.object(knowledge, 'sources', return_value=self.sources), \
             patch.object(knowledge, '_experience_hits', return_value=[]), \
             patch.object(knowledge.config, 'active_profile', return_value={'provider': 'offline'}), \
             patch.object(llm, 'get_provider', side_effect=AssertionError('AI must not be used')):
            return main.api_ask(dict(query=query, guidance=True, use_ai=False, today='2026-11-05'))

    def test_pack_is_the_saved_official_articles(self):
        self.assertEqual(len(self.manifest), 10)
        for row in self.manifest:
            self.assertEqual(office.metadata(row['sha256']), row)

    def test_rebuild_reproduces_the_saved_pack(self):
        import shutil, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'pack'
            shutil.copytree(office.LEAVE_TYPES_BASE, base, ignore=shutil.ignore_patterns('excerpts', 'manifest.json'))
            self.assertEqual(build(base), self.manifest)

    def test_answers_are_quoted_from_the_decrees(self):
        for query, side, lead, phrases in CASES:
            with self.subTest(query=query):
                response = self.ask(query); reply = response['knowledge']; tree = reply['tree']
                self.assertEqual(tree['rule_id'], 'office:leave-types-' + side)
                self.assertIsNone(response['model'])
                self.assertEqual(tree['branches'][0]['label'], lead)
                for phrase in phrases:
                    self.assertIn(phrase, response['answer'])
                for b in tree['branches']:
                    for item in b['items']:
                        for quote in item['support_quotes']:
                            self.assertIn(quote, reply['evidence'][item['ref'] - 1]['text'])

    def test_the_title_is_the_conclusion(self):
        self.assertIn('연가, 병가, 공가, 특별휴가', self.ask('휴가 종류 알려줘')['knowledge']['tree']['title'])

    def test_each_decree_is_used_only_for_its_own_body(self):
        reply = self.ask('지방공무원 휴가 종류는?')['knowledge']
        self.assertTrue(all(h['official']['title'] == '지방공무원 복무규정' for h in reply['evidence']))
        reply = self.ask('국가공무원 휴가 종류는?')['knowledge']
        self.assertTrue(all(h['official']['title'] == '국가공무원 복무규정' for h in reply['evidence']))

    def test_situations_and_other_bodies_keep_their_routes(self):
        for query in ('아이가 아플 때 어떤 휴가가 있어?', '결혼하면 어떤 휴가가 있어?', '병가 며칠?', '연가 며칠?',
                      '소방공무원 휴가 종류는?', '교원 휴가 종류', '명절휴가비 종류', '특별휴가 며칠?',
                      '제가 아파서 쉬어야 하는데 무슨 휴가가 있어?'):
            with self.subTest(query=query):
                self.assertIsNone(leave_types.classify(query))


if __name__ == '__main__':
    unittest.main()
