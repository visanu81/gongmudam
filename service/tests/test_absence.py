"""휴직 grounds and periods are quoted from 국가공무원법·지방공무원법, without AI; pay keeps its own route."""
import json
import unittest
from unittest.mock import patch

from app import absence, knowledge, llm, main, office_knowledge as office
from tools.prepare_advance_pack import build

CASES = (
    ('육아휴직 기간은?', 'both', '육아 휴직', ('자녀 1명에 3년 이내', '제72조', '제64조', '12세 이하')),
    ('육아휴직 몇 년까지 돼?', 'both', '육아 휴직', ('3년',)),
    ('질병휴직 기간은?', 'both', '질병 휴직', ('1년 이내', '2년 더')),
    ('간병휴직 기간', 'both', '가족돌봄 휴직', ('총 3년',)),
    ('유학휴직 기간', 'both', '유학 휴직', ('3년 이내', '2년 더')),
    ('휴직 종류 알려줘', 'both', '휴직 종류', ('본인 의사와 상관없이', '자기개발', '임기제')),
    ('복직은 언제 해?', 'both', '신분과 복직', ('30일 이내',)),
    ('지방공무원 육아휴직 기간', 'local', '육아 휴직', ('제64조', '12세 이하')),
    ('국가공무원 휴직 종류', 'national', '휴직 종류', ('임기제',)),
    ('육아휴직 기간은?\n업무환경: 국가공무원', 'national', '육아 휴직', ('제72조',)),
    ('육아휴직 기간은?\n업무환경: 경기도 소속 지방공무원', 'local', '육아 휴직', ('제64조',)),
)


class AbsenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((office.ABSENCE_BASE / 'manifest.json').read_text(encoding='utf-8'))
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
        self.assertEqual([r['title'] + ' ' + r['article'][:4] for r in self.manifest],
                         ['국가공무원법 제71조', '국가공무원법 제72조', '국가공무원법 제73조', '지방공무원법 제63조', '지방공무원법 제64조', '지방공무원법 제65조'])
        for row in self.manifest:
            self.assertEqual(office.metadata(row['sha256']), row)

    def test_rebuild_reproduces_the_saved_pack(self):
        import shutil, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'pack'
            shutil.copytree(office.ABSENCE_BASE, base, ignore=shutil.ignore_patterns('excerpts', 'manifest.json'))
            self.assertEqual(build(base), self.manifest)

    def test_answers_are_quoted_from_the_laws(self):
        for query, side, lead, phrases in CASES:
            with self.subTest(query=query):
                response = self.ask(query); reply = response['knowledge']; tree = reply['tree']
                self.assertEqual(tree['rule_id'], 'office:absence-' + side)
                self.assertIsNone(response['model'])
                self.assertEqual(tree['branches'][0]['label'], lead)
                for phrase in phrases:
                    self.assertIn(phrase, response['answer'])
                for b in tree['branches']:
                    for item in b['items']:
                        for quote in item['support_quotes']:
                            self.assertIn(quote, reply['evidence'][item['ref'] - 1]['text'])

    def test_the_title_is_the_conclusion(self):
        self.assertEqual(self.ask('육아휴직 기간은?')['knowledge']['tree']['title'], '자녀를 키우거나 임신·출산으로 쉬는 휴직은 자녀 1명에 3년 이내예요.')

    def test_a_named_kind_leaves_the_other_kinds_out(self):
        answer = self.ask('육아휴직 기간은?')['answer']
        self.assertNotIn('유학', answer)
        self.assertNotIn('노동조합', answer)

    def test_each_law_is_used_only_for_its_own_body(self):
        for query, title in (('지방공무원 육아휴직 기간', '지방공무원법'), ('국가공무원 휴직 종류', '국가공무원법')):
            evidence = self.ask(query)['knowledge']['evidence']
            self.assertTrue(evidence)
            self.assertTrue(all(h['official']['title'] == title for h in evidence), query)

    def test_pay_procedure_and_other_bodies_keep_their_routes(self):
        for query in ('휴직하면 월급 나와?', '질병휴직하면 봉급 얼마나 받아?\n업무환경: 국가공무원', '휴직 신청 어떻게 해?',
                      '지방공무원 연가 재직기간에 일반 휴직기간을 넣나요?', '교원 육아휴직 기간', '경찰공무원 휴직 종류',
                      '육아시간 몇 시간?', '가족돌봄휴가 며칠?', '휴직자 호봉 승급은?'):
            with self.subTest(query=query):
                self.assertIsNone(absence.classify(query))


if __name__ == '__main__':
    unittest.main()
