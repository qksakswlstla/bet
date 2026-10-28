"""수동 실행 HTTPS 어댑터. 정상 빈 응답과 실패를 구분하며 비밀값을 저장하지 않는다.
실제 공급원 응답 확인 전인 후보 인터페이스. 배당은 해외 참고자료로만 제공.
"""
from dataclasses import dataclass,field
from datetime import datetime,timezone
import json
import os
import math
import re
import urllib.request
import urllib.parse
import urllib.error
from .validation import timestamp

BASES={'basketball':'https://v1.basketball.api-sports.io','volleyball':'https://v1.volleyball.api-sports.io','football':'https://v3.football.api-sports.io','odds':'https://api.the-odds-api.com/v4'}

@dataclass
class FetchResult:
    status:str
    items:list=field(default_factory=list)
    message:str=''
    collected_at:str=field(default_factory=lambda:datetime.now(timezone.utc).isoformat())
    source:str=''
    quota:dict=field(default_factory=dict)
    errors:object=field(default_factory=dict)
    request_context:dict=field(default_factory=dict)
    causes:list=field(default_factory=list)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise urllib.error.HTTPError(req.full_url,code,'Redirect refused',{},None)


def transport(url,headers):
    req=urllib.request.Request(url,headers=headers)
    # HTTPS/TLS 검증 유지. 응답 크기 제한, 네트워크 자동 재시도 없음.
    with urllib.request.build_opener(NoRedirect()).open(req,timeout=20) as response:
        body=response.read(8_000_001)
        if len(body)>8_000_000:raise ValueError('response too large')
        return json.loads(body),dict(response.headers)


def scrub(value,secret):
    if isinstance(value,dict):return {k:('[REDACTED]' if k.lower() in ('apikey','api_key','x-apisports-key','authorization') else scrub(v,secret)) for k,v in value.items()}
    if isinstance(value,list):return [scrub(v,secret) for v in value]
    if isinstance(value,str) and secret:return value.replace(secret,'[REDACTED]')
    return value


def safe_errors(value):
    """진단용 사본만 보존. 인증/개인 필드와 알려진 키·대표 PII 패턴을 제거."""
    if isinstance(value,dict):
        result={}
        for key,val in value.items():
            label=safe_errors(str(key))
            sensitive=re.search(r'(?i)(authorization|headers?|cookies?|password|secret|token|api.?key|apisports.?key|email|phone|address|username|full.?name|first.?name|last.?name|customer|account.?id|ip.?address)',str(key))
            result[label]='[REDACTED]' if sensitive else safe_errors(val)
        return result
    if isinstance(value,list):return [safe_errors(x) for x in value]
    if not isinstance(value,str):return value
    for name in ('APISPORTS_KEY','ODDS_API_KEY'):
        secret=os.environ.get(name,'')
        if secret:
            for variant in (secret,urllib.parse.quote(secret,safe=''),urllib.parse.quote_plus(secret)):
                value=value.replace(variant,'[REDACTED]')
    value=re.sub(r'https?://[^\s<>]+','[URL REDACTED]',value,flags=re.I)
    value=re.sub(r'(?i)\b(?:authorization|cookie|set-cookie|x-[a-z-]*key)\s*[:=][^\r\n]*','[AUTH REDACTED]',value)
    value=re.sub(r'(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+','[AUTH REDACTED]',value)
    value=re.sub(r'(?i)\b(?:api[_-]?key|token|password|secret|email|phone|address|username|full.?name|first.?name|last.?name)\s*[:=][^\r\n;,]*','[PRIVATE REDACTED]',value)
    value=re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}','[EMAIL REDACTED]',value)
    value=re.sub(r'(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)','[IP REDACTED]',value)
    value=re.sub(r'(?<!\d)(?:\+?\d[ ()-]*){9,15}(?!\d)','[PHONE REDACTED]',value)
    return value


def explain_errors(errors):
    text=json.dumps(errors,ensure_ascii=False).lower()
    causes=[]
    if re.search(r'(season.*(?:not available|not supported|not allowed|access|plan|subscription|only)|(?:free|subscription|plan).*season)',text):
        causes.append('시즌/요금제 접근 제한: 공급원이 허용하는 시즌과 구독 범위를 확인하세요.')
    if re.search(r'(invalid.*(?:key|token)|(?:key|token).*(?:invalid|missing|expired)|unauthenticated|unauthorized|authentication failed)',text):
        causes.append('인증 실패: 키의 유효성 및 해당 종목 권한을 확인하세요.')
    if re.search(r'(rate.?limit|too many requests|quota|request limit|requests? (?:per|limit)|limit.*reached)',text):
        causes.append('호출 한도: 공급원 한도와 재시도 가능 시간을 확인하세요.')
    if re.search(r'(invalid.*(?:parameter|season|league)|(?:parameter|season|league).*(?:invalid|required|must be)|unknown league|missing parameter)',text):
        causes.append('요청 조건 오류: 요청한 대회 ID·시즌·매개변수를 확인하세요.')
    return causes or ['원인 미확인: 아래 공급원 오류를 확인하세요. 시즌 제한이나 인증 문제로 단정하지 않습니다.']


def request(sport,path,params=None,send=None):
    result=_request(sport,path,params,send)
    context={'sport':sport}
    for key in ('league','season'):
        raw=str((params or {}).get(key,''))
        context[key]=raw if re.fullmatch(r'[0-9-]{1,24}',raw) else '미지정/표시 보류'
    result.request_context=context
    return result


def _request(sport,path,params=None,send=None):
    key=os.environ.get('ODDS_API_KEY' if sport=='odds' else 'APISPORTS_KEY','')
    source=BASES[sport]+path
    if not key:return FetchResult('missing_key',message=('ODDS_API_KEY' if sport=='odds' else 'APISPORTS_KEY')+' 환경변수 미설정',source=source)
    params=dict(params or {});headers={'Accept':'application/json','User-Agent':'bet-local-analysis/1'}
    if sport=='odds':params['apiKey']=key
    else:headers['x-apisports-key']=key
    url=source+'?'+urllib.parse.urlencode(params)
    try:
        payload,response_headers=(send or transport)(url,headers)
        payload=scrub(payload,key)
        allowed={'x-requests-remaining','x-requests-used','x-requests-last','x-ratelimit-requests-remaining','x-ratelimit-requests-limit'}
        quota={k.lower():v for k,v in response_headers.items() if k.lower() in allowed and str(v).isdigit()}
        if sport!='odds':
            if isinstance(payload,dict) and payload.get('errors'):
                errors=safe_errors(payload['errors'])
                return FetchResult('api_error',message='공급원 오류: 상세 항목을 확인하세요.',source=source,quota=quota,errors=errors,causes=explain_errors(errors))
            if not isinstance(payload,dict) or 'response' not in payload:return FetchResult('schema_error',message='공급원 응답 구조가 예상과 다릅니다.',source=source)
            paging=payload.get('paging',{})
            if paging and paging.get('total',1)>1:return FetchResult('incomplete',message='여러 페이지 응답입니다. 부분 자료를 전체로 표시하지 않습니다. 조회 범위를 줄이세요.',source=source,quota=quota)
            items=payload['response']
        else:items=payload
        if not isinstance(items,list):return FetchResult('schema_error',message='목록 응답이 아닙니다.',source=source)
        return FetchResult('ok' if items else 'empty',items=items,source=source,quota=quota,message='조회 성공' if items else '정상 조회: 반환 자료 0건')
    except urllib.error.HTTPError as exc:
        state={401:'unauthorized',403:'forbidden',429:'rate_limited'}.get(exc.code,'http_error')
        errors={}
        try:
            body=exc.read(65537)
            if len(body)<=65536:
                detail=json.loads(body)
                if isinstance(detail,dict):errors=safe_errors(detail.get('errors') or detail.get('message') or {})
        except (ValueError,TypeError,OSError,AttributeError):pass
        return FetchResult(state,message=f'HTTP {exc.code}: 상세 오류가 없으면 원인 미확인입니다.',source=source,errors=errors,causes=explain_errors(errors))
    except (urllib.error.URLError,TimeoutError,OSError):
        return FetchResult('connection_error',message='연결 실패. 프록시·인터넷·시간 초과를 확인하세요. 이전 자료를 최신으로 대체하지 않습니다.',source=source)
    except (ValueError,TypeError):return FetchResult('schema_error',message='응답 형식/크기 오류',source=source)


def catalog(sport,send=None):
    result=request(sport,'/sports' if sport=='odds' else '/leagues',send=send)
    if result.status not in ('ok','empty'):return result
    try:
        normalized=[]
        for raw in result.items:
            if sport=='odds':
                normalized.append({'id':str(raw['key']),'name':raw['title'],'country':raw.get('group'),'type':raw.get('description'),'seasons':[], 'current_season':'공급원 목록에 시즌 없음','coverage':None,'raw':raw})
            else:
                if not isinstance(raw.get('seasons',[]),list):raise ValueError('season structure')
                league=raw['league'] if sport=='football' else raw
                normalized.append({'id':str(league['id']),'name':league['name'],'country':raw.get('country'), 'type':league.get('type'), 'seasons':raw.get('seasons',[]),'coverage':raw.get('coverage'),'raw':raw})
        result.items=normalized
    except (KeyError,TypeError,ValueError):result.status='schema_error';result.items=[];result.message='대회 목록 구조 불일치. 지원 여부를 확정할 수 없습니다.'
    return result


def games(sport,league_id,season,date_from,date_to,send=None):
    if sport not in ('football','basketball','volleyball'):raise ValueError('지원 종목 오류')
    start=timestamp(date_from+'T00:00:00+09:00');end=timestamp(date_to+'T23:59:59+09:00')
    if (end-start).days<0 or (end-start).days>31:raise ValueError('조회 범위는 최대 31일입니다.')
    # 종목별 날짜 필터 지원을 추측하지 않고 대회/시즌 목록을 받은 후 KST로 필터링.
    result=request(sport,'/fixtures' if sport=='football' else '/games',{'league':league_id,'season':season},send)
    if result.status not in ('ok','empty'):return result
    try:
        items=[]
        for raw in result.items:
            fixture=raw['fixture'] if sport=='football' else raw
            league=raw['league'];teams=raw['teams'];date=fixture['date']
            if str(league['id'])!=str(league_id) or str(league['season'])!=str(season):raise ValueError('대회·시즌 혼합 응답')
            if not start<=timestamp(date)<=end:continue
            for side in ['home','away']:
                if not teams[side].get('id') or not teams[side].get('name'):raise ValueError('팀 식별자 누락')
            items.append({'provider':'API-Sports/'+sport,'provider_match_id':str(fixture['id']),'provider_home_id':str(teams['home']['id']),'provider_away_id':str(teams['away']['id']),'league_id':str(league_id),'season':str(season),'home':teams['home']['name'],'away':teams['away']['name'],'kickoff':date,'stage':str(league.get('round') or raw.get('stage') or ''),'status':fixture.get('status'),'scores':raw.get('score',raw.get('scores')),'goals':raw.get('goals'),'source':result.source,'collected_at':result.collected_at,'provider_updated_at':None,'data_as_of':None,'raw':raw})
        result.items=items;result.status='ok' if items else 'empty';result.message=f'조회 범위 내 {len(items)}건. 공급원 자료 갱신 시각은 미확보입니다.'
    except (ValueError,KeyError,TypeError):result.status='schema_error';result.items=[];result.message='경기 구조·대회·시즌·시간 검수 실패. 부분 자료를 가져오지 않았습니다.'
    return result


def overseas_odds(sport_key,send=None):
    if not sport_key or any(x not in 'abcdefghijklmnopqrstuvwxyz0123456789_' for x in sport_key):raise ValueError('공급원 sport key 형식 오류')
    result=request('odds','/sports/'+sport_key+'/odds',{'regions':'eu','markets':'h2h','oddsFormat':'decimal','dateFormat':'iso'},send)
    if result.status not in ('ok','empty'):return result
    try:
        items=[]
        for raw in result.items:
            if raw['sport_key']!=sport_key:raise ValueError('스포츠 키 불일치')
            timestamp(raw['commence_time'])
            if not isinstance(raw['bookmakers'],list):raise ValueError('bookmaker structure')
            for bookmaker in raw['bookmakers']:
                if not isinstance(bookmaker,dict) or not isinstance(bookmaker.get('markets'),list):raise ValueError('market structure')
                for market in bookmaker['markets']:
                    if not isinstance(market,dict) or not isinstance(market.get('outcomes'),list):raise ValueError('outcome structure')
                    for outcome in market['outcomes']:
                        if not isinstance(outcome,dict):raise ValueError('outcome structure')
            items.append({'provider':'The Odds API','provider_match_id':str(raw['id']),'home':raw['home_team'],'away':raw['away_team'],'kickoff':raw['commence_time'],'bookmakers':raw['bookmakers'],'source':result.source,'collected_at':result.collected_at,'raw':raw,'betman':False,'match_confirmed':False})
        result.items=items
    except (KeyError,ValueError,TypeError):result.status='schema_error';result.items=[];result.message='해외 배당 응답 검수 실패'
    return result


def odds_rows(event,now=None):
    now=now or datetime.now(timezone.utc);rows=[]
    for bookmaker in event['bookmakers']:
        for market in bookmaker.get('markets',[]):
            updated=market.get('last_update') or bookmaker.get('last_update')
            try:
                age=(now-timestamp(updated)).total_seconds();fresh=0<=age<=900
            except (ValueError,TypeError):fresh=False
            for outcome in market.get('outcomes',[]):
                try: valid_price=math.isfinite(float(outcome.get('price'))) and float(outcome['price'])>1
                except (ValueError,TypeError): valid_price=False
                rows.append({'북메이커':bookmaker.get('title'), '상품':market.get('key'),'선택':outcome.get('name'),'해외 배당':outcome.get('price'),'기준점':outcome.get('point'),'provider_updated_at':updated,'상태':('배당 형식 오류: 사용 보류' if not valid_price else '15분 이내 시각 (정산범위 미확인)' if fresh else '오래됨/갱신시각 미확인: 사용 보류'),'베트맨':'아님'})
    return rows
