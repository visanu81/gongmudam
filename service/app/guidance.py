"""Deterministic preparation guidance; source interpretation stays in reviewed trees.

The data map records provenance, not inferred legal applicability. A generated
graph (including Graphify output) is never accepted as an authoritative rule.
"""
import re
from . import knowledge, manual_knowledge, answer_tree, task_intent, store, leave_situations, service_knowledge
from . import institution_matching as institution_match
from . import guidance_materials

TOPICS = (
    ('goods', '물품 구매·검수', r'물품|사무용품|구매|검수|예산\s*목|예산\s*과목'),
    ('education', '교육 희망자 취합', r'교육.*(?:취합|희망자|모집)|희망자.*취합'),
    ('folder', '업무자료 정리', r'폴더|자료함|파일\s*정리'),
    ('leave', '휴가·복무', r'휴가|연가|공가|병가|대체휴무|특가|근무상황|건강검진|건강진단|헌혈'),
    ('overtime', '초과근무', r'초과근무|시간외근무'),
    ('flex', '근무형태', r'유연근무|시차출퇴근'),
    ('duty', '당직', r'당직'),
    ('security', '보안점검', r'보안점검'),
    ('travel', '출장·여비', r'출장|여비'),
)
PREPARATION = {
    'pay': [('scope','적용 신분과 규정 확인','국가(소방·경찰 포함)인지 지방인지에 따라 보수·수당 규정과 지침이 달라요.'),
            ('materials','조문과 실무 기준 확인','위 결론의 조문과 아래 실무 기준(소관 부처 지침)을 함께 확인하고, 금액은 별표 원문으로 확인해요.'),
            ('check','급여 담당과 처리','개인별 지급액·감액은 소속 기관 급여 담당이 인사기록과 함께 확인해요.')],
    'office': [('scope','실제 상황과 담당 확인','어떤 자료를 누가 처리하는지, 적용 기관과 현재 단계를 확인해요.'),
               ('materials','답변과 원문 조건 확인','위 답변의 근거를 펼쳐 적용 조건과 예외를 확인해요. 기관 서식·보존기간·내부 절차가 더 필요한지 점검해요.'),
               ('check','기관 절차와 처리 기록 확인','결정·승인은 권한 있는 담당자가 진행하고, 처리 내용과 다음 할 일을 기록해요.')],
    'travel': [('scope','적용 조건 확인','소속 기관과 실제 출장 일정, 이동수단·숙박·제공받은 항목을 확인해요.'),
               ('materials','증빙·서식 준비','아래 등록 근거에서 필요한 증빙과 기한을 확인하고, 기관에서 쓰는 서식을 준비해요.'),
               ('system','e-사람에서 신청·정산','아래 매뉴얼의 원문과 쪽수를 참고해 기관 시스템에서 처리해요. 화면·권한 차이는 담당자에게 확인해요.'),
               ('check','처리 결과 확인','신청·결재 상태와 보완 요청을 확인해요. 필요하면 아래 보조 도구에서 계산·증빙을 검토할 수 있어요.')],
    'leave': [('scope','사유에 맞는 휴가 확인','위 안내의 휴가 후보와 실제 사유, 소속 기관에 맞는 기준을 함께 확인해요.'),
              ('materials','기간·서류 확인','아래 규정에서 기간과 필요한 증빙을 확인하고 기관 양식을 준비해요.'),
              ('system','e-사람에서 신청','해당 종류의 신청 화면을 아래 매뉴얼에서 확인하고 기관 시스템에서 처리해요.'),
              ('check','승인·반영 확인','승인 여부와 근무상황 반영을 확인해요.')],
    'goods': [('scope','품목·예산·계약 조건 확인','품목, 기관·회계 구분과 적용 연도를 먼저 확인해요.'),
              ('materials','필요 자료 준비','아래 근거와 기관 양식에서 구매·계약·검수에 필요한 자료를 확인해요.'),
              ('system','기관 구매·회계 절차 진행','기관에서 사용하는 구매·회계 시스템과 결재 절차를 확인해요. e-사람 복무 매뉴얼을 구매 근거로 사용하지 않아요.'),
              ('check','누락·처리 결과 확인','납품·검수·지급 중 현재 단계에 필요한 자료와 처리 결과를 확인해요.')],
    'education': [('scope','교육 안내 확인','교육명·일정·대상 부서·회신 마감을 확인해요.'),('materials','회신 서식 준비','기관 서식과 회신 요청문을 준비해요.'),('check','회신·누락 확인','희망자 없음 기록과 미회신·중복을 확인해요. 자료 취합 도구는 필요할 때 열 수 있어요.')],
    'sidejob': [('scope','겸하려는 활동 정리','활동 내용, 보수·수익, 계속성과 근무 시간·담당 직무의 관련성을 정리해요.'),
                ('materials','금지·허가 기준 확인','아래 영리업무 금지·겸직 허가 근거와 소속 기관 기준을 함께 확인해요.'),
                ('approval','소속 기관 사전 허가 확인','허가 대상과 신청 자료를 담당자에게 확인하고, 활동 전에 기관 절차를 진행해요.'),
                ('check','허가 내용 확인','실제 활동이 허가받은 범위와 일치하는지, 활동 변경 시 확인할 사항이 있는지 점검해요.')],
}
MANUAL_QUERY = {'travel':'e-사람 출장 정산 내역 불러오는 방법', 'leave':'e-사람 근무상황 신청 입력 방법',
                'overtime':'e-사람 초과근무 신청 입력 방법','flex':'e-사람 유연근무 신청 입력 방법',
                'duty':'e-사람 당직 조회 방법','security':'e-사람 보안점검 등록 방법'}


def topic(query):
    if leave_situations.family_care(query):return 'leave','휴가·복무'
    office=knowledge.office_knowledge.classify(query)
    if office:return 'office',' · '.join(knowledge.office_knowledge.LABELS[t] for t in office['topics'])
    context=knowledge.relevance.evidence_context(query)
    if context:return context,{'privacy':'개인정보','overtime_meal':'초과근무 급식비','meeting_meal':'회의·간담회 식비'}[context]
    if knowledge.finance_knowledge.topics(query):return 'finance','예산·회계'
    # Pay, allowance and welfare words (명절휴가비 contains 휴가) are not leave questions.
    area=knowledge.service_rules.domain(query)
    if area:return 'pay',{'pay':'보수·호봉','allowance':'수당','welfare':'맞춤형복지'}[area]
    # Office work about a health check is sorted by the work, not by the words 건강검진.
    probe=leave_situations.HEALTH_CHECK.sub('',query) if leave_situations.health_work(query) else query
    matched=next(((key,label) for key,label,pattern in TOPICS if re.search(pattern,probe)),None)
    if matched:return matched
    domain=service_knowledge.domain(query)
    if domain:return domain[0],domain[1]
    if knowledge.institution_rules.hint(query):return 'institution','기관 자료'
    return 'general','서무 업무'


def effective_query(query, context):
    """Only short follow-ups inherit bounded user text; explicit new topics win."""
    if not isinstance(context,str) or len(context)>3000:return query
    if knowledge.finance_knowledge.topics(context) and re.fullmatch(r'\s*(?:국가기관|국가직|국가공무원|중앙부처|지방자치단체|지자체|지방직|지방공무원|시청|군청|구청)(?:입니다|이에요|이야|야|예요)?[.!?\s]*',query):
        # Scope-only follow-ups keep the immediately requested finance purpose.
        return (context[:max(0,2999-len(query))]+'\n'+query).strip()
    if leave_situations.family_care(context) and topic(query)[0]=='general':
        if re.search(r'\d+\s*(?:살|세)|병원|돌봄|돌봐|돌보|자녀|아이|유급|무급|국가직|지방직|국가공무원|지방공무원|사용했|썼|남았',query) and not re.search(r'출장|물품|구매|초과근무|헌혈|본인.*병가|내가.*아파|제가.*아파',query):
            if re.search(r'지방직|지방공무원',query):context=re.sub(r'국가공무원|국가직|국가기관|중앙부처|소방공무원','',context)
            elif re.search(r'국가공무원|국가직',query):context=re.sub(r'지방공무원|지방직','',context)
            return (context[:max(0,2999-len(query))]+'\n'+query).strip()
    # A short, subject-free follow-up such as '그럼 어떤 양식을 써요?' keeps
    # the most recent task. A new subject (병가, 출장, 예산...) always wins.
    if not institution_match.concepts(query,institution_match.SUBJECTS) and institution_match.concepts(query,institution_match.FACETS):
        if re.match(r'^\s*(?:(?:그럼|그러면|그리고|그거|이거)\s*)?(?:어떤|무슨|뭘|무엇|기한|마감|언제|서류|서식|양식|필수)',query):
            lines=context.splitlines()
            anchor=next((line for line in reversed(lines) if topic(line)[0]!='general'),None)
            if anchor:
                # Keep the task, not an earlier question's requested answer.
                # '마감은?' -> '양식은?' -> '뭘 적어요?' must not require a
                # form to contain a deadline just because the first turn did.
                if knowledge.institution_rules.hint(anchor):
                    old_facets=institution_match.concepts(anchor,institution_match.FACETS)
                    new_facets=institution_match.concepts(query,institution_match.FACETS)
                    for facet in old_facets-new_facets-{'budget','form'}:
                        for word in sorted(institution_match.FACETS[facet],key=len,reverse=True):anchor=anchor.replace(word,' ')
                return (anchor[:max(0,2999-len(query))]+'\n'+query).strip()
    if topic(query)[0]!='general':return query
    if re.search(r'^(?:(?:그럼|그러면|그리고|그런데|좋아|그거|이거)\s*)?(?:정산|계산|도와|기한|언제|서류|서식|어디|신청|숙박|차량|개인차량|자가용|\d+박)',query):
        lines=context.splitlines()
        anchor=next((i for i in range(len(lines)-1,-1,-1) if topic(lines[i])[0]!='general'),None)
        if anchor is not None:
            relevant='\n'.join(lines[anchor:])
            return (relevant[:max(0,2999-len(query))]+'\n'+query).strip()
    return query


def _forms(key,query=''):
    if key=='goods' and knowledge.relevance.is_budget_question(query):return []
    words={'travel':r'출장|여비|정산','leave':r'휴가|연가|복무|근무상황','goods':r'구매|물품|검수','education':r'교육|희망자'}.get(key)
    if not words:return []
    result=[]
    for f in store.list_forms():
        if not re.search(words,f['name']):continue
        document=store.get_document(f['doc_id']) if f.get('doc_id') else None
        result.append(dict(id=f['id'],name=f['name'],href=f"/api/documents/{f['doc_id']}/download" if document else 'index.html#forms',
                           synthetic=bool(re.search(r'모의|합성|예시|가상',f['name']+' '+(f.get('doc_title') or '')+' '+(f.get('doc_filename') or ''))),
                           source_id=f.get('doc_id'),sha256=(document or {}).get('sha256')))
    return result[:5]


def source_map(key,steps,evidence,manuals,forms):
    nodes=[dict(id='topic:'+key,label=key,kind='topic')];edges=[]
    for step in steps:
        node='step:'+key+':'+step['id'];nodes.append(dict(id=node,label=step['title'],kind='preparation'))
        edges.append(dict(source='topic:'+key,target=node,relation='준비 순서'))
    for ref in evidence+manuals:
        sid=ref.get('source_id') or ref['id'];node='source:'+sid+(':'+str(ref['page']) if ref.get('page') else '')
        if any(n['id']==node for n in nodes):continue
        nodes.append(dict(id=node,label=ref['title'],kind=ref.get('reference_kind','legal'),sha256=ref.get('sha256'),loc=ref.get('loc'),page=ref.get('page')))
        edges.append(dict(source='topic:'+key,target=node,relation='검색된 자료'))
    for form in forms:
        node='form:'+form['id'];nodes.append(dict(id=node,label=form['name'],kind='form',sha256=form.get('sha256')))
        edges.append(dict(source='topic:'+key,target=node,relation='등록 서식 후보'))
    return dict(nodes=nodes,edges=edges,note='자료의 관련을 보여줍니다. 법적 적용 관계를 자동 판정한 결과는 아닙니다.')


def respond(query,body,today,public_mode=False):
    from . import answer_reviews
    affiliation=institution_match.clean_profile(body.get('affiliation'))
    effective=institution_match.scope_query(effective_query(query,body.get('situation_context','')),affiliation,
        knowledge.institution_rules.organizations() if affiliation else ())
    reviewed=answer_reviews.lookup(effective,body,today,public_mode=public_mode)
    if reviewed and reviewed['response']: return reviewed['response']
    key,label=topic(effective);library=body.get('knowledge_library_id') or None
    manual_plan=manual_knowledge.classify(effective)
    combined=bool(re.search(r'다녀|\d+\s*박|처리\s*순서|규정|근거|함께|방법과|방법도',effective))
    manual_only=manual_plan and manual_plan['kind']=='manual' and not combined
    if manual_only:
        found=dict(hits=[],experiences=[],excluded=[],intent=None)
        reply=dict(evidence=[],experiences=[],excluded=[],mode='source_search',model=None,answer='',notice='',scope='')
    else:
        # A conduct subject covered only by the national guideline still reaches retrieval.
        if (key=='general' or leave_situations.health_work(effective)) and not knowledge.intent.analyze(effective) and not knowledge.service_guidelines.chapter(effective):
            found=dict(hits=[],experiences=[],excluded=[],intent=None,unavailable_reason='이 질문에 직접 답하는 등록 근거를 확인하지 못했어요. 업무 종류와 관련 규정·지침을 알려주세요.')
        else:found=knowledge.retrieve(effective,library,today,**({'institution_rule_id':body['institution_rule_id']} if body.get('institution_rule_id') else {}),**({'affiliation':affiliation} if affiliation else {}))
        reply=knowledge.answer(effective,found,use_ai=body.get('use_ai') is True)
        reply['tree']=answer_tree.build(effective,reply)
        if (reply.get('office_plan') or found.get('institution')) and reply['tree'].get('kind') in {'summary','reference'}:
            reply['answer']='\n\n'.join(i['text']+f" [근거 {i['ref']}]" for b in reply['tree']['branches'] for i in b['items'])
    manual_query=effective if manual_only else MANUAL_QUERY.get(key,'')
    if not manual_only and key=='travel' and re.search(r'신청|출장\s*전|출장계획',effective) and not re.search(r'정산|다녀',effective):manual_query='e-사람 출장 신청 입력 방법'
    if key=='leave' and not manual_only:
        subtype='가족돌봄휴가' if leave_situations.family_care(effective) else next((s for s in ('배우자출산휴가','출산휴가','경조사휴가','특별휴가','병가','공가','대체휴무','연가','포상휴가') if s in effective.replace(' ','')),None)
        if subtype:manual_query=f'e-사람 {subtype} 신청 입력 방법'
    manual=manual_knowledge.respond(manual_query,library) if manual_query else None
    manual_k=(manual or {}).get('knowledge',{})
    manuals=[e for e in manual_k.get('evidence',[]) if e.get('reference_kind')=='system_manual']
    service=service_knowledge.retrieve(effective,library)
    if key=='pay':service=dict(service,evidence=[])
    if service['evidence'] and not reply.get('evidence') and not manual_only and not found.get('finance') and not found.get('office_plan') and reply.get('tree',{}).get('kind')!='clarification':
        reply['tree']=dict(kind='reference',title='인사혁신처 제도 안내·FAQ에서 관련 설명을 찾았어요',
            branches=[dict(label='제도 설명 · 법령 근거와 별도',items=[dict(text=h['title']+' — '+h['quote'][:240]+('…' if len(h['quote'])>240 else ''),ref=None) for h in service['evidence']])],
            note=service['notice'])
        reply['notice']='관련 제도 설명을 찾았습니다. 개인 적용·최신 기준은 법령과 기관 지침을 별도로 확인해야 해요.'
    defaults=[('scope','상황과 적용 기준 확인','기관·업무 종류와 현재 처리 단계를 알려주세요.'),('materials','근거·서식 확인','질문에 직접 답하는 규정·지침·매뉴얼을 등록하면 원문을 확인할 수 있어요.')]
    steps=[dict(id=sid,title=title,detail=detail,kind='preparation') for sid,title,detail in PREPARATION.get(key,defaults)]
    questions=[]
    if key=='travel':
        if not re.search(r'\d{4}[-./년]\s*\d',effective):questions.append('실제 출장 시작일과 종료일을 알려주세요. 2박 3일만으로 날짜를 정하지 않아요.')
        if not re.search(r'국가공무원|지방공무원|소방공무원|국가기관|지방자치단체',effective):
            questions.append('소속 기관과 적용 신분을 확인해 주세요. 국가·지방·기관별 기준이 다를 수 있어요.')
    elif key=='leave':
        if leave_situations.family_care(effective):questions.extend(leave_situations.questions(effective))
        else:
            plan=reply.get('intent') or {};topics=plan.get('topics',[])
            known_scope=knowledge.intent.supplement.national(effective) or knowledge.intent.supplement.local(effective)
            if not known_scope:questions.append('소속 기관과 국가직·지방직 등 적용 신분을 알려주세요.')
            if 'sick' in topics:questions.append('필요한 병가 기간과 올해 사용한 누계, 공무상 질병·부상인지, 준비할 진단서를 확인해 주세요.')
            elif 'public_health' in topics:questions.append('검진 안내에 적힌 법적 근거와 검진일·직접 필요한 시간, 기관에서 확인할 증빙을 확인해 주세요.')
            elif plan.get('status')=='clarify':questions.append('누가 어떤 사유로 쉬어야 하는지 알려주세요. 휴가 이름은 몰라도 괜찮아요.')
            else:questions.append('신청할 날짜·시간과 올해 같은 종류를 사용한 내역, 소속 기관의 증빙·승인 절차를 확인해 주세요.')
    elif key=='pay' and (not reply.get('evidence') or not knowledge.service_rules.status(effective)):
        questions.append('국가공무원(소방·경찰 포함)인지 지방공무원인지와, 확인하려는 보수·수당 항목 이름을 알려주세요.')
    elif key=='goods':questions.append('소속 기관·회계 구분, 적용 연도와 구매 품목을 확인해 주세요.')
    elif key=='sidejob':questions.extend(['소속 기관·적용 신분과 겸하려는 업무 내용을 알려주세요. 국가공무원 기준을 다른 신분에 그대로 적용하지 않아요.',
        '보수·수익 여부, 계속성, 업무 시간과 담당 직무의 관련성을 확인한 뒤 소속 기관의 사전 허가 절차를 확인해요.'])
    elif key=='general':questions.append('어떤 서무업무인지, 지금 무엇을 처리하려는지 알려주세요.')
    if not manual_only and not reply.get('evidence'):
        # Show the already detected clarification rather than repeating a
        # generic topic question. Missing operational facts need actual data.
        clarification=(reply.get('intent') or {}).get('question')
        if clarification:
            questions.insert(0,clarification)
        elif found.get('finance') and '질문을 나누어' in reply.get('notice',''):
            questions.insert(0,'출장 식비와 초과근무 식비 중 어느 것부터 확인할까요? 소속 기관·회계 구분도 알려주세요.')
        material=guidance_materials.needed(effective)
        if material:
            title,detail=material
            reply['notice']=(reply.get('notice','')+' '+detail).strip()
            reply['tree']=dict(kind='unavailable',title=title+'가 필요해요',branches=[
                dict(label='현재 확인한 범위',items=[dict(text=reply['notice'],ref=None)]),
                dict(label='다음 할 일',items=[dict(text='기관 규정·서식 관리에 기준 자료를 등록하거나, 프로젝트에 업무자료를 추가한 뒤 질문해 주세요.',ref=None)])],
                note='기관 내부 자료나 실시간 업무 현황을 확인한 결과가 아닙니다.')
            questions=[detail]
    tree=reply.get('tree') or {};deadlines=[]
    for branch in tree.get('branches',[]):
        if re.search(r'기한|언제|기간',branch['label']):
            deadlines.extend(dict(text=i['text'],ref=i.get('ref')) for i in branch['items'])
    forms=_forms(key,effective)
    managed_forms=knowledge.institution_rules.related_forms(effective,reply.get('evidence',[]),today,affiliation)
    forms=managed_forms+[f for f in forms if f.get('source_id') not in {m['source_id'] for m in managed_forms}]
    guide=dict(topic=key,title=label+' 처리 방법',context=query,questions=questions,steps=steps,deadlines=deadlines,forms=forms,
               service_guide=service,institution_scope=found.get('institution_scope'),practice=reply.get('practice',[]),
               manual=dict(evidence=manuals,scope=manual_k.get('scope',''),notice=manual_k.get('notice','') if manual_query else '이 업무에 맞는 시스템 매뉴얼을 등록하면 사용법을 연결할 수 있어요.'),
               ai_requested=body.get('use_ai') is True,ai_used=reply.get('mode')=='source_llm',
               notice='진행 순서는 실무 준비 제안입니다. 법정 기한·필수 서류·적용 조건은 아래 등록 근거에서 확인하세요.')
    guide['map']=source_map(key,steps,reply.get('evidence',[])+service['evidence'],manuals,forms)
    result=dict(query=effective,mode='structured_guidance',model=reply.get('model'),profile=None,summary='등록 자료로 처리 방법을 함께 확인해요.',
                answer=reply.get('answer',''),notice=reply.get('notice',''),plan=None,alternatives=[],cited=[],related=[],personal_notes=[],knowledge=reply,guidance=guide)
    action=task_intent.action(effective)
    if action:result['task_action']=action
    if reviewed and reviewed['issues']:
        result['review_warning']=reviewed['issues']
        result['notice']='검토 답변의 근거를 다시 확인해야 하므로 기본 안내를 표시합니다. '+' '.join(reviewed['issues'])
    return result
