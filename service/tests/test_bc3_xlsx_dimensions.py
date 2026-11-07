"""Fixed XML/cell expectations at the existing folder-library/preview boundaries.

Ported from the teammate branch (PC-XLSX-01, V010-05). Their per-unit extraction
records are not ported here, so assertions on that field were left out.
"""
from pathlib import Path
import hashlib
import io
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from unittest.mock import patch
from app import folders, parsers

FIXTURE = Path(__file__).with_name('fixtures') / 'bc3_xlsx_no_dimension.xlsx'
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def row(number, values):
    element = ET.Element(f'{{{NS}}}row', {'r': str(number)})
    for column, value in values:
        cell = ET.SubElement(element, f'{{{NS}}}c', {'r': f'{column}{number}', 't': 'inlineStr'})
        ET.SubElement(ET.SubElement(cell, f'{{{NS}}}is'), f'{{{NS}}}t').text = value
    return element


def workbook_bytes(dimension=None, rows=None):
    """Change declared dimensions/cell XML only; other fixed fixture parts are retained."""
    output = io.BytesIO()
    with zipfile.ZipFile(FIXTURE) as source, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            raw = source.read(item.filename)
            if item.filename == 'xl/worksheets/sheet1.xml':
                sheet = ET.fromstring(raw)
                old = sheet.find(f'{{{NS}}}dimension')
                if old is not None:
                    sheet.remove(old)
                if dimension is not None:
                    sheet.insert(0, ET.Element(f'{{{NS}}}dimension', {'ref': dimension}))
                if rows is not None:
                    sheet.find(f'{{{NS}}}sheetData')[:] = rows
                raw = ET.tostring(sheet, encoding='utf-8', xml_declaration=True)
            target.writestr(item, raw)
    return output.getvalue()


class XlsxDimensionsTests(unittest.TestCase):
    def preview(self, raw):
        return folders.extract(Path('합성.xlsx'), raw)

    def test_missing_dimension_library_keeps_known_body_and_source_hash(self):
        original = FIXTURE.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / '합성 자료'
            source.mkdir()
            path = source / '원문.xlsx'
            path.write_bytes(original)
            with patch.object(folders, 'DB_PATH', root / 'folders.db'):
                folders.initialize()
                created = folders.connect(folders.Connect(name='합성 Excel 검수', roots=[str(source)]))
                restored = folders.detail(created['id'])
            item = restored['files'][0]
            self.assertTrue(item['units'], item['status'])
            self.assertTrue(any('합성 Excel 검수' in unit['text'] for unit in item['units']))
            self.assertEqual(item['sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(path.read_bytes(), original)

    def test_unknown_dimensions_keep_locations_and_partial_warning(self):
        units, status, limited = self.preview(FIXTURE.read_bytes())
        self.assertEqual([unit['loc'] for unit in units], ['합성검수 1행', '합성검수 2행', '합성검수 3행'])
        self.assertTrue(limited)
        self.assertIn('일부', status)
        self.assertTrue(any('합성 Excel 검수 / 1 / 2' == unit['text'] for unit in units))

    def test_known_dimensions_keep_existing_plain_preview_contract(self):
        units, status, limited = self.preview(workbook_bytes('A1:D3'))
        self.assertEqual(status, '본문 확인')
        self.assertFalse(limited)
        self.assertEqual(units[1]['text'], '합성 Excel 검수 / 1 / 2')
        self.assertEqual(units[2]['text'], '보존 대조 / 7 / 8 / 일반값')

    def test_empty_sheets_do_not_invent_body_or_claim_body_read(self):
        for dimension in [None, 'A1']:
            with self.subTest(dimension=dimension):
                units, status, _ = self.preview(workbook_bytes(dimension, []))
                self.assertEqual(units, [])
                self.assertEqual(status, '추출 본문 없음 · 파일명만 확인')

    def test_partially_unspecified_dimensions_remain_bounded_and_partial(self):
        units, _, limited = self.preview(workbook_bytes('A:C'))
        self.assertTrue(any('합성 Excel 검수 / 1 / 2' == unit['text'] for unit in units))
        self.assertTrue(limited)

    def test_sparse_unknown_or_extreme_dimensions_keep_200_row_limit(self):
        rows = [row(1, [('A', '일반 머리글')]), row(200, [('A', '허용 200행')]),
                row(201, [('A', '제외 201행')]), row(1048576, [('A', '제외 마지막행')])]
        for dimension in [None, 'A1:XFD1048576']:
            with self.subTest(dimension=dimension):
                units, _, limited = self.preview(workbook_bytes(dimension, rows))
                text = '\n'.join(unit['text'] for unit in units)
                self.assertIn('허용 200행', text)
                self.assertNotIn('제외', text)
                self.assertLessEqual(len(units), 200)
                self.assertTrue(limited)

    def test_unknown_or_large_columns_keep_30_column_limit(self):
        rows = [row(1, [('A', '일반 머리글')]),
                row(2, [('A', '행 본문'), ('AD', '허용 30열'), ('AE', '제외 31열'), ('XFD', '제외 마지막열')])]
        for dimension in [None, 'A1:XFD2']:
            with self.subTest(dimension=dimension):
                units, _, limited = self.preview(workbook_bytes(dimension, rows))
                text = '\n'.join(unit['text'] for unit in units)
                self.assertIn('허용 30열', text)
                self.assertNotIn('제외', text)
                self.assertTrue(limited)

    def test_long_cell_stays_clipped_and_marked_partial(self):
        units, _, limited = self.preview(workbook_bytes(None, [row(1, [('A', '머리글')]), row(2, [('A', '가' * 1001)])]))
        self.assertEqual(units[1]['text'], '가' * 1000)
        self.assertTrue(limited)

    def test_folder_formula_exclusion_and_document_formula_warning_stay_separate(self):
        units, _, _ = self.preview(FIXTURE.read_bytes())
        self.assertNotIn('=B2+C2', '\n'.join(unit['text'] for unit in units))
        self.assertNotIn('3 ·', '\n'.join(unit['text'] for unit in units))
        parsed = parsers.parse_file(FIXTURE)
        known = next(unit for unit in parsed if unit['loc'] == "시트 '합성검수' 2행")
        self.assertIn('3 · =B2+C2', known['text'])

    def test_corrupt_workbook_stays_present_without_false_body(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = b'PK\x03\x04not-a-workbook'
            source = root / '합성 자료'
            source.mkdir()
            path = source / '손상.xlsx'
            path.write_bytes(raw)
            with patch.object(folders, 'DB_PATH', root / 'folders.db'):
                folders.initialize()
                result = folders.connect(folders.Connect(name='합성 손상 대조', roots=[str(source)]))
            item = result['files'][0]
            self.assertTrue(item['present'])
            self.assertFalse(item['units'])
            self.assertIn('읽기 실패', item['status'])
            self.assertEqual(item['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(path.read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
