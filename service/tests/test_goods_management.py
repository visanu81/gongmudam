"""Scope, complete citations and fail-closed behavior of the offline goods pack."""
import copy
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import goods_management, knowledge, llm, main, office_knowledge as office
from tools import prepare_goods_pack, register_goods_management_pack
from tools.audit_practice_questions import evaluate_case

DAY = date(2026, 10, 26)
CASES = (
 ('국가기관 재물조사는 언제 하고 보고는 언제까지 하나요?', 'national-inventory', ('연 1회', '12월 31일', '2월 말일')),
 ('시청 재물조사는 2년마다 하나요?', 'local-inventory', ('1년마다', '행정안전부')),
 ('지자체 물품 실사 결과는 어디로 보내나요?', 'local-inventory', ('거쳐 제출',)),
 ('국가기관 물품대장을 엑셀로 관리해도 되나요?', 'national-ledger', ('매월 말일', '조달청장과 협의')),
 ('중앙부처 비품이 오래됐어요. 그냥 버려도 되나요?', 'national-disposal', ('불용결정', '500만원 이상', '제17호의3')),
 ('지자체 불용품을 폐기하려면 어떤 절차가 필요한가요?', 'local-disposal', ('지자체장이', '500만원 미만', '다른 목적')),
 ('구청 불용품 매각을 수의계약으로 해도 되나요?', 'local-sale', ('10만원 이하', '500만원 이하', '2회 이상')),
)


class GoodsManagementTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest=json.loads((office.GOODS_BASE/'manifest.json').read_text(encoding='utf-8'))
        cls.sources=[dict(id=r['id'],title=r['title']+' '+r['article'],enabled=True,current=True,
            sha256=r['sha256'],effective_date=r['effective_date'],kind=r['kind'],institution=r['institution'],
            limited=False,library_id=r['collection'],file_id=r['id'],units=r['units'],official=r) for r in cls.manifest]

    def ask(self,query,sources=None,**body):
        with patch.object(knowledge,'sources',return_value=self.sources if sources is None else sources), \
             patch.object(knowledge,'_experience_hits',return_value=[]), \
             patch.object(knowledge.config,'active_profile',return_value={'provider':'offline'}), \
             patch.object(llm,'get_provider',side_effect=AssertionError('AI must not be used')):
            return main.api_ask(dict(query=query,guidance=True,use_ai=False,today='2026-10-26',**body))

    def test_natural_questions_use_scope_specific_exact_originals_without_ai(self):
        for query,rid,phrases in CASES:
            with self.subTest(query=query):
                response=self.ask(query); reply=response['knowledge']; tree=reply['tree']
                self.assertEqual(tree['kind'],'summary',response)
                self.assertEqual(tree['rule_id'],'office:goods-'+rid)
                self.assertFalse(response['guidance']['ai_used'])
                self.assertIsNone(response['model'])
                for phrase in phrases:self.assertIn(phrase,response['answer'])
                scope=rid.split('-')[0]
                for h in reply['evidence']:
                    self.assertTrue(h['official']['id'].startswith('office-goods-'+scope))
                for b in tree['branches']:
                    for item in b['items']:
                        source=reply['evidence'][item['ref']-1]
                        for quote in item['support_quotes']:self.assertIn(quote,source['text'])

    def test_ambiguous_scope_does_not_apply_national_rules(self):
        for q in ('재물조사는 언제 해요?', '공공기관 재물조사 주기는?', '지방공무원 물품대장 작성법',
                  '국가직 소방공무원 불용품 폐기 방법', '공기업 비품을 버려도 되나요?',
                  '국가기관과 지자체 재물조사를 비교해 주세요'):
            with self.subTest(q=q):
                reply=self.ask(q)['knowledge']
                self.assertFalse(reply['evidence'])
                self.assertIn('국가기관인지',reply['notice'])

    def test_personnel_profile_is_not_goods_owner(self):
        plan=goods_management.classify('재물조사 언제 하나요?\n업무환경: 국가공무원')
        self.assertTrue(plan.get('reason'))

    def test_audit_accepts_explicit_scope_request_but_not_an_invented_answer(self):
        case=dict(expected='institution',require_source_groups=[],answer_terms_groups=[])
        for notice in ('공기업·공공기관은 자체 물품관리 규정도 필요해요.',
                       '해당 기관의 실제 대장 서식은 추가 등록이 필요해요.'):
            reply=dict(answer='',notice=notice,knowledge=dict(evidence=[]),guidance={})
            self.assertEqual(evaluate_case(case,reply,[])['failures'],[])
        fake=dict(answer='모든 공공기관은 3년마다 재물조사를 하면 됩니다.',knowledge=dict(evidence=[]),guidance={})
        self.assertTrue(evaluate_case(case,fake,[])['failures'])

    def test_unsupported_details_require_materials_not_fabrication(self):
        for q in ('시청 물품대장에는 어떤 항목을 적나요?', '국가기관 비품대장 필수항목은?',
                  '국가기관 물품대장 엑셀파일 주세요', '지자체 박물관 물품 재물조사 면제?',
                  '국가기관 불용품 매각 수의계약 금액은?', '지자체 토지 불용 폐기 절차',
                  '국가기관 군수품 재물조사', '시청 불용 컴퓨터 하드디스크 보안삭제 방법'):
            with self.subTest(q=q):self.assertFalse(self.ask(q)['knowledge']['evidence'])

    def test_neighbor_questions_keep_their_existing_routes(self):
        for q in ('사무용품을 무슨 예산 목으로 사나요?', '국가기관 물품 납품 검사 기간은?',
                  '아이 병원에 가려면 무슨 휴가?', '출장정산 해줘'):
            self.assertIsNone(goods_management.classify(q))
        self.assertIn('records',office.classify('기록물 폐기 절차는?')['topics'])
        self.assertIn('privacy',office.classify('개인정보가 있는 명단 파기 절차는?')['topics'])

    def test_missing_pack_never_falls_back_to_unrelated_goods_inspection(self):
        result=office.documents('국가기관 재물조사',[],DAY)
        self.assertEqual(result[0],[])
        self.assertTrue(result[1])

    def test_required_source_missing_disabled_stale_or_changed_blocks_summary(self):
        sid='office-goods-local-act-60'; q='지자체 재물조사 주기는?'
        self.assertFalse(self.ask(q,[r for r in self.sources if r['id']!=sid])['knowledge']['evidence'])
        for field,value in (('enabled',False),('current',False),('sha256','0'*64)):
            data=copy.deepcopy(self.sources)
            next(r for r in data if r['id']==sid)[field]=value
            self.assertFalse(self.ask(q,data)['knowledge']['evidence'])

    def test_date_scope_does_not_present_current_pack_as_historical_or_future(self):
        for q in ('2020년 지자체 재물조사 주기는?', '2027년 국가기관 재물조사 주기는?',
                  '2026-09-01 지자체 불용품 처리 절차는?'):
            self.assertFalse(self.ask(q)['knowledge']['evidence'])

    def test_offline_rebuild_and_tampered_original_fail(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)/'pack';shutil.copytree(office.GOODS_BASE,base)
            self.assertEqual(prepare_goods_pack.build(base),self.manifest)
            row=next(r for r in self.manifest if r['id']=='office-goods-national-act-19')
            (base/'raw'/row['raw_file']).write_bytes(b'changed')
            with self.assertRaises(ValueError):prepare_goods_pack.build(base)
            with patch.object(office,'GOODS_BASE',base):
                self.assertFalse(self.ask('국가기관 재물조사 주기는?')['knowledge']['evidence'])

    def test_original_routes_match_saved_text_and_are_plain_text(self):
        client=TestClient(main.app)
        for row in self.manifest:
            r=client.get('/api/office-sources/'+row['sha256']+'/original')
            self.assertEqual(r.status_code,200)
            self.assertTrue(r.headers['content-type'].startswith('text/plain'))
            self.assertIn(row['units'][0]['text'],r.text)

    def test_registration_is_additive_and_repeat_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'folders.db'
            with closing(sqlite3.connect(db)) as c:
                c.execute('CREATE TABLE libraries(id TEXT PRIMARY KEY,version INTEGER,payload TEXT)')
                c.execute('CREATE TABLE knowledge_sources(id TEXT PRIMARY KEY,library_id TEXT,file_id TEXT,enabled INTEGER,payload TEXT)')
                c.execute('CREATE TABLE user_work(id TEXT PRIMARY KEY, value TEXT)')
                c.execute('INSERT INTO user_work VALUES(?,?)',('keep','same'))
                c.commit()
            dry=register_goods_management_pack.register(db)
            self.assertEqual(len(dry['would_add']),len(self.manifest))
            applied=register_goods_management_pack.register(db,apply=True)
            self.assertEqual(len(applied['added']),len(self.manifest))
            self.assertTrue(Path(applied['backup']).exists())
            self.assertEqual(register_goods_management_pack.register(db,apply=True)['added'],[])
            with closing(sqlite3.connect(db)) as c:
                self.assertEqual(c.execute('SELECT * FROM user_work').fetchall(),[('keep','same')])


if __name__=='__main__':unittest.main()
