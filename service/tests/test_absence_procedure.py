"""휴직 신청·복직·보고 절차 is answered from the reviewed rules, without AI."""
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import absence, knowledge, llm, main, office_knowledge as office
from tools.prepare_advance_pack import build

CASES = (
    ('휴직 신청 절차', 'both', '종류별 신청 방법', '국가공무원은 휴직 종류별 신청서', ('별지 제41호', '별지 제32호', '별지 제6호', '30일 이내', '별지 제25호')),
    ('휴직 어떻게 신청해?', 'both', '종류별 신청 방법', '지방공무원은 소속 기관 인사부서', ('임용권자',)),
    ('국가공무원 휴직 신청 절차', 'national', '종류별 신청 방법', '휴직 종류별 신청서와', ('별지 제42호', '별지 제38호')),
    ('지방공무원 휴직 신청 절차', 'local', '종류별 신청 방법', '운영지침에 서식이 있는 것은 자기개발휴직뿐', ('별지 제6호', '제65조')),
    ('휴직 서류 뭐 내야 해?\n업무환경: 지방공무원', 'local', '종류별 신청 방법', '지방공무원 휴직은', ('별지 제6호',)),
    ('육아휴직 신청 절차', 'both', '육아 휴직', '육아휴직 신청서(공무원 임용규칙 별지 제41호)', ('출산휴가와 이어', '특별한 사정이 없으면')),
    ('국가공무원 육아휴직 어떻게 신청해?', 'national', '육아 휴직', '육아휴직 신청서(공무원 임용규칙 별지 제41호)와', ('제91조',)),
    ('지방공무원 육아휴직 신청서', 'local', '육아 휴직', '지방공무원 육아휴직은 임용권자가 명해요', ('소속 기관 인사부서',)),
    ('질병휴직 신청 서류', 'both', '질병 휴직', '진단서나 사유 증빙자료를', ('제57조의7', '제38조의18', '공무상')),
    ('가족돌봄휴직 절차', 'both', '가족돌봄 휴직', '별지 제42호', ('실제로 돌볼 수 있으면',)),
    ('유학휴직 신청 서류', 'both', '유학 휴직', '별지 제38호', ('입학허가서', '실제 학업')),
    ('자기개발휴직 신청 방법', 'both', '자기개발 휴직', '지방공무원은 별지 제6호', ('분기별', '별지 제32호')),
    ('병역휴직 신청 절차', 'both', '누가 명하나', '병역휴직은 신청과 관계없이', ('본인 의사와 관계없이',)),
    ('복직 어떻게 해?', 'both', '복직', '30일 이내에 복귀 신고', ('별지 제48호', '제65조')),
    ('복직원 서식', 'both', '복직', '국가공무원 복직원 서식은 공무원 임용규칙 별지 제48호', ('운영지침에는 복직원 서식이 없어요', '30일 이내')),
    ('국가공무원 복직원 어디 있어?', 'national', '복직', '복직원 서식은 공무원 임용규칙 별지 제48호', ('제73조',)),
    ('지방공무원 복직원 서식', 'local', '복직', '운영지침에는 복직원 서식이 없어요', ('제65조',)),
    ('육아휴직 복직 절차', 'both', '복직', '30일 이내에 복귀 신고', ('제73조',)),
    ('질병휴직 복직 서류', 'both', '질병 휴직', '질병휴직 복직은 진단서나', ('난임', '제70조')),
    ('휴직 복직 절차', 'both', '종류별 신청 방법', '휴직 종류별 신청서', ('별지 제48호',)),
    ('휴직 중 복무상황 보고', 'both', '휴직 중 보고', '국가공무원은 매 반기', ('별지 제25호', '별지 제2호', '매 분기')),
    ('지방공무원 휴직 복무상황 보고', 'local', '휴직 중 보고', '지방공무원은 매 반기, 질병·유학·육아·자기개발 휴직은 매 분기', ('별지 제2호',)),
)


class AbsenceProcedureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((office.ABSENCE_PROCEDURE_BASE / 'manifest.json').read_text(encoding='utf-8'))
        rows = cls.manifest + json.loads((office.ABSENCE_BASE / 'manifest.json').read_text(encoding='utf-8'))
        cls.sources = [dict(id=r['id'], title=r['title'] + ' ' + r['article'], enabled=True, current=True,
                            sha256=r['sha256'], effective_date=r['effective_date'], kind=r['kind'], institution=r['institution'],
                            limited=False, library_id=r['collection'], file_id=r['id'], units=r['units'], official=r) for r in rows]

    def ask(self, query):
        with patch.object(knowledge, 'sources', return_value=self.sources), \
             patch.object(knowledge, '_experience_hits', return_value=[]), \
             patch.object(knowledge.config, 'active_profile', return_value={'provider': 'offline'}), \
             patch.object(llm, 'get_provider', side_effect=AssertionError('AI must not be used')):
            return main.api_ask(dict(query=query, guidance=True, use_ai=False, today='2026-11-06'))

    def test_pack_is_the_saved_official_text(self):
        self.assertEqual(len(self.manifest), 16)
        for row in self.manifest:
            self.assertEqual(office.metadata(row['sha256']), row)

    def test_rebuild_reproduces_the_saved_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'pack'
            shutil.copytree(office.ABSENCE_PROCEDURE_BASE, base, ignore=shutil.ignore_patterns('excerpts', 'manifest.json'))
            self.assertEqual(build(base), self.manifest)

    def test_answers_are_quoted_from_the_rules(self):
        for query, side, lead, title, phrases in CASES:
            with self.subTest(query=query):
                response = self.ask(query)
                reply = response['knowledge']
                tree = reply['tree']
                self.assertEqual(tree['rule_id'], f'office:absence-procedure-{side}')
                self.assertIsNone(response['model'])
                self.assertEqual(tree['branches'][0]['label'], lead)
                self.assertIn(title, tree['title'])
                shown = tree['title'] + ' '.join(i['text'] for b in tree['branches'] for i in b['items'])
                for phrase in phrases:
                    self.assertIn(phrase, shown)
                for branch in tree['branches']:
                    for item in branch['items']:
                        for quote in item['support_quotes']:
                            self.assertIn(quote, reply['evidence'][item['ref'] - 1]['text'])

    def test_national_forms_are_never_given_to_a_local_officer(self):
        for query in ('지방공무원 휴직 신청 절차', '지방공무원 육아휴직 신청서', '지방공무원 복직원 서식', '지방공무원 가족돌봄휴직 절차'):
            with self.subTest(query=query):
                response = self.ask(query)
                tree = response['knowledge']['tree']
                shown = tree['title'] + ' '.join(i['text'] for b in tree['branches'] for i in b['items'])
                self.assertNotRegex(shown, r'별지 제(?:25|32|38|39|40|41|42|48)호')
                self.assertNotIn('공무원 임용규칙', shown)
                self.assertEqual({h['official']['institution'] for h in response['knowledge']['evidence']}, {'지방공무원'})

    def test_the_local_guideline_really_has_no_other_leave_form(self):
        # The answer tells local officers to ask 인사부서; only 별지 6 is an application form in this guideline.
        raw = (office.ABSENCE_PROCEDURE_BASE / 'raw' / 'guide.html').read_text(encoding='utf-8')
        forms = re.findall(r'\[별지 ?\d+\][^<\n]*', raw)
        self.assertTrue(forms)
        self.assertEqual([f for f in forms if '휴직' in f and '신청' in f], ['[별지 6] 자기개발휴직 신청서 '])
        self.assertFalse([f for f in forms if '복직' in f])

    def test_the_form_list_is_the_rule_pages_own_lines(self):
        raw = (office.ABSENCE_PROCEDURE_BASE / 'raw' / 'rule.html').read_text(encoding='utf-8')
        record = json.loads((office.ABSENCE_PROCEDURE_BASE / 'raw' / 'rule-forms.json').read_text(encoding='utf-8'))
        for line in record['text'].splitlines():
            self.assertIn(line, raw)

    def test_other_questions_keep_their_routes(self):
        for query in ('휴직하면 월급 나와?', '육아휴직 수당 신청', '휴직 연장 신청 어떻게 해?', '휴직 취소 절차', '고용휴직 신청 절차', '민간근무휴직 신청 서류',
                      '경찰공무원 휴직 신청 절차', '휴직 신청 절차\n업무환경: 소방공무원', '교원 육아휴직 신청', '가족돌봄휴가 신청', '파견 복귀 절차', '휴직자 호봉 승급은?'):
            with self.subTest(query=query):
                self.assertIsNone(absence.classify(query))
        # The grounds and periods stay on the law's own answer.
        for query in ('육아휴직 기간', '휴직 종류', '복직은 언제 해?'):
            with self.subTest(query=query):
                self.assertEqual(absence.classify(query)['topics'], ['absence'])


if __name__ == '__main__':
    unittest.main()
