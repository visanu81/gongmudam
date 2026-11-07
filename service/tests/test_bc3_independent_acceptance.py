"""Frozen independent review counterexamples; no generated legal answers."""
import copy,unittest
from datetime import date
from app import knowledge_intent as intent,document_context
TODAY=date(2026,11,3)
CONTRACT={'official':{'title':'지방자치단체를 당사자로 하는 계약에 관한 법률','article':'제17조(검사)'},'institution':'지방자치단체','effective_date':'2026-10-20'}
TRAVEL={'official':{'title':'공무원 여비 규정','article':'제3조(여비의 지급 구분)'},'institution':'국가공무원','effective_date':'2026-10-02'}
LEAVE={'official':{'title':'지방공무원 복무규정','article':'제7조의5(병가)'},'institution':'지방공무원','effective_date':'2026-10-02'}

class IndependentAcceptance(unittest.TestCase):
    def test_question_about_party_is_not_confirmed_party_fact(self):
        q='소방공무원입니다. 계약당사자는 지방자치단체입니다? 검사 원문을 설명해 주세요.'
        self.assertTrue(intent.scope_reason(q,CONTRACT,TODAY))

    def test_question_about_national_identity_is_not_confirmed_identity(self):
        for q in ['국가직 교사입니다? 여비 원문을 설명해 주세요.']:
            with self.subTest(query=q):self.assertTrue(intent.scope_reason(q,TRAVEL,TODAY))

    def test_retracted_contract_premise_is_not_confirmed_party(self):
        q='소방공무원입니다. 계약당사자가 지방자치단체인 물품계약의 검사라는 전제는 사실이 아닙니다. 검사 원문을 설명해 주세요.'
        self.assertTrue(intent.scope_reason(q,CONTRACT,TODAY))

    def test_retracted_national_identity_claim_is_not_confirmed_identity(self):
        q='국가직 교사입니다. 국가직 교사라는 주장은 사실이 아닙니다. 여비 원문을 설명해 주세요.'
        self.assertTrue(intent.scope_reason(q,TRAVEL,TODAY))

    def test_numeric_month_with_particle_still_requires_earlier_version(self):
        for text in ['2026-09에','2026.09의','2026/09부터','2026-09까지','2026-09에는','2026-09경']:
            with self.subTest(text=text):self.assertTrue(intent.scope_reason(text+' 지방직 병가 원문',LEAVE,TODAY))

    def test_normal_questions_dates_ranks_and_input_remain_intact(self):
        cases=[('소방공무원입니다. 계약당사자는 지방자치단체입니다. 물품 납품검사 원문에서 어떤 기준을 확인할 수 있나요?',CONTRACT),('소방공무원입니다. 계약당사자가 지방자치단체인 물품계약의 검사 원문을 설명해 주실 수 있나요?',CONTRACT),('국가직 교사입니다. 여비 원문을 설명해 주실 수 있나요?',TRAVEL),('2026-11에 지방직 병가 원문',LEAVE),('2026년 9급 지방직 병가 원문',LEAVE),('2026년 9명이 신청한 지방직 병가 원문',LEAVE),('2026-10-03에 지방직 병가 원문',LEAVE),('지방직 병가 예규 제2026-09호 원문',LEAVE)]
        cases += [('국가직 교사입니다. 여비를 무조건 지급한다는 주장은 사실이 아닙니다. 여비 원문을 설명해 주세요.',TRAVEL),('국가직 교사입니다. 국가공무원에게 여비를 무조건 지급한다는 주장은 사실이 아닙니다. 여비 원문을 설명해 주세요.',TRAVEL),('소방공무원입니다. 계약당사자는 지방자치단체입니다. 검사를 생략한다는 주장은 사실이 아닙니다. 검사 원문을 설명해 주세요.',CONTRACT)]
        for q,s in cases:
            with self.subTest(query=q):
                before=copy.deepcopy(s);self.assertEqual(intent.scope_reason(q,s,TODAY),'');self.assertEqual(s,before)
        self.assertEqual(document_context.event_dates('2026-09에 지방직 병가 원문'),set())

if __name__=='__main__':unittest.main(verbosity=2)
