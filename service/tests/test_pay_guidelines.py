"""Pay guidelines shown as practice beside pay, allowance and welfare answers."""
import json
import shutil
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch
from test_core import Base
from app import knowledge, llm, pay_guidelines

TODAY = date(2026, 10, 31)


class PayGuidelinesTest(Base):
    def setUp(self):
        pay_guidelines.catalog.cache_clear()

    def practice(self, query):
        with patch.object(llm, 'get_provider', side_effect=AssertionError('AI is disabled')):
            return knowledge.retrieve(query, None, TODAY).get('practice') or []

    def test_both_guidelines_are_hash_verified(self):
        found = pay_guidelines.catalog()
        self.assertEqual(sorted(found), ['local', 'national'])
        self.assertEqual(found['national'][0]['publication'], '인사혁신처예규 제226호')
        self.assertEqual(found['local'][0]['publication'], '행정안전부예규 제389호')
        self.assertGreater(len(found['national'][1]), 600)

    def test_changed_page_is_not_used(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            copy = tmp / pay_guidelines.COLLECTION
            shutil.copytree(pay_guidelines.BASE, copy)
            pages = copy / 'local-389.pages.json'
            pages.write_text(pages.read_text(encoding='utf-8').replace('정근수당', '정근 수당', 1), encoding='utf-8')
            with patch.object(pay_guidelines, 'BASE', copy):
                pay_guidelines.catalog.cache_clear()
                self.assertEqual(sorted(pay_guidelines.catalog()), ['national'])
        finally:
            pay_guidelines.catalog.cache_clear()
            shutil.rmtree(tmp, ignore_errors=True)

    def test_practice_follows_the_regulation_the_answer_used(self):
        national = self.practice('국가공무원 정근수당 언제 받아?')
        self.assertEqual(national[0]['official']['publication'], '인사혁신처예규 제226호')
        self.assertTrue(national[0]['official']['article'].startswith('제7장'))
        local = self.practice('지방공무원 가족수당 얼마야?')
        self.assertEqual(local[0]['official']['publication'], '행정안전부예규 제389호')
        self.assertTrue(local[0]['official']['article'].startswith('제5장'))
        self.assertIn('가족수당', local[0]['quote'].splitlines()[0])
        # The answer keeps the quote that starts at the subject.
        query = '지방공무원 가족수당 얼마야?'
        reply = knowledge.answer(query, knowledge.retrieve(query, None, TODAY), use_ai=False)
        self.assertEqual(reply['practice'][0]['quote'], local[0]['quote'])
        welfare = self.practice('맞춤형복지 포인트 사용 기준은?')
        self.assertTrue(welfare[0]['official']['article'].startswith('제11장'))

    def test_unmapped_equation_glyphs_are_marked_not_shown(self):
        # 226 p.76: the 6/12 fraction is stored as private-use glyphs; no PDF reader recovers it.
        row, pages = pay_guidelines.catalog()['national']
        stored = next(p for p in pages if p['page'] == 76)['text']
        self.assertTrue(pay_guidelines.UNREADABLE.search(stored))
        shown = pay_guidelines.readable(stored)
        self.assertFalse(pay_guidelines.UNREADABLE.search(shown))
        self.assertIn('7,554,360원×[수식·기호: 원문 확인 필요]', shown)

    def test_symbol_font_marks_become_brackets_boxes_and_dots(self):
        # U+F000 wraps law names in 226·389 and marks bullets in 지방재정 전문; U+F85E is a middle dot.
        text = '국가공무원법 및  결제대금 지각조퇴 금액×'
        self.assertEqual(pay_guidelines.readable(text), '「국가공무원법」 및 □ 결제대금 지각ㆍ조퇴 금액×[수식·기호: 원문 확인 필요]')

    def test_answers_show_unmapped_glyphs_readably(self):
        hit = dict(id='lib:1', text='(예시)신용카드결제대금 지방회계법 제1조', title='합성 지침', loc='p.1',
                   source_id='lib', kind='guideline', score=1.0, limited=False, official=None)
        reply = knowledge.answer('결제대금 기준', dict(hits=[hit], experiences=[], excluded=[], intent=None), use_ai=False)
        self.assertEqual(reply['evidence'][0]['text'], '(예시)□신용카드결제대금 「지방회계법」 제1조')
        self.assertFalse(pay_guidelines.UNREADABLE.search(json.dumps(reply, ensure_ascii=False)))

    def test_holiday_bonus_is_a_pay_question_not_leave(self):
        from app import guidance
        self.assertEqual(guidance.topic('명절휴가비 얼마나 나와?')[0], 'pay')
        self.assertEqual(guidance.topic('연가 며칠 남았어?')[0], 'leave')

    def test_no_practice_without_a_matching_section(self):
        # The guideline has no payday section, and a holiday bonus is not a leave question.
        self.assertEqual(self.practice('월급 언제 나와?\n업무환경: 지방공무원'), [])
        holiday = self.practice('명절휴가비 얼마나 나와?\n업무환경: 국가공무원')
        self.assertEqual([p['official']['publication'] for p in holiday], ['인사혁신처예규 제226호'])
