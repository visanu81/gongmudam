"""Personal details that must not be put on the shared demo site.

The shared site shows every upload to every visitor. A real application form
(성명·휴대전화·이메일) was uploaded there on 2026-11-02, so files with these
details are refused before they are stored; the personal app is unaffected.
Office numbers and institutional addresses appear in public notices and pass.
"""
import re

RESIDENT = re.compile(r'(?<!\d)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\s*-\s*[1-8]\d{6}(?!\d)')
MOBILE = re.compile(r'(?<!\d)01[016789][-.\s]?(\d{3,4})[-.\s]?(\d{4})(?!\d)')
PERSONAL_MAIL = re.compile(r'[\w.+-]+@(?:gmail|naver|hanmail|daum|nate|kakao|hotmail|outlook|yahoo|icloud|live)\.(?:com|net|co\.kr)\b', re.I)


def _real_mobile(match):
    # Placeholders such as 010-0000-0000 or 010-1234-5678 fill synthetic and sample forms
    # (the contest notice's sample form uses 010-1234-…); a real number of that shape passes too.
    middle, last = match.groups()
    return (len(set(middle + last)) > 1 and middle not in ('000', '0000', '123', '1234')
            and last not in ('0000', '1234', '5678'))


def found(text):
    """Kinds of personal details in the text, in a fixed order; empty when none."""
    kinds = []
    if RESIDENT.search(text):
        kinds.append('주민등록번호')
    if any(_real_mobile(m) for m in MOBILE.finditer(text)):
        kinds.append('휴대전화 번호')
    if PERSONAL_MAIL.search(text):
        kinds.append('개인 이메일')
    return kinds


def refusal(name, kinds):
    return (f"공유 시연 사이트에는 개인정보({', '.join(kinds)})가 든 파일을 올릴 수 없습니다: {name}. "
            '다른 방문자도 볼 수 있습니다. 실제 업무 파일은 개인용 앱에서 여세요.')
