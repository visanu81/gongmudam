"""National fire/education staff: generic travel evidence, not payment approval."""
# Ported from the teammate branch. Difference: fire officers already read 공무원 여비 규정 and the
# national conduct decree here (소방공무원 복무규정 제10조), so only the teacher cases hold.
import copy,json,unittest
from datetime import date
from pathlib import Path
from app import knowledge_intent as intent, personnel_scope

TODAY=date(2026,11,3)
IDS={'191eae3832624733a206a9dd152e4120','243ca624713948529fd3d16292770ffb','9a03b7196838440fbd02755fef71db1f','a9069d8f479a4a7ba5e78f0e53348898','c5876ef8354a4eae8991ecd0f83e9495','e63421d3ede84dcc92e7f7e84f48f73c'}
BUNDLE=json.loads((Path(__file__).resolve().parents[1]/'submission-data/knowledge.json').read_text(encoding='utf-8'))
SOURCES=[s for s in (BUNDLE['sources'] if isinstance(BUNDLE,dict) else BUNDLE) if s['id'] in IDS]
SOURCE=next(s for s in SOURCES if s['id']=='243ca624713948529fd3d16292770ffb')

class NationalTravelScope(unittest.TestCase):
    def test_explicit_national_fire_and_education_can_select_travel_originals(self):
        self.assertEqual(len(SOURCES),6)
        for role in ['소방공무원','교육공무원','교사']:
            for source in SOURCES:
                q=f'국가직 {role}입니다. 공무원 여비 규정 원문을 설명해 주세요.'
                with self.subTest(role=role,source=source['id']):self.assertEqual(intent.scope_reason(q,source,TODAY),'')

    def test_missing_or_local_framework_still_needs_applicable_original(self):
        for q in ['교육공무원 여비 원문','사립학교 교사 여비 원문','국가직 지방직 소방공무원 여비 원문']:
            with self.subTest(query=q):self.assertTrue(intent.scope_reason(q,SOURCE,TODAY))

    def test_non_civil_staff_are_not_admitted_by_new_exception(self):
        for job in ['공무직','군인','회사원','공기업 직원']:
            with self.subTest(job=job):self.assertTrue(intent.scope_reason('국가직 '+job+' 여비 원문',SOURCE,TODAY))

    def test_national_destination_is_not_national_employee_identity(self):
        for q in ['사립학교 교사입니다. 국가기관으로 출장갈 때 여비 원문을 설명해 주세요.','국가기관 초청으로 출장하는 사립학교 교사입니다. 여비 원문을 설명해 주세요.','국가직이 아닌 사립학교 교사입니다. 국가기관 출장 여비 원문','국가직 교사일 수도 있습니다. 여비 원문']:
            with self.subTest(query=q):self.assertTrue(intent.scope_reason(q,SOURCE,TODAY))

    def test_retracted_national_identity_is_not_accepted(self):
        for text in ['국가직 교사입니다. 정정합니다. 국가직이 아닙니다. 여비 원문','국가직 교사입니다. 국가공무원 신분이 미확인입니다. 여비 원문','국가직 교사입니다. 신분은 미확인입니다. 여비 원문을 설명해 주세요.','국가직 교사입니다. 국가공무원 신분이 불확실합니다. 여비 원문']:
            with self.subTest(text=text):self.assertTrue(intent.scope_reason(text,SOURCE,TODAY))

    def test_personnel_statutes_keep_their_role_guards(self):
        for role in ['교육공무원']:
            s={'official':{'title':'국가공무원 복무규정'},'institution':'국가공무원'}
            with self.subTest(role=role):self.assertTrue(intent.scope_reason('국가직 '+role+' 병가 원문',s,TODAY))

    def test_history_month_and_date_guards_are_retained(self):
        self.assertTrue(intent.scope_reason('국가직 소방공무원 2026년 9월 여비 원문',SOURCE,TODAY))
        self.assertTrue(intent.scope_reason('국가직 소방공무원 2026년 9월 1일 여비 원문',SOURCE,TODAY))
        self.assertEqual(intent.scope_reason('국가직 소방공무원 2026년 11월 여비 원문',SOURCE,TODAY),'')

    def test_input_source_and_untrusted_title_are_not_changed(self):
        q='국가직 교사 여비 원문';s=copy.deepcopy(SOURCE);before=copy.deepcopy(s)
        intent.scope_reason(q,s,TODAY);self.assertEqual(s,before);self.assertEqual(q,'국가직 교사 여비 원문')
        untrusted={'title':'공무원 여비 규정','institution':'국가공무원'}
        self.assertTrue(intent.scope_reason(q,untrusted,TODAY))

if __name__=='__main__':unittest.main(verbosity=2)
