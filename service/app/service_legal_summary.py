"""Reviewed v70 explanations for the three other requested real-world checks."""
import re
from . import official_sources

SICK='c4edc04864da363cc056b9ed5ccfd1086ac5364b3fcd356e9e8492a3c2489aae'
HEALTH='f459b93473b181b1dc9333903d8ccc97f66930fc7954fabe074a2ff8628d3533'
PROHIBITED='a454f317a1a87afbfb26d58cd040a6d3ac05aa4b1dbb75633deca3f37d02dc44'
PERMISSION='66d99077842d39bb41c3c36211f1977f55ed2e31c2ffdbf18e6185a21c777230'


def build(query,reply):
    topics=(reply.get('intent') or {}).get('topics',[]);evidence=reply.get('evidence',[])
    if len(topics)!=1:return None
    nodes=[]
    def item(sha,text,*anchors):
        for ref,hit in enumerate(evidence,1):
            if hit.get('sha256')!=sha or not official_sources.metadata(sha):continue
            quotes=[]
            for anchor in anchors:
                match=re.search(r'\s*'.join(map(re.escape,anchor)),hit['text'])
                if not match:break
                quotes.append(match[0])
            if len(quotes)==len(anchors):
                nodes.append(dict(text=text,ref=ref,support_quotes=quotes));return
        raise ValueError('Reviewed support missing')
    try:
        if topics==['sick']:
            title='본인이 아파서 근무가 어렵다면 병가를 확인해요'
            item(SICK,'본인의 질병·부상으로 직무를 수행하기 어렵거나, 감염병으로 다른 공무원의 건강에 영향을 미칠 우려가 있다면 병가로 신청하세요.',
                 '질병 또는 부상으로 인하여 직무를 수행할 수 없을 때','감염병')
            item(SICK,'일반 병가와 공무상 병가는 구분해요. 필요한 기간과 올해 사용한 일수를 확인하고 승인 절차를 진행해요.',
                 '연 60일','공무상 질병 또는 부상','연 180일')
            item(SICK,'병가 일수가 연간 6일을 초과하면 의사의 진단서를 첨부해야 해요. 실제 기간·증빙은 소속 담당자에게 확인해요.',
                 '병가 일수가 연간 6일을 초과','의사의 진단서')
        elif topics==['public_health']:
            title='법정 건강검진이라면 ‘공가’로 상신하세요.'
            item(HEALTH,'신청할 복무 종류는 공가입니다. 국민건강보험법에 따른 국가건강검진 등 조문에 정해진 본인 검진을 받을 때 해당해요.',
                 '산업안전보건법','국민건강보험법','건강검진','결핵예방법')
            item(HEALTH,'검진에 직접 필요한 기간 또는 시간만 신청하세요. 하루 전체가 자동으로 인정되는 것은 아니며, 개인이 선택한 종합검진이나 일반 진료는 공가 대상인지 별도 확인해야 해요.',
                 '직접 필요한 기간 또는 시간')
        elif topics==['side_job']:
            title='겸직은 금지 업무인지 먼저 보고 사전 허가를 확인해요'
            item(PROHIBITED,'직무 능률 저하, 공무에 대한 부당한 영향, 국가 이익과의 상반 등 금지 요건에 해당하는 영리 업무인지 먼저 확인해요.',
                 '직무 능률을 떨어뜨리거나','공무에 대하여 부당한 영향을','국가의 이익과 상반')
            item(PERMISSION,'금지되는 영리 업무에 해당하지 않는 다른 직무도 겸하려면 소속 기관장의 사전 허가를 받아야 해요. 허가는 담당 직무 수행에 지장이 없는 경우로 한정돼요.',
                 '제25조의 영리 업무에 해당하지 아니하는 다른 직무','사전 허가','직무 수행에 지장이 없는 경우')
        else:return None
    except ValueError:return None
    branches=([dict(label='신청할 복무',items=[nodes[0]]),
               dict(label='사용 기간·시간',items=[nodes[1]])]
              if topics==['public_health'] else
              [dict(label='국가공무원 기준 · 확인할 내용',items=nodes)])
    return dict(kind='summary',title=title,rule_id='service-v70-'+topics[0],
        reviewed_source_sha256s=sorted({evidence[n['ref']-1]['sha256'] for n in nodes}),
        branches=branches,
        note='국가공무원 복무규정에서 확인한 요약이에요. 실제 소속·신분과 기관 절차를 확인한 뒤 적용하세요.')
