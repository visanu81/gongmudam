"""Uploaded office documents are zip files of XML; entity tricks inside them must not be expanded."""
import tempfile
import unittest
import zipfile
from pathlib import Path

from app import parsers, project_text

BOMB = (b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;">]>'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p></w:body></w:document>')
SECTION = (b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa">]>'
           b'<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"><hp:p xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
           b'<hp:run><hp:t>&a;</hp:t></hp:run></hp:p></hs:sec>')


def archive(folder, name, members):
    path = Path(folder) / name
    with zipfile.ZipFile(path, 'w') as z:
        for member, content in members.items():
            z.writestr(member, content)
    return path


class XmlSafetyTest(unittest.TestCase):
    def test_hwpx_with_entities_is_refused_as_a_broken_document(self):
        with tempfile.TemporaryDirectory() as folder:
            path = archive(folder, 'bomb.hwpx', {'Contents/section0.xml': SECTION})
            with self.assertRaises(parsers.ParseError):
                parsers.parse_file(path)

    def test_project_text_never_returns_expanded_entities(self):
        with tempfile.TemporaryDirectory() as folder:
            path = archive(folder, 'bomb.docx', {'word/document.xml': BOMB})
            result = project_text.extract(path)
            self.assertNotIn('aaaaaaaaaa', str(result))

    def test_ordinary_hwpx_still_reads(self):
        plain = SECTION.replace(b'<!DOCTYPE l [<!ENTITY a "aaaaaaaaaa">]>', b'').replace(b'&a;', '정상 문서'.encode())
        with tempfile.TemporaryDirectory() as folder:
            path = archive(folder, 'plain.hwpx', {'Contents/section0.xml': plain})
            self.assertIn('정상 문서', str(parsers.parse_file(path)))


if __name__ == '__main__':
    unittest.main()
