"""업무추진비 공개 questions are answered from the saved 훈령 and 집행지침 sections, without AI."""
import json
import re
import unittest
from unittest.mock import patch

from app import expense_disclosure, knowledge, llm, main, office_knowledge as office
from tools import prepare_expense_pack

CASES = (
    ('지방자치단체 업무추진비 공개 주기는?', 'local', ('최소 분기마다', '1개월 이내', '노력')),
    ('시청 업무추진비 집행내역 홈페이지 공개 항목 알려줘', 'local', ('사용자, 일시, 장소', '결제방법')),
    ('국가기관 업무추진비 공개해야 해?', 'national', ('기관장의 업무추진비 사용내역', '자체 세부지침')),
)


class ExpenseDisclosureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((office.EXPENSE_BASE / 'manifest.json').read_text(encoding='utf-8'))
        cls.sources = [dict(id=r['id'], title=r['title'] + ' ' + r['article'], enabled=True, current=True,
                            sha256=r['sha256'], effective_date=r['effective_date'], kind=r['kind'], institution=r['institution'],
                            limited=False, library_id=r['collection'], file_id=r['id'], units=r['units'], official=r) for r in cls.manifest]

    def ask(self, query):
        with patch.object(knowledge, 'sources', return_value=self.sources), \
             patch.object(knowledge, '_experience_hits', return_value=[]), \
             patch.object(knowledge.config, 'active_profile', return_value={'provider': 'offline'}), \
             patch.object(llm, 'get_provider', side_effect=AssertionError('AI must not be used')):
            return main.api_ask(dict(query=query, guidance=True, use_ai=False, today='2026-11-04'))

    def test_pack_is_cut_from_the_reviewed_originals(self):
        self.assertEqual([r['id'] for r in self.manifest], ['office-expense-local-disclosure', 'office-expense-national-disclosure'])
        for row in self.manifest:
            self.assertEqual(office.metadata(row['sha256']), row)
        local = self.manifest[0]['units']
        self.assertEqual(len(local), 1)
        self.assertTrue(local[0]['text'].startswith('제121조(집행현황의 공개)'))
        self.assertIn('2-3. 공개방법', local[0]['text'])

    def test_rebuild_reproduces_the_saved_pack(self):
        import shutil, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'pack'
            shutil.copytree(office.EXPENSE_BASE, base, ignore=shutil.ignore_patterns('excerpts', 'manifest.json'))
            self.assertEqual(prepare_expense_pack.build(base), self.manifest)

    def test_disclosure_is_quoted_from_the_matching_source(self):
        for query, scope, phrases in CASES:
            with self.subTest(query=query):
                response = self.ask(query); reply = response['knowledge']; tree = reply['tree']
                self.assertEqual(tree['rule_id'], f'office:expense-{scope}-disclosure')
                self.assertIsNone(response['model'])
                self.assertEqual([h['official']['id'] for h in reply['evidence']], [f'office-expense-{scope}-disclosure'])
                for phrase in phrases:
                    self.assertIn(phrase, response['answer'])
                for b in tree['branches']:
                    for item in b['items']:
                        for quote in item['support_quotes']:
                            self.assertIn(quote, reply['evidence'][item['ref'] - 1]['text'])

    def test_the_asked_part_comes_first(self):
        self.assertTrue(self.ask('지방자치단체 업무추진비 공개 주기는?')['answer'].startswith('최소 분기마다'))
        tree = self.ask('도의회 업무추진비 홈페이지 공개 항목')['knowledge']['tree']
        self.assertEqual(tree['branches'][0]['label'], '공개 단위·항목·방법')

    def test_body_is_asked_not_guessed(self):
        for query in ('업무추진비 공개 주기는?', '공공기관 업무추진비 공개 기준'):
            with self.subTest(query=query):
                reply = self.ask(query)['knowledge']
                self.assertFalse(reply['evidence'])
                self.assertTrue(re.search('국가기관인지|공공기관', reply['notice']))

    def test_other_questions_keep_their_routes(self):
        for query in ('지방자치단체 업무추진비 집행 기준', '업무추진비 정보공개청구 처리 기한', '초빙강사료 집행내역 공개 주기'):
            with self.subTest(query=query):
                self.assertIsNone(expense_disclosure.classify(query))
        self.assertEqual(office.classify('업무추진비 정보공개청구 처리 기한')['topics'], ['disclosure'])


if __name__ == '__main__':
    unittest.main()
