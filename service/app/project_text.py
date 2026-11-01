"""Bounded local text extraction for project-folder Q&A."""
from __future__ import annotations

import csv
import io
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

MAX_FILE_BYTES = 64 * 1024 * 1024
# Uncompressed size and member limits for HWPX/DOCX/XLSX. Government guides in
# HWPX reach ~70MB uncompressed; 20MB stopped them entirely (2026-11-01).
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 4000
MAX_UNITS = 100_000
MAX_TEXT_CHARS = 8_000_000
CHUNK_CHARS = 1800
MAX_PDF_PAGES = 1000
# Bump when extraction changes what units a file yields; files read by an older
# extractor are read again and their old citations are shown as changed.
EXTRACTOR_VERSION = 'structured-20261101'
SUPPORTED = {'.txt', '.md', '.csv', '.pdf', '.xlsx', '.docx', '.hwpx', '.hwp'}


class _Limit(Exception):
    pass


class _Collector:
    def __init__(self):
        self.units = []
        self.chars = 0
        self.partial = False

    def add(self, loc, text):
        if text is None or text == '':
            return
        text = str(text)
        for start in range(0, len(text), CHUNK_CHARS):
            piece = text[start:start + CHUNK_CHARS]
            remaining = MAX_TEXT_CHARS - self.chars
            if len(self.units) >= MAX_UNITS or remaining <= 0:
                self.partial = True
                return
            if len(piece) > remaining:
                piece = piece[:remaining]
                self.partial = True
            self.units.append({'loc': str(loc), 'text': piece})
            self.chars += len(piece)
            if self.partial:
                return
        if len(text) > CHUNK_CHARS:
            # Chunks cite the same source location and preserve exact substrings.
            pass


def _decode(data):
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        return data.decode('cp949')


def _text(path, out):
    # Bounded by MAX_FILE_BYTES before reading.
    text = _decode(path.read_bytes())
    for number, line in enumerate(text.splitlines(), 1):
        out.add(f'{number}행', line)
        if out.partial:
            break


def _csv(path, out):
    raw = path.read_bytes()
    reader = csv.reader(io.StringIO(_decode(raw)))
    for number, row in enumerate(reader, 1):
        out.add(f'{number}행', ', '.join(row))
        if out.partial:
            break


def _archive(path):
    archive = zipfile.ZipFile(path)
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_MEMBERS:
        archive.close()
        raise _Limit('압축 파일 구성원 한도 초과')
    if sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES:
        archive.close()
        raise _Limit('압축 해제 크기 한도 초과')
    names = [i.filename.casefold() for i in infos]
    if any(i.flag_bits & 1 for i in infos):
        archive.close()
        raise _Limit('암호화된 압축 파일')
    if any('vbaproject' in name or 'externallinks/' in name for name in names):
        archive.close()
        raise _Limit('매크로 또는 외부 링크가 포함된 문서')
    return archive, infos


def _pdf(path, out):
    from pypdf import PdfReader
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        out.partial = True
        out.detail = '암호화된 PDF · 본문을 읽지 못함'
        return
    if len(reader.pages) > MAX_PDF_PAGES:
        out.partial = True
        out.detail = f'PDF 페이지 {MAX_PDF_PAGES}쪽 한도 · 이후 페이지 미확인'
    for number, page in enumerate(reader.pages[:MAX_PDF_PAGES], 1):
        try:
            text = page.extract_text() or ''
        except Exception:
            out.partial = True
            text = ''
        if text.strip():
            out.add(f'PDF {number}쪽', text)
        else:
            out.partial = True
            out.detail = '텍스트 없는 페이지 포함 · 이미지 PDF일 수 있음'
        if len(out.units) >= MAX_UNITS or out.chars >= MAX_TEXT_CHARS:
            out.partial = True
            break


def _xlsx(path, out):
    archive, infos = _archive(path)
    missing_formula_result = False
    try:
        for info in infos:
            name = info.filename.casefold()
            if not (name.startswith('xl/worksheets/') and name.endswith('.xml')):
                continue
            with archive.open(info) as stream:
                root = ET.parse(stream).getroot()
            for cell in root.iter():
                if cell.tag.rsplit('}', 1)[-1] != 'c':
                    continue
                formula = next((child for child in cell if child.tag.rsplit('}', 1)[-1] == 'f'), None)
                value = next((child for child in cell if child.tag.rsplit('}', 1)[-1] == 'v'), None)
                if formula is not None and (value is None or not (value.text or '').strip()):
                    missing_formula_result = True
                    break
            if missing_formula_result:
                break
    finally:
        archive.close()
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        for sheet in book.worksheets:
            for row_number, row in enumerate(sheet.iter_rows(), 1):
                cells = [c for c in row if c.value is not None]
                if not cells:
                    continue
                first, last = cells[0].column, cells[-1].column
                from openpyxl.utils import get_column_letter
                values = ' | '.join(f'{get_column_letter(c.column)}={c.value}' for c in cells)
                out.add(f'{sheet.title}!{get_column_letter(first)}{row_number}:{get_column_letter(last)}{row_number}', values)
                if out.partial:
                    return
    finally:
        book.close()
    if missing_formula_result:
        out.partial = True
        out.detail = '수식 계산 결과 미저장 셀 포함 · 수식은 계산하지 않음'


def _docx(path, out):
    archive, infos = _archive(path)
    from docx import Document
    doc = Document(path)
    def read_container(container, label):
        for number, para in enumerate(container.paragraphs, 1):
            out.add(f'{label} {number}문단'.strip(), para.text)
            if out.partial:
                return
        for tnum, table in enumerate(container.tables, 1):
            for rnum, row in enumerate(table.rows, 1):
                out.add(f'{label} 표 {tnum} {rnum}행', ' | '.join(cell.text for cell in row.cells))
                if out.partial:
                    return
    try:
        read_container(doc, '')
        if out.partial:
            return
        seen_parts = set()
        for snum, section in enumerate(doc.sections, 1):
            containers = (
                (f'머리말 {snum}', section.header),
                (f'꼬리말 {snum}', section.footer),
                (f'첫 페이지 머리말 {snum}', section.first_page_header),
                (f'첫 페이지 꼬리말 {snum}', section.first_page_footer),
                (f'짝수 페이지 머리말 {snum}', section.even_page_header),
                (f'짝수 페이지 꼬리말 {snum}', section.even_page_footer),
            )
            for label, container in containers:
                part_key = str(container.part.partname)
                if part_key in seen_parts:
                    continue
                seen_parts.add(part_key)
                read_container(container, label)
                if out.partial:
                    return

        # python-docx does not expose text boxes, notes, or comments as body
        # content. Signal partial whenever those unsupported areas contain text.
        for info in infos:
            name = info.filename.casefold()
            if not name.endswith('.xml'):
                continue
            if name in {'word/document.xml'} or name.startswith(('word/header', 'word/footer')):
                with archive.open(info) as stream:
                    root = ET.parse(stream).getroot()
                for node in root.iter():
                    if node.tag.rsplit('}', 1)[-1] == 'txbxContent' and any(
                            (child.text or '').strip() for child in node.iter()):
                        out.partial = True
                        out.detail = '본문 텍스트 상자 포함 · 일부 영역 미확인'
                        break
            elif name.startswith(('word/footnotes', 'word/endnotes', 'word/comments')):
                with archive.open(info) as stream:
                    root = ET.parse(stream).getroot()
                if any(node.tag.rsplit('}', 1)[-1] == 't' and (node.text or '').strip() for node in root.iter()):
                    out.partial = True
                    out.detail = '각주·미주·댓글 포함 · 일부 영역 미확인'
    finally:
        archive.close()


def _hwpx(path, out):
    archive, infos = _archive(path)
    try:
        sections = sorted((i for i in infos if i.filename.startswith('Contents/section') and i.filename.endswith('.xml')),
                          key=lambda i: i.filename)
        for snum, info in enumerate(sections, 1):
            with archive.open(info) as stream:
                root = ET.parse(stream).getroot()
            pnum = 0
            for para in root.iter():
                if para.tag.rsplit('}', 1)[-1] == 'p':
                    pnum += 1
                    pieces = []

                    def read_text(node, is_root=False):
                        tag = node.tag.rsplit('}', 1)[-1]
                        if not is_root and tag == 'p':
                            return
                        if tag in {'t', 'line'} and node.text:
                            pieces.append(node.text)
                        for child in node:
                            child_tag = child.tag.rsplit('}', 1)[-1]
                            if child_tag == 'fwSpace':
                                pieces.append(' ')
                            elif child_tag == 'tab':
                                pieces.append('\t')
                            elif child_tag == 'lineBreak':
                                pieces.append('\n')
                            else:
                                read_text(child)
                            if child.tail:
                                pieces.append(child.tail)

                    read_text(para, is_root=True)
                    text = ''.join(pieces)
                    out.add(f'{snum}구역 {pnum}문단', text)
                    if out.partial:
                        return
    finally:
        archive.close()
    _hwpx_unread_areas(path, out)


def _hwpx_unread_areas(path, out):
    """Master pages, headers and footers are not read; say so when they hold text."""
    archive, infos = _archive(path)
    try:
        covered = {i.filename for i in infos if i.filename.startswith('Contents/section') and i.filename.endswith('.xml')}
        for info in infos:
            name = info.filename.casefold()
            if (info.filename in covered or not name.endswith('.xml')
                    or not any(token in name for token in ('masterpage', 'header', 'footer'))):
                continue
            with archive.open(info) as stream:
                root = ET.parse(stream).getroot()
            if any(node.tag.rsplit('}', 1)[-1] in {'t', 'line'} and (node.text or '').strip()
                   for node in root.iter()):
                out.partial = True
                out.detail = '마스터·머리말·꼬리말 영역 포함 · 일부 영역 미확인'
    finally:
        archive.close()


def extract(path: Path) -> dict:
    """Extract source text into bounded, citation-locatable units."""
    out = _Collector()
    try:
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED:
            return {'units': [], 'status': 'unsupported', 'detail': '지원하지 않는 파일 형식'}
        if path.stat().st_size > MAX_FILE_BYTES:
            return {'units': [], 'status': 'partial', 'detail': '파일 크기 한도 초과 · 일부 또는 전체 본문 미확인'}
        from . import document_convert
        converter = ''
        if suffix in document_convert.STRUCTURED | {'.pdf'}:
            if suffix == '.hwpx':
                _archive(path)[0].close()  # Same bomb, encryption and macro checks before any converter.
            try:
                converter = document_convert.convert(path, out.add)
            except document_convert.ConvertError as error:
                out = _Collector()
                if suffix == '.hwp':
                    # The registry's own HWP 5 reader is the fallback for old Hancom files.
                    from . import parsers
                    try:
                        for unit in parsers.parse_file(path):
                            out.add(unit['loc'], unit['text'])
                        converter = 'HWP 기본 해석기'
                    except Exception:
                        return {'units': [], 'status': 'error', 'detail': f'HWP 본문을 읽지 못했습니다 · {error}'}
        if converter:
            if suffix == '.hwpx':
                _hwpx_unread_areas(path, out)
        elif suffix in {'.txt', '.md'}:
            _text(path, out)
        elif suffix == '.csv':
            _csv(path, out)
        elif suffix == '.pdf':
            _pdf(path, out)
        elif suffix == '.xlsx':
            _xlsx(path, out)
        elif suffix == '.docx':
            _docx(path, out)
        else:
            _hwpx(path, out)
        detail = getattr(out, 'detail', '')
        status = 'partial' if out.partial else ('ready' if out.units else 'partial')
        if not detail and converter and status == 'ready':
            detail = f'본문 추출 완료 · 표는 행과 열 이름을 함께 보존({converter})'
        if not detail:
            detail = '본문 추출 완료' if status == 'ready' else ('추출 가능한 텍스트가 없습니다' if not out.units else '자원 한도로 본문 일부만 추출했습니다')
        return {'units': out.units, 'status': status, 'detail': detail}
    except _Limit as exc:
        return {'units': out.units, 'status': 'partial', 'detail': f'{exc} · 본문 일부 미확인'}
    except Exception:
        return {'units': out.units, 'status': 'error', 'detail': '파일 본문을 읽지 못했습니다 · 형식·손상·권한을 확인하세요'}
