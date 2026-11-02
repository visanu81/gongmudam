"""Structure-preserving conversion for 업무자료 정리 (skdconv for Office/Hancom files, kordoc for PDF)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app import document_convert, project_text

SAMPLES = Path(__file__).resolve().parents[1] / 'sample_data/규정자료'


class TableUnitsTest(unittest.TestCase):
    def test_rows_keep_their_column_names_and_merged_cells_stay_in_place(self):
        rows = [[('부서', 1, 1), ('대상 인원', 1, 1), ('참석 인원', 1, 1)],
                [('회계과', 1, 1), ('8', 1, 1), ('0', 1, 1)],
                [('합계', 2, 1), ('23', 1, 1)]]
        units = document_convert._table_units(rows)
        self.assertEqual(units[1], ('2행', '부서: 회계과 / 대상 인원: 8 / 참석 인원: 0'))
        self.assertEqual(units[2], ('3행', '부서: 합계 / 참석 인원: 23'))

    def test_spreadsheet_cells_covered_by_a_merge_do_not_shift_values(self):
        rows = [[('부서', 1, 1), ('대상', 1, 1), ('참석', 1, 1)],
                [('합계', 2, 1), ('', 1, 1), ('23', 1, 1)]]
        self.assertEqual(document_convert._table_units(rows)[1][1], '부서: 합계 / 참석: 23')

    def test_title_row_above_the_header_is_plain_text(self):
        rows = [[('교육 취합', 3, 1)], [('부서', 1, 1), ('인원', 1, 1), ('회신', 1, 1)], [('총무과', 1, 1), ('9', 1, 1), ('완료', 1, 1)]]
        units = document_convert._table_units(rows)
        self.assertEqual(units[0][1], '교육 취합')
        self.assertEqual(units[2][1], '부서: 총무과 / 인원: 9 / 회신: 완료')

    def test_application_form_reads_label_value_rows_and_the_people_header(self):
        # A synthetic application form: the first row is a choice, labels sit beside values,
        # and a header row for the people starts midway.
        rows = [[('참가\n구분', 2, 1), ('■ 개인 □ 팀 (팀명: )', 6, 1)],
                [('기관\n정보', 1, 2), ('기관명', 1, 1), ('가람시청', 6, 1)],
                [('담당부서명', 1, 1), ('총무과 기획팀', 6, 1)],
                [('❷ 참가자 정보', 8, 1)],
                [('구분', 1, 1), ('성명', 1, 1), ('부서', 1, 1), ('직급', 1, 1), ('직위', 1, 1), ('연락처', 1, 1), ('이메일', 1, 1), ('역할', 1, 1)],
                [('개인', 1, 1), ('홍길동', 1, 1), ('민원과', 1, 1), ('주무관', 1, 1), ('', 1, 1), ('010-0000-0000', 1, 1), ('a@example.test', 1, 1), ('개발', 1, 1)],
                [('과제명', 2, 1), ('합성 도우미', 6, 1)]]
        texts = [text for _, text in document_convert._table_units(rows)]
        self.assertIn('기관 정보 · 기관명: 가람시청', texts)
        self.assertIn('기관 정보 · 담당부서명: 총무과 기획팀', texts)
        self.assertIn('구분: 개인 / 성명: 홍길동 / 부서: 민원과 / 직급: 주무관 / 연락처: 010-0000-0000 / 이메일: a@example.test / 역할: 개발', texts)
        self.assertIn('과제명: 합성 도우미', texts)

    def test_blank_form_rows_are_fields_not_column_names(self):
        # A blank form lists one label per row, then label | unit rows.
        rows = [[('소속', 1, 1), ('', 1, 1)], [('직급', 1, 1), ('', 1, 1)], [('출장 기간', 1, 1), ('', 1, 1)],
                [('운임', 1, 1), ('원', 1, 1)], [('숙박비', 1, 1), ('원', 1, 1)]]
        texts = [text for _, text in document_convert._table_units(rows)]
        self.assertEqual(texts, ['소속', '직급', '출장 기간', '운임: 원', '숙박비: 원'])

    def test_second_header_row_names_both_levels_and_data_rows_stay_data(self):
        rows = [[('구분', 1, 1), ('운임', 3, 1)],
                [('도시', 1, 1), ('일등석', 1, 1), ('비즈니스', 1, 1), ('일반석', 1, 1)],
                [('콜롬보', 1, 1), ('4,780,400', 1, 1), ('3,414,500', 1, 1), ('2,050,000', 1, 1)],
                [('요구권자', 1, 1), ('장', 1, 1), ('부서장', 1, 1), ('장', 1, 1)]]
        texts = [text for _, text in document_convert._table_units(rows)]
        self.assertIn('구분 도시: 콜롬보 / 운임 일등석: 4,780,400 / 운임 비즈니스: 3,414,500 / 운임 일반석: 2,050,000', texts)
        self.assertIn('구분 도시: 요구권자 / 운임 일등석: 장 / 운임 비즈니스: 부서장 / 운임 일반석: 장', texts)


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def hwpx_table(self):
        """A minimal HWPX with a header row and a merged total row."""
        import zipfile
        ns = 'http://www.hancom.co.kr/hwpml/2011/paragraph'
        def para(text): return f'<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>'
        def cell(text, col, row, span=1): return (f'<hp:tc><hp:subList>{para(text)}</hp:subList><hp:cellAddr colAddr="{col}" rowAddr="{row}"/>'
                                                  f'<hp:cellSpan colSpan="{span}" rowSpan="1"/></hp:tc>')
        rows = [['부서', '대상 인원', '참석 인원'], ['회계과', '8', '0'], ['총무과', '12', '9']]
        trs = ''.join('<hp:tr>' + ''.join(cell(v, c, r) for c, v in enumerate(row)) + '</hp:tr>' for r, row in enumerate(rows))
        trs += '<hp:tr>' + cell('합계', 0, 3, 2) + cell('9', 2, 3) + '</hp:tr>'
        xml = (f'<hs:sec xmlns:hp="{ns}" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section">{para("교육 회신 현황")}'
               f'<hp:p><hp:run><hp:tbl rowCnt="4" colCnt="3">{trs}</hp:tbl></hp:run></hp:p></hs:sec>')
        path = self.root / '현황.hwpx'
        with zipfile.ZipFile(path, 'w') as z:z.writestr('Contents/section0.xml', xml)
        return path

    def test_hwpx_table_rows_carry_their_column_names(self):
        result = project_text.extract(self.hwpx_table())
        self.assertEqual(result['status'], 'ready')
        self.assertIn('skdconv', result['detail'])
        texts = [u['text'] for u in result['units']]
        self.assertIn('부서: 회계과 / 대상 인원: 8 / 참석 인원: 0', texts)
        self.assertIn('부서: 합계 / 참석 인원: 9', texts)

    def test_docx_and_xlsx_stay_with_the_built_in_reader(self):
        import openpyxl
        wb = openpyxl.Workbook(); wb.active.append(['부서', '인원']); wb.active.append(['회계과', 8])
        path = self.root / '취합.xlsx'; wb.save(path)
        with patch.object(document_convert, 'convert') as convert:
            result = project_text.extract(path)
        convert.assert_not_called()
        self.assertTrue(any('회계과' in u['text'] for u in result['units']))

    def test_hwpx_sample_reads_through_the_converter(self):
        result = project_text.extract(SAMPLES / '07_서식_국내출장여비정산서_가상.hwpx')
        self.assertEqual(result['status'], 'ready')
        self.assertIn('skdconv', result['detail'])

    def test_a_failing_converter_falls_back_to_the_built_in_reader(self):
        with patch.object(document_convert, '_skdconv_blocks', side_effect=document_convert.ConvertError('실패')):
            result = project_text.extract(self.hwpx_table())
        self.assertEqual(result['status'], 'ready')
        self.assertNotIn('skdconv', result['detail'])
        self.assertTrue(any('회계과' in u['text'] for u in result['units']))

    def test_unreadable_hwp_reports_an_error_instead_of_empty_text(self):
        path = self.root / '손상.hwp'; path.write_bytes(b'not a hancom file')
        result = project_text.extract(path)
        self.assertEqual(result['status'], 'error')
        self.assertIn('HWP', result['detail'])

    def test_archive_safety_checks_run_before_any_converter(self):
        path = self.hwpx_table()
        with patch.object(project_text, 'MAX_ARCHIVE_BYTES', 10), patch.object(document_convert, 'convert') as convert:
            result = project_text.extract(path)
        convert.assert_not_called()
        self.assertEqual(result['status'], 'partial')

    @unittest.skipUnless(document_convert.kordoc_cli(), 'kordoc is not installed here (tools/install_kordoc.py)')
    def test_pdf_reads_through_kordoc_with_page_locations(self):
        import os
        # kordoc runs from its own folder, so a relative path must still reach the file.
        relative = Path(os.path.relpath(SAMPLES / '02_공통_물품구매지침_가상.pdf'))
        result = project_text.extract(relative)
        self.assertIn('kordoc', result['detail'])
        self.assertTrue(result['units'][0]['loc'].startswith('1쪽'))
        self.assertTrue(any('14일 이내' in u['text'] for u in result['units']))

    def test_pdf_without_kordoc_uses_the_built_in_reader(self):
        with patch.object(document_convert, 'kordoc_cli', return_value=None):
            result = project_text.extract(SAMPLES / '02_공통_물품구매지침_가상.pdf')
        self.assertEqual(result['status'], 'ready')
        self.assertNotIn('kordoc', result['detail'])
