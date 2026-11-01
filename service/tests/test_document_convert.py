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
