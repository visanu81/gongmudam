"""성과상여금 지급 시기 is answered from the two pay guidelines, without AI."""
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import knowledge, llm, main, office_knowledge as office, pay_guidelines, service_kinds
from tools.prepare_advance_pack import build

CASES = (
    ('성과상여금 언제 지급?', 'bonus-timing-both', {'공무원보수 등의 업무지침', '지방공무원보수업무 등 처리지침'},
     ('2월 말까지', '지급시기', '3월 말까지', '전년도 12월 31일', '7일 이상')),
    ('성과상여금 언제 나와?', 'bonus-timing-both', {'공무원보수 등의 업무지침', '지방공무원보수업무 등 처리지침'}, ('일시금',)),
    ('국가공무원 성과상여금 지급 시기', 'bonus-timing-national', {'공무원보수 등의 업무지침'}, ('소속 장관', '3월 말까지')),
    ('지방공무원 성과상여금 언제 받아?', 'bonus-timing-local', {'지방공무원보수업무 등 처리지침'}, ('지방의회 의장', '상반기 6월까지')),
    ('성과급 언제 들어와?\n업무환경: 지방공무원', 'bonus-timing-local', {'지방공무원보수업무 등 처리지침'}, ('2월 말까지',)),
)


class BonusTimingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((office.BONUS_BASE / 'manifest.json').read_text(encoding='utf-8'))
        cls.sources = [dict(id=r['id'], title=r['title'] + ' ' + r['article'], enabled=True, current=True,
                            sha256=r['sha256'], effective_date=r['effective_date'], kind=r['kind'], institution=r['institution'],
                            limited=False, library_id=r['collection'], file_id=r['id'], units=r['units'], official=r) for r in cls.manifest]

    def ask(self, query):
        with patch.object(knowledge, 'sources', return_value=self.sources), \
             patch.object(knowledge, '_experience_hits', return_value=[]), \
             patch.object(knowledge.config, 'active_profile', return_value={'provider': 'offline'}), \
             patch.object(llm, 'get_provider', side_effect=AssertionError('AI must not be used')):
            return main.api_ask(dict(query=query, guidance=True, use_ai=False, today='2026-11-06'))

    def test_pack_is_the_hash_checked_guideline_pages(self):
        self.assertEqual(len(self.manifest), 6)
        pages = {row['title']: {p['page']: p for p in found} for row, found in pay_guidelines.catalog().values()}
        for row in self.manifest:
            with self.subTest(source=row['id']):
                self.assertEqual(office.metadata(row['sha256']), row)
                raw = json.loads((office.BONUS_BASE / 'raw' / row['raw_file']).read_text(encoding='utf-8'))
                self.assertEqual(raw, pages[row['title']][raw['page']])
                self.assertEqual(hashlib.sha256(raw['text'].encode('utf-8')).hexdigest(), raw['sha256'])

    def test_rebuild_reproduces_the_saved_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'pack'
            shutil.copytree(office.BONUS_BASE, base, ignore=shutil.ignore_patterns('excerpts', 'manifest.json'))
            self.assertEqual(build(base), self.manifest)

    def test_answers_are_quoted_from_the_guidelines(self):
        for query, rule, titles, phrases in CASES:
            with self.subTest(query=query):
                response = self.ask(query)
                reply = response['knowledge']
                tree = reply['tree']
                self.assertEqual(tree['rule_id'], 'office:' + rule)
                self.assertIsNone(response['model'])
                self.assertIn('지침에 정해진 지급 달은 없고', tree['title'])
                self.assertEqual({h['official']['title'] for h in reply['evidence']}, titles)
                for phrase in phrases:
                    self.assertIn(phrase, response['answer'])
                for branch in tree['branches']:
                    for item in branch['items']:
                        for quote in item['support_quotes']:
                            self.assertIn(quote, reply['evidence'][item['ref'] - 1]['text'])

    def test_no_guideline_page_fixes_a_payment_month(self):
        # The conclusion says no month is set, so the whole bonus chapter of each guideline is read.
        chapters = {'national': '제8장', 'local': '제6장'}
        for key, (_row, pages) in pay_guidelines.catalog().items():
            found = [p for p in pages if p['chapter'].replace(' ', '').startswith(chapters[key])]
            self.assertGreater(len(found), 50)
            for page in found:
                self.assertNotRegex(''.join(page['text'].split()), r'[0-9]+월(?:말|중)?(?:까지|에)(?:성과상여금을)?지급(?:한다|하여야)')

    def test_other_bonus_questions_and_bodies_keep_their_routes(self):
        for query in ('성과상여금 지급 기준', '성과상여금 등급 언제 나와?', '성과상여금 얼마 받아?', '휴직 중 성과상여금 언제 받아?', '퇴직하면 성과상여금 언제 받아?',
                      '성과연봉 언제 지급?', '소방공무원 성과상여금 언제 지급?', '성과상여금 언제 지급?\n업무환경: 경찰공무원', '회사 성과급 언제 나와?'):
            with self.subTest(query=query):
                self.assertIsNone(service_kinds.classify(query))


if __name__ == '__main__':
    unittest.main()
