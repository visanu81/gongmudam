"""CR3-26/27 semantic loss repro; synthetic parser inputs, no calculation rules."""
import tempfile,unittest,zipfile
from pathlib import Path
from app import parsers,store

class SemanticSymbols(unittest.TestCase):
    def test_CR3_26_missing_math_operator_is_not_silently_dropped(self):
        for operator in ['≤','≥','≠','−','÷','×','±','%','-']:
            with self.subTest(operator=operator):
                source=f'금액 10 {operator} 2'
                self.assertEqual(parsers._layout_missing_lines('금액 10 2',source),[source])
    def test_CR3_26_whitespace_layout_only_does_not_duplicate(self):
        self.assertEqual(parsers._layout_missing_lines('금액 10 ≤ 2','금액   10 ≤ 2'),[])
    def test_CR3_27_hwpx_equation_script_remains_in_its_paragraph(self):
        xml='''<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p><hp:run><hp:t>금액×</hp:t><hp:equation><hp:script>{6개월} over {12개월}</hp:script></hp:equation><hp:t> 뒤</hp:t></hp:run></hp:p></hs:sec>'''
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'equation.hwpx'
            with zipfile.ZipFile(path,'w') as z:z.writestr('Contents/section0.xml',xml)
            result=parsers.parse_file(path)
        self.assertEqual(len(result),1)
        self.assertIn('금액×',result[0]['text']);self.assertIn('{6개월} over {12개월}',result[0]['text']);self.assertTrue(result[0]['text'].endswith(' 뒤'))
        self.assertIn('수식',result[0]['text']) # Raw Hancom script, explicitly not rendered mathematics.

if __name__=='__main__':unittest.main(verbosity=2)
