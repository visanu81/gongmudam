"""Pay and allowance amounts come from the hash-checked 2026 annexes, with the formula and source."""
import io, json, unittest

from app import pay_tables


def raw_text(name):
    data = (pay_tables.BASE / 'raw' / name).read_bytes()
    if name.endswith('.txt'):
        return data.decode('utf-8')
    import pypdf
    return '\n'.join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(data)).pages)


class TablesTest(unittest.TestCase):
    def test_stored_tables_are_what_the_annex_pdfs_say(self):
        manifest, tables = pay_tables.load()
        for key, entry in manifest.items():
            with self.subTest(key=key):
                self.assertEqual(json.loads(json.dumps(pay_tables.PARSERS[entry['kind']](raw_text(entry['raw_file'])))), tables[key])
                self.assertTrue(entry['source_url'].startswith('https://www.law.go.kr/'))

    def test_known_cells(self):
        _, t = pay_tables.load()
        general, fire = t['salary-general']['rows'], t['salary-police-fire']['rows']
        self.assertEqual(general['1'][8], 2_133_000)            # 9급 1호봉
        self.assertEqual(general['24'][0], None)                # 1급 has 23 호봉
        self.assertEqual(general['32'][5], 4_967_800)           # only 6급 reaches 32호봉
        self.assertEqual(fire['5'][8], 2_427_500)               # 경장·소방교 5호봉
        self.assertEqual(t['salary-police-fire']['columns'][9], '순경/소방사')
        # 별표 5 and the local 제10조 write the same 가족수당 differently (40,000원 / 월 4만원).
        self.assertEqual(t['family-national'], t['family-local'])
        self.assertEqual(t['family-national'], dict(spouse=40_000, other=20_000, children=[50_000, 80_000, 120_000]))
        self.assertEqual(t['subsidy-national']['general'], [750_000, 650_000, 500_000, 400_000, 250_000, 185_000, 180_000, 175_000, 175_000])
        self.assertEqual(t['subsidy-national']['police_fire'][5:7], [185_000, 185_000])   # 경감·경위 share a row
        self.assertEqual(t['subsidy-local']['deputy_4'], [450_000])


class CalculateTest(unittest.TestCase):
    def lines(self, question, context=''):
        return [(l['label'], l['amount']) for l in pay_tables.calculate(question, context)['lines']]

    def test_salary_holiday_and_longevity(self):
        self.assertEqual(self.lines('9급 1호봉 봉급 얼마야?'), [('9급 1호봉 월봉급액', 2_133_000)])
        self.assertEqual(self.lines('소방교 5호봉 명절휴가비 얼마 나와?'),
                         [('소방교 5호봉 월봉급액', 2_427_500), ('명절휴가비(설·추석 각각)', 1_456_500)])
        self.assertEqual(self.lines('7급 10호봉 재직 7년 정근수당 계산해줘'),
                         [('7급 10호봉 월봉급액', 3_133_300), ('정근수당(1월·7월 각각, 근무연수 7년)', 1_096_655), ('정근수당 가산금(매월)', 50_000)])
        # 20년 이상 25년 미만 adds the 10,000원 추가 가산금.
        self.assertIn(('정근수당 가산금(매월)', 110_000), self.lines('5급 20호봉 재직 22년 정근수당 얼마'))
        self.assertIn(('정근수당(1월·7월 각각, 근무연수 1년)', 241_290), self.lines('8급 6호봉 근무 1년 정근수당 얼마'))

    def test_ranks_that_share_a_prefix(self):
        self.assertEqual(self.lines('소방정 3호봉 월급 얼마?'), [('소방정 3호봉 월봉급액', 3_885_800)])
        self.assertEqual(self.lines('소방정감 1호봉 봉급 얼마'), [('소방정감 1호봉 월봉급액', 4_905_100)])
        self.assertEqual(self.lines('경감 2호봉 봉급 얼마'), [('경감 2호봉 월봉급액', 2_814_700)])

    def test_family_allowance(self):
        self.assertEqual(self.lines('배우자랑 자녀 둘 있으면 가족수당 얼마야?'),
                         [('가족수당 배우자(매월)', 40_000), ('가족수당 첫째 자녀(매월)', 50_000), ('가족수당 둘째 자녀(매월)', 80_000)])
        self.assertEqual(self.lines('아이 셋 가족수당 얼마'), [('가족수당 첫째 자녀(매월)', 50_000), ('가족수당 둘째 자녀(매월)', 80_000), ('가족수당 셋째 자녀(매월)', 120_000)])
        self.assertEqual(self.lines('아내와 어머니 부양하면 가족수당 얼마 받아?'), [('가족수당 배우자(매월)', 40_000), ('가족수당 그 밖의 부양가족 1명(매월)', 20_000)])
        # Family allowance needs no grade; 부모님 without a number is asked, not guessed.
        r = pay_tables.calculate('가족수당 얼마 나와?')
        self.assertEqual((r['lines'], r['needs']), ([], ['부양가족(예: 배우자, 자녀 2명)']))
        self.assertEqual(pay_tables.calculate('부모님 모시면 가족수당 얼마')['needs'], ['자녀 외 부양가족 수(예: 부모님 2명)'])
        r = pay_tables.calculate('배우자 부모님 2명 자녀 2명 가족수당 계산해줘')
        self.assertIn('4명 이내', r['notes'][0])
        local = pay_tables.calculate('배우자 가족수당 얼마', '지방공무원')
        self.assertEqual([s['law'] for s in local['sources']], ['지방공무원 수당 등에 관한 규정'])

    def test_grade_subsidy(self):
        self.assertEqual(self.lines('7급 직급보조비 얼마야?'), [('직급보조비(매월, 7급)', 180_000)])
        self.assertEqual(self.lines('소방위 직급보조비 얼마'), [('직급보조비(매월, 소방위)', 185_000)])
        self.assertEqual(self.lines('9급 3호봉 봉급이랑 직급보조비 얼마'), [('9급 3호봉 월봉급액', 2_168_000), ('직급보조비(매월, 9급)', 175_000)])
        self.assertIn('4급 부단체장은 월 450,000원', pay_tables.calculate('4급 직급보조비 얼마', '지방공무원')['notes'][0])
        self.assertEqual(pay_tables.calculate('직급보조비 얼마 받아?')['needs'], ['직급(예: 7급, 소방교)'])

    def test_overtime_from_the_guideline_rate_table(self):
        self.assertEqual(self.lines('7급 시간외근무수당 20시간 얼마?'),
                         [('시간외근무수당 시간당 단가(7급)', 12_368), ('시간외근무수당 20시간', 247_360)])
        self.assertEqual(self.lines('소방교 초과근무 15시간 수당 얼마'),
                         [('시간외근무수당 시간당 단가(소방교)', 12_584), ('시간외근무수당 15시간', 188_760)])
        self.assertEqual(self.lines('9급 휴일근무수당 2일 얼마'), [('휴일근무수당 1일 단가(9급)', 88_017), ('휴일근무수당 2일', 176_034)])
        # The rate table starts at 5급; a 호봉 in the question adds no salary line.
        self.assertIn('지급단가표', pay_tables.calculate('4급 시간외근무수당 얼마')['notes'][0])
        self.assertEqual(self.lines('7급 5호봉 초과근무 10시간 얼마')[0], ('시간외근무수당 시간당 단가(7급)', 12_368))
        self.assertEqual(pay_tables.calculate('시간외근무수당 얼마야?')['needs'], ['직급(예: 7급, 소방교)'])
        self.assertIsNone(pay_tables.calculate('시간외근무 신청 방법'))
        local = pay_tables.calculate('8급 시간외근무수당 단가', '지방공무원')
        self.assertEqual([s['law'] for s in local['sources']], ['지방공무원보수업무 등 처리지침'])

    def test_missing_information_is_named(self):
        r = pay_tables.calculate('명절휴가비 얼마나 나와?')
        self.assertEqual((r['lines'], r['needs']), ([], ['직급(예: 7급, 소방교)', '호봉(예: 5호봉)']))
        r = pay_tables.calculate('1급 30호봉 봉급 얼마')
        self.assertEqual(r['lines'], []); self.assertIn('30호봉이 없습니다', r['notes'][0])
        r = pay_tables.calculate('정근수당 계산해줘 재직 7년')
        self.assertIn('35%', r['notes'][0]); self.assertIn('호봉(예: 5호봉)', r['needs'])

    def test_local_servants_cite_the_local_rules(self):
        r = pay_tables.calculate('6급 15호봉 근무 12년 정근수당 얼마', '업무환경: 경기도 소속 지방공무원')
        self.assertIn('지방공무원 수당 등에 관한 규정 제6조', r['notes'][0])
        self.assertEqual([s['law'] for s in r['sources']], ['공무원보수규정', '지방공무원 수당 등에 관한 규정'])

    def test_answers_carry_the_calculation(self):
        from app import main
        reply = main._with_pay({'mode': 'structured_guidance'}, '9급 1호봉 봉급 얼마야?', {'situation_context': ''})
        self.assertEqual(reply['pay_calculation']['lines'][0]['amount'], 2_133_000)
        self.assertNotIn('pay_calculation', main._with_pay({}, '연가는 며칠이야?', {}))
        # A confirmed 지방공무원 소속 cites the local allowance rule, as the answer search does.
        local = dict(confirmed=True, personnel_framework='local_public_official', organization='경기도청', department='', region='')
        reply = main._with_pay({}, '7급 10호봉 재직 7년 정근수당 계산해줘', {'affiliation': local})
        self.assertTrue(reply['pay_calculation']['notes'][0].startswith('지방공무원 수당 등에 관한 규정 제6조'))

    def test_other_questions_get_no_calculation(self):
        for q in ('연가는 며칠이야?', '봉급 지급일은?', '정근수당 지급 기준 알려줘', '2026년 9급 공채 일정'):
            with self.subTest(q=q):
                self.assertIsNone(pay_tables.calculate(q))


if __name__ == '__main__':
    unittest.main()
