"""F-CONTRACT-SCOPE-01: explicit institutional contract scope vs employee role."""
import unittest
from datetime import date
from app import knowledge_intent as intent, personnel_scope

TODAY=date(2026,11,3)
LAW='지방자치단체를 당사자로 하는 계약에 관한 법률'
SOURCE={'official':{'title':LAW,'article':'제17조(검사)'},'institution':'지방자치단체 물품·계약업무','effective_date':'2026-10-20'}

class ContractPartyScope(unittest.TestCase):
    def test_explicit_local_contract_is_not_rejected_for_employee_role(self):
        for role in ['소방공무원','교육공무원','공무직']:
            for statement in ['계약당사자가 지방자치단체인 물품 구매계약','계약당사자는 지방자치단체입니다. 물품 구매계약','계약당사자가 지방자치단체인 용역계약']:
                q=f'{role}입니다. {statement}의 검사 원문을 설명해 주세요.'
                with self.subTest(query=q):self.assertEqual(intent.scope_reason(q,SOURCE,TODAY),'')

    def test_neutral_existing_control_still_selects_same_source(self):
        q='계약당사자가 지방자치단체인 물품 구매계약의 검사 원문을 설명해 주세요.'
        self.assertEqual(intent.scope_reason(q,SOURCE,TODAY),'')

    def test_missing_negative_or_uncertain_party_does_not_open_role_guard(self):
        for text in ['물품 구매계약 검사 절차를 알려주세요.','계약당사자가 지방자치단체가 아닙니다. 검사 기준은?','계약당사자가 지방자치단체인 것은 아닙니다. 검사 기준은?','계약당사자는 지방자치단체인지 미확인입니다. 검사 기준은?','계약당사자가 지방자치단체인 물품계약이 아닙니다. 검사 기준은?','계약당사자가 지방자치단체인 물품계약일 수도 있습니다. 검사 원문을 설명해 주세요.','계약당사자가 지방자치단체인 물품계약이라는 주장은 거짓입니다. 검사 원문을 설명해 주세요.']:
            q='소방공무원입니다. '+text
            with self.subTest(query=q):self.assertTrue(intent.scope_reason(q,SOURCE,TODAY))

    def test_later_retraction_keeps_party_unconfirmed(self):
        for text in ['계약당사자는 지방자치단체입니다. 정정합니다. 계약당사자는 미확인입니다.','계약당사자는 지방자치단체입니다. 다만 아직 확인하지 않았습니다.','실제 당사자는 모릅니다. 만약 계약당사자가 지방자치단체인 물품계약의 검사라면 기준은 무엇인가요?','만약 계약당사자가 지방자치단체인 물품계약의 검사 원문을 묻는다면?']:
            with self.subTest(text=text):self.assertTrue(intent.scope_reason('소방공무원입니다. '+text,SOURCE,TODAY))

    def test_multiline_clear_party_is_supported(self):
        q='소방공무원입니다.\n계약당사자는 지방자치단체입니다\n검사 원문을 설명해 주세요.'
        self.assertEqual(intent.scope_reason(q,SOURCE,TODAY),'')

    def test_uncertainty_about_question_is_not_party_uncertainty(self):
        for text in ['계약당사자는 지방자치단체입니다. 검사 원문에서 어떤 기준을 확인할 수 있나요?','계약당사자가 지방자치단체인 물품계약의 검사 원문에서 어떤 기준인지 설명해 주세요.']:
            with self.subTest(text=text):self.assertEqual(intent.scope_reason('소방공무원입니다. '+text,SOURCE,TODAY),'')

    def test_national_contract_and_framework_conflict_still_hold(self):
        for text in ['국가기관 물품계약 검사 원문을 설명해 주세요.','국가직 지방직 모두이며 계약당사자가 지방자치단체인 물품계약입니다.']:
            with self.subTest(text=text):self.assertTrue(intent.scope_reason('소방공무원입니다. '+text,SOURCE,TODAY))

    def test_personnel_statute_special_role_guard_is_unchanged(self):
        s={'official':{'title':'지방공무원 복무규정'},'institution':'지방공무원'}
        q='소방공무원입니다. 계약당사자는 지방자치단체입니다. 제 병가 기준은?'
        self.assertTrue(intent.scope_reason(q,s,TODAY))

    def test_historical_case_still_needs_historical_version(self):
        q='소방공무원입니다. 계약당사자가 지방자치단체인 물품 구매계약의 2026년 9월 1일 검사 원문을 설명해 주세요.'
        self.assertIn('사건일',intent.scope_reason(q,SOURCE,TODAY))

    def test_unchanged_query_and_trusted_decree_only(self):
        q='소방공무원입니다. 계약당사자는 지방자치단체입니다. 검사 기준은?'
        before=q
        decree={**SOURCE,'official':{'title':LAW+' 시행령','article':'제64조(검사)'}}
        self.assertEqual(intent.scope_reason(q,decree,TODAY),'')
        self.assertEqual(q,before)
        arbitrary={'title':LAW,'institution':'지방자치단체'}
        self.assertTrue(intent.scope_reason(q,arbitrary,TODAY))

if __name__=='__main__':unittest.main(verbosity=2)
