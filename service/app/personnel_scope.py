"""Whose status a question states. Explicit clues only, not legal applicability.

Ported from the teammate branch (BC2/C review): another person's status and a
labeled organization name are not the asker's, and 기간 제한 is not 기간제.
"""
import re

_NATIONAL = ('국가공무원', '국가직', '국가기관', '중앙부처', '국가회계', '국가예산')
_LOCAL = ('지방공무원', '지방직', '지자체', '지방자치단체')


def _own_clauses(body):
    """Drop another actor's declaration and labeled organizations; keep unclear subjects intact."""
    flat_body = re.sub(r'\s+', '', body)
    multiple = any(t in flat_body for t in ('각각', '둘다', '비교', '함께', '모두', '두사람'))
    own = re.search(r'(?<![가-힣])(?:내|제|저의|나의)\s+(?!(?:배우자|아내|남편|동료|자녀|부모))', body)
    if own and not multiple:
        # Remove declarations about another actor, not spouse-related leave events.
        body = re.sub(
            r'(?:배우자|아내|남편|동료|친구)(?:는|은|가|이)\s*.*?'
            r'(?=(?<![가-힣])(?:나는|저는|본인은|제가)\s*|[.!?;\n]|$)',
            '', body)
    without_org = re.sub(
        r'(?:소속기관|기관명|근무기관)\s*[:：]\s*.*?'
        r'(?=(?<![가-힣])(?:나는|저는|본인은|제가)\s*|[.!?;\n]|$)',
        '', body)
    # A labeled organization is the only clue when no status is stated, so it stays then.
    stated = re.sub(r'\s+', '', without_org)
    return without_org if any(t in stated for t in _NATIONAL + _LOCAL + ('공무원', '공무직', '소방관', '교사', '교원')) else body


def subject_query(query):
    """The question with other people's status removed; the 업무환경 line stays as it was."""
    parts = re.split(r'((?:^|\n)\s*업무환경:\s*)', query, maxsplit=1)
    return _own_clauses(parts[0]) + ''.join(parts[1:])


def subject_text(query):
    """Own clauses plus the confirmed 업무환경 status when the question names none."""
    parts = re.split(r'(?:^|\n)\s*업무환경:\s*', query, maxsplit=1)
    body = _own_clauses(parts[0])
    explicit = re.sub(r'\s+', '', body)
    if len(parts) == 2 and not any(t in explicit for t in _NATIONAL + _LOCAL):
        label = parts[1].split('·', 1)[0].strip()
        if label in ('국가공무원', '지방공무원', '공무직'):
            body += '\n' + label
    return body


def analyze(query):
    subject = subject_text(query)
    q = re.sub(r'\s+', '', subject)
    national = any(t in q for t in _NATIONAL)
    local = any(t in q for t in _LOCAL)
    # A child's teacher is not the employee's personnel category.
    employee = re.sub(r'(?:담임)?교사(?:와의|와|상담)', '', q)
    # '기간 제한' is a limit, not the employment noun '기간제'. Match it
    # before flattening so '기간제 한 명' stays intact; '한테' is a particle.
    worker = re.sub(r'\s+', '', re.sub(r'기간\s*제한(?!테)', '', subject))
    roles = [role for role, words in (
        ('fire', ('소방공무원', '소방관')),
        ('teacher', ('교육공무원', '교사', '교원')),
        ('public_worker', ('공무직', '무기계약직', '무기계약', '무기계약근로자', '기간제', '기간제근로자', '기간제직원')),
        ('general', ('일반직',)),
    ) if any(word in (worker if role == 'public_worker' else employee) for word in words)]
    conflict = national and local
    return dict(framework=None if conflict else 'national' if national else 'local' if local else None,
                roles=roles, conflict=conflict)
