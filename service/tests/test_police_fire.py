"""경찰·소방공무원의 휴직·징계·휴가 종류 is answered from the laws, without AI."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import knowledge, llm, main, office_knowledge as office, police_fire
from tools.prepare_advance_pack import build

CASES = (
    ('경찰공무원 휴직 종류', 'absence-police', '경찰공무원 휴직 종류는 국가공무원법 제71조', ('노조 전임', '특례'), {'국가공무원법', '경찰공무원법'}),
    ('소방관 휴직 종류', 'absence-fire', '소방공무원 휴직 종류는 국가공무원법 제71조', ('자기개발', '특례'), {'국가공무원법', '소방공무원법'}),
    ('휴직 뭐가 있어?\n업무환경: 소방공무원', 'absence-fire', '소방공무원 휴직 종류는', ('병역',), {'국가공무원법', '소방공무원법'}),
    ('경찰공무원 질병휴직 기간', 'absence-police', '5년 이내(3년 연장 가능)', ('제5조 제1호', '제29조'), {'국가공무원법', '경찰공무원법'}),
    ('소방공무원 공상 휴직 얼마나 돼?', 'absence-fire', '5년 이내(3년 연장 가능)', ('제5조 제2호', '제24조의2'), {'국가공무원법', '소방공무원법'}),
    ('경찰공무원 생사불명 휴직 기간', 'absence-police', '법원의 실종선고를 받는 날까지', ('제29조',), {'국가공무원법', '경찰공무원법'}),
    ('소방공무원 생사불명 휴직 기간', 'absence-fire', '3개월 이내', ('제72조',), {'국가공무원법', '소방공무원법'}),
    ('소방공무원 육아휴직 기간', 'absence-fire', '자녀 1명에 3년 이내', ('12세 이하',), {'국가공무원법', '소방공무원법'}),
    ('경찰공무원 연수 휴직 기간', 'absence-police', '2년 이내', ('경찰청장 또는 해양경찰청장이 지정',), {'국가공무원법', '경찰공무원법'}),
    ('해양경찰 휴직 기간', 'absence-police', '휴직 기간은 종류마다', ('실종선고',), {'국가공무원법', '경찰공무원법'}),
    ('경찰 징계 종류', 'discipline-police', '경찰공무원 징계도 국가공무원법에 따라', ('제79조', '견책'), {'국가공무원법', '경찰공무원법'}),
    ('소방공무원 징계 뭐가 있어?', 'discipline-fire', '소방공무원 징계도 국가공무원법에 따라', ('제80조',), {'국가공무원법', '소방공무원법'}),
    ('경찰공무원 감봉은 얼마나 깎여?', 'discipline-police', '감봉은 1개월 이상 3개월 이하', ('3분의 1',), {'국가공무원법', '경찰공무원법'}),
    ('경찰공무원 휴가 종류', 'leave-types-police', '경찰공무원 휴가도 국가공무원 복무규정에 따라', ('제18조', '제20조', '장기재직'), {'국가공무원 복무규정', '경찰공무원 복무규정'}),
    ('소방공무원 휴가 종류', 'leave-types-fire', '소방공무원 휴가도 국가공무원 복무규정을 준용해', ('제8조의2', '제9조', '조례'), {'국가공무원 복무규정', '소방공무원 복무규정'}),
    ('휴가 종류는?\n업무환경: 경찰공무원', 'leave-types-police', '포상휴가는 1회 10일 이내', ('제18조',), {'국가공무원 복무규정', '경찰공무원 복무규정'}),
    ('소방관인데 휴가 뭐가 있어?', 'leave-types-fire', '시·도 소속의 특별휴가', ('장기재직휴가는 조례',), {'국가공무원 복무규정', '소방공무원 복무규정'}),
)
PROCEDURE_CASES = (
    ('경찰공무원 휴직 신청 절차', 'absence-procedure-police', '경찰공무원 휴직은 임용권자가 명해요', ('제4조', '별지 제6호', '인사부서', '제73조', '제36조'), {'국가공무원법', '경찰공무원법', '경찰공무원 임용령', '경찰공무원 임용령 시행규칙', '공무원 임용규칙'}),
    ('소방공무원 휴직 신청 절차', 'absence-procedure-fire', '소방공무원 휴직은 임용권자가 명해요', ('제3조', '소방서장', '인사부서', '제73조', '제33조'), {'국가공무원법', '소방공무원법', '소방공무원 임용령', '소방공무원 임용령 시행규칙', '공무원 임용규칙'}),
    ('휴직은 어떻게 신청해?\n업무환경: 소방공무원', 'absence-procedure-fire', '소방공무원 휴직은', ('소방서장',), None),
    ('경찰공무원 육아휴직 신청 서류', 'absence-procedure-police', '경찰공무원 육아휴직은 임용권자가 명해요', ('특별한 사정이 없으면', '나눠서', '제30조의2'), None),
    ('소방관 육아휴직 신청서', 'absence-procedure-fire', '소방공무원 육아휴직은 임용권자가 명해요', ('나눠서', '별지 제41호', '인사부서에 확인'), None),
    ('경찰 질병휴직 진단서 제출해야 해?', 'absence-procedure-police', '경찰공무원 질병휴직은 임용권자가 명해요', ('제47조의2',), None),
    ('소방공무원 가족돌봄휴직 신청 방법', 'absence-procedure-fire', '소방공무원 가족돌봄휴직은', ('시행규칙의 별지 서식',), None),
    ('경찰공무원 유학휴직 서류', 'absence-procedure-police', '경찰공무원 유학휴직은', ('시행규칙의 별지 서식',), None),
    ('경찰공무원 병역휴직 신청 절차', 'absence-procedure-police', '병역휴직은 신청과 관계없이 임용권자가 명해요', ('제71조 제1항',), None),
    ('경찰공무원 복직 절차', 'absence-procedure-police', '휴직 사유가 없어지면 30일 이내에 신고', ('제73조',), None),
    ('소방공무원 복직원 서식', 'absence-procedure-fire', '소방공무원 임용령과 시행규칙에는 복직원 서식이 없어요', ('제73조',), None),
    ('소방공무원 질병휴직 복직 서류', 'absence-procedure-fire', '휴직 사유가 없어지면 30일 이내에 신고', ('제73조',), None),
    ('경찰공무원 공상 휴직 연장 절차', 'absence-procedure-police', '총 휴직 기간이 5년을 넘으면 임용심사위원회', ('제47조의2', '제57조의7'), None),
    ('소방공무원 공상휴직 연장 어떻게 해?', 'absence-procedure-fire', '총 휴직 기간이 5년을 넘으면 임용심사위원회', ('제61조', '제57조의7'), None),
)


class PoliceFireTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((office.POLICE_FIRE_BASE / 'manifest.json').read_text(encoding='utf-8'))
        rows = list(cls.manifest)
        rows += json.loads((office.POLICE_FIRE_PROCEDURE_BASE / 'manifest.json').read_text(encoding='utf-8'))
        for base in (office.ABSENCE_BASE, office.KINDS_BASE, office.LEAVE_TYPES_BASE, office.ABSENCE_PROCEDURE_BASE):
            rows += json.loads((base / 'manifest.json').read_text(encoding='utf-8'))
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
        self.assertEqual(len(self.manifest), 12)
        for row in self.manifest:
            self.assertEqual(office.metadata(row['sha256']), row)

    def test_rebuild_reproduces_the_saved_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'pack'
            shutil.copytree(office.POLICE_FIRE_BASE, base, ignore=shutil.ignore_patterns('excerpts', 'manifest.json'))
            self.assertEqual(build(base), self.manifest)

    def test_answers_are_quoted_from_the_laws(self):
        for query, rule, title, phrases, laws in CASES:
            with self.subTest(query=query):
                response = self.ask(query)
                reply = response['knowledge']
                tree = reply['tree']
                self.assertEqual(tree['rule_id'], 'office:' + rule)
                self.assertIsNone(response['model'])
                self.assertIn(title, tree['title'])
                shown = tree['title'] + ' '.join(i['text'] for b in tree['branches'] for i in b['items'])
                for phrase in phrases:
                    self.assertIn(phrase, shown)
                self.assertEqual({h['official']['title'] for h in reply['evidence']}, laws)
                for branch in tree['branches']:
                    for item in branch['items']:
                        for quote in item['support_quotes']:
                            self.assertIn(quote, reply['evidence'][item['ref'] - 1]['text'])

    def test_procedure_pack_rebuilds_from_the_saved_originals(self):
        manifest = json.loads((office.POLICE_FIRE_PROCEDURE_BASE / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest), 10)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'pack'
            shutil.copytree(office.POLICE_FIRE_PROCEDURE_BASE, base, ignore=shutil.ignore_patterns('excerpts', 'manifest.json'))
            self.assertEqual(build(base), manifest)

    def test_procedure_answers_lead_with_who_decides_and_where_to_ask(self):
        for query, rule, title, phrases, laws in PROCEDURE_CASES:
            with self.subTest(query=query):
                response = self.ask(query)
                reply = response['knowledge']
                tree = reply['tree']
                self.assertEqual(tree['rule_id'], 'office:' + rule)
                self.assertIsNone(response['model'])
                self.assertIn(title, tree['title'])
                shown = tree['title'] + ' '.join(i['text'] for b in tree['branches'] for i in b['items'])
                for phrase in phrases:
                    self.assertIn(phrase, shown)
                if laws:
                    self.assertTrue(laws <= {h['official']['title'] for h in reply['evidence']})
                for branch in tree['branches']:
                    for item in branch['items']:
                        for quote in item['support_quotes']:
                            self.assertIn(quote, reply['evidence'][item['ref'] - 1]['text'])

    def test_national_forms_are_not_given_as_this_bodys_forms(self):
        for query in ('경찰공무원 휴직 신청 절차', '소방공무원 육아휴직 신청서', '경찰공무원 복직원 서식'):
            with self.subTest(query=query):
                tree = self.ask(query)['knowledge']['tree']
                self.assertNotIn('별지 제', tree['title'])
                shown = ' '.join(i['text'] for b in tree['branches'] for i in b['items'])
                for national in ('별지 제48호', '별지 제42호', '분기별로', '매 반기'):
                    self.assertNotIn(national, shown)

    def test_procedure_answers_keep_each_body_apart(self):
        police = self.ask('경찰공무원 휴직 신청 절차')['knowledge']['tree']
        fire = self.ask('소방공무원 휴직 신청 절차')['knowledge']['tree']
        self.assertNotIn('소방', police['title'] + ' '.join(i['text'] for b in police['branches'] for i in b['items']))
        self.assertNotIn('경찰', fire['title'] + ' '.join(i['text'] for b in fire['branches'] for i in b['items']))
        self.assertIn('인사발령 통지', [b['label'] for b in police['branches']])
        self.assertNotIn('인사발령 통지', [b['label'] for b in fire['branches']])

    def test_each_body_gets_only_its_own_exceptions(self):
        fire = self.ask('소방공무원 생사불명 휴직 기간')
        self.assertNotIn('실종선고', fire['answer'])
        police = self.ask('경찰공무원 생사불명 휴직 기간')
        self.assertNotIn('3개월 이내', police['answer'])
        for query, absent in (('경찰공무원 휴가 종류', ('소방', '조례')), ('소방공무원 휴가 종류', ('경찰',)), ('경찰공무원 휴직 종류', ('소방',)), ('소방공무원 징계 종류', ('경찰',))):
            with self.subTest(query=query):
                tree = self.ask(query)['knowledge']['tree']
                shown = tree['title'] + ' '.join(i['text'] for b in tree['branches'] for i in b['items'])
                for word in absent:
                    self.assertNotIn(word, shown)

    def test_fire_public_leave_is_read_from_its_own_decree(self):
        response = self.ask('소방공무원 휴가 종류')
        self.assertEqual({h['official']['article'] for h in response['knowledge']['evidence'] if h['official']['title'] == '국가공무원 복무규정'} & {'제19조(공가)'}, set())
        self.assertIn('제8조의2(공가)', {h['official']['article'] for h in response['knowledge']['evidence']})

    def test_other_questions_keep_their_routes(self):
        for query in ('소방공무원 공가 사유가 뭐예요?', '경찰공무원 공가는 어떤 경우에 받을 수 있나요?', '경찰공무원 연가는 며칠인가요?', '소방공무원 포상휴가는 며칠까지 가능한가요?',
                      '경찰 포상휴가는 연가에 포함돼?', '경찰공무원 휴직 복무상황 보고', '소방공무원 고용휴직 신청 절차', '해양경찰 휴직 신청 절차', '휴직 신청 절차\n업무환경: 해양경찰', '경찰공무원 징계 기준', '소방공무원 징계 절차', '경찰공무원 음주운전 징계',
                      '경찰공무원 의무 알려줘', '소방공무원 승진 소요 최저연수', '의무경찰 휴가 종류', '의무소방 휴직 종류', '경찰청 일반직 휴가 종류', '소방서 공무직 휴직 종류',
                      '경찰과 소방 휴가 종류', '교원 휴직 종류', '휴직 종류', '휴가 종류는?', '지방공무원 휴가 종류\n업무환경: 소방공무원'):
            with self.subTest(query=query):
                self.assertIsNone(police_fire.classify(query))

    def test_coast_guard_stays_on_the_law_and_off_the_police_decree(self):
        # 경찰공무원법 covers 해양경찰, but 경찰공무원 임용령 제2조의2 leaves it out.
        self.assertEqual(police_fire.classify('해양경찰 공상 휴직 연장 절차')['rules'], ['absence-police'])

    def test_a_body_is_not_guessed_for_a_general_question(self):
        self.assertNotIn('police', office.classify('휴가 종류는?')['rules'][0])
        self.assertEqual(office.classify('휴직 종류\n업무환경: 국가공무원')['rules'], ['absence-national'])


if __name__ == '__main__':
    unittest.main()
