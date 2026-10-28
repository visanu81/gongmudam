"""Local feedback and explicitly published, source-bound reviewed answers.

Feedback is a user report, never a new regulation. Published answers match only
reviewed question spellings and the same affiliation/material selection. Source
changes fail closed; original law files and previous answers are never rewritten.
"""
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
import hashlib
import json
import os
import re
import sqlite3
import unicodedata
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from . import folders, institution_matching as matching

router = APIRouter(prefix='/api/answer-reviews', tags=['실무 질문·답변 검토함'])


def stamp(): return datetime.now(timezone.utc).isoformat()
def encode(value): return json.dumps(value, ensure_ascii=False, sort_keys=True)
def digest(value): return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()
def normalized(value): return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value)).strip().rstrip('?!？！.。').casefold()
def db_path(): return folders.DB_PATH.parent / 'answer-reviews.db'


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Context(Strict):
    query: str = Field(min_length=1, max_length=3000)
    affiliation: dict | None = None
    library_id: str | None = Field(default=None, max_length=120)
    institution_rule_id: str | None = Field(default=None, max_length=80)
    today: date

    @field_validator('affiliation')
    @classmethod
    def affiliation_checked(cls, value):
        if value is None: return None
        profile = matching.clean_profile(value)
        if not profile: raise ValueError('소속을 확인한 뒤 다시 질문해 주세요.')
        return profile


class OriginalEvidence(Strict):
    source_id: str = Field(max_length=160)
    sha256: str = Field(max_length=64)
    loc: str = Field(default='', max_length=500)
    quote: str = Field(default='', max_length=8000)


class Feedback(Strict):
    context: Context
    rating: Literal['solved', 'wrong', 'insufficient']
    note: str = Field(default='', max_length=2000)
    original_answer: str = Field(default='', max_length=12000)
    original_evidence: list[OriginalEvidence] = Field(default_factory=list, max_length=30)


class FeedbackEdit(Strict):
    revision: int = Field(ge=1, strict=True)
    rating: Literal['solved', 'wrong', 'insufficient']
    note: str = Field(default='', max_length=2000)


class Reference(Strict):
    source_id: str = Field(min_length=1, max_length=160)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    unit_index: int = Field(ge=0, strict=True)
    quote: str = Field(min_length=1, max_length=20000)


class Draft(Strict):
    revision: int = Field(ge=1, strict=True)
    answer: str = Field(min_length=1, max_length=12000)
    reviewer: str = Field(min_length=2, max_length=80)
    alternate_questions: list[str] = Field(default_factory=list, max_length=8)
    valid_from: date
    valid_until: date | None = None
    change_note: str = Field(default='', max_length=1000)
    evidence: list[Reference] = Field(min_length=1, max_length=6)

    @field_validator('answer', 'reviewer')
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError('답변과 검토자 이름을 입력하세요.')
        return value

    @field_validator('alternate_questions')
    @classmethod
    def aliases_checked(cls, values):
        result = list(dict.fromkeys(v.strip() for v in values))
        if any(not normalized(v) or len(v) > 3000 for v in result):
            raise ValueError('대체 질문은 한 줄에 하나씩 1~3000자로 입력하세요.')
        return result

    @model_validator(mode='after')
    def period_checked(self):
        if self.valid_until and self.valid_until < self.valid_from:
            raise ValueError('적용 종료일은 시작일보다 빠를 수 없습니다.')
        return self


class Action(Strict):
    revision: int = Field(ge=1, strict=True)
    operation: Literal['apply', 'disable', 'resolve', 'reopen']
    version_id: str | None = None
    reviewed_sha256: str | None = None
    confirmed: bool = False


def public(request=None):
    return os.environ.get('GONGMUDAM_PUBLIC') == '1' or bool(request and getattr(request.app.state, 'public_demo', False))


def writable(request):
    if public(request): raise HTTPException(403, '공개 시연에서는 검토 답변을 변경하지 않습니다. 개인용 로컬 앱에서 관리하세요.')
    origin = request.headers.get('origin')
    if origin and urlsplit(origin).netloc != request.headers.get('host'):
        raise HTTPException(403, '다른 사이트에서 검토 기록을 변경할 수 없습니다.')


@contextmanager
def db(write=False):
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=20)
    c.row_factory = sqlite3.Row
    try:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS answer_reviews(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS answer_review_versions(id TEXT PRIMARY KEY,review_id TEXT NOT NULL,number INTEGER NOT NULL,payload TEXT NOT NULL,UNIQUE(review_id,number));
        CREATE TABLE IF NOT EXISTS answer_review_events(id TEXT PRIMARY KEY,review_id TEXT NOT NULL,at TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS answer_review_keys(scope TEXT NOT NULL,question TEXT NOT NULL,review_id TEXT NOT NULL,version_id TEXT NOT NULL,PRIMARY KEY(scope,question));
        ''')
        if write: c.execute('BEGIN IMMEDIATE')
        with c: yield c
    finally:
        c.close()


def get(c, key, revision=None):
    row = c.execute('SELECT * FROM answer_reviews WHERE id=?', (key,)).fetchone()
    if not row: raise HTTPException(404, '검토 기록이 없습니다.')
    value = json.loads(row['payload']) | dict(revision=row['revision'])
    if revision is not None and value['revision'] != revision:
        raise HTTPException(409, '다른 변경이 있습니다. 입력 내용을 보존한 뒤 최신 기록을 다시 여세요.')
    return value


def versions(c, key):
    return [json.loads(r[0]) for r in c.execute('SELECT payload FROM answer_review_versions WHERE review_id=? ORDER BY number', (key,))]


def version(c, key, vid):
    row = c.execute('SELECT payload FROM answer_review_versions WHERE review_id=? AND id=?', (key, vid)).fetchone()
    if not row: raise HTTPException(404, '검토 답변 버전이 없습니다.')
    return json.loads(row[0])


def scope_key(context):
    return digest({k: context.get(k) for k in ('affiliation', 'library_id', 'institution_rule_id')})


def response_context(query, body, today):
    return Context(query=query, affiliation=matching.clean_profile(body.get('affiliation')),
                   library_id=body.get('knowledge_library_id') or None,
                   institution_rule_id=body.get('institution_rule_id') or None, today=today).model_dump(mode='json')


def source_map():
    from . import knowledge
    return {s['id']: s for s in knowledge.sources()}


def source_issue(source, context, universe):
    from . import knowledge_intent, institution_rules
    if not source or not source.get('enabled') or not source.get('current') or source.get('deleted'):
        return '근거가 없거나 사용 제외·변경된 자료입니다.'
    if context.get('library_id') and source['library_id'] != context['library_id']:
        return '질문에서 선택한 자료함 밖의 근거입니다.'
    day = context['today']
    if source.get('effective_date') and source['effective_date'] > day:
        return '질문의 기준일에 아직 시행되지 않은 근거입니다.'
    try: years, dates = institution_rules.query_dates(context['query'])
    except ValueError: return '질문에 적힌 날짜를 다시 확인하세요.'
    if not institution_rules.applicable(source,date.fromisoformat(day),years,dates):
        return '질문한 날짜·연도에 적용 가능한 근거인지 확인하세요.'
    reason = knowledge_intent.scope_reason(context['query'], source | {'effective_date': source.get('effective_date') or ''}, date.fromisoformat(day))
    if reason: return reason
    if source.get('reference_kind') == 'institution_rule':
        managed = [s for s in universe.values() if s.get('reference_kind') == 'institution_rule' and s.get('enabled')]
        scoped, _ = matching.scoped_sources(context['query'], managed, context.get('affiliation'))
        if source['id'] not in {s['id'] for s in scoped}:
            return '확인한 소속·질문 기관에 맞지 않는 기관 자료입니다.'
        selected = context.get('institution_rule_id')
        if selected and source.get('managed_rule_id') != selected:
            return '질문에서 선택한 기관 자료와 다릅니다.'
    return ''


def resolve(references, context, universe=None):
    universe = source_map() if universe is None else universe
    result, seen = [], set()
    for ref in references:
        source = universe.get(ref['source_id'])
        issue = source_issue(source, context, universe)
        if issue: raise HTTPException(422, issue)
        if source['sha256'] != ref['sha256']:
            raise HTTPException(422, '근거 원문이 바뀌었습니다. 현재 원문을 다시 선택해 주세요.')
        index = ref['unit_index']
        if type(index) is not int or index < 0 or index >= len(source['units']):
            raise HTTPException(422, '근거의 쪽수·문단 위치를 다시 선택하세요.')
        unit = source['units'][index]
        if not ref['quote'].strip() or ref['quote'] not in unit['text']:
            raise HTTPException(422, '인용문은 선택한 원문 안의 정확한 문구여야 합니다.')
        key = (source['id'], index, ref['quote'])
        if key in seen: raise HTTPException(422, '같은 근거가 중복 선택됐습니다.')
        seen.add(key)
        fields = ('title', 'kind', 'institution', 'effective_date', 'sha256', 'limited', 'library_id', 'file_id',
                  'official', 'reference_kind', 'managed_rule_id', 'managed_version_id', 'managed_version_number',
                  'page', 'page_count', 'indexed_pages')
        hit = {k: source[k] for k in fields if k in source}
        hit.update(id=f"review:{source['id']}:{index}", source_id=source['id'], unit_index=index,
                   text=unit['text'], quote=ref['quote'], loc=unit.get('loc', '문단'))
        if source.get('reference_kind') == 'system_manual': hit['page'] = unit.get('page')
        if source.get('reference_kind') == 'institution_rule': hit['loc'] += f" · v{source['managed_version_number']}"
        result.append(hit)
    if not result: raise HTTPException(422, '적용할 답변에는 확인한 근거를 하나 이상 연결하세요.')
    return result


def validation(doc, v, universe=None, today=None, query=None):
    context = dict(doc['context'])
    if today: context['today'] = today.isoformat()
    if query is not None: context['query'] = query
    issues = []
    try: evidence = resolve(v['evidence'], context, universe)
    except HTTPException as exc: evidence = []; issues.append(str(exc.detail))
    return evidence, issues


def present(c, doc, universe=None, detail=True):
    value = dict(doc)
    active = version(c, doc['id'], doc['active_version_id']) if doc.get('active_version_id') else None
    issues = validation(doc, active, universe)[1] if active and doc['enabled'] else []
    if doc['enabled'] and issues: state = 'needs_review'
    elif not doc['enabled'] and doc['closed']: state = 'disabled' if active else 'resolved'
    elif doc.get('draft_version_id') and doc['draft_version_id'] != doc.get('active_version_id'): state = 'draft'
    elif doc['enabled']: state = 'applied'
    else: state = 'pending'
    value.update(state=state, validation_issues=issues, reviewer=active['reviewer'] if active else '',
                 applied_version=active['number'] if active else None)
    if detail:
        value['versions'] = versions(c, doc['id'])
        value['history'] = [dict(id=r['id'], at=r['at'], kind=r['kind'], **json.loads(r['payload']))
                            for r in c.execute('SELECT * FROM answer_review_events WHERE review_id=? ORDER BY rowid', (doc['id'],))]
    return value


def save(c, doc, kind, before, detail=None):
    doc['updated_at'] = stamp()
    doc['revision'] += 1
    c.execute('UPDATE answer_reviews SET revision=?,payload=? WHERE id=?', (doc['revision'], encode(doc), doc['id']))
    c.execute('INSERT INTO answer_review_events VALUES(?,?,?,?,?)',
              (uuid.uuid4().hex, doc['id'], stamp(), kind, encode(dict(before=before, after={k:doc.get(k) for k in before}, detail=detail or {}))))


@router.get('')
def listing(request: Request, status: Literal['open', 'applied', 'resolved', 'all']='open', query: str=Query(default='', max_length=300)):
    with db() as c:
        docs = [get(c,r[0]) for r in c.execute('SELECT id FROM answer_reviews ORDER BY rowid DESC LIMIT 500')]
        universe = source_map() if any(d['enabled'] for d in docs) else {}
        items = [present(c,d,universe,detail=False) for d in docs]
    if query: items = [d for d in items if query.casefold() in (d['query']+' '+d['note']+' '+(d['context'].get('affiliation') or {}).get('organization','')).casefold()]
    groups = {'open': {'pending','draft','needs_review'}, 'applied': {'applied'}, 'resolved': {'resolved','disabled'}}
    if status != 'all': items = [d for d in items if d['state'] in groups[status]]
    # List summaries exclude potentially long displayed-answer snapshots.
    items = [{k:d[k] for k in ('id','query','rating','revision','state','created_at','updated_at','reviewer','applied_version','validation_issues')} for d in items]
    return dict(items=items, public_read_only=public(request), notice='개인용 PC의 검토 기록입니다. 검토자 이름은 입력 기록이며 계정 인증이나 기관의 공식 승인을 뜻하지 않습니다.')


@router.post('', status_code=201)
def create(body: Feedback, request: Request):
    writable(request)
    context = body.context.model_dump(mode='json')
    key = uuid.uuid4().hex
    doc = dict(id=key, revision=1, query=context['query'], context=context, rating=body.rating, note=body.note,
               original_answer=body.original_answer, original_evidence=[r.model_dump() for r in body.original_evidence],
               created_at=stamp(), updated_at=stamp(), active_version_id=None, draft_version_id=None, enabled=False, closed=False)
    with db(write=True) as c:
        c.execute('INSERT INTO answer_reviews VALUES(?,?,?)', (key,1,encode(doc)))
        c.execute('INSERT INTO answer_review_events VALUES(?,?,?,?,?)', (uuid.uuid4().hex,key,stamp(),'의견 등록',encode(dict(before={},after={'rating':body.rating,'note':body.note}))))
        return present(c,doc)


@router.get('/sources')
def candidates(review_id: str, query: str=Query(default='', max_length=300)):
    from .search import BM25
    with db() as c: doc = get(c,review_id)
    universe = source_map()
    units = []
    for source in universe.values():
        if source_issue(source,doc['context'],universe): continue
        for index,unit in enumerate(source['units']):
            if not unit['text'].strip(): continue
            units.append(dict(source_id=source['id'],sha256=source['sha256'],unit_index=index,title=source['title'],
                              loc=unit.get('loc','문단'),text=unit['text'][:20000],kind=source['kind'],
                              institution=source.get('institution',''),effective_date=source.get('effective_date','')))
    search = query or doc['query']
    order = BM25([u['title']+' '+u['text'] for u in units]).top(search,k=24,min_score=0.1) if units else []
    return dict(items=[units[i] for i,_ in order])


@router.get('/{key}')
def detail(key: str):
    with db() as c: return present(c,get(c,key))


@router.patch('/{key}/feedback')
def feedback(key: str, body: FeedbackEdit, request: Request):
    writable(request)
    with db(write=True) as c:
        doc = get(c,key,body.revision)
        before = {k:doc[k] for k in ('rating','note')}
        doc.update(rating=body.rating,note=body.note)
        save(c,doc,'의견 수정',before)
        return present(c,doc)


@router.post('/{key}/versions', status_code=201)
def draft(key: str, body: Draft, request: Request):
    writable(request)
    with db(write=True) as c:
        doc = get(c,key,body.revision)
        evidence = resolve([r.model_dump() for r in body.evidence],doc['context'])
        payload = body.model_dump(mode='json',exclude={'revision'}) | dict(evidence=evidence)
        payload.update(id=uuid.uuid4().hex,number=len(versions(c,key))+1,created_at=stamp())
        payload['sha256'] = digest(payload)
        c.execute('INSERT INTO answer_review_versions VALUES(?,?,?,?)',
                  (payload['id'],key,payload['number'],encode(payload)))
        before = {'draft_version_id':doc.get('draft_version_id')}
        doc['draft_version_id'] = payload['id']
        doc['closed'] = False
        save(c,doc,'수정안 저장',before,dict(version_id=payload['id'],reviewer=body.reviewer))
        return present(c,doc)


def question_keys(doc, v):
    from . import institution_rules
    profile = doc['context'].get('affiliation')
    organizations = institution_rules.organizations() if profile else ()
    return {normalized(doc['query']), *(normalized(matching.scope_query(q,profile,organizations)) for q in v['alternate_questions'])}


@router.patch('/{key}')
def action(key: str, body: Action, request: Request):
    writable(request)
    with db(write=True) as c:
        doc = get(c,key,body.revision)
        before = {k:doc.get(k) for k in ('enabled','closed','active_version_id')}
        if body.operation == 'apply':
            v = version(c,key,body.version_id)
            if body.version_id != doc.get('draft_version_id') or body.reviewed_sha256 != v['sha256'] or not body.confirmed:
                raise HTTPException(422, '저장한 최신 수정안과 근거를 확인한 뒤 적용해 주세요.')
            _,issues = validation(doc,v)
            if issues: raise HTTPException(422,' '.join(issues))
            scope = scope_key(doc['context'])
            keys = question_keys(doc,v)
            for question in keys:
                _, issues = validation(doc,v,query=question)
                if issues: raise HTTPException(422, '대체 질문의 적용 범위를 확인하세요. '+' '.join(issues))
                old = c.execute('SELECT review_id FROM answer_review_keys WHERE scope=? AND question=?',(scope,question)).fetchone()
                if old and old[0] != key: raise HTTPException(409,'같은 질문·소속에 적용 중인 다른 검토 답변이 있습니다. 기존 답변을 먼저 확인해 주세요.')
            c.execute('DELETE FROM answer_review_keys WHERE review_id=?',(key,))
            c.executemany('INSERT INTO answer_review_keys VALUES(?,?,?,?)',[(scope,q,key,v['id']) for q in keys])
            doc.update(enabled=True,closed=True,active_version_id=v['id'],applied_at=stamp())
        elif body.operation == 'disable':
            c.execute('DELETE FROM answer_review_keys WHERE review_id=?',(key,))
            doc.update(enabled=False,closed=True)
        elif body.operation == 'resolve': doc['closed'] = True
        elif body.operation == 'reopen':
            c.execute('DELETE FROM answer_review_keys WHERE review_id=?',(key,))
            doc.update(enabled=False,closed=False)
        save(c,doc,{'apply':'수정안 적용','disable':'적용 중지','resolve':'검토 완료','reopen':'다시 검토'}[body.operation],before)
        return present(c,doc)


def lookup(query, body, today, public_mode=False):
    if public_mode or public() or not db_path().is_file(): return None
    context = response_context(query,body,today)
    with db() as c:
        found = c.execute('SELECT review_id,version_id FROM answer_review_keys WHERE scope=? AND question=?',
                          (scope_key(context),normalized(query))).fetchone()
        if not found: return None
        doc = get(c,found['review_id'])
        if not doc['enabled'] or doc['active_version_id'] != found['version_id']: return None
        v = version(c,doc['id'],found['version_id'])
    if today.isoformat() < v['valid_from'] or v.get('valid_until') and today.isoformat() > v['valid_until']: return None
    evidence,issues = validation(doc,v,today=today,query=query)
    if issues: return dict(issues=issues,response=None)
    info = dict(review_id=doc['id'],version_id=v['id'],version_number=v['number'],reviewer=v['reviewer'],
                reviewed_at=doc.get('applied_at',v['created_at']),valid_from=v['valid_from'],valid_until=v.get('valid_until'))
    tree = dict(kind='reviewed',title='담당자가 검토한 답변',branches=[dict(label='검토 답변',items=[dict(text=v['answer'],ref=None)])],
                note='검토자가 작성한 답변입니다. 연결된 원문과 적용 조건을 함께 확인하세요. 법령 원문을 수정하거나 AI를 학습시킨 결과가 아닙니다.')
    reply = dict(evidence=evidence,experiences=[],excluded=[],mode='source_search',model=None,notice='',
                 answer=v['answer'],tree=tree,scope='검토자가 선택한 등록 원문입니다. 인용 일치 검사는 법적 해석이나 기관 승인을 보증하지 않습니다.')
    response = dict(query=query,mode='source_search',model=None,profile=None,summary='담당자가 검토한 답변',
                    answer=v['answer'],notice='',plan=None,alternatives=[],cited=[],related=[],personal_notes=[],knowledge=reply,
                    reviewed_answer=info,review_context=context)
    return dict(issues=[],response=response)
