"""대회별 자료 경계와 종목별 조건부 모형. 학습된 계수는 제공하지 않는다."""
import json
import math
from datetime import datetime, timezone, timedelta
from collections import Counter
import numpy as np
from .validation import timestamp

COMPETITIONS = {'KBL':'basketball', 'KOVO':'volleyball', 'NBA':'basketball', 'J리그컵':'football', 'AFC 챔피언스리그 엘리트':'football'}
VERSIONS = {'basketball':'shared-pace-conditional-1', 'volleyball':'rally-set-conditional-1', 'football':'poisson-90-conditional-2'}
MARKETS = {'basketball':['연장 포함 승패','연장 포함 점수 핸디캡','연장 포함 총득점'], 'volleyball':['경기 승패','세트 핸디캡','경기 총득점'], 'football':['90분 승무패','90분 3-way 핸디캡','90분 총득점']}
# 실제 수치 추정치가 아닌 예시 전용 가정. 실자료 입력에는 자동 주입하지 않음.
EXAMPLE_PARAMS = {'basketball':{'pace':80.,'pace_sd':5.,'home_eff':1.1,'away_eff':1.05,'residual_sd':8.,'close_pace':1.05,'blowout_pace':.95,'overtime_fraction':.125},'volleyball':{'rally_home':.52,'fatigue_per_set':0.,'substitution_delta':0.,'substitution_after_point':15},'football':{'home_xg':1.5,'away_xg':1.1,'minute':0,'home_score':0,'away_score':0}}


def scope(row):
    return (row['competition'], row['season'], row['division'])


def fixture(row):
    return (*scope(row), row['match_id'])


def group(row):
    return (*scope(row), row['market'], str(row.get('line','')), row['rules_version'])


def outcomes(row):
    if '총득점' in row['market']:
        return ['over','under']
    if row['market'] in ('90분 승무패','90분 3-way 핸디캡'):
        return ['home','draw','away']
    return ['home','away']


def validate_market(row):
    sport=COMPETITIONS.get(row.get('competition'))
    if sport is None or row.get('market') not in MARKETS[sport]:
        raise ValueError('지원하지 않는 대회·상품')
    market=row['market'];raw=row.get('line','')
    if '핸디캡' not in market and '총득점' not in market:
        if str(raw).strip(): raise ValueError('승패 상품에 기준점 사용 불가')
        return
    line=float(raw)
    if not math.isfinite(line): raise ValueError('기준점은 유한한 수여야 합니다.')
    if market=='90분 3-way 핸디캡':
        if not line.is_integer(): raise ValueError('정수 3-way 핸디캡만 지원')
    elif line%1!=.5: raise ValueError('환급 상품 미지원: 반점 기준만 지원')


def pregame(row,now=None):
    now=now or datetime.now(timezone.utc)
    return now<timestamp(row['deadline']) and all(float(row['params'].get(k,0))==0 for k in ['minute','home_score','away_score'])


def number(params,key,lo,hi):
    x=float(params[key])
    if not math.isfinite(x) or not lo<=x<=hi:
        raise ValueError(f'{key}: {lo}~{hi} 범위가 필요합니다.')
    return x


def check_params(sport,p):
    if not isinstance(p,dict) or set(p)!=set(EXAMPLE_PARAMS[sport]):
        raise ValueError('필수 모형 변수 누락 또는 지원하지 않는 변수입니다. 선수 이름/퇴장 수를 자동 계수로 처리하지 않습니다.')
    if any(isinstance(v,bool) for v in p.values()): raise ValueError('모형 변수는 숫자여야 합니다.')
    if sport=='football':
        for k in ['home_xg','away_xg']: number(p,k,0,8)
        number(p,'minute',0,90)
        for k in ['home_score','away_score']:
            x=number(p,k,0,30)
            if x!=int(x): raise ValueError('점수는 정수여야 합니다.')
    elif sport=='basketball':
        for k,lo,hi in [('pace',20,150),('pace_sd',0,30),('home_eff',.1,3),('away_eff',.1,3),('residual_sd',.1,40),('close_pace',.5,1.5),('blowout_pace',.5,1.5),('overtime_fraction',.01,.5)]: number(p,k,lo,hi)
    else:
        for k,lo,hi in [('rally_home',.05,.95),('fatigue_per_set',-.1,.1),('substitution_delta',-.3,.3),('substitution_after_point',0,60)]: number(p,k,lo,hi)


def validate(rows,now=None):
    now=now or datetime.now(timezone.utc)
    reports=[]; seen=set(); identities={}; aliases={}; fixtures_by_teams={}
    for r in rows:
        errors=[]; warnings=[]
        try:
            for flag in ['rules_verified','model_inputs_supported','combination_verified','odds_available_verified','source_conflict']:
                if flag in r and type(r[flag])!=bool: errors.append('확인 표시는 true/false만 허용: '+flag)
            for k in ['competition','season','division','stage','match_id','home_id','away_id','home','away','kickoff','deadline','source','collected_at','as_of','kind','market','rules_version','rules_source','basis']:
                if not str(r.get(k,'')).strip(): errors.append(f'필수 항목 누락: {k}')
            sport=COMPETITIONS[r['competition']]
            if r['division'] not in (['남자부','여자부'] if r['competition']=='KOVO' else ['해당 없음']): errors.append('남녀 구분이 대회와 맞지 않습니다.')
            if r['kind'] not in ('example','real'): errors.append('실제/예시 구분 오류')
            if r['market'] not in MARKETS[sport]: errors.append('해당 종목에서 지원하지 않는 상품입니다.')
            if r['home_id']==r['away_id']: errors.append('홈·원정 팀 ID가 같습니다.')
            key=(*fixture(r),r['market'],str(r.get('line','')))
            if key in seen: errors.append('같은 경기·상품·기준점 중복')
            seen.add(key)
            team_pair=(r['home_id'],r['away_id'],timestamp(r['kickoff']))
            if fixture(r) in identities and identities[fixture(r)]!=team_pair: errors.append('경기 ID에 서로 다른 팀/시각이 연결되었습니다.')
            identities[fixture(r)]=team_pair
            physical=(*scope(r),*team_pair)
            if physical in fixtures_by_teams and fixtures_by_teams[physical]!=r['match_id']: errors.append('같은 팀·시각 경기에 다른 경기 ID 사용')
            fixtures_by_teams[physical]=r['match_id']
            for side in ['home','away']:
                alias=(*scope(r),str(r.get('provider','manual')), ''.join(r[side].lower().split()))
                if alias in aliases and aliases[alias]!=r[side+'_id']: errors.append('같은 공급원 팀 이름이 여러 ID에 연결됨')
                aliases[alias]=r[side+'_id']
            ko,dl,col,asof=[timestamp(r[k]) for k in ['kickoff','deadline','collected_at','as_of']]
            if not asof<=col<=now or not col<dl<=ko: errors.append('시각 순서 오류 또는 마감 후 수집')
            if now>=dl: warnings.append('구매 마감 지남: 새 예측·조합 보류')
            if (now-col).total_seconds()>86400: warnings.append('24시간 이상 지난 정보')
            if not isinstance(r.get('odds'),dict): raise ValueError('배당 객체 필요')
            if not isinstance(r.get('params'),dict): raise ValueError('모형 객체 필요')
            keys=outcomes(r)
            if set(r['odds'])!=set(keys): errors.append('상품 선택지와 배당 묶음이 맞지 않습니다.')
            for v in r['odds'].values():
                if not math.isfinite(float(v)) or not 1<float(v)<=1000: errors.append('배당 범위 오류')
            if '핸디캡' in r['market'] or '총득점' in r['market']:
                line=float(r['line'])
                if not math.isfinite(line): errors.append('기준점 오류')
                elif r['market']=='90분 3-way 핸디캡':
                    if not line.is_integer(): errors.append('3-way 핸디캡은 정수 기준만 지원')
                elif line%1!=.5: errors.append('환급 혼동 방지를 위해 반점 기준만 지원')
            elif str(r.get('line','')).strip(): errors.append('승패 상품에는 기준점을 넣지 마세요.')
            try: check_params(sport,r['params'])
            except (KeyError,ValueError,TypeError): warnings.append('모형 입력 미확보/오류: 확률 출력 보류')
            if r['kind']=='real' and (r.get('rules_verified') is not True or r.get('model_inputs_supported') is not True):
                warnings.append('규칙/입력 근거 확인 미완료: 확률 출력 보류')
            if r.get('source_conflict'): warnings.append('출처 충돌: 분석 보류')
            if not isinstance(r.get('evidence',[]),list): raise ValueError('근거 목록 형식 오류')
            for e in r.get('evidence',[]):
                if not isinstance(e,dict): raise ValueError('근거 형식 오류')
                if e.get('type') not in ('official','report','assumption'): errors.append('근거 유형은 official/report/assumption 중 하나')
                if not e.get('source'): errors.append('근거 출처 누락')
                if not timestamp(e['as_of'])<=timestamp(e['collected_at'])<=col: errors.append('개별 근거 기준·수집 시각 순서 오류 또는 미래 정보')
        except (KeyError,ValueError,TypeError,OverflowError):
            errors.append('필수 자료·모형 입력·시각·배당 형식 확인 필요')
        warnings.append('학습·실제 과거 성능·추천 기준 미검증. 입력 가정에 따른 실험용 결과입니다.')
        reports.append({'errors':errors,'warnings':warnings})
    return reports


def analyzable(r,report):
    try: check_params(COMPETITIONS[r['competition']],r['params'])
    except (KeyError,ValueError,TypeError): return False
    return not report['errors'] and not r.get('source_conflict') and (r['kind']=='example' or (r.get('rules_verified') is True and r.get('model_inputs_supported') is True))


def simulate(row,runs=5000,seed=42,params=None):
    if not isinstance(runs,int) or not 1000<=runs<=20000: raise ValueError('실행 횟수 1000~20000')
    validate_market(row)
    sport=COMPETITIONS[row['competition']]; p=dict(row['params'] if params is None else params); check_params(sport,p)
    p={k:float(v) for k,v in p.items()}
    rng=np.random.default_rng(seed); extras={}
    if sport=='football':
        left=(90-p['minute'])/90
        h=rng.poisson(p['home_xg']*left,runs)+p['home_score']; a=rng.poisson(p['away_xg']*left,runs)+p['away_score']
        total=h+a; margin=h-a
        extras['score_distribution']={k:v/runs for k,v in Counter(f'{int(x)}:{int(y)}' for x,y in zip(h,a)).most_common(12)}
    elif sport=='basketball':
        pace=np.maximum(1,rng.normal(p['pace'],p['pace_sd'],runs))
        # 전반 점수차에 따라 후반 속도를 조건부 변경; 계수는 사용자 가정.
        h1=np.maximum(0,rng.normal(pace*p['home_eff']/2,p['residual_sd']/np.sqrt(2)))
        a1=np.maximum(0,rng.normal(pace*p['away_eff']/2,p['residual_sd']/np.sqrt(2)))
        factor=np.where(abs(h1-a1)<=5,p['close_pace'],np.where(abs(h1-a1)>=15,p['blowout_pace'],1.))
        h=np.rint(h1+np.maximum(0,rng.normal(pace*factor*p['home_eff']/2,p['residual_sd']/np.sqrt(2)))).astype(int)
        a=np.rint(a1+np.maximum(0,rng.normal(pace*factor*p['away_eff']/2,p['residual_sd']/np.sqrt(2)))).astype(int)
        extras['regulation_draw_probability']=float(np.mean(h==a))
        for _ in range(100):
            ties=h==a
            if not ties.any(): break
            n=int(ties.sum()); ot=pace[ties]*p['overtime_fraction']
            h[ties]+=rng.poisson(ot*p['home_eff']);a[ties]+=rng.poisson(ot*p['away_eff'])
        if (h==a).any(): raise ValueError('연장 반복 수렴 실패: 결과를 출력하지 않습니다.')
        total=h+a; margin=h-a
        extras['score_correlation']=float(np.corrcoef(h,a)[0,1])
    else:
        hs=np.zeros(runs,int);aws=np.zeros(runs,int);total=np.zeros(runs,int); set_scores=[]
        for si in range(5):
            active=(hs<3)&(aws<3); h=np.zeros(runs,int);a=np.zeros(runs,int);target=15 if si==4 else 25
            for _ in range(10000):
                if not active.any():break
                chance=np.clip(p['rally_home']+si*p['fatigue_per_set']+np.where(h+a>=p['substitution_after_point'],p['substitution_delta'],0),.01,.99)
                win=rng.random(runs)<chance
                h+=active&win;a+=active&~win
                active &= ~((np.maximum(h,a)>=target)&(abs(h-a)>=2))
            if active.any():raise ValueError('듀스 수렴 실패: 미완료 결과는 출력하지 않습니다.')
            played=(hs<3)&(aws<3)
            hs+=played&(h>a);aws+=played&(a>h);total+=h+a
            set_scores.append(np.stack([h,a],axis=1))
        h,a=hs,aws;margin=h-a
        extras['set_score_distribution']={k:v/runs for k,v in Counter(f'{x}:{y}' for x,y in zip(h,a)).items()}
        extras['sample_sets']=[s[0].tolist() for s in set_scores if s[0].sum()>0]
    market=row['market']; line=float(row.get('line') or 0)
    if '총득점' in market: selected={'over':total>line,'under':total<line}
    elif '핸디캡' in market:
        selected={'home':margin+line>0,'away':margin+line<0}
        if sport=='football':selected['draw']=margin+line==0
    else:
        selected={'home':margin>0,'away':margin<0}
        if sport=='football':selected['draw']=margin==0
    probs={k:float(np.mean(selected[k])) for k in outcomes(row)}
    if abs(sum(probs.values())-1)>1e-9: raise ValueError('상품 확률 합계 오류')
    return {'version':VERSIONS[sport], 'scope':list(scope(row)), 'market':market,'line':row.get('line'), 'runs':runs,'seed':seed,'params':p,'probabilities':probs,'mean_total':float(np.mean(total)), 'margin_quantiles':np.quantile(margin,[.05,.5,.95]).tolist(),'total_quantiles':np.quantile(total,[.05,.5,.95]).tolist(),'margin_distribution':{str(k):v/runs for k,v in Counter(margin.tolist()).items()},'total_distribution':{str(k):v/runs for k,v in Counter(total.tolist()).items()},**extras}


def demos():
    now=datetime.now(timezone.utc).replace(microsecond=0);rows=[]
    for comp,sport in COMPETITIONS.items():
        for div in (['남자부','여자부'] if comp=='KOVO' else ['해당 없음']):
            r={'competition':comp,'season':'예시 시즌','division':div,'stage':'예시 단계','match_id':f'DEMO-{comp}-{div}','home_id':'demo-home','away_id':'demo-away','home':'예시 홈팀','away':'예시 원정팀','provider':'example','kickoff':(now+timedelta(days=2)).isoformat(),'deadline':(now+timedelta(days=2,minutes=-10)).isoformat(),'source':'합성 예시','collected_at':now.isoformat(),'as_of':now.isoformat(),'kind':'example','market':MARKETS[sport][0],'line':'','rules_version':'가정 규칙 v1','rules_source':'실제 규정 미확인; 예시 구조 가정','rules_verified':False,'model_inputs_supported':False,'combination_verified':False,'odds_available_verified':False,'source_conflict':False,'basis':'합성 모형 입력, 실제 팀 자료 아님','params':dict(EXAMPLE_PARAMS[sport]),'evidence':[]}
            r['odds']={k:2. if k!='draw' else 3. for k in outcomes(r)};rows.append(r)
    return rows


def official_set_result(sets):
    """25점/5세트15점, 2점차 가정 규칙과 일치하는 결과만 승인."""
    wins=[0,0];points=[0,0]
    if not isinstance(sets,list) or not 3<=len(sets)<=5: raise ValueError('세트는 3~5개')
    for i,pair in enumerate(sets):
        if max(wins)==3 or len(pair)!=2:raise ValueError('종료 후 추가 세트')
        h,a=pair;target=15 if i==4 else 25
        if any(type(v)!=int or v<0 for v in pair):raise ValueError('세트 득점 오류')
        hi,lo=max(pair),min(pair)
        if not (hi==target and lo<=target-2 or hi>target and hi-lo==2):raise ValueError('불가능한 세트 점수')
        wins[0 if h>a else 1]+=1;points[0]+=h;points[1]+=a
    if max(wins)!=3:raise ValueError('미종료 경기')
    return wins,points


def settle_outcome(row,result):
    validate_market(row)
    if not isinstance(result,dict): raise ValueError('공식 결과는 객체 형식이어야 합니다.')
    sport=COMPETITIONS[row['competition']]
    if sport=='volleyball':
        (h,a),points=official_set_result(result['sets']);total=sum(points)
    else:
        field='regulation' if sport=='football' else 'including_overtime'
        h,a=result[field]
        if any(type(v)!=int or v<0 for v in [h,a]):raise ValueError('최종 점수 오류')
        if sport=='basketball' and h==a:raise ValueError('연장 포함 농구 결과는 무승부 불가')
        total=h+a
    line=float(row.get('line') or 0)
    if '총득점' in row['market']:return 'over' if total>line else 'under'
    margin=h-a+(line if '핸디캡' in row['market'] else 0)
    return 'home' if margin>0 else 'away' if margin<0 else 'draw'
