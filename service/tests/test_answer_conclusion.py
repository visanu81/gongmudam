import copy
import unittest
from app import answer_conclusion, knowledge_intent, leave_situations


class AnswerConclusionTest(unittest.TestCase):
    def test_promoted_answer_keeps_full_condition_citation_and_original_tree(self):
        first=dict(text='일비는 여행일수에 따라 지급해요.',ref=1,support_quotes=['여행일수'])
        decision=dict(text='공무용 차량 이용 등 정해진 조건이면 일비의 절반을 지급해요.',ref=2,support_quotes=['2분의 1'])
        tree=dict(kind='summary',rule_id='daily-car',title='감액을 확인해요',branches=[dict(label='기본',items=[first]),dict(label='차량',items=[decision])])
        before=copy.deepcopy(tree)
        result=answer_conclusion.lead('공무용 차량 출장 일비',tree)
        self.assertEqual(result['title'],decision['text'])
        self.assertEqual(result['branches'][0]['items'][0],decision)
        self.assertEqual(tree,before)
        self.assertEqual(sum(len(b['items']) for b in result['branches']),2)

    def test_unverified_missing_and_clarifying_answers_are_not_asserted(self):
        for kind in ('unavailable','extract','clarification','reference'):
            tree=dict(kind=kind,rule_id='daily-car',title='자료 필요',branches=[])
            self.assertEqual(answer_conclusion.lead('일비',tree),tree)
        for item in (dict(text='일비의 절반',ref=1),dict(text='일비의 절반',support_quotes=['2분의 1'])):
            tree=dict(kind='summary',rule_id='daily-car',title='확인 필요',branches=[dict(label='기준',items=[item])])
            self.assertEqual(answer_conclusion.lead('일비',tree),tree)

    def test_drafting_question_promotes_specific_absence_item(self):
        nodes=[dict(text='결재를 받기 전에 검토와 관련 부서 협조를 받아요.',ref=1,support_quotes=['검토']),dict(text='결재권자가 없으면 직무를 대리하는 사람이 대결해요. 중요한 내용은 사후 보고해요.',ref=2,support_quotes=['대결','사후'])]
        tree=dict(kind='summary',rule_id='office:documents-drafting',branches=[dict(label='기안',items=nodes)])
        self.assertEqual(answer_conclusion.lead('결재권자가 출장인데 대결할 수 있나요?',tree)['title'],nodes[1]['text'])
        self.assertEqual(answer_conclusion.lead('기안 검토 결재 순서는?',tree)['title'],nodes[0]['text'])

    def test_own_illness_recognized_without_leave_name(self):
        q='국가공무원인데 제가 독감으로 출근이 어려워요. 어떤 휴가로 신청해야 하나요?'
        self.assertEqual(knowledge_intent.analyze(q)['topics'],['sick'])
        for q in ('아이가 독감인데 제가 병원에 동행하려고 휴가를 써요','저는 아프지 않지만 근무가 어려워요','본인 건강검진으로 출근을 못 해요'):
            self.assertFalse(leave_situations.self_sick(q))

    def test_ambiguous_leave_asks_for_reason_not_leave_name(self):
        plan=knowledge_intent.analyze('휴가를 쓰려고 하는데 어떤 걸로 해야 하나요?')
        self.assertEqual(plan['status'],'clarify')
        self.assertIn('어떤 사유',plan['question'])
        self.assertNotIn('어떤 휴가',plan['question'])
