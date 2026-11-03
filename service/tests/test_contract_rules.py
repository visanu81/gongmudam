"""수의계약 amount limits come from the decree of the contracting body, quoted, without AI."""
import json
import re
import unittest
from unittest.mock import patch

from app import contract_rules, knowledge, llm, main, office_knowledge as office

CASES = (
    ('지방자치단체 수의계약 한도는?', 'local', ('2천만원 이하', '1억원 이하', '4억원')),
    ('시청에서 2천만원 이하 물품 수의계약 가능해?', 'local', ('2천만원 이하', '청년창업기업')),
    ('국가기관 물품 수의계약 얼마까지 가능해?', 'national', ('2천만원 이하', '5천만원 이하', '재정경제부장관')),
)


class ContractRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((office.CONTRACT_BASE / 'manifest.json').read_text(encoding='utf-8'))
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
        self.assertEqual([r['article'] for r in self.manifest], ['제25조(수의계약에 의할 수 있는 경우)', '제26조(수의계약에 의할 수 있는 경우)'])
        for row in self.manifest:
            self.assertEqual(office.metadata(row['sha256']), row)
            self.assertTrue(row['source_url'].startswith('https://www.law.go.kr/'))

    def test_limits_are_quoted_from_the_matching_decree(self):
        for query, scope, phrases in CASES:
            with self.subTest(query=query):
                response = self.ask(query); reply = response['knowledge']; tree = reply['tree']
                self.assertEqual(tree['rule_id'], f'office:contract-{scope}-private')
                self.assertIsNone(response['model'])
                self.assertEqual([h['official']['id'] for h in reply['evidence']],
                                 ['office-contract-local-decree-25' if scope == 'local' else 'office-contract-national-decree-26'])
                for phrase in phrases:
                    self.assertIn(phrase, response['answer'])
                for b in tree['branches']:
                    for item in b['items']:
                        for quote in item['support_quotes']:
                            self.assertIn(quote, reply['evidence'][item['ref'] - 1]['text'])

    def test_contracting_body_is_asked_not_guessed(self):
        for query in ('수의계약 금액 기준은?', '국가기관과 지자체 수의계약 한도 비교', '공공기관 수의계약 한도'):
            with self.subTest(query=query):
                reply = self.ask(query)['knowledge']
                self.assertFalse(reply['evidence'])
                self.assertTrue(re.search('국가기관인지|공공기관', reply['notice']))

    def test_selection_procedure_stays_on_the_quote_article(self):
        for query in ('수의계약 대상자 선정 절차는?', '지방자치단체 수의계약 견적 몇 명?', '연가 며칠이야?'):
            with self.subTest(query=query):
                self.assertIsNone(contract_rules.classify(query))


if __name__ == '__main__':
    unittest.main()
