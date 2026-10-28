"""Conservative Korean query normalization for project excerpts, without an LLM."""
import re

# Interpret a small, explicit status vocabulary. Do not infer missing replies
# merely from a department name or from absence in another document.
PENDING_REPLY = re.compile(
    r'미\s*회신|'
    r'회신\s*(?:을\s*)?(?:하지\s*(?:않|못)[가-힣]*|안\s*(?:한|했[가-힣]*|하[가-힣]*|된)|전(?:인)?(?![가-힣])|대기|없[가-힣]*)'
)
STOP = {
    '자료', '내용', '파일', '알려줘', '찾아줘', '주세요', '무엇', '어떻게',
    '확인', '보고서', '초안', '작성', '요약', '핵심', '비교', '정리', '해줘',
    '일정과', '만들어줘', '이를', '그걸', '언제', '얼마', '누구', '알려',
    '정리해줘', '작성해줘', '어디', '어느', '어떤', '몇', '아직', '지금',
    '현재', '좀', '있을까요', '궁금해요', '부탁드립니다', '간단히', '간략히', '간단하게',
}


def pending_reply(question):
    return bool(PENDING_REPLY.search(question))


def terms(question):
    normalized = PENDING_REPLY.sub(' 미회신 ', question.lower())
    words = re.findall(r'[가-힣A-Za-z0-9]{2,}', normalized)
    result = []
    for word in words:
        word = re.sub(r'(해주세요|알려주세요|인가요|입니까|일까요|있나요|어디죠|해줘|알려줘|찾아줘)$', '', word)
        word = re.sub(r'(으로|에서|에는|은|는|을|를|이|가|의|와|과)$', '', word)
        if len(word) >= 2 and word not in STOP and word not in result:
            result.append(word)
    return result


def reply_anchors(question):
    """Keep concrete topic constraints; 'department' is the requested field."""
    return [word for word in terms(question) if word not in {'미회신', '부서', '곳', '어디'}]


def has_pending_reply(text):
    return bool(PENDING_REPLY.search(text))


def task_plan(question, draft=False):
    """Recognize bounded document tasks; keep subject words as search constraints."""
    compare = bool(re.search(r'비교|차이|다른지|어떻게\s*다른|뭐가\s*다른|달라진|변경점', question))
    summary = bool(re.search(r'요약|간추|핵심|(?:간단|짧게|한눈에).*정리', question))
    writing = bool(re.search(r'초안|(?:보고서|안내문|요청문|문서).*(?:써|작성|만들)', question))
    writing_action = bool(re.search(r'(?:초안|보고서|안내문|요청문|문서).*(?:써\s*(?:줘|주세요)|작성해|작성하|만들어)', question))
    schedule = bool(re.search(r'일정|날짜|일자|마감|기한|할\s*일|다음\s*조치', question)) and bool(
        re.search(r'정리|뽑|찾|목록|할\s*일|일정과|일정.*(?:알려|보여)', question))
    mode = ('draft' if draft or writing_action else 'compare' if compare else 'summary' if summary else
            'draft' if writing else 'schedule' if schedule else 'lookup')
    # A summary request containing dates is still a summary. A collection request
    # using only '정리' and explicit dates/actions is a schedule.
    if mode == 'lookup' and re.search(r'정리해|정리해줘', question):
        mode = 'summary'
    if pending_reply(question) and mode in {'summary', 'schedule'} and not re.search(r'날짜|기한|마감|일정|할\s*일|전체\s*자료', question):
        mode = 'lookup'
    if mode == 'lookup':
        return {'mode': mode, 'topics': [], 'fields': []}
    q = re.sub(r'(?:이|두|여러|모든|전체|선택한|해당|등록한|첨부한|읽은|기존)\s*(?:자료들?|문서들?|파일들?|보고서)(?:의|을|를|에서|로|은|는)?', ' ', question)
    q = re.sub(r'(?:\d+|한|두|세|네)\s*(?:문장|줄|단락)(?:으로|로|만)?', ' ', q)
    q = re.sub(r'(자료|문서|파일|내용)(?:으로|에서|부터|까지|로|만|에)', r'\1', q)
    q = re.sub(r'해야\s*할\s*일(?:만|을|은|이)?', ' ', q)
    q = re.sub(r'요약[가-힣]*|정리[가-힣]*|간추[가-힣]*|알려[가-힣]*|찾아[가-힣]*|뽑아[가-힣]*|만들[가-힣]*|써\s*(?:줘|주세요)|작성[가-힣]*|보여[가-힣]*', ' ', q)
    ignore = {
        '이', '두', '각', '여러', '전체', '모든', '핵심만', '핵심', '간단히', '간단', '짧게',
        '한눈에', '주요', '중요', '정도', '여기', '여기서', '여기에서', '내가', '제가',
        '우리', '내용', '자료들', '바탕', '기반', '보고', '보고서', '준비', '상황', '현황',
        '초안', '안내', '최초', '처음', '변경', '수정', '개정', '서로', '각각', '다른지',
        '다른', '뭐', '뭐가', '차이', '차이점', '비교', '날짜', '날짜랑', '일자', '일정',
        '마감', '기한', '장소', '대상', '해야', '할', '할일', '일', '일만', '다음', '조치',
        '기존', '까지', '간략히', '문장', 'txt', 'pdf', 'xlsx', 'docx', 'md',
    }
    topics = []
    for word in terms(q):
        word = re.sub(r'(자료|문서|파일|내용)$', '', word) if len(word) > 3 else word
        if pending_reply(question) and word == '부서':
            continue
        if word not in ignore and len(word) >= 2:
            topics.append(word)
    fields = [field for field, pattern in (
        ('deadline', r'마감|기한'), ('when', r'날짜|일자|교육일|일시'),
        ('where', r'장소|교육장|어디서'), ('who', r'대상'),
        ('owner', r'담당자'), ('amount', r'금액|예산'),
    ) if re.search(pattern, question)]
    return {'mode': mode, 'topics': list(dict.fromkeys(topics)), 'fields': fields}


def is_draft_request(question):
    return task_plan(question)['mode'] == 'draft'
