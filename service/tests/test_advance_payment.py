"""선금 questions are quoted from 지방회계법·국고금 관리법, their decrees and the 계약예규, without AI."""
import json
import unittest
from unittest.mock import patch

from app import advance_payment, knowledge, llm, main, office_knowledge as office
from tools.prepare_advance_pack import build

CASES = (
    ('지자체 공사 선금 얼마까지 줄 수 있어?', 'local', '지급 한도', ('70%', '14일 이내', '구매계약은 빠져요', '30%는 의무')),
    ('지방자치단체 용역 선금은 청구받고 며칠 안에 줘야 해?', 'local', '지급 기한', ('14일 이내', '문서로')),
    ('국가기관 공사 선금 한도는?', 'national', '지급 한도', ('70%', '100%', '재정경제부장관', '20억원 미만 50%')),
    ('지자체 선금 정산은 어떻게 해?', 'local-procedure', '사용과 정산', ('기성·기납 대가를 줄 때마다', '선금전용계좌')),
    ('지자체 선금 보증서 면제되는 경우는?', 'local-procedure', '보증서', ('지급확약서', '60일 이상')),
    ('국가기관 선금 보증서 받아야 해?', 'national-procedure', '보증서', ('보증서', '30일 이상')),
    ('국가기관 선금 반환 청구는 언제 해?', 'national-procedure', '반환 청구', ('계약금액 감액', '매일의 잔액')),
    ('중앙부처 선금 지급 기한은?', 'national', '지급 기한', ('14일 이내',)),
    ('선금 얼마까지 줄 수 있어?\n업무환경: 경기도 소속 지방공무원', 'local', '지급 한도', ('70%',)),
    ('선금 지급 한도는?\n업무환경: 국가공무원', 'national', '지급 한도', ('100%',)),
)


class AdvancePaymentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = [r for base in (office.ADVANCE_BASE, office.ADVANCE_RULE_BASE)
                        for r in json.loads((base / 'manifest.json').read_text(encoding='utf-8'))]
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
        self.assertEqual([r['title'] + ' ' + r['article'][:5] for r in self.manifest],
                         ['지방회계법 제35조(', '지방회계법 시행령 제44조(', '국고금 관리법 제26조(', '국고금 관리법 시행령 제40조(',
                          '지방자치단체 입찰 및 계약 집행기준 제1장 제', '정부 입찰ㆍ계약 집행기준 제34조(', '정부 입찰ㆍ계약 집행기준 제35조(',
                          '정부 입찰ㆍ계약 집행기준 제36조(', '정부 입찰ㆍ계약 집행기준 제37조(', '정부 입찰ㆍ계약 집행기준 제38조('])
        local_rule = self.manifest[4]['units'][0]['text']
        self.assertTrue(local_rule.startswith('제2절 선금 및 대가 지급') and '6. 대가의 지급' not in local_rule)
        self.assertNotIn('- 13 -', local_rule)
        for row in self.manifest:
            self.assertEqual(office.metadata(row['sha256']), row)

    def test_rebuild_reproduces_the_saved_pack(self):
        import shutil, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            rows = []
            for n, pack in enumerate((office.ADVANCE_BASE, office.ADVANCE_RULE_BASE)):
                base = Path(tmp) / str(n)
                shutil.copytree(pack, base, ignore=shutil.ignore_patterns('excerpts', 'manifest.json'))
                rows += build(base)
            self.assertEqual(rows, self.manifest)

    def test_answers_are_quoted_from_the_right_law(self):
        for query, side, lead, phrases in CASES:
            with self.subTest(query=query):
                response = self.ask(query); reply = response['knowledge']; tree = reply['tree']
                self.assertEqual(tree['rule_id'], 'office:advance-' + side)
                self.assertIsNone(response['model'])
                self.assertEqual(tree['branches'][0]['label'], lead)
                self.assertTrue(all(h['official']['id'].startswith('office-advance-' + side.split('-')[0]) for h in reply['evidence']))
                for phrase in phrases:
                    self.assertIn(phrase, response['answer'])
                for b in tree['branches']:
                    for item in b['items']:
                        for quote in item['support_quotes']:
                            self.assertIn(quote, reply['evidence'][item['ref'] - 1]['text'])

    def test_unknown_body_is_asked(self):
        for query in ('선금 지급할 수 있어?', '선금 정산은 어떻게 해?'):
            with self.subTest(query=query):
                reply = self.ask(query)['knowledge']
                self.assertFalse(reply['evidence'])
                self.assertIn('국가기관인지 지방자치단체인지', reply['notice'])

    def test_inspection_questions_keep_the_local_contract_route(self):
        for query in ('지방자치단체 선금 지급이 검사 후 지급 원칙의 예외인가요?',
                      '지방자치단체에서 물품을 납품받으면 검사 전에 대금을 지급해도 되나요? 선금급 예외도 확인해주세요.',
                      '국가기관 물품 대금 언제까지 지급해야 해?', '업무추진비 공개 주기'):
            with self.subTest(query=query):
                self.assertIsNone(advance_payment.classify(query))


if __name__ == '__main__':
    unittest.main()
