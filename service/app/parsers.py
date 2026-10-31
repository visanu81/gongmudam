"""문서 파서: hwp, hwpx, pdf, xlsx, docx, txt/md/csv 를 '단위(unit)' 목록으로 바꾼다.

단위 = {"text": 본문, "loc": 사람이 읽는 위치(예: "3쪽", "시트 '일정' 5행", "12번째 문단")}
원본 파일은 읽기 전용으로 열며 절대 수정하지 않는다.
"""
from __future__ import annotations

import csv
import io
import re
import struct
import zipfile
import zlib
import warnings
from pathlib import Path
from xml.etree import ElementTree as ET

SUPPORTED = {".hwp", ".hwpx", ".pdf", ".xlsx", ".xlsm", ".docx", ".txt", ".md", ".csv"}


class ParseError(RuntimeError):
    pass


def parse_file(path: Path) -> list[dict]:
    ext = path.suffix.lower()
    fn = {
        ".hwp": _parse_hwp, ".hwpx": _parse_hwpx, ".pdf": _parse_pdf,
        ".xlsx": _parse_xlsx, ".xlsm": _parse_xlsx, ".docx": _parse_docx,
        ".txt": _parse_text, ".md": _parse_text, ".csv": _parse_csv,
    }.get(ext)
    if fn is None:
        raise ParseError(f"지원하지 않는 형식: {ext}")
    try:
        units = fn(path)
    except (ET.ParseError, csv.Error, struct.error, UnicodeError, zlib.error, KeyError, zipfile.BadZipFile) as e:
        raise ParseError(f"문서 구조 또는 인코딩이 올바르지 않습니다: {e}") from e
    return [u for u in units if u["text"].strip()]


# ---------------------------------------------------------------- 텍스트
def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ParseError("지원 인코딩(UTF-8, CP949, EUC-KR)으로 원문을 읽을 수 없습니다.")


def _parse_text(path: Path) -> list[dict]:
    lines = _read_text(path).splitlines()
    return [{"text": ln.strip(), "loc": f"{i}행"} for i, ln in enumerate(lines, 1) if ln.strip()]


def _parse_csv(path: Path) -> list[dict]:
    reader = csv.reader(io.StringIO(_read_text(path)), strict=True)
    rows, row_numbers = [], []
    while True:
        start = reader.line_num + 1
        try:
            row = next(reader)
        except StopIteration:
            break
        rows.append(row)
        row_numbers.append(start)
    return _rows_to_units(rows, sheet=None, row_numbers=row_numbers)


def _rows_to_units(rows: list[list], sheet: str | None, row_numbers=None) -> list[dict]:
    """첫 행을 머리글로 보고 각 행을 '머리글: 값' 문장으로 만든다."""
    units = []
    rows = [[("" if c is None else str(c).strip()) for c in r] for r in rows]
    header_index = next((i for i, r in enumerate(rows) if any(r)), None)
    if header_index is None:
        return units
    header = rows[header_index]
    prefix = f"시트 '{sheet}' " if sheet else ""
    for idx, r in enumerate(rows[header_index + 1:], header_index + 2):
        if row_numbers is not None:
            idx = row_numbers[idx - 1]
        if any(r[len(header):]):
            raise ParseError(f"{prefix}{idx}행의 값이 머리글 열 수를 초과합니다.")
        parts = []
        for h, v in zip(header, r):
            if v:
                parts.append(f"{h}: {v}" if h else v)
        if parts:
            units.append({"text": " / ".join(parts), "loc": f"{prefix}{idx}행"})
    return units


# ---------------------------------------------------------------- 엑셀
def _parse_xlsx(path: Path) -> list[dict]:
    import openpyxl
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"엑셀을 열 수 없습니다: {e}") from e
    units = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append([_cell(c) for c in row])
        units += _rows_to_units(rows, ws.title)
    wb.close()
    return units


def _cell(v):
    if v is None:
        return ""
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    return str(v)


# ---------------------------------------------------------------- PDF
def _parse_pdf(path: Path) -> list[dict]:
    from pypdf import PdfReader
    try:
        reader = PdfReader(str(path))
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"PDF를 열 수 없습니다: {e}") from e
    units = []
    for pno, page in enumerate(reader.pages, 1):
        plain = page.extract_text() or ""
        layout_failed = False
        try:
            text = page.extract_text(extraction_mode="layout", layout_mode_strip_rotated=False) or ""
        except Exception:  # noqa: BLE001
            layout_failed = True
            # r2 (N5): layout mode raises on some valid pages (e.g. a page without
            # /Contents) and r1 then rejected the whole document. Fall back to the
            # r4 plain extraction for that page only.
            text = plain
        # Two consecutive printed footers on a landscape sheet identify a
        # two-up spread. Preserve its content-stream order rather than merging
        # columns into sentences; defer semantic layout reading to the reviewer.
        spread = re.search(r"(?m)^\s*-\s*(\d+)\s*-\s{3,}-\s*(\d+)\s*-\s*$", text)
        two_up = (float(page.mediabox.width) > float(page.mediabox.height)
                  and spread is not None and int(spread[2]) == int(spread[1]) + 1)
        supplement = []
        if two_up:
            text = plain
        elif not layout_failed:
            # r2: layout mode can drop running headers, side tabs or footers.
            # Re-add the plain-mode lines that carry the missing characters so no
            # letter/digit of the page is lost (duplication is preferred to omission).
            supplement = _layout_missing_lines(text, plain)
        for para in _split_paragraphs(text):
            unit = {"text": para, "loc": f"{pno}쪽"}
            if two_up:
                unit["layout_review"] = f"2면 배치 · 인쇄 {spread[1]}·{spread[2]}쪽 · 원문 확인 필요"
            units.append(unit)
        for line in supplement:
            units.append({"text": line, "loc": f"{pno}쪽", "extraction_note": "layout 추출 누락 보충(일반 추출 줄)"})
    return units


# CR3-26: mathematical operators and ranges carry meaning even when letters match.
_CHARS = re.compile(r"[가-힣0-9A-Za-z<>=+−×÷≤≥≠±%‰/\-]")


def _layout_missing_lines(layout_text: str, plain_text: str) -> list[str]:
    from collections import Counter
    lost = Counter(_CHARS.findall(plain_text)) - Counter(_CHARS.findall(layout_text))
    lines = [ln.strip() for ln in plain_text.splitlines() if ln.strip()]
    chosen = set()
    # First the lines that are mostly missing (headers, side tabs, footers), then any
    # line still needed so that every missing letter/digit is covered.
    for strict in (True, False):
        for i, line in enumerate(lines):
            if not +lost:
                break
            have = Counter(_CHARS.findall(line))
            overlap = sum((have & lost).values())
            if i in chosen or not overlap or (strict and overlap * 2 < sum(have.values())):
                continue
            chosen.add(i)
            lost -= have
    return [lines[i] for i in sorted(chosen)]


def _split_paragraphs(text: str) -> list[str]:
    lines = [ln.strip() for ln in text.splitlines()]
    out, buf = [], []
    for ln in lines:
        if not ln:
            if buf:
                out.append(" ".join(buf))
                buf = []
            continue
        # 번호·기호로 시작하면 새 문단으로 본다
        if buf and re.match(r"^(\((?:[0-9]+|[가-하])\)|[0-9]+[.)]|[가-하][.)]|[□○◦▶\-•※]|제\s*\d+\s*조)", ln):
            out.append(" ".join(buf))
            buf = []
        buf.append(ln)
    if buf:
        out.append(" ".join(buf))
    return out


# ---------------------------------------------------------------- DOCX
def _parse_docx(path: Path) -> list[dict]:
    try:
        z = zipfile.ZipFile(path)
        xml = z.read("word/document.xml")
    except Exception as e:  # noqa: BLE001
        raise ParseError(f"DOCX를 열 수 없습니다: {e}") from e
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ET.fromstring(xml)
    units = []
    for i, p in enumerate(root.iter(ns + "p"), 1):
        t = "".join(x.text or "" for x in p.iter(ns + "t")).strip()
        if t:
            units.append({"text": t, "loc": f"{i}번째 문단"})
    return units


# ---------------------------------------------------------------- HWPX (OWPML, zip+xml)
# OWPML <hp:t> children. 'hypen' is the schema's own spelling of the hyphen control.
# Markers without text (title mark, highlighter start/end) add nothing (r2: r1 inserted a space).
_HWPX_CONTROLS = {'nbSpace': ' ', 'fwSpace': ' ', 'tab': '\t', 'lineBreak': '\n',
                  'hypen': '-', 'hyphen': '-', 'titleMark': '', 'markpenBegin': '', 'markpenEnd': ''}


def _hwpx_text(element):
    out = [element.text or '']
    for child in element:
        name = child.tag.rsplit('}',1)[-1]
        if name in _HWPX_CONTROLS:out.append(_HWPX_CONTROLS[name])
        else:
            # Unknown element: keep its text; an empty one keeps a word boundary (r1 rule).
            warnings.warn(f'HWPX 본문 제어 요소 확인 필요: {name}', RuntimeWarning)
            out.append(_hwpx_text(child) or ' ')
        out.append(child.tail or '')
    return ''.join(out)


def _parse_hwpx(path: Path) -> list[dict]:
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise ParseError("HWPX 파일 구조가 올바르지 않습니다.") from e
    sections = sorted(
        (n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
        key=lambda n: int(re.findall(r"\d+", n)[-1]),
    )
    if not sections:
        raise ParseError("HWPX 본문(section)이 없습니다.")
    units, n = [], 0
    for sec in sections:
        root = ET.fromstring(z.read(sec))
        for p in root.iter():
            if not p.tag.endswith("}p"):
                continue
            # 표 안의 문단은 바깥 문단과 별도로 수집되므로 직속 run 의 글자만 모은다
            texts = []
            for run in p:
                if not run.tag.endswith("}run"):
                    continue
                for t in run:
                    if t.tag.endswith("}t"):
                        texts.append(_hwpx_text(t))
                    elif t.tag.endswith("}equation"):
                        # CR3-27: keep raw Hancom equation source in position; no evaluation.
                        script = next((e.text or '' for e in t.iter() if e.tag.endswith('}script')), '')
                        texts.append('[한컴 수식 원문 · 표시 미검증: ' + script + ']')
            line = "".join(texts).strip()
            if line:
                n += 1
                units.append({"text": line, "loc": f"{n}번째 문단"})
    return units


# ---------------------------------------------------------------- HWP 5.0 (OLE 바이너리)
HWPTAG_PARA_TEXT = 0x10 + 51
_EXT_CTRL = {1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23}
_INLINE_CTRL = {4, 5, 6, 7, 8, 9, 19, 20}


def _parse_hwp(path: Path) -> list[dict]:
    import olefile
    if not olefile.isOleFile(str(path)):
        raise ParseError("HWP 5.0 형식이 아닙니다 (HWP 3.0 이하는 미지원).")
    ole = olefile.OleFileIO(str(path))
    try:
        header = ole.openstream("FileHeader").read()
        flags = struct.unpack("<I", header[36:40])[0]
        compressed, encrypted, distribute = flags & 1, flags & 2, flags & 4
        if encrypted:
            raise ParseError("암호가 걸린 HWP 문서입니다.")
        storage = "ViewText" if distribute else "BodyText"
        if distribute:
            raise ParseError("배포용 HWP 문서는 본문을 읽을 수 없습니다.")
        secs = sorted(
            (e for e in ole.listdir() if e[0] == storage and e[1].startswith("Section")),
            key=lambda e: int(e[1][7:]),
        )
        units, n = [], 0
        for entry in secs:
            data = ole.openstream(entry).read()
            if compressed:
                data = zlib.decompress(data, -15)
            for line in _hwp_records_text(data):
                line = line.strip()
                if line:
                    n += 1
                    units.append({"text": line, "loc": f"{n}번째 문단"})
        return units
    finally:
        ole.close()


def _hwp_records_text(data: bytes):
    pos, size = 0, len(data)
    while pos + 4 <= size:
        hdr = struct.unpack("<I", data[pos:pos + 4])[0]
        pos += 4
        tag, length = hdr & 0x3FF, (hdr >> 20) & 0xFFF
        if length == 0xFFF:
            if pos + 4 > size:
                raise ParseError("HWP 확장 레코드 길이가 잘렸습니다.")
            length = struct.unpack("<I", data[pos:pos + 4])[0]
            pos += 4
        if pos + length > size:
            raise ParseError("HWP 레코드 본문이 잘렸습니다.")
        payload = data[pos:pos + length]
        pos += length
        if tag == HWPTAG_PARA_TEXT:
            yield _hwp_para_text(payload)
    if pos != size:
        raise ParseError("HWP 레코드 머리글이 잘렸습니다.")


def _hwp_para_text(payload: bytes) -> str:
    if len(payload) % 2:
        raise ParseError("HWP 문자 레코드 길이가 올바르지 않습니다.")
    out, i, n = [], 0, len(payload) // 2
    while i < n:
        ch = struct.unpack("<H", payload[i * 2:i * 2 + 2])[0]
        if ch < 32:
            # HWP5 table 6: character-sized hyphen/nonbreaking/fixed-width space.
            # Normalize spacing while preserving the original word boundary.
            if ch in (24, 30, 31):
                out.append('-' if ch == 24 else ' ')
                i += 1
                continue
            if ch in _EXT_CTRL or ch in _INLINE_CTRL:
                if i + 8 > n:
                    raise ParseError("HWP 제어문자 레코드가 잘렸습니다.")
                if ch == 9:  # 탭도 8글자 크기의 인라인 컨트롤
                    out.append("\t")
                i += 8
                continue
            if ch in (10, 13):
                out.append("\n")
            i += 1
            continue
        if 0xD800 <= ch <= 0xDBFF:
            if i + 1 >= n:
                raise ParseError("HWP UTF-16 문자가 손상되었습니다.")
            low = struct.unpack("<H", payload[(i + 1) * 2:(i + 2) * 2])[0]
            if not 0xDC00 <= low <= 0xDFFF:
                raise ParseError("HWP UTF-16 문자가 손상되었습니다.")
            out.append(chr(0x10000 + ((ch - 0xD800) << 10) + low - 0xDC00))
            i += 2
            continue
        if 0xDC00 <= ch <= 0xDFFF:
            raise ParseError("HWP UTF-16 문자가 손상되었습니다.")
        out.append(chr(ch))
        i += 1
    return "".join(out)
