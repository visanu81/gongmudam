"""Pay and allowance amounts come from the hash-checked 2026 annexes, with the formula and source."""
import io, json, unittest

from app import pay_tables


def pdf_text(name):
    import pypdf
    return '\n'.join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO((pay_tables.BASE / 'raw' / name).read_bytes())).pages)


class TablesTest(unittest.TestCase):
    def test_stored_tables_are_what_the_annex_pdfs_say(self):
        manifest, tables = pay_tables.load()
        for key, entry in manifest.items():
            with self.subTest(key=key):
                parse = pay_tables.parse_salary if entry['kind'] == 'salary' else pay_tables.parse_longevity
                self.assertEqual(json.loads(json.dumps(parse(pdf_text(entry['raw_file'])))), tables[key])
                self.assertTrue(entry['source_url'].startswith('https://www.law.go.kr/'))

    def test_known_cells(self):
        _, t = pay_tables.load()
        general, fire = t['salary-general']['rows'], t['salary-police-fire']['rows']
        self.assertEqual(general['1'][8], 2_133_000)            # 9급 1호봉
        self.assertEqual(general['24'][0], None)                # 1급 has 23 호봉
        self.assertEqual(general['32'][5], 4_967_800)           # only 6급 reaches 32호봉
        self.assertEqual(fire['5'][8], 2_427_500)               # 경장·소방교 5호봉
        self.assertEqual(t['salary-police-fire']['columns'][9], '순경/소방사')


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
