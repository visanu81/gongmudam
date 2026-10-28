"""Situation-based family-care intent and preparation guidance."""
from unittest.mock import patch

from test_core import Base
from app import guidance, knowledge_intent, main


class FamilyCareSituationTest(Base):
    def setUp(self):
        self.hit = dict(id='law-unit', source_id='law', title='검증용 복무 안내',
                        sha256='a' * 64, text='가족돌봄휴가는 신청할 수 있다.',
                        loc='제1조', official=None)
        self.found = dict(hits=[self.hit], experiences=[], excluded=[], intent=None,
                          requires_basis=True)

    def run_guide(self, query, **body):
        with patch('app.knowledge.retrieve', return_value=self.found), \
             patch('app.guidance.manual_knowledge.respond', return_value={'knowledge': {}}):
            return main.api_ask(dict(query=query, guidance=True, today='2026-10-24', **body))

    def test_child_illness_question_matches_family_care(self):
        plan = knowledge_intent.analyze('아이가 아파서 휴가를 써야 하는데 어떤 걸로 선택해야 해?')
        self.assertIn('family_care', plan['topics'])
        self.assertEqual(plan['status'], 'ready')

    def test_child_situation_aliases_match_with_leave_context(self):
        for query in ('아들 열나요 휴가를 써야 해', '딸 독감이라 쉬어야 해',
                      '아이 병원 동행 때문에 휴가', '자녀돌봄휴가를 써야 해'):
            with self.subTest(query=query):
                self.assertIn('family_care', knowledge_intent.analyze(query)['topics'])

    def test_employee_illness_incidental_family_and_bereavement_are_not_family_care(self):
        for query in ('본인이 아파서 병가를 쓰고 싶어', '아이는 건강하고 내가 아파서 병가',
                      '아이가 아픈 게 아니라 제가 아파서 병가를 쓰려고 해',
                      '가족 사망으로 경조사휴가를 쓰고 싶어'):
            with self.subTest(query=query):
                plan = knowledge_intent.analyze(query)
                self.assertNotIn('family_care', plan['topics'])

    def test_guidance_recognizes_child_illness_as_leave_without_vacation_word(self):
        result = self.run_guide('아이가 아파서 하루 쉬어야 해')
        self.assertEqual(result['guidance']['topic'], 'leave')
        questions = ' '.join(result['guidance']['questions'])
        self.assertNotIn('휴가 종류', questions)
        for clue in ('소속', '국가', '나이', '병원', '돌봄', '사용'):
            self.assertIn(clue, questions)

    def test_followup_keeps_child_illness_context_and_explicit_topic_wins(self):
        context = '아이가 아파서 휴가를 알아보는 중'
        self.assertIn('family_care', knowledge_intent.analyze(
            guidance.effective_query('7살이고 병원에 같이 가야 해', context))['topics'])
        self.assertEqual(guidance.effective_query('출장 신청 방법', context), '출장 신청 방법')
        for query in ('국가직인데 연가 이월 방법이 궁금해','지방직인데 유연근무는 어떻게 신청하나요','국가공무원 징계 종류 알려줘'):
            self.assertEqual(guidance.effective_query(query,context),query)
        fixed=guidance.effective_query('지방직이고 자녀는 7세야','국가공무원인데 아이가 아파서 휴가를 알아보는 중')
        self.assertNotIn('국가공무원',fixed)

