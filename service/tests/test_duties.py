"""공무원의 의무, 복무 위반, 승진소요최저연수, 공문 보존기간, 예비군 복무 are answered from the rules, without AI."""
import json
import unittest
from unittest.mock import patch

from app import knowledge, llm, main, office_knowledge as office, service_kinds
from tools.prepare_advance_pack import build

CASES = (
    ('복무 의무 뭐 있어?', 'duties-both', ('성실', '비밀 엄수', '제47조', '퇴직 후에도')),
    ('공무원 의무 알려줘', 'duties-both', ('집단 행위 금지', '제66조')),
    ('지방공무원 의무 알려줘', 'duties-local', ('주민 전체의 봉사자', '제58조')),
    ('공무원 의무 뭐야?\n업무환경: 국가공무원', 'duties-national', ('국민 전체의 봉사자', '제60조')),
    ('복무 위반하면 어떻게 돼?', 'violation-both', ('징계 의결을 요구', '제78조', '제69조', '파면')),
    ('지방공무원 복무 위반하면 어떻게 돼?', 'violation-local', ('제69조', '조례')),
    ('승진 소요 최저연수는?', 'promotion-both', ('4·5급 3년', '6급 2년', '제31조', '제33조', '육아휴직')),
    ('국가공무원 승진 최저연수', 'promotion-national', ('우정', '제31조')),
    ('지방공무원 승진 소요 최저연수', 'promotion-local', ('3급 이상 2년', '제33조')),
)


class DutiesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((office.DUTIES_BASE / 'manifest.json').read_text(encoding='utf-8'))
        rows = cls.manifest + [r for base in (office.LEAVE_TYPES_BASE, office.KINDS_BASE) for r in json.loads((base / 'manifest.json').read_text(encoding='utf-8'))]
        cls.sources = [dict(id=r['id'], title=r['title'] + ' ' + r['article'], enabled=True, current=True,
                            sha256=r['sha256'], effective_date=r['effective_date'], kind=r['kind'], institution=r['institution'],
                            limited=False, library_id=r['collection'], file_id=r['id'], units=r['units'], official=r) for r in rows]

    def ask(self, query):
        with patch.object(knowledge, 'sources', return_value=self.sources), \
             patch.object(knowledge, '_experience_hits', return_value=[]), \
             patch.object(knowledge.config, 'active_profile', return_value={'provider': 'offline'}), \
             patch.object(llm, 'get_provider', side_effect=AssertionError('AI must not be used')):
            return main.api_ask(dict(query=query, guidance=True, use_ai=False, today='2026-11-06'))

    def test_pack_is_the_saved_official_articles(self):
        self.assertEqual(len(self.manifest), 30)
        for row in self.manifest:
            self.assertEqual(office.metadata(row['sha256']), row)

    def test_rebuild_reproduces_the_saved_pack(self):
        import shutil, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'pack'
            shutil.copytree(office.DUTIES_BASE, base, ignore=shutil.ignore_patterns('excerpts', 'manifest.json'))
            self.assertEqual(build(base), self.manifest)

    def test_answers_are_quoted_from_the_rules(self):
        for query, rule, phrases in CASES:
            with self.subTest(query=query):
                response = self.ask(query); reply = response['knowledge']; tree = reply['tree']
                self.assertEqual(tree['rule_id'], 'office:' + rule)
                self.assertIsNone(response['model'])
                self.assertNotIn('먼저 확인할 내용', tree['title'])
                for phrase in phrases:
                    self.assertIn(phrase, response['answer'])
                for b in tree['branches']:
                    for item in b['items']:
                        for quote in item['support_quotes']:
                            self.assertIn(quote, reply['evidence'][item['ref'] - 1]['text'])

    def test_a_named_rank_is_the_conclusion(self):
        for query, title in (('9급 승진 몇 년 걸려?', '9급에서 승진하려면 1년 이상'), ('6급 승진 최저연수', '6급에서 승진하려면 2년 이상'),
                             ('5급 승진 소요연수', '5급에서 승진하려면 3년 이상'), ('지방공무원 3급 승진 몇 년 걸려?', '3급에서 승진하려면 2년 이상')):
            with self.subTest(query=query):
                self.assertIn(title, self.ask(query)['knowledge']['tree']['title'])
        # 공무원임용령 제31조 does not list 3급.
        self.assertNotIn('3급에서', self.ask('국가공무원 3급 승진 몇 년 걸려?')['knowledge']['tree']['title'])

    def test_each_law_is_used_only_for_its_own_body(self):
        for query, titles in (('지방공무원 의무 알려줘', {'지방공무원법'}), ('국가공무원 승진 최저연수', {'공무원임용령'})):
            self.assertEqual({h['official']['title'] for h in self.ask(query)['knowledge']['evidence']}, titles)

    def test_public_leave_cases_are_named(self):
        response = self.ask('예비군 가는데 복무 어떻게 올려?')
        tree = response['knowledge']['tree']
        self.assertEqual(tree['rule_id'], 'office:official-leave-both')
        self.assertIn('예비군 훈련은', tree['title'])
        self.assertIn('공가', tree['title'])

    def test_a_document_retention_question_is_a_records_question(self):
        for query in ('공문 보존기간은?', '문서 보존기간 얼마야?', '기안문 보존기간'):
            with self.subTest(query=query):
                self.assertEqual(office.classify(query)['rules'], ['records-retention-detail'])

    def test_specific_cases_and_other_bodies_keep_their_routes(self):
        for query in ('음주운전 복무 위반하면 어떻게 돼?', '승진시험 며칠 공가?', '승진 가산점 몇 점이야?', '승진 후보자 명부 언제 작성해?', '경찰공무원 의무 알려줘',
                      '근속승진 호봉은?', '복무 규정 어디서 봐?', '겸직 허가 받아야 해?\n업무환경: 국가공무원', '소방공무원 승진 소요 최저연수'):
            with self.subTest(query=query):
                self.assertIsNone(service_kinds.classify(query))


if __name__ == '__main__':
    unittest.main()
