"""Regression checks for silent truncation and incorrect source locations."""
import struct
import tempfile
import unittest
from pathlib import Path
from app import parsers


class ParserBoundaryTest(unittest.TestCase):
    def parse(self, suffix, raw):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ('input' + suffix)
            path.write_bytes(raw)
            return parsers.parse_file(path)

    def test_invalid_encoding_is_not_replacement_evidence(self):
        with self.assertRaises(parsers.ParseError):
            self.parse('.txt', b'\xff\xff\x80')

    def test_csv_extra_column_is_not_silently_dropped(self):
        with self.assertRaises(parsers.ParseError):
            self.parse('.csv', b'A,B\n1,2,extra\n')

    def test_csv_unclosed_quote_is_rejected(self):
        with self.assertRaises(parsers.ParseError):
            self.parse('.csv', b'A,B\n1,"unfinished')

    def test_csv_multiline_and_blank_rows_preserve_source_lines(self):
        units = self.parse('.csv', b'A,B\n1,"first\nsecond"\n\n2,last\n')
        self.assertEqual(units[-1], {'text': 'A: 2 / B: last', 'loc': '5행'})

    def test_hwp_surrogate_pair_preserved(self):
        text = '한글😀끝'
        self.assertEqual(parsers._hwp_para_text(text.encode('utf-16le')), text)

    def test_truncated_hwp_record_is_rejected(self):
        data = struct.pack('<I', parsers.HWPTAG_PARA_TEXT | 100 << 20) + b'A\x00'
        with self.assertRaises(parsers.ParseError):
            list(parsers._hwp_records_text(data))

    def test_hwp_truncated_header_and_control_are_rejected(self):
        with self.assertRaises(parsers.ParseError):
            list(parsers._hwp_records_text(b'\x43\x00'))
        with self.assertRaises(parsers.ParseError):
            parsers._hwp_para_text(struct.pack('<H', 9))

    def test_hwp_character_controls_preserve_word_boundaries(self):
        for code, expected in [(24, '제-1항'), (30, '제 1항'), (31, '제 1항')]:
            raw = '제'.encode('utf-16le') + struct.pack('<H', code) + '1항'.encode('utf-16le')
            self.assertEqual(parsers._hwp_para_text(raw), expected)

    def test_folder_decoders_reject_invalid_bytes(self):
        import io
        from app import folders, folder_scan_io
        with self.assertRaises(ValueError):
            folders.extract(Path('bad.txt'), b'\xff\xff\x80')
        with self.assertRaises(ValueError):
            folder_scan_io.text_preview(io.BytesIO(b'\xff\xff\x80'))

    def test_hwp_surrogates_must_be_adjacent_in_original(self):
        raw = b'\x3d\xd8' + struct.pack('<8H', 2, 0, 0, 0, 0, 0, 0, 2) + b'\x00\xde'
        with self.assertRaises(parsers.ParseError):
            parsers._hwp_para_text(raw)

    def test_preview_cp949_after_ascii_prefix(self):
        import io
        from app import folder_scan_io
        stream = io.BytesIO((b'A' * 1000 + b'\n') * 70 + '한글\n'.encode('cp949'))
        units, status, limited = folder_scan_io.text_preview(stream)
        self.assertEqual(units[-1]['text'], '한글')
        self.assertFalse(limited)
        self.assertFalse(stream.closed)
