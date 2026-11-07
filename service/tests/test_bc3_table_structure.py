"""Independent HTML relations: equal cell words can carry different row/column meaning."""
import unittest
from app import regulation_sources as sources

PREFIX='<h1>제1조(목적)</h1><p>이 합성 지침은 표의 구분과 금액, 적용 조건을 함께 확인하는 검수용 원문입니다. 원문의 예외와 조건을 임의로 삭제하거나 법적 지급액을 확정하지 않습니다. 실제 법률 자료가 아닌 독립 구조 경계 시험이며 외부 사이트는 조회하지 않습니다.</p>'

class TableStructureTests(unittest.TestCase):
    def material(self,table):return sources.material((PREFIX+table).encode('utf-8'))

    def test_two_columns_and_two_rows_are_not_the_same_material(self):
        columns='<table><tr><td>구분</td><td>금액</td></tr></table>'
        rows='<table><tr><td>구분</td></tr><tr><td>금액</td></tr></table>'
        self.assertNotEqual(self.material(columns),self.material(rows))

    def test_colspan_change_with_identical_words_is_material(self):
        first='<table><tr><td colspan="1">대상</td><td>기준</td></tr></table>'
        changed='<table><tr><td colspan="2">대상</td><td>기준</td></tr></table>'
        self.assertNotEqual(self.material(first),self.material(changed))

    def test_rowspan_change_with_identical_words_is_material(self):
        first='<table><tr><td rowspan="1">대상</td><td>기준</td></tr><tr><td>예외</td></tr></table>'
        changed=first.replace('rowspan="1"','rowspan="2"')
        self.assertNotEqual(self.material(first),self.material(changed))

    def test_header_and_body_cells_with_identical_words_are_distinct(self):
        header='<table><tr><th>대상</th><td>기준</td></tr></table>'
        body=header.replace('<th>','<td>').replace('</th>','</td>')
        self.assertNotEqual(self.material(header),self.material(body))

    def test_formatting_and_cosmetic_attributes_do_not_trigger_structure_change(self):
        first='<table><tr><td>대상 기준</td><td>금액</td></tr></table>'
        pretty='<table class="pretty">\n<tr style="color:blue"> <td>대상  기준</td>\n<td>금액</td> </tr>\n</table>'
        self.assertEqual(self.material(first),self.material(pretty))

    def test_implicit_unit_spans_and_explicit_unit_spans_are_equivalent(self):
        first='<table><tr><td>대상</td><td>금액</td></tr></table>'
        explicit=first.replace('<td>','<td colspan="1" rowspan="1">')
        self.assertEqual(self.material(first),self.material(explicit))

    def test_structure_markers_cannot_make_empty_body_pass_minimum_text_check(self):
        raw=('<h1>목적</h1><table>'+'<tr><td></td></tr>'*50+'</table>').encode('utf-8')
        with self.assertRaises(ValueError):sources.material(raw)

    def test_source_and_fixture_bytes_are_not_modified(self):
        raw=(PREFIX+'<table><tr><td>보존</td></tr></table>').encode('utf-8')
        before=bytes(raw);sources.material(raw);self.assertEqual(raw,before)

    def test_void_column_html_and_xhtml_notation_are_equivalent(self):
        first='<table><colgroup><col span="2"></colgroup><tr><td>대상</td><td>금액</td></tr></table>'
        self_closed=first.replace('<col span="2">','<col span="2"/>')
        self.assertEqual(self.material(first),self.material(self_closed))

    def test_column_group_span_change_is_material(self):
        first='<table><colgroup span="1"></colgroup><tr><td>대상</td><td>금액</td></tr></table>'
        self.assertNotEqual(self.material(first),self.material(first.replace('span="1"','span="2"')))

if __name__=='__main__':unittest.main()
