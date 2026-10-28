"""Real reviewed legal excerpts, not synthetic assertions of entitlement."""
import json
from unittest.mock import patch
from test_core import Base,ROOT
from app import knowledge,main,llm


class FamilyCareSourcesTest(Base):
    def setUp(self):
        knowledge.initialize()
        root=ROOT/'reference_data/official-20261020'
        rows=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        self.sources=[]
        for row in rows:
            if row.get('collection')!='v70' and row['article'] not in ('제20조(특별휴가)','제7조의7(특별휴가)'):continue
            text=(root/'excerpts'/row['filename']).read_text(encoding='utf-8')
            self.sources.append(dict(id=row['sha256'][:20],title=row['title']+' '+row['article'],enabled=True,current=True,
                sha256=row['sha256'],effective_date=row['effective_date'],kind=row['kind'],institution=row['institution'],
                limited=False,library_id='public',file_id=row['sha256'][:20],units=[dict(text=text,loc='보관 본문')],official=row))

    def ask(self,q,**kwargs):
        with patch.object(knowledge,'sources',return_value=self.sources),patch.object(llm,'get_provider',side_effect=AssertionError('AI off')):
            return main.api_ask(dict(query=q,guidance=True,today='2026-10-24',**kwargs))

    def test_child_illness_recommends_candidate_before_asking_conditions(self):
        for prefix,title in (('','지방공무원 복무규정'),('지방공무원인데 ','지방공무원 복무규정'),('국가공무원인데 ','국가공무원 복무규정')):
            with self.subTest(scope=prefix):
                result=self.ask(prefix+'아이가 아파서 휴가를 써야 하는데 어떤 걸로 선택해야 해?')
                reply=result['knowledge'];tree=reply['tree']
                self.assertEqual(tree.get('rule_id'),'family-care-situation')
                self.assertIn('가족돌봄휴가',tree['title'])
                self.assertTrue(all(h['official']['title']==title for h in reply['evidence']))
                self.assertFalse(result['guidance']['ai_used'])
                self.assertNotIn('휴가 종류',' '.join(result['guidance']['questions']))
                for b in tree['branches']:
                    for item in b['items']:
                        hit=reply['evidence'][item['ref']-1]
                        self.assertTrue(all(quote in hit['quote'] for quote in item['support_quotes']))

    def test_national_heading_only_is_not_family_care_authority(self):
        self.sources=[s for s in self.sources if s['sha256']=='771949c7db9bd292de07a63cbc8e62df6674027e63cc57419cc3a90fe13261a5']
        result=self.ask('국가공무원 자녀돌봄휴가를 쓰려면?')
        self.assertFalse(result['knowledge']['evidence'])
        self.assertNotEqual(result['knowledge']['tree'].get('rule_id'),'family-care-situation')

    def test_specific_followup_keeps_purpose_and_national_scope(self):
        result=self.ask('7살이고 병원에 같이 가야 해',situation_context='국가공무원인데 아이가 아파서 휴가를 알아보고 있어')
        self.assertEqual(result['knowledge']['tree'].get('rule_id'),'family-care-situation')
        self.assertTrue(all(e['official']['title']=='국가공무원 복무규정' for e in result['knowledge']['evidence']))
        plain=self.ask('국가공무원인데 아이가 아파서 하루 쉬어야 해')
        self.assertEqual(plain['knowledge']['tree'].get('rule_id'),'family-care-situation')
        self.assertTrue(all('질병, 사고, 노령' in e['quote'] and '가족돌봄휴가는 무급으로 하되' in e['quote'] for e in plain['knowledge']['evidence']))

    def test_four_requested_situations_keep_exact_legal_support_with_ai_off(self):
        cases=[('국가공무원인데 아이가 아파서 휴가를 써야 해','family-care-situation',('제20조',)),
            ('국가공무원인데 제가 독감으로 출근이 어려워요. 병가를 쓰려면?','service-v70-sick',('제18조',)),
            ('국가공무원 국민건강보험공단 건강검진을 받으려는데 어떤 휴가를 쓰나요?','service-v70-public_health',('제19조',)),
            ('국가공무원 유튜브 수익이 생기면 겸직 허가를 먼저 받아야 하나요?','service-v70-side_job',('제25조','제26조'))]
        for q,rule,articles in cases:
            with self.subTest(query=q):
                result=self.ask(q);reply=result['knowledge']
                self.assertEqual(reply['tree'].get('rule_id'),rule)
                if rule in ('service-v70-sick','service-v70-public_health'):
                    self.assertNotIn('휴가를 쓰려는 사유',' '.join(result['guidance']['questions']))
                for a in articles:self.assertTrue(any(e['official']['article'].startswith(a+'(') for e in reply['evidence']))
                for b in reply['tree']['branches']:
                    for item in b['items']:
                        self.assertTrue(all(quote in reply['evidence'][item['ref']-1]['quote'] for quote in item['support_quotes']))
                self.assertFalse(result['guidance']['ai_used'])
