import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from docx import Document
from openpyxl import Workbook
from pypdf import PdfWriter

from app import document_convert, project_text


class ProjectTextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_unmapped_glyphs_are_stored_readably(self):
        path = self.root / '지침.txt'
        path.write_text('지방회계법  결제대금 금액×', encoding='utf-8')
        self.assertEqual(project_text.extract(path)['units'][0]['text'], '「지방회계법」 □ 결제대금 금액×[수식·기호: 원문 확인 필요]')

    def test_pdf_extracts_actual_page_21_text(self):
        class Page:
            def __init__(self, number):
                self.number = number

            def extract_text(self):
                return f'page-{self.number}'

        class Reader:
            is_encrypted = False
            pages = [Page(number) for number in range(1, 22)]

        path = self.root / 'long.pdf'
        path.write_bytes(b'%PDF placeholder')
        with patch('pypdf.PdfReader', return_value=Reader()):
            result = project_text.extract(path)
        self.assertEqual(result['status'], 'ready')
        self.assertIn({'loc': 'PDF 21쪽', 'text': 'page-21'}, result['units'])

    def test_xlsx_reads_later_sheets_and_rows(self):
        path = self.root / 'large.xlsx'
        book = Workbook()
        sheet = book.active
        sheet.title = '첫째'
        for row in range(1, 502):
            sheet.cell(row, 1, f'값{row}')
        for number in range(2, 7):
            book.create_sheet(f'시트{number}')
        book['시트6']['C1'] = '마지막 시트'
        book.save(path)
        result = project_text.extract(path)
        self.assertEqual(result['status'], 'ready')
        self.assertTrue(any(unit['loc'] == '첫째!A501:A501' and '값501' in unit['text'] for unit in result['units']))
        self.assertTrue(any(unit['loc'] == '시트6!C1:C1' for unit in result['units']))

    def test_xlsx_formula_without_saved_result_is_partial(self):
        path = self.root / 'formula.xlsx'
        book = Workbook()
        book.active['A1'] = '=1+1'
        book.save(path)
        result = project_text.extract(path)
        self.assertEqual(result['status'], 'partial')
        self.assertIn('수식 계산 결과 미저장', result['detail'])

    def test_unsupported_empty_and_encrypted_pdf(self):
        unsupported = project_text.extract(self.root / 'x.bin')
        self.assertEqual(unsupported['status'], 'unsupported')

        empty = self.root / 'empty.pdf'
        with empty.open('wb') as stream:
            PdfWriter().write(stream)
        self.assertEqual(project_text.extract(empty)['status'], 'partial')

        encrypted = self.root / 'locked.pdf'
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.encrypt('secret')
        with encrypted.open('wb') as stream:
            writer.write(stream)
        result = project_text.extract(encrypted)
        self.assertEqual(result['status'], 'partial')
        self.assertIn('암호화', result['detail'])

    def test_docx_table_and_chunk_preservation(self):
        path = self.root / 'table.docx'
        doc = Document()
        doc.add_paragraph('본문')
        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = '표 안'
        table.cell(0, 1).text = '내용'
        doc.save(path)
        result = project_text.extract(path)
        self.assertTrue(any('표 안' in unit['text'] and '내용' in unit['text'] for unit in result['units']))

        long_path = self.root / 'long.txt'
        content = '가' * (project_text.CHUNK_CHARS + 5)
        long_path.write_text(content, encoding='utf-8')
        chunks = project_text.extract(long_path)
        self.assertEqual(''.join(unit['text'] for unit in chunks['units']), content)
        self.assertEqual(len(chunks['units']), 2)
        self.assertEqual(chunks['units'][0]['loc'], chunks['units'][1]['loc'])

    def test_docx_header_footer_are_extracted_and_linked_parts_deduplicated(self):
        path = self.root / 'header-footer.docx'
        doc = Document()
        doc.add_paragraph('본문')
        doc.sections[0].header.paragraphs[0].text = '기한은 머리말에 있음'
        doc.sections[0].footer.paragraphs[0].text = '문의는 꼬리말에 있음'
        second = doc.add_section()
        second.header.is_linked_to_previous = True
        second.footer.is_linked_to_previous = True
        doc.save(path)
        result = project_text.extract(path)
        self.assertEqual(result['status'], 'ready')
        self.assertTrue(any(unit['loc'] == '머리말 1 1문단' and '기한' in unit['text'] for unit in result['units']))
        self.assertTrue(any(unit['loc'] == '꼬리말 1 1문단' and '문의' in unit['text'] for unit in result['units']))
        self.assertFalse(any(unit['loc'].startswith('머리말 2') or unit['loc'].startswith('꼬리말 2') for unit in result['units']))

    def test_docx_first_page_and_even_page_headers_are_extracted(self):
        path = self.root / 'special-headers.docx'
        doc = Document()
        section = doc.sections[0]
        section.different_first_page_header_footer = True
        section.first_page_header.paragraphs[0].text = '첫 페이지에만 있는 기한'
        section.even_page_header.paragraphs[0].text = '짝수 페이지 보충 내용'
        section.first_page_footer.paragraphs[0].text = '첫 페이지 꼬리말'
        doc.save(path)
        result = project_text.extract(path)
        self.assertEqual(result['status'], 'ready')
        self.assertTrue(any('첫 페이지에만 있는 기한' in unit['text'] for unit in result['units']))
        self.assertTrue(any('짝수 페이지 보충 내용' in unit['text'] for unit in result['units']))
        self.assertTrue(any('첫 페이지 꼬리말' in unit['text'] for unit in result['units']))

    def test_hwpx_typical_archive_path_and_nested_table_text(self):
        path = self.root / 'source.hwpx'
        xml = ('<hp:sec xmlns:hp="urn:test"><hp:p><hp:run><hp:t>문단</hp:t></hp:run></hp:p>'
               '<hp:tbl><hp:tr><hp:tc><hp:p><hp:run><hp:t>표내용</hp:t></hp:run></hp:p>'
               '</hp:tc></hp:tr></hp:tbl></hp:sec>')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('Contents/section0.xml', xml)
        result = project_text.extract(path)
        self.assertEqual(result['status'], 'ready')
        self.assertTrue(any('문단' in unit['text'] for unit in result['units']))
        self.assertTrue(any('표내용' in unit['text'] for unit in result['units']))

    def test_hwpx_preserves_inline_child_tails_and_readable_controls(self):
        path = self.root / 'inline.hwpx'
        xml = ('<hp:sec xmlns:hp="urn:test"><hp:p><hp:run><hp:t>가.<hp:fwSpace/>'
               '공무원교육훈련기관의 예산</hp:t></hp:run></hp:p>'
               '<hp:p><hp:run><hp:t>에서<hp:lineBreak/>지급한다.</hp:t></hp:run></hp:p>'
               '<hp:p><hp:run><hp:t>바깥<hp:p><hp:run><hp:t>안쪽</hp:t></hp:run>'
               '</hp:p>끝</hp:t></hp:run></hp:p></hp:sec>')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('Contents/section0.xml', xml)
        result = project_text.extract(path)
        self.assertEqual(result['status'], 'ready')
        texts = [unit['text'] for unit in result['units']]
        # HWPX now reads through skdconv so table rows stay together. Known differences from
        # the former reader: a forced line break joins without a space, and a paragraph nested
        # inside another is read inline. The text itself is kept.
        self.assertIn('가. 공무원교육훈련기관의 예산', texts)
        self.assertIn('에서지급한다.', texts)
        self.assertTrue(any('바깥' in t and '안쪽' in t and '끝' in t for t in texts))
        # The built-in reader, used when the converter fails, keeps its exact behaviour.
        with patch.object(document_convert, '_skdconv_blocks', side_effect=document_convert.ConvertError('x')):
            by_loc = {unit['loc']: unit['text'] for unit in project_text.extract(path)['units']}
        self.assertEqual(by_loc['1구역 1문단'], '가. 공무원교육훈련기관의 예산')
        self.assertEqual(by_loc['1구역 2문단'], '에서\n지급한다.')
        self.assertEqual(by_loc['1구역 3문단'], '바깥끝')
        self.assertEqual(by_loc['1구역 4문단'], '안쪽')

    def test_archive_limits_and_macro_external_links_for_office_files(self):
        path = self.root / 'malicious.xlsx'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('xl/externalLinks/externalLink1.xml', '<link/>')
        result = project_text.extract(path)
        self.assertEqual(result['status'], 'partial')
        self.assertIn('외부 링크', result['detail'])

        with patch.object(project_text, 'MAX_ARCHIVE_MEMBERS', 1):
            many = self.root / 'many.docx'
            with zipfile.ZipFile(many, 'w') as archive:
                archive.writestr('one', '1')
                archive.writestr('two', '2')
            result = project_text.extract(many)
        self.assertEqual(result['status'], 'partial')
        self.assertIn('구성원 한도', result['detail'])

    def test_resource_bounds_report_partial(self):
        path = self.root / 'large.txt'
        path.write_text('첫째\n둘째\n셋째', encoding='utf-8')
        with patch.object(project_text, 'MAX_UNITS', 1):
            result = project_text.extract(path)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['units']), 1)

        with patch.object(project_text, 'MAX_FILE_BYTES', 0):
            self.assertEqual(project_text.extract(path)['status'], 'partial')


if __name__ == '__main__':
    unittest.main()
