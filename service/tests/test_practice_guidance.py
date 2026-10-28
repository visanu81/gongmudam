"""Regression checks for repeated failures in the 100-question audit."""
from unittest.mock import patch
from test_core import Base
from app import guidance, knowledge, knowledge_intent, knowledge_supplement, finance_knowledge, llm


class PracticeGuidanceTest(Base):
    def respond(self,query,hits=None,**extra):
        found=dict(hits=hits or [],experiences=[],excluded=[],intent=None,
                   unavailable_reason='직접 답하는 등록 근거가 없습니다.',**extra)
        with patch.object(knowledge,'retrieve',return_value=found), \
                patch.object(guidance.knowledge.institution_rules,'hint',return_value=bool(hits)), \
                patch.object(guidance.manual_knowledge,'respond',return_value=None), \
                patch.object(guidance.service_knowledge,'retrieve',return_value=dict(evidence=[])), \
                patch.object(llm,'get_provider',side_effect=AssertionError('AI is disabled')):
            return guidance.respond(query,dict(use_ai=False),__import__('datetime').date(2026,10,26))

    def test_manual_request_keeps_cancel_action(self):
        query='e-사람에서 출장 신청을 취소하는 방법을 알려주세요.'
        with patch.object(guidance.manual_knowledge,'respond',return_value=None) as manual, \
                patch.object(knowledge,'retrieve',side_effect=AssertionError('manual-only')):
            guidance.respond(query,{},__import__('datetime').date(2026,10,26))
        manual.assert_called_once_with(query,None)

    def test_travel_cancellation_cannot_use_unrelated_pages(self):
        from app import manual_knowledge as manual
        query='e-사람 출장 신청 취소 방법'
        doc=dict(id='manual',title='스마트출장앱 교육.pdf',reference_kind=manual.KIND,
                 enabled=True,current=True,units=[dict(page=i+1,text=text) for i,text in enumerate([
                     '공무원증 발급 신청은 취소를 클릭한다.',
                     '복무 > 출장관리 > 예산과목 관리. 부서 매핑을 취소한다.',
                     '출장 지급명세서를 전송한 후 지급 취소 가능 여부를 확인한다.',
                     '목차 출장신청서 작성 예약내역 취소',
                 ])])
        self.assertEqual(manual.retrieve(query,[doc],manual.classify(query)),[])

    def test_missing_business_data_names_required_materials(self):
        for query,term in (
            ('우리 부서 예산 잔액과 집행률은?','집행 내역'),
            ('교육 신청을 아직 안 보낸 부서는?','회신 내역'),
            ('복사용지 재고를 알려줘','물품대장'),
            ('출장복명서 제출기한은?','여비 정산 기한'),
        ):
            with self.subTest(query=query):
                result=self.respond(query)
                self.assertFalse(result['knowledge']['evidence'])
                self.assertIn(term,result['notice'])
                self.assertTrue(result['guidance']['questions'])
                self.assertEqual(result['knowledge']['tree']['kind'],'unavailable')

    def test_material_hint_does_not_replace_found_institution_evidence(self):
        hit=dict(id='i:0',source_id='i',title='기관 예산 요구 안내',sha256='a'*64,
                 text='예산 요구서는 11월 1일까지 제출한다.',loc='1행',official=None)
        result=self.respond('우리 기관 예산 요구서 제출 마감은?',[hit])
        self.assertEqual(result['knowledge']['evidence'][0]['source_id'],'i')
        self.assertNotIn('기관 예산 편성 안내가 필요',result['knowledge']['tree']['title'])

    def test_mixed_meal_question_offers_a_concrete_next_question(self):
        query='출장 식비와 초과근무 식비를 각각 알려줘'
        found=dict(hits=[],experiences=[],excluded=[],intent=None,finance=True,
                   unavailable_reason='질문을 나누어 각각 확인해 주세요.')
        with patch.object(knowledge,'retrieve',return_value=found):
            result=guidance.respond(query,dict(use_ai=False),__import__('datetime').date(2026,10,26))
        self.assertIn('어느 것부터',result['guidance']['questions'][0])

    def test_budget_vimok_aliases_do_not_select_inspection(self):
        for query in ('국가기관 컴퓨터 예산 비목은?', '국가기관 모니터는 어떤 비목으로 사나요?'):
            self.assertIn('assets',finance_knowledge.topics(query))
            self.assertIsNone(knowledge_intent.analyze(query))

    def test_contract_conditions_require_delegated_rules(self):
        query='지자체 물품 검사조서는 얼마까지 생략해도 되나요?'
        self.assertIn('goods_inspection_limit',knowledge_intent.analyze(query)['topics'])
        self.assertIn((knowledge_supplement.DECREE,'제65조('),knowledge_supplement.requirements('goods_inspection_limit',query))
        self.assertIn((knowledge_supplement.DECREE,'제68조('),knowledge_supplement.requirements('goods_payment_interest','지방자치단체 물품 대금 지연이자는 얼마인가요?'))
        self.assertIn('goods_payment',knowledge_intent.analyze('지자체 계약 대가는 검사를 마치기 전에 지급해도 되나요?')['topics'])
