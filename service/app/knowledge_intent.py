"""Question intent and direct-source coverage. Never infers an allowance or leave entitlement."""
import re
from . import document_context
from . import knowledge_supplement as supplement
from . import leave_situations
from . import personnel_scope


def flat(text):
    return re.sub(r'\s+', '', text)


BUDGET_TERMS = ('예산과목','예산목','예산항목','예산비목','무슨비목','어느비목','어떤비목','통계목','편성목','세목','세출과목','무슨목','어느목','어떤목',
    '어느과목','어떤과목','무슨과목','어떤예산','어느예산','무슨예산','어디예산','사무관리비','일반수용비',
    '일반운영비','자산취득비','자산및물품취득비','201-01','405-01')


# Synonyms concern the question only; cited text is never rewritten.
TOPICS = {
    'travel_rate_domestic': ('국내 여비 금액표', ('숙박비','일비','식비')),
    'travel_rate_foreign': ('국외 여비 금액표', ('국외','숙박비','일비','식비')),
    'travel_group': ('여비 지급 구분표', ('지급구분','제2호','제1호')),
    'travel_fuel_details': ('자가용 연료비의 세부 산정 기준', ('연료비','킬로','계산')),
    'travel_provided_meals': ('식사 제공 시 식비 감액 기준', ('식사제공','급식','식비감액')),
    'occasion_use': ('경조사휴가 사용기한·분할 기준', ('경조사','사용기한','분할')),
    'goods_inspection_deadline': ('납품검사의 완료 기한', ('검사','검수','기한')),
    'travel_settlement': ('출장 정산·증빙', ('정산','영수증','증빙','증거서류')),
    'travel_card': ('출장비 결제 방법', ('카드','현금','결제')),
    'travel_local': ('근무지 내 출장', ('근무지내','관내','같은시군','같은시·군','12킬로','12km')),
    'travel_daily': ('일비 지급', ('일비',)),
    'travel_lodging': ('숙박비 지급', ('숙박비','숙박료','호텔비')),
    'travel_meal': ('식비 지급', ('식비','식대')),
    'travel_extra': ('여비 초과지출·추가 정산', ('추가정산','초과지출','부득이')),
    'travel_private_car': ('자가용 운임·연료비', ('자가용','기름값','주유비','연료비','내차')),
    'travel_taxi': ('출장 택시비', ('택시',)),
    'travel_flight': ('항공 운임·좌석 등급', ('항공권','비즈니스석','비지니스석','일등석')),
    'travel_mileage': ('공무 항공 마일리지', ('마일리지',)),
    'travel_education': ('선발된 교육출장의 세부 기준', ('교육대상자','교육출장')),
    'travel_risk': ('출장 관련 위험수당', ('위험수당',)),
    'travel_general': ('질문한 직군의 여비 기준', ('여비','출장')),
    'travel_foreign_local': ('국외 근무지 내 출장 기준', ('국외','해외')),
    'annual': ('연가 일수·재직기간', ('연가','연차')),
    'annual_use': ('연가 사용·승인 절차', ('반일','반차','승인','허가절차','이월','저축','당겨','연속')),
    'sick': ('병가', ('병가',)),
    'public_health': ('법정 건강검진 공가', ('건강검진','건강진단','국가검진')),
    'public_blood': ('헌혈 공가', ('헌혈',)),
    'public_leave': ('공가 사유', ('공가',)),
    'childcare': ('육아시간', ('육아시간',)),
    'family_care': ('가족돌봄휴가', ('가족돌봄','가족돌봄휴가')),
    'side_job': ('영리업무 금지·겸직 허가', ('겸직','영리업무')),
    'maternity': ('본인 출산휴가', ('출산휴가',)),
    'pregnancy_check': ('임신검진휴가', ('임신검진','임신중검진')),
    'pregnancy_accompany': ('임신검진 동행휴가', ('임신검진동행','검진동행휴가')),
    'maternal_time': ('모성보호시간', ('모성보호시간',)),
    'miscarriage': ('유산·사산휴가', ('유산휴가','사산휴가')),
    'fertility': ('난임치료시술휴가', ('난임',)),
    'women_health': ('여성보건휴가', ('여성보건휴가','생리휴가')),
    'disaster_leave': ('재해구호휴가', ('재해구호휴가',)),
    'mental_leave': ('심리안정휴가', ('심리안정휴가',)),
    'occasion': ('경조사휴가 일수표', ('배우자출산','아내출산','와이프출산','경조사','결혼','사망')),
    'compensatory': ('대체휴무', ('대체휴무','대체휴가')),
    'reward_leave': ('포상휴가', ('포상휴가',)),
    'long_service': ('장기재직휴가', ('장기재직','조례로 정하는')),
    'region_leave': ('지역 고유 특별휴가', ('새내기도약','생일특별','악성민원','조례로 정하는')),
    'election_rest': ('선거사무 후 휴무', ('선거','휴무')),
    **{key:(label,(word,)) for key,label,word in (
        ('allowance_diligence','정근수당','정근수당'),('allowance_family','가족수당','가족수당'),
        ('allowance_overtime','시간외근무수당','시간외근무수당'),('allowance_holiday','명절휴가비','명절휴가비'),
        ('allowance_annual','연가보상비','연가보상비'),('allowance_childcare','육아휴직수당','육아휴직수당'),
        ('allowance_meal','정액급식비','정액급식비'),('allowance_management','관리업무수당','관리업무수당'),
        ('allowance_risk','위험근무수당','위험근무수당'),('allowance_special','특수업무수당','특수업무수당'),
        ('allowance_remote','특수지근무수당','특수지근무수당'),('allowance_senior','대우공무원수당','대우공무원수당'),
        ('allowance_performance','성과상여금','성과상여금'),('allowance_position','직급보조비','직급보조비'),
        ('allowance_proxy','업무대행수당','업무대행수당'),('allowance_night','야간근무수당','야간근무수당'),
        ('allowance_holiday_work','휴일근무수당','휴일근무수당'),('allowance_housing','주택수당','주택수당'),
        ('allowance_tuition','자녀학비보조수당','자녀학비'))},
    'welfare_points': ('맞춤형 복지점수', ('맞춤형복지','복지점수')),
    'welfare_grant': ('복지점수 부여 기준', ('복지점수','부여')),
    'pay_payday': ('보수 지급일', ('지급일','보수')),'pay_initial_step': ('초임호봉 획정', ('초임호봉','경력')),
    'pay_promotion_step': ('승진 시 호봉 획정', ('승진','호봉')),'pay_regular_raise': ('정기승급', ('승급기간','승급')),
    'pay_raise_limit': ('승급 제한', ('승급','제한')),'pay_reassess': ('호봉 재획정', ('재획정','호봉')),
    'pay_deduct_leave': ('휴직기간 봉급 감액', ('휴직','봉급')),'pay_deduct_absence': ('결근기간 봉급 감액', ('결근','봉급')),
    'pay_deduct_discipline': ('징계처분기간 보수 감액', ('징계','감액')),'pay_deduct_suspension': ('직위해제기간 봉급 감액', ('직위해제','봉급')),
    'pay_calc': ('월 중 보수 계산', ('일할','보수계산')),'pay_table': ('봉급표', ('봉급','봉급표')),
    'leave_holiday': ('휴가 중 토요일·공휴일', ('토요일','공휴일')),
    'drinking': ('근무시간 중 음주', ('음주',)),
    'overtime': ('시간외근무·공휴일 근무', ('시간외근무','초과근무')),
    'duty': ('당직·비상근무', ('당직','비상근무','비상소집')),
    'travel_limit': ('휴무일 여행의 제한', ('여행','신고')),
    'shift': ('교대제 근무', ('교대',)),
    'politics': ('정치적 행위', ('정치','선거운동')),
    'dress': ('복장·복제', ('복장','복제','용모')),
    'work_hours': ('근무시간', ('근무시간','출근')),
    'goods_inspection': ('물품 검사·검사조서', ('검수','검사','검사조서')),
    'goods_inspection_limit': ('검사조서 생략 금액', ('검사조서','생략')),
    'goods_payment': ('대금 지급·선금 예외', ('대금','대가','선금','돈부터','돈을먼저','돈먼저')),
    'goods_payment_deadline': ('대가 지급의 구체적인 기한', ('대금','대가')),
    'goods_payment_interest': ('대가 지급 지체이자의 법적 근거', ('지체일수','이자')),
    'goods_quote': ('견적서·견적 비교', ('견적',)),
    'goods_private_contract': ('수의계약 한도·조건', ('수의계약',)),
    'goods_disposal': ('불용·폐기', ('불용','폐기')),
    'goods_defect': ('불량품 반품·교환', ('불량','반품','교환')),
    'account_points': ('업무 구매 인센티브 처리', ('포인트','적립금','마일리지','인센티브')),
    'account_lecturer': ('초빙강사료 집행 공개', ('초빙강사료','초빙강연료')),
    'account_disclosure': ('업무추진비 집행 공개의 별표', ('업무추진비',)),
    'account_incentive_disclosure': ('인센티브 세입·집행내역 공개', ('인센티브','세입조치')),
    'account_retirement_disclosure': ('장기근속·퇴직자 집행내역 공개', ('장기근속','퇴직')),
}
SPECIAL = {'childcare':'육아시간','family_care':'가족돌봄휴가','maternity':'출산휴가',
    'pregnancy_check':'임신검진휴가','pregnancy_accompany':'임신검진동행휴가','maternal_time':'모성보호시간',
    'miscarriage':'유산휴가','fertility':'난임치료시술휴가','women_health':'여성보건휴가',
    'disaster_leave':'재해구호휴가','mental_leave':'심리안정휴가','occasion':'경조사휴가'}
ARTICLE = {
    'travel_settlement': ('공무원 여비 규정','제8조의2('), 'travel_card': ('공무원 여비 규정','제8조의2('),
    'travel_local': ('공무원 여비 규정','제18조('),
    **{t:('공무원 여비 규정','제16조(') for t in ('travel_daily','travel_lodging','travel_meal','travel_extra')},
    'annual': ('지방공무원 복무규정','제7조('), 'sick': ('지방공무원 복무규정','제7조의5('),
    **{t:('지방공무원 복무규정','제7조의6(') for t in ('public_health','public_blood','public_leave')},
    **{t:('지방공무원 복무규정','제7조의7(') for t in SPECIAL},
    'goods_inspection': ('지방자치단체를 당사자로 하는 계약에 관한 법률','제17조('),
    'goods_payment': ('지방자치단체를 당사자로 하는 계약에 관한 법률','제18조('),
    'goods_payment_interest': ('지방자치단체를 당사자로 하는 계약에 관한 법률','제18조('),
    'account_points': ('지방자치단체 회계관리에 관한 훈령','제120조('),
    'account_lecturer': ('지방자치단체 회계관리에 관한 훈령','제121조('),
    'account_incentive_disclosure': ('지방자치단체 회계관리에 관한 훈령','제121조('),
    'account_retirement_disclosure': ('지방자치단체 회계관리에 관한 훈령','제121조('),
}
MISSING = {
    'travel_rate_domestic':'국내 여비 금액표인 별표 2와 지급 근거 제16조를 함께 등록해야 합니다.',
    'travel_rate_foreign':'국외 여비 금액표인 별표 4와 지급 근거 제16조를 함께 등록해야 합니다.',
    'occasion':'경조사휴가 일수를 확인할 별표 1이 필요합니다.',
    'goods_inspection_limit':'검사조서 작성 생략 금액을 정한 시행령 등 직접 기준이 필요합니다.',
    'goods_payment_deadline':'대가 지급의 구체적인 기한을 정한 시행령 등 직접 기준이 필요합니다.',
    'account_disclosure':'업무추진비 공개 항목·주기·시기를 정한 별표 2의2가 필요합니다.',
    'goods_private_contract':'수의계약을 할 수 있는 금액·요건을 정한 지방계약법 시행령 제25조(국가기관은 국가계약법 시행령 제26조)가 필요합니다.',
    'travel_education':'교육대상자로 선발된 출장에 적용하는 인사혁신처 세부 기준이 필요합니다.',
}


def amount_question(query):
    q=flat(query)
    if any(t in q for t in ('퍼센트','몇%','비율')):return False
    if any(t in q for t in ('기한','언제까지','얼마나빨리')) and not re.search(r'얼마(?!나빨리)|몇원|금액은',q):
        return False
    return bool(re.search(r'얼마(?!나빨리)|몇(?:만)?원|금액|지급액|기준액|상한|한도',q))


# Common wording mapped to the article name; a bare '수당' is too broad to answer.
ALLOWANCE_WORDS=(('allowance_overtime',('시간외근무수당','초과근무수당','야근수당','시간외수당')),('allowance_holiday',('명절휴가비','명절상여','명절수당')),
    ('allowance_annual',('연가보상비','연가보상','연차수당')),('allowance_performance',('성과상여금','성과급')),
    ('allowance_tuition',('자녀학비보조','학비보조수당')),('allowance_position',('직급보조비',)),('allowance_meal',('정액급식비',)))


PAY_WORDS=(('pay_deduct_suspension',('직위해제',)),('pay_deduct_leave',('휴직',)),('pay_deduct_absence',('결근',)),
    ('pay_deduct_discipline',('징계','감봉','정직')),('pay_raise_limit',('승급제한','승급이제한','승급안')),('pay_reassess',('재획정',)),
    ('pay_promotion_step',('승진',)),('pay_initial_step',('초임호봉','호봉획정','경력환산','경력인정','호봉산정','경력')),
    ('pay_regular_raise',('정기승급','승급')),('pay_payday',('지급일','월급날','급여일','언제나와','언제들어','언제줘','며칠에')),
    ('pay_calc',('일할','월중','중도','보수계산')),('pay_table',('봉급표','봉급액','호봉표','얼마')))


def _allowance(q):
    from . import service_rules
    area=service_rules.domain(q)
    if not area:return None
    if area=='pay':
        found=next((key for key,words in PAY_WORDS if any(w in q for w in words)),None)
        if found:return dict(topics=[found],status='ready',question='',recognized=True,labels=[TOPICS[found][0]])
        return dict(topics=[],status='clarify',question='어떤 보수 업무인가요? 초임호봉 획정, 정기승급, 보수 지급일, 휴직·결근·징계 시 감액처럼 알려주세요.',recognized=True,labels=[])
    if any(t in q for t in ('맞춤형복지','복지점수','복지포인트','후생복지')):
        topic='welfare_grant' if any(t in q for t in ('부여','기본복지','변동복지','몇점','배정')) else 'welfare_points'
        return dict(topics=[topic],status='ready',question='',recognized=True,labels=[TOPICS[topic][0]])
    found=next((key for key,words in ALLOWANCE_WORDS if any(w in q for w in words)),None)
    found=found or next((key for key in TOPICS if key.startswith('allowance_') and TOPICS[key][1][0] in q),None)
    if found:return dict(topics=[found],status='ready',question='',recognized=True,labels=[TOPICS[found][0]])
    if '수당' in q and not any(t in q for t in ('위험수당','출장')):
        return dict(topics=[],status='clarify',question='어떤 수당인가요? 정근수당·가족수당·시간외근무수당·명절휴가비처럼 수당 이름을 알려주세요.',recognized=True,labels=[])
    return None


def analyze(query):
    q=flat(query)
    # The separately scoped budget-table matcher remains responsible for budget questions.
    if any(t in q for t in BUDGET_TERMS):
        if any(t in q for t in ('병가','연가','출장','출산휴가')) and any(t in q for t in ('각각','둘다','함께','이랑','비교')):
            return dict(topics=[],status='clarify',question='예산 과목과 다른 업무는 적용 자료가 달라요. 질문을 하나씩 나누어 알려주세요.',recognized=True,labels=[])
        return None
    # '시간외근무' contains '외근' but is overtime, not a business trip.
    travel=any(t in q for t in ('출장','여비','일비','숙박비','숙박료','호텔비','기름값','택시비','주유비','항공권')) or bool(re.search(r'(?<!시간)외근',q))
    # Private use of a work card is not a travel question, whatever else the sentence says about 출장.
    if private_card_use(query):travel=False
    if not travel:
        allowance=_allowance(q)
        if allowance:return allowance
    care=leave_situations.family_care(query)
    own_sick=leave_situations.self_sick(query)
    # "부모님 돌아가시면 며칠 쉬어?" asks about leave without using the word.
    occasion_days=bool(re.search(r'(?:부모|아버지|어머니|배우자|할아버지|할머니|형제|자매|자녀|부친상|모친상|돌아가|별세|사망|결혼).{0,12}(?:며칠|쉬어|쉬나|쉴수|쉬는)',q))
    leave=care or own_sick or occasion_days or leave_situations.asks_which_leave(q) or any(t in q for t in ('휴가','휴무','연가','연차','병가','공가','육아시간','모성보호','헌혈')) or (any(t in q for t in ('건강검진','건강진단')) and not leave_situations.health_work(query))
    sidejob=any(t in q for t in ('겸직','영리업무','유튜브수익','유튜브수입'))
    goods=any(t in q for t in ('물품','납품','검수','검사조서','수의계약','불용','견적','법인카드','문구점','인센티브','포인트','적립금','마일리지','강사료','강연료','지방자치단체선금','퇴직예정자기념품'))
    # 업무추진비 itself is the finance pack's 업무추진비 section; only its disclosure is an account topic.
    goods=goods or ('업무추진비' in q and '공개' in q)
    goods=goods or ('계약' in q and any(t in q for t in ('대가','대금','선금')))
    goods=goods or (not leave and _explicit_local_contract_party(query))
    if private_card_use(query):goods=False
    topics=[];question=''
    def add(topic):
        if topic not in topics:topics.append(topic)
    if sidejob:add('side_job')
    if travel:
        for t in ('travel_private_car','travel_taxi','travel_flight','travel_mileage','travel_risk'):
            if any(a in q for a in TOPICS[t][1]):add(t)
        if ('교육대상자' in q or '교육출장' in q) and any(t in q for t in ('선발','세부기준','지급기준')):add('travel_education')
        if 'travel_private_car' in topics and (amount_question(query) or any(t in q for t in ('계산','리터','킬로','km','연비'))):
            topics.remove('travel_private_car');add('travel_fuel_details')
        if not topics:
            lodging=any(t in q for t in ('숙박','호텔'))
            meal=any(t in q for t in ('식비','식대'))
            extra=(lodging or meal) and any(t in q for t in ('초과','추가정산','부득이'))
            local=any(t in q for t in TOPICS['travel_local'][1])
            if any(t in q for t in ('지급구분','몇호','1호인지','2호인지')):add('travel_group')
            elif any(t in q for t in ('지급표','금액표','별표2','별표4')):
                add('travel_rate_foreign' if supplement.foreign_query(query) or '별표4' in q else 'travel_rate_domestic')
            elif extra:add('travel_extra')
            elif local:
                add('travel_foreign_local' if any(t in q for t in ('국외','해외','미국','외국','일본','중국')) else 'travel_local')
                if any(t in q for t in TOPICS['travel_settlement'][1]):add('travel_settlement')
            elif any(t in q for t in ('현금','카드','결제')):add('travel_card')
            elif any(t in q for t in ('정산','영수증','증빙','증거서류')):add('travel_settlement')
            elif '일비' in q:add('travel_daily')
            elif lodging:add('travel_lodging')
            elif meal:add('travel_meal')
            elif any(t in q for t in ('군인','공무직','교육공무원','교사','공기업')):add('travel_general')
            else:question='출장의 어떤 부분이 궁금한가요? 정산 기한·증빙, 관내 여비, 일비 감액 등 처리할 내용을 알려주세요.'
        if any(t in q for t in ('각각','둘다','함께','이랑','비교','일비와','숙박비와','숙박비상한과')):
            if 'travel_local' not in topics and 'travel_extra' not in topics:
                for t in ('travel_daily','travel_lodging','travel_meal','travel_settlement'):
                    if any(a in q for a in TOPICS[t][1]):add(t)
        rates=set(topics)&{'travel_daily','travel_lodging','travel_meal'}
        if rates and amount_question(query) and 'travel_extra' not in topics:
            topics[:]=[t for t in topics if t not in rates]
            add('travel_rate_foreign' if supplement.foreign_query(query) else 'travel_rate_domestic')
        if any(t in q for t in ('식비','식사','급식')) and any(t in q for t in ('제공','무료','포함','급식')):
            topics[:]=[t for t in topics if t not in ('travel_meal','travel_rate_domestic','travel_rate_foreign')]
            add('travel_provided_meals')
    if leave:
        if care:add('family_care')
        # A stated purpose takes precedence over alternatives mentioned for comparison ('연가 대신 공가').
        for t in ('childcare','family_care','maternal_time','pregnancy_accompany','pregnancy_check','miscarriage','fertility','women_health','disaster_leave','mental_leave'):
            if any(a in q for a in TOPICS[t][1]):add(t)
        if 'pregnancy_accompany' in topics and 'pregnancy_check' in topics:topics.remove('pregnancy_check')
        if any(t in q for t in ('배우자','아내','와이프')) and any(t in q for t in ('산전검진','임신검진')) and '동행' in q:
            add('pregnancy_accompany')
            if 'pregnancy_check' in topics:topics.remove('pregnancy_check')
        if any(t in q for t in ('유산','사산')):add('miscarriage')
        if not any(t in SPECIAL for t in topics) and any(t in q for t in ('배우자','아내','와이프')) and '출산' in q:add('occasion')
        if not any(t in SPECIAL for t in topics) and any(t in q for t in ('경조사','결혼','사망','입양','돌아가셨','돌아가셔','돌아가신','돌아가시','별세','부친상','모친상','장례')):add('occasion')
        if 'occasion' in topics and any(t in q for t in ('사용기한','분할','나눠','언제까지')):
            topics.remove('occasion');add('occasion_use')
        if not any(t in SPECIAL for t in topics) and '출산' in q:add('maternity')
        # Whether a weekend inside a leave counts is its own rule, whatever the leave type.
        if not any(t in SPECIAL for t in topics) and any(t in q for t in ('토요일','공휴일')) and any(t in q for t in ('포함','들어가','산입','일수에','빼','제외')):
            add('leave_holiday')
        if not any(t in SPECIAL for t in topics) and 'leave_holiday' not in topics:
            if '연가' in q and '병가' in q and any(t in q for t in ('가산','더해','추가','안썼','미사용','사용하지않','22일')):add('annual')
            elif any(a in q for a in TOPICS['public_health'][1]) and not leave_situations.after_health_check(query):add('public_health')
            elif '헌혈' in q:add('public_blood')
            elif '병가' in q or own_sick or leave_situations.after_health_check(query):add('sick')
            elif any(t in q for t in ('대체휴무','대체휴가')):add('compensatory')
            elif '포상휴가' in q:add('reward_leave')
            elif '장기재직' in q or any(t in q for t in TOPICS['region_leave'][1][:3]):
                from . import service_rules
                # The days differ by status and province; a national figure would mislead others.
                if not (service_rules.status(query) or service_rules.region(query)):
                    question='장기재직휴가와 지역 특별휴가는 신분과 소속에 따라 달라요. 국가·지방(시·도)·소방·경찰 중 어디에 해당하는지 알려주세요.'
                else:add('long_service' if '장기재직' in q else 'region_leave')
            elif '선거' in q and '휴무' in q:add('election_rest')
            elif '여행' in q and '휴무' in q:add('travel_limit')
            elif any(t in q for t in ('토요일','공휴일')):add('leave_holiday')
            elif any(t in q for t in ('연가','연차')):
                if any(t in q for t in ('남은','남았','잔여','잔량')) and not any(t in q for t in ('근거','규정','이월','보상')):question='개인의 남은 연가는 규정만으로 알 수 없어요. 올해 부여·이월·사용한 연가 내역을 확인해 주세요.'
                elif any(t in q for t in TOPICS['annual_use'][1]) and not any(t in q for t in ('보상','재직기간')):add('annual_use')
                else:add('annual')
            elif '공가' in q or (leave_situations.asks_which_leave(q) and any(t in q for t in ('예비군','민방위','병역판정','투표','승진시험','전직시험'))):
                if any(t in q for t in ('병원','진료')):question='어떤 사유의 방문인가요? 본인 진료, 법정 건강검진, 가족 진료 동행은 적용 기준이 달라요.'
                else:add('public_leave')
            else:question='누가 어떤 사유로 쉬어야 하나요? 본인 질병, 가족 돌봄, 검진 등 상황을 알려주시면 맞는 휴가를 안내할게요.'
        if 'sick' in topics and any(t in q for t in ('연가기본일수','연가일수표','연가일수와','연가와병가','연가및병가')):add('annual')
        if any(t in q for t in ('각각','둘다','비교','연가와','연가및','병가와','병가및')):
            if '연가' in q:add('annual')
            if '병가' in q:add('sick')
    if goods and not (travel and not any(t in q for t in ('물품','납품','검수','견적'))):
        if '업무추진비' in q:add('account_disclosure')
        elif any(t in q for t in ('집행','공개')) and any(t in q for t in ('강사료','강연료')):add('account_lecturer')
        elif '공개' in q and any(t in q for t in TOPICS['account_points'][1]):add('account_incentive_disclosure')
        elif '공개' in q and '퇴직' in q:add('account_retirement_disclosure')
        elif any(t in q for t in TOPICS['account_points'][1]):add('account_points')
        else:
            goods_start=len(topics)
            for t in ('goods_quote','goods_private_contract','goods_disposal','goods_defect'):
                if any(a in q for a in TOPICS[t][1]):add(t)
            if 'goods_quote' in topics and 'goods_private_contract' in topics and not any(t in q for t in ('수의계약한도','수의계약가능금액','수의계약요건')):topics.remove('goods_private_contract')
            # 제30조 is the selection procedure (견적); the amount limits are a different article.
            if 'goods_private_contract' in topics and any(t in q for t in ('선정','절차')) and not any(t in q for t in ('한도','금액','요건','얼마','이하')):
                topics[topics.index('goods_private_contract')]='goods_quote'
            if len(topics)==goods_start:
                pay=any(t in q for t in ('대금','대가','선금','돈부터','돈을먼저','돈먼저'))
                inspect=any(t in q for t in ('검사','검수','검사조서','품질인증','성능시험'))
                if pay:
                    if '이자' in q:add('goods_payment_interest')
                    elif any(t in q for t in ('며칠','몇일','기한','언제까지','몇영업일')) or re.search(r'\d+(?:영업)?일(?:안|내|이내)',q):add('goods_payment_deadline')
                    else:add('goods_payment')
                    if inspect and any(t in q for t in ('검사와','검수와','검사및','검수및','각각','같이','둘다')):add('goods_inspection')
                elif inspect:
                    skip=any(t in q for t in ('생략','안써도','안작성','작성하지않','생략해도'))
                    money=amount_question(query) or bool(re.search(r'\d+[만천억,]*원',q))
                    if skip and money:add('goods_inspection_limit')
                    elif any(t in q for t in ('며칠','몇일','기한','언제까지')):add('goods_inspection_deadline')
                    else:add('goods_inspection')
                else:question='물품 구매의 어떤 단계인가요? 예산 과목, 견적·계약, 납품 검사, 대금 지급 중 궁금한 부분을 알려주세요.'
    conduct=None
    # e-사람 screen questions stay with the system manual.
    if not (travel or leave or goods or sidejob or re.search(r'e[-·]?사람|이사람|스마트출장',q)):
        # One conduct subject per question, the most specific first.
        conduct=next((t for t in ('drinking','overtime','duty','travel_limit','shift','politics','dress','work_hours')
                      if any(a in q for a in TOPICS[t][1][:1 if t=='travel_limit' else None])),None)
        if conduct=='work_hours' and not re.search(r'근무시간(?:은|이|은몇|몇|이몇|이어떻게|변경|조정|기준)|출근시간|퇴근시간',q):conduct=None
        if conduct:add(conduct)
    if not (travel or leave or goods or sidejob or conduct) and (re.search(r'^(?:그럼|그러면|그거|그건|그것|이거)',q) or '검사' in q or '재직기간' in q):
        question='어떤 업무와 상황인지 함께 알려주세요. 다른 업무의 기준을 임의로 적용하지 않을게요.'
    elif not (travel or leave or goods or sidejob or conduct):
        return None
    if supplement.national(query) and any(t in flat(personnel_scope.subject_query(query)) for t in ('지방공무원','지방직','지자체','지방자치단체')) and not _explicit_local_contract_party(query):
        question='국가기관과 지방기관의 기준은 적용 범위가 달라요. 기관별 질문을 나누어 알려주시면 각각 맞는 근거로 확인할게요.'
    elif goods and not question and 'fire' in personnel_scope.analyze(query)['roles'] and not _explicit_local_contract_party(query):
        question='소방공무원은 소속에 따라 적용되는 계약 법령이 달라요. 계약당사자가 지방자치단체(시·도)인지 국가기관(소방청·소속기관)인지 알려주세요.'
    return dict(topics=topics,status='clarify' if question else 'ready',question=question,
                recognized=True,labels=[TOPICS[t][0] for t in topics])


def expanded_terms(plan):
    return ' '.join(a for t in (plan or {}).get('topics',[]) for a in TOPICS[t][1][:2])


def private_card_use(query):
    q=flat(query)
    # Card points have their own rule in the accounting directive.
    return any(t in q for t in ('구매카드','법인카드','업무용카드')) and bool(re.search(r'사적|개인적|개인용|개인사용',q)) and not any(t in q for t in ('포인트','적립금','마일리지','인센티브'))


def _scope_clauses(text):
    """Retain question endings when checking an asserted identity/party."""
    return [(flat(m[1]),m[2]) for m in re.finditer(r'([^.!?？。;\n]+)([.!?？。;\n]?)',text) if flat(m[1])]


def _retracted_scope_claim(clause,subject_pattern):
    return bool(re.search(subject_pattern+r'.*?(?:전제|주장|진술)(?:은|는|이|가)(?:사실)?(?:이)?(?:아니|아닙|아님)',clause))


def _explicit_local_contract_party(query):
    clauses=_scope_clauses(query)
    claims=[(part,end) for part,end in clauses if '당사자' in part]
    if len(claims)!=1 or claims[0][0].count('계약당사자')!=1:
        return False
    # A later correction can retract a previous assertion. Ordinary questions
    # such as "확인할 수 있나요" do not express uncertainty about the party.
    if any(re.search(r'정정|철회|미확인|불명|불분명|불확실|확인하지않|거짓|허위',part) or _retracted_scope_claim(part,r'계약당사자') for part,end in clauses):
        return False
    claim,end=claims[0]
    if re.fullmatch(r'계약당사자(?:가|는)지방자치단체(?:입니다|이다)',claim):
        return end not in ('?','？')
    # Close the affirmative relative phrase at the contract noun and its case
    # marker, instead of accepting an uncertain/negated noun prefix.
    return bool(re.match(r'계약당사자(?:가|는)지방자치단체인(?:물품|공사|용역|구매|납품)+계약(?:의|에서)(?:\d{4}년\d{1,2}월\d{1,2}일)?(?:납품)?(?:검사|검수|대가|대금|수의계약|제\d+조|원문|절차|기준)',claim))


def _explicit_national_travel_staff(query):
    subject=personnel_scope.subject_text(query)
    clauses=_scope_clauses(subject)
    identity_claim=r'(?:국가직|국가공무원)(?:인)?(?:소방공무원|소방관|교육공무원|교사|교원|신분)?(?:이?라는)'
    if any(_retracted_scope_claim(part,identity_claim) for part,end in clauses):
        return False
    if re.search(r'정정|철회|(?:국가직|국가공무원)(?:신분)?(?:이|은|는)?(?:아니|아닙|아님|아닌|인지|미확인|불명|불분명|불확실)|신분(?:이|은|는)?(?:미확인|불명|불분명|불확실)',flat(subject)):
        return False
    if re.search(r'(?:사립|민간)(?:학교)?(?:의)?(?:교사|교원|교육공무원)',flat(subject)):
        return False
    # An institution visited/inviting the employee is not an employee category.
    # Only the confirmed 업무환경 marker or a clear own declaration opens this exception.
    asserted=bool(re.search(r'(?m)^\s*업무환경:\s*국가공무원\s*$',query))
    for part,end in clauses:
        identity=r'(?:저는|나는|본인은)?(?:국가직|국가공무원(?:인)?)(?:소방공무원|소방관|교육공무원|교사|교원)'
        if re.fullmatch(r'(?:저는|나는|본인은)?(?:국가직|국가공무원)(?:입니다|이다|이에요)',part) or re.fullmatch(identity+r'(?:입니다|이다|이에요)',part):
            if end in ('?','？'):
                return False
            asserted=True
        elif re.match(identity+r'(?=여비|출장|국내|국외|\d{4}년)',part):
            asserted=True
    return asserted


CONTRACT_LAWS={'지방자치단체를당사자로하는계약에관한법률','지방자치단체를당사자로하는계약에관한법률시행령'}


def scope_reason(query, source, today, personnel=None):
    official=source.get('official') or {}
    q=flat(query);title=official.get('title','') or source.get('title','')
    scope=flat(title+' '+source.get('institution',''))
    personnel=personnel or personnel_scope.analyze(query)
    if re.search(r'지방지(?:인데|이에|으로)',q):return '적용 신분 표현을 확인해 주세요. 국가·지방 기준을 임의로 정하지 않습니다.'
    if personnel['conflict']:return '국가·지방의 적용 대상을 나누어 확인해야 합니다.'
    # A named local-government contract concerns the contracting institution, not the
    # asker's personnel rules. This does not authorize a contract or a payment.
    contract_law=flat(title) in CONTRACT_LAWS
    local_contract=(contract_law and flat(official.get('title','')) in CONTRACT_LAWS
                    and personnel['framework']=='local' and _explicit_local_contract_party(query))
    # 공무원 여비 규정 also covers a clearly national fire or education official.
    national_travel=(personnel['framework']=='national' and personnel['roles'] in (['fire'],['teacher'])
                     and flat(official.get('title',''))=='공무원여비규정' and _explicit_national_travel_staff(query))
    # A fire officer may belong to a province or to the national fire agency, so the party decides.
    if contract_law and not local_contract and 'fire' in personnel['roles']:
        return '계약당사자가 지방자치단체인지 국가기관인지 확인해야 적용 법령을 고를 수 있습니다.'
    # Fire officers follow their own decree and the national one, never the local one.
    if 'fire' in personnel['roles'] and '지방공무원복무규정' in flat(title):
        return '질문한 직군·기관에 적용할 별도의 근거가 필요합니다.'
    subject=flat(personnel_scope.subject_query(query))
    # Mentioning a child's teacher does not make the questioner a teacher.
    employee_q=re.sub(r'(?:담임)?교사(?:와의|와|상담)', '',subject)
    jobs=('군인','공무직','교육공무원','교사','교원','공기업','사기업','민간기업','회사원')
    requested=[t for t in jobs if t in employee_q]
    # 무기계약·기간제 workers are under employment terms, not the conduct decrees.
    if 'public_worker' in personnel['roles'] and '공무직' not in requested:requested.append('공무직')
    if not local_contract and requested and not any(t in scope for t in requested) and not (national_travel and set(requested)<={'교육공무원','교사','교원'}):
        return '질문한 직군·기관에 적용할 별도의 근거가 필요합니다.'
    if any(t in subject for t in ('국가기관','국가공무원','국가직','중앙부처','국가회계')) and any(t in scope for t in ('지방공무원','지방자치단체','교육청','학교')) and '국가공무원' not in scope:
        return '국가기관·국가공무원에 적용할 근거가 필요합니다.'
    if supplement.local(query) and '국가공무원복무규정' in flat(title):return '지방공무원에게 국가공무원 복무규정을 대신 적용하지 않습니다.'
    effective=source.get('effective_date') or ''
    # A later edition is not applied to an earlier event. A month is compared from its
    # first day only as a bound; no incident day is invented for the answer.
    dates=document_context.event_dates(query)
    if dates and effective and min(dates).isoformat()<effective:
        return '질문한 사건일에 시행된 원문이 필요합니다. 이후 시행본을 소급 적용하지 않습니다.'
    if effective and any(not 1<=month<=12 or f'{year:04d}-{month:02d}-01'<effective for year,month in document_context.event_months(query)):
        return '질문한 사건일에 시행된 원문이 필요합니다. 이후 시행본을 소급 적용하지 않습니다.'
    years={int(y) for y in re.findall(r'(?<!\d)(20\d{2})(?!\d)',supplement.without_document_numbers(query))}
    if years and min(years)<int(source.get('effective_date','0000')[:4] or 0):
        return '질문한 과거 시점에 시행된 원문이 필요합니다. 현재 등록한 판본을 소급 적용하지 않습니다.'
    return ''


def supports(topic, hit, query=''):
    official=hit.get('official') or {}; text=flat(hit['text']); title=flat(hit['title'])
    if official:
        from . import service_rules
        target=service_rules.expected(topic,query)
        if target:
            # The stated status decides the regulation; fire/police special rules first.
            if topic=='family_care' and not all(t in text for t in ('가족돌봄휴가','질병,사고,노령','연간10일','가족돌봄휴가는무급으로하되')):return False
            if official.get('title')!=target[0] or not official.get('article','').startswith(target[1]):return False
            # The local decree only delegates these leaves; its other paragraphs are not the answer.
            if topic in ('long_service','region_leave') and target[0]=='지방공무원 복무규정' and '조례로정하는바에따른다' not in text:return False
            return not (topic in SPECIAL and SPECIAL[topic] not in text)
        expected=ARTICLE.get(topic)
        if supplement.national(query):
            if topic=='sick':expected=('국가공무원 복무규정','제18조(')
            elif topic in ('public_health','public_blood','public_leave'):expected=('국가공무원 복무규정','제19조(')
        if topic=='family_care':
            expected=('국가공무원 복무규정','제20조(') if supplement.national(query) else ARTICLE[topic]
            # An article heading/para.1 about weddings is not family-care evidence.
            # Neither is the paid-leave paragraph alone: preserve its preceding
            # eligibility causes, child/relative scope, and overall annual limit.
            if not all(t in text for t in ('가족돌봄휴가','질병,사고,노령','연간10일','가족돌봄휴가는무급으로하되')):return False
        if not expected or official.get('title')!=expected[0] or not official.get('article','').startswith(expected[1]):return False
        if topic in SPECIAL and SPECIAL[topic] not in text:return False
        return True
    # A meeting memo is searchable reference material, not a rule establishing an entitlement.
    # Uploaded regulations/manuals still need a substantive rule in the matching passage.
    if any(t in title for t in ('합성','모의','시연')):return False
    if hit.get('kind') not in ('법령·규정','기관 지침','업무편람'):return False
    anchors=TOPICS[topic][1]
    if not any(a in text for a in anchors):return False
    if re.search(r'다루지않|기준.{0,10}(?:없|정하지않)|검토하지않|별도확인필요',text):return False
    if not re.search(r'하여야|해야|한다|정한다|할수있|신청|지급|제출',text):return False
    deadline=topic=='goods_payment_deadline' or topic=='travel_settlement' and any(t in flat(query) for t in ('기한','언제까지','며칠','몇일'))
    if deadline and not re.search(r'\d+(?:영업)?(?:일|주|개월)',text):return False
    if topic=='goods_inspection_limit' and not re.search(r'\d+[만천억,]*원',text):return False
    return True


def filter_hits(query,hits,plan):
    if plan['status']=='clarify':return [],plan['question']
    topics=plan['topics']
    question=supplement.clarification(query,topics,hits)
    if question:
        plan.update(status='clarify',question=question);return [],question
    if 'occasion' in topics and not supplement.occasion_supported(query):
        return [],supplement.occasion_unsupported_reason(query)
    required={(t,tuple(target)) for t in topics for target in (supplement.requirements(t,query) or [(None,None)])}
    candidates=[]
    for h in hits:
        covered={(t,target) for t,target in required if (supplement.matches(h,target) if target[0] else supports(t,h,query))}
        if covered:candidates.append((h,covered))
    candidates=[c for c in candidates if c[1]]
    needed=set(required);selected=[]
    while needed and candidates and len(selected)<6:
        candidates.sort(key=lambda c:(len(c[1]&needed),c[0]['score']),reverse=True)
        hit,covered=candidates.pop(0)
        if not covered&needed:break
        selected.append(hit);needed-=covered
    if needed:
        reasons=[MISSING.get(t,'등록 자료에서 '+TOPICS[t][0]+'의 직접 근거를 확인할 수 없습니다.') for t in sorted({t for t,_ in needed})]
        return [],' '.join(reasons)
    # General legal-basis questions can still show the statute alone. When a
    # current delegated rule is registered, include its conditions too. Amount
    # and calculation questions above continue to require the delegated rule.
    supplementary=[]
    if 'goods_inspection' in topics and '검사조서' in flat(query) and '생략' in flat(query):
        supplementary.append((supplement.DECREE,'제65조('))
    if 'goods_payment_interest' in topics:
        supplementary.append((supplement.DECREE,'제68조('))
    for target in supplementary:
        extra=next((h for h in hits if supplement.matches(h,target)),None)
        if extra and all(h['id']!=extra['id'] for h in selected) and len(selected)<6:
            selected.append(extra)
    return selected,''


def summary_allowed(rule_id,query,plan):
    if not plan:return True
    topics=set(plan['topics']);q=flat(query)
    rules={
        'settlement': {'travel_settlement'}, 'additional-settlement': {'travel_extra'},
        'local-trip': {'travel_local'}, 'daily-car': {'travel_daily'}, 'annual-leave': {'annual'},
        'sick-leave': {'sick'}, 'health-leave': {'public_health'}, 'blood-leave': {'public_blood'},
        'childcare-time': {'childcare'}, 'family-care': {'family_care'},
        'goods-inspection': {'goods_inspection'}, 'goods-payment': {'goods_payment'},
        'card-points': {'account_points'}, 'instructor-disclosure': {'account_lecturer'},
    }
    if topics!=rules.get(rule_id,set()):return False
    if rule_id=='annual-leave':
        years=[int(n) for n in re.findall(r'(?<!\d)(\d{1,2})년',q)]
        return bool(years and len(years)==1 and years[0]>=6 and not any(t in q for t in ('보상','휴직','산입','병가','가산','22일')))
    if rule_id=='additional-settlement' and any(t in q for t in ('퍼센트','비율','%','식비','식대')):return False
    if rule_id=='goods-inspection' and any(t in q for t in ('비용','부담','파손','성능시험')):return False
    if rule_id=='sick-leave' and any(t in q for t in ('시간','환산')):return False
    if rule_id=='daily-car' and not any(t in q for t in ('공무용차량','공용차량','관용차량','공용차','관용차')):return False
    if rule_id=='family-care' and not any(t in q for t in ('유급','무급','급여','일수','며칠','몇일','열흘','10일')):return False
    if rule_id=='local-trip' and any(t in q for t in ('범위','거리','12킬로','12km','정의')):return False
    return True
