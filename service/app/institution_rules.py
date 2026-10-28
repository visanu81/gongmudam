"""Versioned institution-owned text, with explicit publication and soft deletion.

Original files and every saved version are immutable. Publication changes only
the current source pointer, never a bundled law or a previous answer's snapshot.
"""
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import Literal
import difflib
import hashlib
import json
import os
import re
import tempfile
import uuid
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import PlainTextResponse, FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from . import folders, project_text, institution_matching as matching
from .search import BM25

router=APIRouter(prefix='/api/institution-rules',tags=['기관 규정·서식 관리'])
LIBRARY='institution-rules'
KINDS=('기관 규정','기관 지침','서식','업무편람','참고자료')
MAX_TEXT=200_000

def stamp():return datetime.now(timezone.utc).isoformat()
def sha(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()
def flat(text):return ''.join(str(text).split()).casefold()
def assets_root():return folders.DB_PATH.parent/'institution-rule-assets'
def encoded(value):return json.dumps(value,ensure_ascii=False)

class Draft(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=1,max_length=160)
    institution:str=Field(min_length=2,max_length=120)
    kind:Literal['기관 규정','기관 지침','서식','업무편람','참고자료']='기관 지침'
    category:Literal['미분류','예산·회계','복무·휴가','출장·여비','물품·계약','교육·행사','문서·기록','보안·개인정보','기타']='미분류'
    keywords:list[str]=Field(min_length=1,max_length=12)
    text:str=Field(min_length=1,max_length=MAX_TEXT)
    effective_date:date|None=None
    scope_notes:str=Field(default='',max_length=1000)
    change_note:str=Field(default='',max_length=500)
    @field_validator('title','institution','text')
    @classmethod
    def not_blank(cls,value,info):
        if not value.strip():raise ValueError('빈 내용은 저장할 수 없습니다.')
        if info.field_name=='institution' and len(flat(value))<2:raise ValueError('기관명을 확인하세요.')
        if info.field_name in {'title','institution'}:return value.strip()
        return value
    @field_validator('keywords')
    @classmethod
    def keyword_values(cls,value):
        result=list(dict.fromkeys(v.strip() for v in value))
        if any(len(flat(v))<2 or len(v)>60 for v in result):raise ValueError('질문 연결어는 2~60자로 입력하세요.')
        return result

class RevisionDraft(Draft):
    revision:int=Field(ge=1)
    based_on:str|None=None

class Action(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int=Field(ge=1)
    operation:Literal['apply','enable','disable','delete','restore']
    version_id:str|None=None
    reviewed_sha256:str|None=None
    note:str=Field(default='',max_length=500)

class Import(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source_type:Literal['document','knowledge']
    source_id:str
    sha256:str
    institution:str=Field(min_length=2,max_length=120)
    keywords:list[str]=Field(min_length=1,max_length=12)

def initialize():
    with folders.db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS institution_rule_docs(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,payload TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS institution_rule_versions(id TEXT PRIMARY KEY,doc_id TEXT NOT NULL,number INTEGER NOT NULL,payload TEXT NOT NULL,UNIQUE(doc_id,number))')
        c.execute('CREATE TABLE IF NOT EXISTS institution_rule_events(id TEXT PRIMARY KEY,doc_id TEXT NOT NULL,at TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS knowledge_sources(id TEXT PRIMARY KEY,library_id TEXT,file_id TEXT,enabled INTEGER,payload TEXT,UNIQUE(library_id,file_id))')

def writable(request):
    if getattr(request.app.state,'public_demo',False) or os.environ.get('GONGMUDAM_PUBLIC')=='1':
        raise HTTPException(403,'공개 시연에서는 기관 규정을 변경하지 않습니다. 개인용 로컬 앱에서 관리하세요.')
    origin=request.headers.get('origin')
    if origin and urlsplit(origin).netloc!=request.headers.get('host'):
        raise HTTPException(403,'다른 사이트에서 기관 자료를 변경할 수 없습니다.')

def get(c,key,revision=None):
    row=c.execute('SELECT revision,payload FROM institution_rule_docs WHERE id=?',(key,)).fetchone()
    if not row:raise HTTPException(404,'기관 자료가 없습니다.')
    doc=json.loads(row['payload'])|{'revision':row['revision']}
    if revision is not None and doc['revision']!=revision:raise HTTPException(409,'다른 변경이 있습니다. 입력 내용을 보존한 뒤 최신 자료를 다시 여세요.')
    return doc

def versions(c,key):
    return [{'category':'미분류',**json.loads(r[0])} for r in c.execute('SELECT payload FROM institution_rule_versions WHERE doc_id=? ORDER BY number',(key,))]
def version(c,key,vid):
    row=c.execute('SELECT payload FROM institution_rule_versions WHERE doc_id=? AND id=?',(key,vid)).fetchone()
    if not row:raise HTTPException(404,'자료 버전이 없습니다.')
    value=json.loads(row[0])
    if sha(value['text'])!=value['sha256'] or '\n'.join(u['text'] for u in value['units'])!=value['text']:
        raise HTTPException(409,'버전 본문이 변경됐습니다. 보관 원문을 확인하세요.')
    return {'category':'미분류',**value}

def event(c,doc,kind,vid=None,note=''):
    c.execute('INSERT INTO institution_rule_events VALUES(?,?,?,?,?)',(uuid.uuid4().hex,doc['id'],stamp(),kind,encoded(dict(version_id=vid,note=note,revision=doc['revision']))))

def save(c,doc):
    doc['updated_at']=stamp()
    c.execute('UPDATE institution_rule_docs SET revision=?,payload=? WHERE id=?',(doc['revision'],encoded(doc),doc['id']))

def detail(c,doc,full=True):
    values=versions(c,doc['id'])
    active=next((v for v in values if v['id']==doc['active_version_id']),None)
    display=active or values[-1]
    result=doc|{k:display[k] for k in ('title','kind','category','institution','keywords','effective_date','scope_notes')}
    events=[dict(id=r['id'],at=r['at'],kind=r['kind'],**json.loads(r['payload'])) for r in c.execute('SELECT * FROM institution_rule_events WHERE doc_id=? ORDER BY rowid DESC',(doc['id'],))]
    applied={e['version_id'] for e in events if e['kind']=='apply'}
    result.update(source_id='institution:'+doc['id'],deleted=bool(doc['deleted_at']),active_version_number=active['number'] if active else None,pending_count=sum(v['id'] not in applied for v in values),version_count=len(values))
    if full:result.update(versions=values,events=events)
    return result

def make_version(c,doc,body,origin=None,units=None,based_on=None):
    old=versions(c,doc['id'])
    if len(old)>=100:raise HTTPException(422,'자료당 버전이 100개입니다. 별도 자료로 등록하세요.')
    if based_on:version(c,doc['id'],based_on)
    values=body.model_dump(mode='json',exclude={'revision','based_on'})
    new=dict(id=uuid.uuid4().hex,number=(old[-1]['number']+1 if old else 1),created_at=stamp(),based_on=based_on,
             sha256=sha(body.text),origin=origin or {},units=units or [dict(loc='편집 본문',text=body.text)],**values)
    comparable=('title','institution','kind','category','keywords','text','effective_date','scope_notes')
    if old and all(old[-1].get(k)==new.get(k) for k in comparable):raise HTTPException(422,'변경된 내용이 없습니다.')
    c.execute('INSERT INTO institution_rule_versions VALUES(?,?,?,?)',(new['id'],doc['id'],new['number'],encoded(new)))
    return new

def create(body,origin=None,units=None):
    initialize()
    with folders.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('SELECT count(*) FROM institution_rule_docs').fetchone()[0]>=500:raise HTTPException(422,'기관 자료가 500개입니다.')
        doc=dict(id=uuid.uuid4().hex,revision=1,enabled=False,active_version_id=None,deleted_at=None,created_at=stamp(),updated_at=stamp())
        c.execute('INSERT INTO institution_rule_docs VALUES(?,?,?)',(doc['id'],1,encoded(doc)))
        value=make_version(c,doc,body,origin,units)
        event(c,doc,'create',value['id'],body.change_note)
        return detail(c,doc)

def revise(key,body,origin=None,units=None):
    initialize()
    with folders.db() as c:
        c.execute('BEGIN IMMEDIATE');doc=get(c,key,body.revision)
        if doc['deleted_at']:raise HTTPException(409,'삭제 자료는 먼저 복원하세요.')
        value=make_version(c,doc,body,origin,units,body.based_on)
        doc['revision']+=1;save(c,doc);event(c,doc,'draft',value['id'],body.change_note)
        return detail(c,doc)

def sync_source(c,doc):
    if not doc['active_version_id']:return
    value=version(c,doc['id'],doc['active_version_id'])
    source=dict(id='institution:'+doc['id'],library_id=LIBRARY,library_name='기관 적용 자료',file_id=doc['id'],path='',
                title=value['title'],kind=value['kind'],category=value.get('category','미분류'),
                institution=value['institution'],effective_date=value['effective_date'] or '',sha256=value['sha256'],units=value['units'],
                limited=False,reference_kind='institution_rule',managed_rule_id=doc['id'],managed_version_id=value['id'],
                managed_version_number=value['number'],managed_revision=doc['revision'],keywords=value['keywords'],scope_notes=value['scope_notes'],
                deleted=bool(doc['deleted_at']),registered_at=stamp())
    enabled=bool(doc['enabled'] and not doc['deleted_at'])
    c.execute('INSERT INTO knowledge_sources VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled,payload=excluded.payload',
              (source['id'],LIBRARY,doc['id'],int(enabled),encoded(source)))

def is_current(source):
    try:
        with folders.db() as c:
            doc=get(c,source['managed_rule_id']);value=version(c,doc['id'],source['managed_version_id'])
            return not doc['deleted_at'] and doc['active_version_id']==value['id'] and value['sha256']==source['sha256'] and value['units']==source['units']
    except (HTTPException,KeyError,sqlite_error):return False

def source_view(source):
    """Use immutable version metadata, including the original registered kind.

    Older source pointers flattened forms into guidance. Read them correctly
    without rewriting users' stored documents or historical versions.
    """
    if source.get('reference_kind')!='institution_rule':return source
    try:
        with folders.db() as c:
            value=version(c,source['managed_rule_id'],source['managed_version_id'])
        fields=('title','kind','category','institution','keywords','effective_date','scope_notes')
        return source|{k:value[k] for k in fields}
    except (HTTPException,KeyError,sqlite_error):return source

# sqlite errors are kept local so a damaged managed snapshot cannot hide all
# other registered sources.
import sqlite3
sqlite_error=sqlite3.Error

@router.get('')
def list_rules(request:Request,include_deleted:bool=False):
    initialize()
    with folders.db() as c:
        docs=[get(c,r[0]) for r in c.execute('SELECT id FROM institution_rule_docs ORDER BY rowid DESC').fetchall()]
        return dict(items=[detail(c,d,False) for d in docs if include_deleted or not d['deleted_at']],
                    categories=list(matching.CATEGORIES),public_read_only=bool(getattr(request.app.state,'public_demo',False) or os.environ.get('GONGMUDAM_PUBLIC')=='1'),
                    notice='초안은 답변에 쓰지 않습니다. 비교 후 적용한 기관 자료만 사용하며 공통 법령을 대체하지 않습니다.')

@router.get('/imports')
def import_choices():
    from . import store,knowledge
    return dict(items=[dict(source_type='document',id=d['id'],title=d['title'],sha256=d['sha256']) for d in store.list_documents() if d['layer']!='공통']+
                [dict(source_type='knowledge',id=d['id'],title=d['title'],sha256=d['sha256']) for d in knowledge.sources()
                 if not d.get('official') and d.get('reference_kind') not in {'system_manual','institution_rule'} and d['current'] and not d['limited']])

@router.post('/import',status_code=201)
def import_rule(body:Import,request:Request):
    writable(request)
    from . import store,knowledge
    if body.source_type=='document':
        src=store.get_document(body.source_id)
        if not src:raise HTTPException(404,'가져올 문서가 없습니다.')
        if src['layer']=='공통':raise HTTPException(422,'공통 자료는 직접 수정하지 않습니다. 기관 소유 자료를 선택하세요.')
        units=[dict(loc=c['loc'],text=c['text']) for c in src['chunks']]
    else:
        src=next((s for s in knowledge.sources() if s['id']==body.source_id),None)
        if not src:raise HTTPException(404,'가져올 자료가 없습니다.')
        if src.get('official') or src.get('reference_kind') in {'system_manual','institution_rule'}:raise HTTPException(422,'공통 법령·매뉴얼·기관 버전 원문은 이 경로에서 변경하지 않습니다.')
        if not src['current'] or src['limited']:raise HTTPException(409,'전체 최신 본문을 읽은 자료만 가져오세요.')
        units=src['units']
    if src['sha256']!=body.sha256:raise HTTPException(409,'원문이 바뀌었습니다. 목록을 다시 확인하세요.')
    text='\n'.join(u['text'] for u in units)
    draft=Draft(title=src['title'],institution=body.institution,keywords=body.keywords,text=text,change_note='기존 등록 자료에서 기관 초안으로 가져옴')
    return create(draft,dict(source_type=body.source_type,source_id=body.source_id,sha256=body.sha256),units)

@router.post('/upload',status_code=201)
def upload_rule(request:Request,file:UploadFile=File(...),title:str=Form(...),institution:str=Form(...),
                keywords:str=Form(...),kind:str=Form('기관 지침'),category:str=Form('미분류'),effective_date:str=Form(''),scope_notes:str=Form(''),change_note:str=Form(''),
                rule_id:str=Form(''),revision:int|None=Form(None)):
    writable(request)
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in project_text.SUPPORTED:raise HTTPException(422,'지원 형식은 PDF·DOCX·XLSX·HWPX·TXT·MD·CSV입니다. 이미지 PDF는 OCR이 필요합니다.')
    with tempfile.TemporaryDirectory(prefix='institution-rule-') as temp:
        path=Path(temp)/('upload'+suffix);total=0
        with path.open('wb') as stream:
            while chunk:=file.file.read(1024*1024):
                total+=len(chunk)
                if total>project_text.MAX_FILE_BYTES:raise HTTPException(413,'파일 크기 한도를 초과했습니다.')
                stream.write(chunk)
        read=project_text.extract(path)
        if read['status']!='ready':raise HTTPException(422,'전체 본문을 읽지 못했습니다: '+read['detail'])
        try:
            body=Draft(title=title,institution=institution,kind=kind,category=category,keywords=json.loads(keywords),text='\n'.join(u['text'] for u in read['units']),
                       effective_date=effective_date or None,scope_notes=scope_notes,change_note=change_note)
        except (ValueError,TypeError) as exc:raise HTTPException(422,'기관·연결어·시행일·본문 입력을 확인하세요.') from exc
        raw=path.read_bytes();raw_sha=hashlib.sha256(raw).hexdigest();root=assets_root();root.mkdir(parents=True,exist_ok=True)
        asset=root/(raw_sha+suffix)
        try:
            with asset.open('xb') as out:out.write(raw)
        except FileExistsError:
            if hashlib.sha256(asset.read_bytes()).hexdigest()!=raw_sha:raise HTTPException(409,'보관 파일이 변경됐습니다.')
        origin=dict(filename=Path(file.filename or 'upload').name,asset=asset.name,sha256=raw_sha,bytes=len(raw))
        if rule_id:
            if revision is None:raise HTTPException(422,'자료 revision이 필요합니다.')
            return revise(rule_id,RevisionDraft(**body.model_dump(),revision=revision),origin,read['units'])
        return create(body,origin,read['units'])

@router.post('',status_code=201)
def create_rule(body:Draft,request:Request):writable(request);return create(body)

@router.get('/{key}')
def read_rule(key:str):
    initialize()
    with folders.db() as c:return detail(c,get(c,key))

@router.post('/{key}/versions',status_code=201)
def save_draft(key:str,body:RevisionDraft,request:Request):writable(request);return revise(key,body)

@router.get('/{key}/compare')
def compare(key:str,to_version:str,from_version:str=''):
    initialize()
    with folders.db() as c:
        doc=get(c,key);after=version(c,key,to_version);before=version(c,key,from_version) if from_version else None
        left=(before or {}).get('text','').splitlines();right=after['text'].splitlines()
        changes=[dict(tag=tag,before_lines=left[i:j],after_lines=right[k:l]) for tag,i,j,k,l in difflib.SequenceMatcher(None,left,right,autojunk=True).get_opcodes()] if len(left)+len(right)<8000 else [dict(tag='replace',before_lines=left,after_lines=right)]
        fields=('title','kind','category','institution','keywords','effective_date','scope_notes')
        return dict(document_id=key,revision=doc['revision'],before=before,after=after,changes=changes,
                    metadata_changes=[dict(field=f,before=(before or {}).get(f),after=after[f]) for f in fields if (before or {}).get(f)!=after[f]])

@router.patch('/{key}')
def action(key:str,body:Action,request:Request):
    writable(request);initialize()
    with folders.db() as c:
        c.execute('BEGIN IMMEDIATE');doc=get(c,key,body.revision);op=body.operation
        if doc['deleted_at'] and op!='restore':raise HTTPException(409,'삭제 자료는 먼저 복원하세요.')
        if op=='apply':
            value=version(c,key,body.version_id)
            if value['sha256']!=body.reviewed_sha256:raise HTTPException(409,'비교한 버전과 다릅니다. 변경 내용을 다시 확인하세요.')
            today=datetime.now(timezone(timedelta(hours=9))).date().isoformat()
            if value['effective_date'] and value['effective_date']>today:raise HTTPException(422,'시행일 이전입니다. 초안으로 보관하고 시행일 이후 적용하세요.')
            doc.update(active_version_id=value['id'],enabled=True)
        elif op=='enable':
            if not doc['active_version_id']:raise HTTPException(422,'비교 후 적용할 버전을 먼저 선택하세요.')
            version(c,key,doc['active_version_id']);doc['enabled']=True
        elif op=='disable':doc['enabled']=False
        elif op=='delete':doc.update(deleted_at=stamp(),enabled=False)
        elif op=='restore':
            if not doc['deleted_at']:raise HTTPException(422,'삭제된 자료가 아닙니다.')
            doc.update(deleted_at=None,enabled=False)
        doc['revision']+=1;save(c,doc);sync_source(c,doc);event(c,doc,op,doc['active_version_id'],body.note)
        return detail(c,doc)

@router.get('/{key}/versions/{vid}/original')
def original(key:str,vid:str):
    initialize()
    with folders.db() as c:
        doc=get(c,key);value=version(c,key,vid)
        state='현재 적용본' if doc['active_version_id']==vid and doc['enabled'] and not doc['deleted_at'] else '과거·미적용·삭제 보관본'
        return PlainTextResponse(value['text'],headers={'Cache-Control':'no-store','X-Rule-Version':str(value['number']),'X-Rule-State':'current' if state=='현재 적용본' else 'archived'})

@router.get('/{key}/versions/{vid}/file')
def original_file(key:str,vid:str):
    initialize()
    with folders.db() as c:
        get(c,key);value=version(c,key,vid);origin=value.get('origin',{})
    name=origin.get('asset','')
    if not name or Path(name).name!=name:raise HTTPException(404,'이 버전에는 원본 파일 사본이 없습니다.')
    path=assets_root()/name
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=origin['sha256']:raise HTTPException(409,'원본 파일 사본을 확인하세요.')
    return FileResponse(path,filename=origin['filename'],headers={'Cache-Control':'no-store'})

def hint(query):
    initialize()
    with folders.db() as c:
        for (payload,) in c.execute("SELECT payload FROM knowledge_sources WHERE library_id=? AND enabled=1",(LIBRARY,)):
            source=json.loads(payload)
            if matching.relevant(query,source):return True
    return False

def organizations():
    initialize()
    with folders.db() as c:
        return list({json.loads(row[0])['institution'] for row in c.execute('SELECT payload FROM knowledge_sources WHERE library_id=? AND enabled=1',(LIBRARY,))})

def query_dates(query):
    years={int(y) for y in re.findall(r'(20\d{2})\s*년',query)}
    dates=[date(int(y),int(m),int(d)) for y,m,d in re.findall(r'(20\d{2})[-./년]\s*(\d{1,2})[-./월]\s*(\d{1,2})',query)]
    return years,dates

def applicable(source,today,years,dates):
    effective=source.get('effective_date')
    if not source['current'] or effective and effective>today.isoformat():return False
    if any(y>today.year or effective and y<int(effective[:4]) for y in years):return False
    if any(day>today or effective and day.isoformat()<effective for day in dates):return False
    return not ((years or dates) and not effective)

def related_forms(query,evidence,today,affiliation=None):
    """Link applied forms named by a question, citation or adjacent declaration.

    Searching another document may restrict its answer evidence, but should not
    hide a form that the cited instructions name. Institution and date scope
    still come from the user's question, never from newly appended text.
    """
    from . import knowledge
    try:years,dates=query_dates(query)
    except ValueError:return []
    scoped,_=matching.scoped_sources(query,knowledge.sources(LIBRARY),affiliation)
    references=[query,*[h.get('text','') for h in evidence]]
    # Uploaded TXT/DOCX files have separate extraction units. A declaration
    # immediately beside a cited unit belongs to that same checked version,
    # even when it does not contain the requested deadline search words.
    if not matching.concepts(query,matching.FACETS)&{'budget','amount'}:
        for hit in evidence:
            if hit.get('reference_kind')!='institution_rule':continue
            source=next((s for s in scoped if s.get('managed_rule_id')==hit.get('managed_rule_id') and
                s.get('managed_version_id')==hit.get('managed_version_id') and s.get('sha256')==hit.get('sha256') and
                s.get('reference_kind')=='institution_rule'),None)
            if not source or not source['enabled'] or not applicable(source,today,years,dates):continue
            units=source['units']
            for index,unit in enumerate(units):
                if hit.get('text')!=unit['text'] or hit.get('loc')!=f"{unit['loc']} · v{source['managed_version_number']}":continue
                for neighbor in units[max(0,index-1):index]+units[index+1:index+2]:
                    if re.match(r'\s*(?:필요(?:한)?|관련|첨부)\s*(?:서식|양식)\s*(?:은|는|:|：)',neighbor['text']):
                        references.append(neighbor['text'])
    match_text=flat('\n'.join(references))
    result=[]
    for source in scoped:
        if source.get('reference_kind')!='institution_rule' or source.get('kind')!='서식':continue
        if not source['enabled'] or not applicable(source,today,years,dates):continue
        identifiers=[source['title'],*source.get('keywords',[])]
        if not any(flat(name) in match_text for name in identifiers if name.strip()):continue
        try:
            with folders.db() as c:
                doc=get(c,source['managed_rule_id'])
                value=version(c,doc['id'],source['managed_version_id'])
                if not doc['enabled'] or doc['deleted_at'] or doc['active_version_id']!=value['id']:continue
            base=f"/api/institution-rules/{doc['id']}/versions/{value['id']}"
            result.append(dict(id=doc['id'],name=value['title'],kind='서식',reference_kind='institution_rule',
                version_number=value['number'],source_id=source['id'],sha256=value['sha256'],
                href=base+'/original',manager_href=f"index.html?rule={doc['id']}&rule_version={value['id']}#docs",
                synthetic=bool(re.search(r'모의|합성|예시|가상|시연',value['title']+' '+value['scope_notes']))))
        except (HTTPException,KeyError,sqlite_error):continue
    return result[:5]

def attach(query,found,docs,today,selected_id=None,affiliation=None):
    universe=[d for d in docs if d.get('reference_kind')=='institution_rule' and d['enabled'] and not d.get('deleted')]
    scoped,scope=matching.scoped_sources(query,universe,affiliation)
    matches=[d for d in scoped if (not selected_id or d.get('managed_rule_id')==selected_id) and matching.relevant(query,d)]
    if not matches and scoped:return found
    if not matches and not any(matching.relevant(query,d) for d in universe):return found
    reason='관련 기관 자료를 찾았어요. 내 소속 설정에서 기관을 확인하거나 질문에 기관명을 알려주세요.'
    if scope=='explicit_other':reason='질문에서 지정한 기관의 적용 자료를 확인하지 못했어요. 다른 기관의 자료를 대신 사용하지 않아요.'
    elif scope=='affiliation':reason='내 소속 '+matching.clean_profile(affiliation)['organization']+'에 적용된 관련 기관 자료가 없어요. 해당 기관의 지침·서식을 등록해 주세요.'
    if not matches:
        if found['hits']:return found|{'institution_notice':reason}
        return found|{'requires_basis':True,'unavailable_reason':reason}
    hits=[]
    try:requested_years,date_values=query_dates(query)
    except ValueError:return found|{'requires_basis':True,'unavailable_reason':'질문한 날짜를 확인하세요.'}
    search_query=matching.expand(query)
    matches=[d for d in matches if applicable(d,today,requested_years,date_values)]
    ranking=BM25([d['title']+' '+' '.join(d.get('keywords',[]))+' '+'\n'.join(u['text'] for u in d['units']) for d in matches]).top(search_query,k=3,min_score=0.1)
    for idx,_ in ranking:
        d=matches[idx]
        units=d['units'];rank=BM25([u['text'] for u in units]).top(search_query,k=2,min_score=0.1)
        for i,score in rank:
            u=units[i]
            if not matching.relevant(query,d|{'units':[u]}):continue
            hits.append(dict(id=f"{d['id']}:{d['managed_version_id']}:{i}",source_id=d['id'],title=d['title'],text=u['text'],
                loc=f"{u['loc']} · v{d['managed_version_number']}",sha256=d['sha256'],official=None,limited=False,
                kind=d['kind'],category=d.get('category','미분류'),institution=d['institution'],effective_date=d['effective_date'],library_id=LIBRARY,file_id=d['file_id'],
                reference_kind='institution_rule',managed_rule_id=d['managed_rule_id'],managed_version_id=d['managed_version_id'],
                managed_version_number=d['managed_version_number'],scope_notes=d['scope_notes'],score=score))
    if not hits:
        reason='현재 적용된 기관 자료에서 이 질문·기준일에 맞는 본문을 확인하지 못했습니다. 버전 이력과 시행일을 확인하세요.'
        return found|({'institution_notice':reason} if found['hits'] else {'requires_basis':True,'unavailable_reason':reason})
    organizations=' · '.join(dict.fromkeys(h['institution'] for h in hits))
    note=('내 소속 설정' if scope=='affiliation' else '질문에 지정한 기관')+' 기준: '+organizations+' · 현재 적용된 원문을 찾아 안내해요.'
    return found|{'hits':found['hits']+hits,'requires_basis':True,'institution':True,'institution_notice':note,'institution_scope':dict(organizations=list(dict.fromkeys(h['institution'] for h in hits)),basis=scope)}


def extend_tree(query,reply,base):
    hits=[(i,h) for i,h in enumerate(reply.get('evidence',[]),1) if h.get('reference_kind')=='institution_rule']
    if not hits:return base
    items=[]
    for ref,h in hits:
        lines=[line.strip() for line in h['text'].splitlines() if line.strip()]
        ranked=BM25(lines).top(matching.expand(query),k=2,min_score=0.1) if lines else []
        for i,_ in ranked:
            quote=lines[i][:600]
            items.append(dict(text=quote,ref=ref,support_quotes=[quote]))
    if not items:return base
    branch=dict(label='기관에서 적용한 자료 · 원문 발췌',items=items)
    note='기관 담당자가 적용한 버전의 원문입니다. 공통 법령을 대체하거나 법적 적합성을 자동 승인한 답변은 아닙니다.'
    if base.get('kind') in {'summary','reference'}:
        return base|{'branches':base['branches']+[branch],'note':base.get('note','')+' '+note}
    return dict(kind='reference',title='기관에서 적용한 자료를 확인하세요',branches=[branch],note=note)
