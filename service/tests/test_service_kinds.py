"""공가 사유, 징계 종류·효력, 유연근무 유형 are quoted from the rules, without AI; specific cases keep their routes."""
import json
import unittest
from unittest.mock import patch

from app import knowledge, llm, main, office_knowledge as office, service_kinds
from tools.prepare_advance_pack import build

CASES = (
    ('공가 종류 알려줘', 'leave_types', 'official-leave-both', ('투표', '헌혈', '제1급감염병', '제19조에만')),
    ('공가는 언제 쓸 수 있어?', 'leave_types', 'official-leave-both', ('건강검진',)),
    ('지방공무원 공가 사유', 'leave_types', 'official-leave-local', ('제7조의6',)),
    ('국가공무원 공가 종류\n업무환경: 국가공무원', 'leave_types', 'official-leave-national', ('제19조', '거주지')),
    ('징계 종류 알려줘', 'discipline', 'discipline-both', ('파면, 해임, 강등, 정직, 감봉, 견책', '제70조', '3분의 1')),
    ('징계 종류는 뭐가 있어?\n업무환경: 경기도 소속 지방공무원', 'discipline', 'discipline-local', ('제70조', '제71조')),
    ('국가공무원 징계 종류', 'discipline', 'discipline-national', ('제79조', '제80조')),
    ('감봉은 얼마나 깎여?', 'discipline', 'discipline-both', ('3분의 1',)),
    ('유연근무 종류는?', 'flex', 'flex-both', ('탄력근무제', '재량근무제', '원격근무제', '조례·지침', '제3조')),
    ('국가공무원 유연근무 유형 알려줘', 'flex', 'flex-national', ('시차출퇴근형', '스마트워크', '제10조')),
)


class ServiceKindsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = []
        for base in (office.KINDS_BASE, office.LEAVE_TYPES_BASE):
            rows += json.loads((base / 'manifest.json').read_text(encoding='utf-8'))
        cls.manifest = json.loads((office.KINDS_BASE / 'manifest.json').read_text(encoding='utf-8'))
        cls.sources = [dict(id=r['id'], title=r['title'] + ' ' + r['article'], enabled=True, current=True,
                            sha256=r['sha256'], effective_date=r['effective_date'], kind=r['kind'], institution=r['institution'],
                            limited=False, library_id=r['collection'], file_id=r['id'], units=r['units'], official=r) for r in rows]

    def ask(self, query):
        with patch.object(knowledge, 'sources', return_value=self.sources), \
             patch.object(knowledge, '_experience_hits', return_value=[]), \
             patch.object(knowledge.config, 'active_profile', return_value={'provider': 'offline'}), \
             patch.object(llm, 'get_provider', side_effect=AssertionError('AI must not be used')):
            return main.api_ask(dict(query=query, guidance=True, use_ai=False, today='2026-11-05'))

    def test_pack_is_the_saved_official_text(self):
        self.assertEqual(len(self.manifest), 7)
        for row in self.manifest:
            self.assertEqual(office.metadata(row['sha256']), row)
        guideline = next(r for r in self.manifest if r['id'] == 'office-kinds-guideline-flex')
        sections = json.loads((office.KINDS_BASE.parent / 'service-guidelines-20261029/sections.json').read_text(encoding='utf-8'))
        self.assertEqual(next(s['text'] for s in sections if s['id'] == 'guideline-0034').strip(), guideline['units'][0]['text'])

    def test_rebuild_reproduces_the_saved_pack(self):
        import shutil, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'pack'
            shutil.copytree(office.KINDS_BASE, base, ignore=shutil.ignore_patterns('excerpts', 'manifest.json'))
            self.assertEqual(build(base), self.manifest)

    def test_answers_are_quoted_from_the_rules(self):
        for query, topic, rule, phrases in CASES:
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

    def test_national_flex_types_are_not_given_as_local_rules(self):
        response = self.ask('지방공무원 유연근무 종류는?')
        self.assertEqual(response['knowledge']['tree']['rule_id'], 'office:flex-local')
        self.assertIn('조례·지침', response['answer'])
        for word in ('탄력근무제', '재량근무제', '원격근무제'):
            self.assertNotIn(word, response['answer'])
        self.assertTrue(all(h['official']['title'] == '지방공무원 복무규정' for h in response['knowledge']['evidence']))

    def test_the_named_penalty_is_the_conclusion(self):
        self.assertIn('감봉은 1개월 이상 3개월 이하', self.ask('감봉은 얼마나 깎여?')['knowledge']['tree']['title'])

    def test_a_confirmed_affiliation_with_its_own_decree_keeps_its_route(self):
        from app import absence, leave_types
        for context in ('경기도 소속 소방공무원', '경찰공무원'):
            suffix = '\n업무환경: ' + context
            self.assertIsNone(service_kinds.classify('공가 사유 알려줘' + suffix))
            self.assertIsNone(service_kinds.classify('징계 종류 알려줘' + suffix))
            self.assertIsNone(absence.classify('육아휴직 기간은?' + suffix))
            self.assertIsNone(leave_types.classify('휴가 종류' + suffix))

    def test_specific_cases_and_other_bodies_keep_their_routes(self):
        for query in ('헌혈하면 공가 되나요?', '건강검진 공가 며칠이야?', '공가 신청 어떻게 해?', '징계 시효는?', '징계위원회 종류', '음주운전 징계 기준',
                      '유연근무 신청 어떻게 해?', '재택근무 몇 시간까지?', '경찰공무원 징계 종류', '교원 공가 종류', '연가 며칠?'):
            with self.subTest(query=query):
                self.assertIsNone(service_kinds.classify(query))


if __name__ == '__main__':
    unittest.main()
