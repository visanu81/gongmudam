"""Natural-language aliases for reviewed office guidance routing."""
import unittest

from app.office_knowledge import classify


class PracticeOfficeAliasesTest(unittest.TestCase):
    def assert_route(self, query, topic, rule):
        plan = classify(query)
        self.assertIsNotNone(plan, query)
        self.assertIn(topic, plan['topics'], query)
        self.assertIn(rule, plan['rules'], query)

    def test_child_application_consent_routes_to_existing_privacy_rule(self):
        self.assert_route(
            '만 14세 미만 아동의 교육 신청 정보를 받을 때 동의는 어떻게 확인하나요?',
            'privacy', 'privacy-child')

    def test_participant_contact_deletion_is_a_data_subject_request(self):
        self.assert_route(
            '교육 참가자가 본인 연락처를 삭제해 달라고 요청했어요.',
            'privacy', 'privacy-rectify')

    def test_general_document_receipt_questions_accept_recipient_aliases(self):
        for query in (
            '문서과에서 받은 공문은 어느 부서로 넘기나요?',
            '당직 중에 공문을 받았어요. 다음 날 누구에게 넘기나요?',
        ):
            with self.subTest(query=query):
                self.assert_route(query, 'documents', 'documents-receipt')

    def test_named_counterapproval_routes_to_existing_drafting_rule(self):
        self.assert_route(
            '결재권자가 출장 중일 때 대결은 어떻게 하나요?',
            'documents', 'documents-drafting')

    def test_child_leave_and_ordinary_list_deletion_are_not_privacy_rights(self):
        self.assertIsNone(classify('아동 돌봄휴가 신청은 어떻게 하나요?'))
        self.assertIsNone(classify('교육 자료 파일을 삭제해 주세요.'))

    def test_completed_attendee_list_deletion_keeps_existing_roster_privacy_route(self):
        plan = classify('교육 참석자 명단을 삭제해도 되나요?')
        self.assertIn('privacy', plan['topics'])
        self.assertIn('privacy-delete', plan['rules'])
        self.assertNotIn('privacy-rectify', plan['rules'])

    def test_agency_specific_document_route_stays_unsupported(self):
        for query in (
            '우리 부서 공문은 어느 부서로 넘기나요?',
            '서울시청에서 받은 공문은 어느 부서로 넘기나요?',
            '당직 중에 공문을 받았어요. 담당자 이름과 연락처를 알려주세요.',
        ):
            with self.subTest(query=query):
                plan = classify(query)
                self.assertIsNotNone(plan)
                self.assertIn('unsupported', plan['rules'])

    def test_e_saram_leave_and_travel_calculation_are_not_document_drafting(self):
        for query in (
            'e-사람 휴가신청에서 대결 결재권자를 어떻게 지정하나요?',
            '이사람 휴가신청에서 대결 결재권자를 어떻게 지정하나요?',
            '스마트출장 대결 결재권자를 어디서 지정하나요?',
            '휴가신청에서 결재권자 대결을 어떻게 지정하나요?',
            '출장신청에서 결재권자 대결을 어떻게 지정하나요?',
            '결재권자가 출장 중일 때 대결 여비 계산은 어떻게 하나요?',
        ):
            with self.subTest(query=query):
                self.assertIsNone(classify(query))


if __name__ == '__main__':
    unittest.main()
