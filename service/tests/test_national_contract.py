"""National-agency contract steps are quoted from 국가계약법 시행령, without AI; local ones keep 지방계약법."""
import json
import unittest
from unittest.mock import patch

from app import knowledge, llm, main, national_contract, office_knowledge as office
from tools.prepare_goods_pack import build

CASES = (
    ('국가기관 물품 대금 언제까지 지급해야 해?', 'payment', 58, ('5일 이내', '공휴일과 토요일', '3일')),
    ('국가기관 대금 지급 늦으면 이자 줘야 해?', 'interest', 59, ('대출평균금리', '다음 날부터')),
    ('국가기관 물품 검사는 언제까지 해야 해?', 'inspection', 55, ('14일 이내', '7일')),
    ('국가기관 검사조서 작성 생략 금액은?', 'inspection-report', 56, ('3천만원 이하', '3천만원 미만')),
    ('중앙부처 수의계약 견적서 몇 개 받아야 해?', 'quote', 30, ('2인 이상', '2천만원 이하', '전자조달시스템')),
)


class NationalContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((office.NATIONAL_CONTRACT_BASE / 'manifest.json').read_text(encoding='utf-8'))
        cls.sources = [dict(id=r['id'], title=r['title'] + ' ' + r['article'], enabled=True, current=True,
                            sha256=r['sha256'], effective_date=r['effective_date'], kind=r['kind'], institution=r['institution'],
                            limited=False, library_id=r['collection'], file_id=r['id'], units=r['units'], official=r) for r in cls.manifest]

    def ask(self, query):
        with patch.object(knowledge, 'sources', return_value=self.sources), \
             patch.object(knowledge, '_experience_hits', return_value=[]), \
             patch.object(knowledge.config, 'active_profile', return_value={'provider': 'offline'}), \
             patch.object(llm, 'get_provider', side_effect=AssertionError('AI must not be used')):
            return main.api_ask(dict(query=query, guidance=True, use_ai=False, today='2026-11-04'))

    def test_pack_is_the_saved_official_articles(self):
        self.assertEqual([r['article'][:5] for r in self.manifest], ['제30조(', '제55조(', '제56조(', '제58조(', '제59조('])
        for row in self.manifest:
            self.assertEqual(office.metadata(row['sha256']), row)
            self.assertIn('lsiSeq=285893', row['source_url'])

    def test_rebuild_reproduces_the_saved_pack(self):
        import shutil, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'pack'
            shutil.copytree(office.NATIONAL_CONTRACT_BASE, base, ignore=shutil.ignore_patterns('excerpts', 'manifest.json'))
            self.assertEqual(build(base), self.manifest)

    def test_steps_are_quoted_from_the_national_decree(self):
        for query, rule, article, phrases in CASES:
            with self.subTest(query=query):
                response = self.ask(query); reply = response['knowledge']; tree = reply['tree']
                self.assertEqual(tree['rule_id'], 'office:ncontract-' + rule)
                self.assertIsNone(response['model'])
                self.assertEqual([h['official']['id'] for h in reply['evidence']], [f'office-ncontract-decree-{article}'])
                for phrase in phrases:
                    self.assertIn(phrase, response['answer'])
                for b in tree['branches']:
                    for item in b['items']:
                        for quote in item['support_quotes']:
                            self.assertIn(quote, reply['evidence'][item['ref'] - 1]['text'])

    def test_local_and_unnamed_questions_keep_their_routes(self):
        for query in ('지자체 물품 대금 언제까지 지급해야 해?', '검사조서 작성 생략 금액은?', '물품 대금 언제까지 줘야 해?',
                      '국가기관 선금 지급 가능해?', '국가기관 물품 수의계약 얼마까지 가능해?', '국가공무원 연가 며칠?'):
            with self.subTest(query=query):
                self.assertIsNone(national_contract.classify(query))


if __name__ == '__main__':
    unittest.main()
