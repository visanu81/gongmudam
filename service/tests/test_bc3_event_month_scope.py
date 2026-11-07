"""F-EVENT-MONTH-01: a month is an interval, never an invented incident day."""
import unittest
from datetime import date
from app import knowledge_intent as intent, document_context

TODAY=date(2026,11,3)
SOURCE={'official':{'title':'지방공무원 복무규정','article':'제7조의5(병가)'},'institution':'지방공무원','effective_date':'2026-10-02'}

class EventMonthScope(unittest.TestCase):
    def test_known_month_before_source_requires_earlier_original(self):
        for month in ['2026년 9월','2026-09','2026.09','2026/09']:
            with self.subTest(month=month):self.assertTrue(intent.scope_reason(month+' 지방직 병가 원문',SOURCE,TODAY))

    def test_month_straddling_commencement_needs_precise_event(self):
        self.assertTrue(intent.scope_reason('2026년 10월 지방직 병가 원문',SOURCE,TODAY))

    def test_whole_month_after_commencement_is_not_blanket_held(self):
        self.assertEqual(intent.scope_reason('2026년 11월 지방직 병가 원문',SOURCE,TODAY),'')
        first={**SOURCE,'effective_date':'2026-10-01'}
        self.assertEqual(intent.scope_reason('2026년 10월 지방직 병가 원문',first,TODAY),'')

    def test_complete_date_is_not_reinterpreted_as_first_of_month(self):
        self.assertEqual(intent.scope_reason('2026년 10월 3일 지방직 병가 원문',SOURCE,TODAY),'')
        self.assertEqual(intent.scope_reason('2026-10-03 지방직 병가 원문',SOURCE,TODAY),'')
        self.assertTrue(intent.scope_reason('2026년 9월 1일 지방직 병가 원문',SOURCE,TODAY))
        self.assertEqual(document_context.event_dates('2026년 10월 지방직 병가 원문'),set())

    def test_document_number_is_not_an_event_month(self):
        self.assertEqual(intent.scope_reason('지방직 병가 예규 제2026-09호의 원문',SOURCE,TODAY),'')

    def test_rank_people_and_counts_are_not_months(self):
        for text in ['2026년 9급 지방직 병가 원문','2026년 9명이 신청한 지방직 병가 기준','2026년 9회 지방직 병가 원문','2026년 99명 지방직 병가 원문']:
            with self.subTest(text=text):self.assertEqual(intent.scope_reason(text,SOURCE,TODAY),'')

    def test_invalid_explicit_month_is_not_assigned_a_valid_date(self):
        for month in ['2026년 0월','2026년 13월']:
            with self.subTest(month=month):self.assertTrue(intent.scope_reason(month+' 지방직 병가 원문',SOURCE,TODAY))

    def test_source_and_question_are_not_mutated(self):
        import copy
        q='2026년 9월 지방직 병가 원문';s=copy.deepcopy(SOURCE);before=copy.deepcopy(s)
        intent.scope_reason(q,s,TODAY)
        self.assertEqual(s,before);self.assertEqual(q,'2026년 9월 지방직 병가 원문')

if __name__=='__main__':unittest.main(verbosity=2)
