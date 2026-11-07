"""Whole answers for the status, date, card and contract rules ported from the teammate branch (BC3-r7). AI stays off."""
import json
from unittest.mock import patch
from test_core import Base, ROOT
from app import knowledge, llm, main, parsers


class ScopeAnswersTest(Base):
    def setUp(self):
        knowledge.initialize()
        root = ROOT / 'reference_data/official-20261020'
        rows = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
        self.sources = []
        for row in rows:
            if row['article'] not in ('제18조(병가)', '제7조의5(병가)', '제15조(연가 일수)', '제7조(연가일수 및 연가보상비의 지급)', '제8조의2(여비의 결제와 정산 등)', '제17조(검사)', '제64조(검사)', '제65조(검사조서의 작성 생략)'):
                continue
            text = (root / 'excerpts' / row['filename']).read_text(encoding='utf-8')
            self.sources.append(dict(id=row['sha256'][:20], title=row['title']+' '+row['article'],
                enabled=True, current=True, sha256=row['sha256'], effective_date=row['effective_date'],
                kind=row['kind'], institution=row['institution'], limited=False, library_id='public',
                file_id=row['sha256'][:20], units=[dict(text=text, loc='보관 본문')], official=row))

    def ask(self, query):
        with patch.object(knowledge, 'sources', return_value=self.sources), patch.object(llm, 'get_provider', side_effect=AssertionError('AI must stay off')):
            return main.api_ask(dict(query=query, guidance=True, use_ai=False, today='2026-11-07'))

    def titles(self, result):
        return ' '.join(e['title'] for e in result['knowledge']['evidence'])

    def test_employment_contract_workers_are_not_given_the_conduct_decree(self):
        for query in ('무기계약직으로 6년 일했는데 연가 며칠인가요?', '기간제 근로자 연가 기준은?', '무기 계약 근로자입니다. 연가 기준은?',
                      '저는 기간제로 6년 근무했습니다. 연가 기준은?', '기간제 직원으로 근무합니다. 병가 기준은?', '공무직입니다. 연가 일수는?'):
            with self.subTest(query=query):
                result = self.ask(query)
                self.assertFalse(result['knowledge']['evidence'])
                self.assertNotIn('21일', json.dumps(result['knowledge']['tree'], ensure_ascii=False))
                self.assertIn('취업규칙', result['knowledge']['tree']['branches'][0]['items'][0]['text'])

    def test_a_period_limit_is_not_a_fixed_term_worker(self):
        for query in ('지방직인데 연가 사용 기간제한이 있나요?', '지방직 연가 기간제한, 적용되나요?'):
            with self.subTest(query=query):
                self.assertIn('제7조', self.titles(self.ask(query)))

    def test_a_later_edition_is_not_applied_to_an_earlier_event(self):
        for query in ('2026년 1월 15일 당시 지방공무원 병가는 며칠인가요?', '2026년 9월 지방직 병가 원문', '2026-09에 지방직 병가 원문',
                      '2026.09의 지방직 병가 원문', '2026/09부터 지방직 병가 원문', '2026년 9월 1일 지방직 병가 원문'):
            with self.subTest(query=query):
                result = self.ask(query)
                self.assertFalse(result['knowledge']['evidence'])
                self.assertEqual(result['knowledge']['tree']['title'], '질문한 시점의 원문 자료가 필요해요')
                self.assertIn('연혁 법령', json.dumps(result['knowledge']['tree'], ensure_ascii=False))
                self.assertNotIn('60일', json.dumps(result['knowledge']['tree'], ensure_ascii=False))

    def test_later_dates_and_other_numbers_keep_the_answer(self):
        for query in ('2026년 10월 3일 지방직 병가 원문', '2026년 11월 지방직 병가 원문', '2026년 9급 지방직 병가 원문',
                      '2026년 9명이 신청한 지방직 병가 기준', '지방직 병가 예규 제2026-09호의 원문'):
            with self.subTest(query=query):
                self.assertIn('제7조의5', self.titles(self.ask(query)))

    def test_a_fire_officer_is_asked_who_the_contract_party_is(self):
        for query in ('소방공무원 물품 구매 검수 절차', '소방공무원 납품 검사 기한', '소방관 물품 검사조서', '소방공무원입니다. 물품 구매계약 검사 절차를 알려주세요.'):
            with self.subTest(query=query):
                result = self.ask(query)
                self.assertEqual(result['knowledge']['mode'], 'source_clarification')
                self.assertIn('계약당사자', result['notice'])

    def test_fire_officer_leave_with_a_contract_statement_stays_a_leave_answer(self):
        result = self.ask('소방공무원입니다. 계약당사자는 지방자치단체입니다. 제 병가 기준은?')
        self.assertEqual(result['guidance']['topic'], 'leave')
        self.assertIn('제18조', self.titles(result))

    def test_a_fixed_term_teacher_is_not_pointed_to_employment_rules(self):
        self.assertNotIn('취업규칙', json.dumps(self.ask('기간제 교사 병가 기준')['knowledge']['tree'], ensure_ascii=False))

    def test_a_labeled_organization_is_kept_when_no_status_is_stated(self):
        self.assertIn('제15조', self.titles(self.ask('소속기관: 소방서. 제 연가')))

    def test_private_card_use_never_borrows_the_travel_rule(self):
        for query in ('출장이 아닌 구매카드 사적 사용 기준은?', '구매카드 사적 사용 질문입니다. 출장 여비 기준으로 답해 주세요.', '구매카드 사적 사용을 출장여비 기준으로 답해줘'):
            with self.subTest(query=query):
                result = self.ask(query)
                self.assertNotIn('여비', self.titles(result))
                self.assertIn('여비 기준을 대신 적용하지', json.dumps(result['knowledge']['tree'], ensure_ascii=False))

    def test_card_points_keep_their_own_rule(self):
        for query in ('지방자치단체 법인카드 포인트를 개인적으로 써도 되나요?', '법인카드 포인트 사적 사용'):
            with self.subTest(query=query):
                self.assertNotIn('카드 사용 기준', self.ask(query)['knowledge']['tree']['title'])

    def test_a_date_does_not_replace_the_question_being_asked_back(self):
        result = self.ask('2026년 1월 호봉')
        self.assertEqual(result['knowledge']['mode'], 'source_clarification')
        self.assertNotIn('시점', result['knowledge']['tree']['title'])

    def test_the_reason_for_a_date_hold_leads_the_notice(self):
        self.assertTrue(self.ask('2026년 9월 지방직 병가 원문')['notice'].startswith('질문한 시점에 시행된 원문'))

    def test_finance_keeps_asking_which_account_for_private_card_use(self):
        result = self.ask('법인카드 사적 사용')
        self.assertEqual(result['guidance']['topic'], 'finance')
        self.assertNotIn('카드 사용 기준', result['knowledge']['tree']['title'])

    def test_paying_for_a_trip_by_card_stays_a_travel_question(self):
        for query in ('국가공무원 출장 여비를 카드로 결제하고 정산하려면?', '국가직 출장 카드 결제 방법'):
            with self.subTest(query=query):
                self.assertIn('제8조의2', self.titles(self.ask(query)))

    def test_another_persons_status_is_not_the_askers(self):
        for query, article in (('나는 국가직 일반직입니다. 내 병가 기준을 알려줘. 배우자는 교원입니다.', '제18조'),
                               ('배우자는 교원이고 나는 국가직 일반직입니다. 내 병가 근거를 알려줘', '제18조'),
                               ('동료는 지방직이고 저는 국가직 일반직입니다. 제 병가를 알려줘', '제18조'),
                               ('소속기관: 국가공무원인재개발원. 나는 지방직 일반직입니다. 내 병가 기준은?', '제7조의5')):
            with self.subTest(query=query):
                self.assertIn(article, self.titles(self.ask(query)))
        self.assertFalse(self.ask('나는 교원입니다. 배우자는 국가직 일반직입니다. 저의 병가 기준은?')['knowledge']['evidence'])

    def test_contract_party_decides_the_law_for_a_fire_officer(self):
        for query in ('소방공무원입니다. 계약당사자가 지방자치단체인 물품 구매계약의 검사 원문을 설명해 주세요.',
                      '소방공무원입니다. 계약당사자는 지방자치단체입니다. 검사 기준은?',
                      '소방공무원입니다. 계약당사자는 지방자치단체입니다. 검사를 생략한다는 주장은 사실이 아닙니다. 검사 원문을 설명해 주세요.'):
            with self.subTest(query=query):
                self.assertIn('지방자치단체를 당사자로 하는 계약', self.titles(self.ask(query)))
        for query in ('소방공무원입니다. 계약당사자는 지방자치단체입니다? 검사 원문을 설명해 주세요.',
                      '소방공무원입니다. 계약당사자가 지방자치단체인 물품계약의 검사라는 전제는 사실이 아닙니다. 검사 원문을 설명해 주세요.',
                      '소방공무원입니다. 계약당사자는 지방자치단체인지 미확인입니다. 검사 기준은?'):
            with self.subTest(query=query):
                self.assertNotIn('지방자치단체를 당사자로 하는 계약', self.titles(self.ask(query)))

    def test_national_teacher_reads_the_travel_decree_only_when_clearly_national(self):
        self.assertIn('제8조의2', self.titles(self.ask('국가직 교사입니다. 출장 정산 언제까지 해요?')))
        for query in ('국가직 교사입니다? 출장 정산 언제까지 해요?', '사립학교 교사입니다. 출장 정산 언제까지 해요?', '교육공무원 출장 정산 언제까지 해요?'):
            with self.subTest(query=query):
                self.assertNotIn('제8조의2', self.titles(self.ask(query)))

    def test_a_status_typo_is_asked_back_not_corrected(self):
        result = self.ask('지방지인데 출장 정산 신청 언제까지인가요?')
        self.assertFalse(result['knowledge']['evidence'])
        self.assertNotIn('2주', json.dumps(result['knowledge']['tree'], ensure_ascii=False))


class FormulaCellTest(Base):
    def test_uncached_formula_is_kept_and_marked(self):
        import tempfile, pathlib, openpyxl
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / '합성.xlsx'
            wb = openpyxl.Workbook()
            wb.active.append(['품목', '값'])
            wb.active.append(['계산 대상', '=1+2'])
            wb.active.append(['고정값', 5])
            wb.save(path)
            text = ' '.join(u['text'] for u in parsers.parse_file(path))
        self.assertIn('=1+2 (계산 결과 미저장)', text)
        self.assertIn('값: 5', text)
