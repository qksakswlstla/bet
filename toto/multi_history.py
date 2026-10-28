import json
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
from .multisport import validate,analyzable,fixture,group,settle_outcome,outcomes,simulate
from .validation import timestamp,kst


def load(path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, payload TEXT)')
        return [json.loads(x[0]) for x in db.execute('SELECT payload FROM records')]


def save(path,row,now=None):
    now=now or datetime.now(timezone.utc)
    if not analyzable(row,validate([row],now)[0]) or now>=timestamp(row['deadline']):raise ValueError('검수·시각·근거 확인 필요')
    if any(tuple(x['group'])==group(row) and tuple(x['fixture'])==fixture(row) and x['row']['kind']==row['kind'] for x in load(path)):raise ValueError('동일 경기·상품 첫 예측을 이미 저장했습니다.')
    result=simulate(row)
    # 경기 중 조건은 사전 예측 기록에서 제외.
    if any(row['params'].get(k,0)!=0 for k in ['minute','home_score','away_score']):raise ValueError('경기 중 조건은 사전 예측으로 저장할 수 없습니다.')
    record={'id':str(uuid.uuid4()),'row':row,'fixture':fixture(row),'group':group(row),'created_at':now.isoformat(),'prediction':result,'result':None}
    with sqlite3.connect(path) as db:db.execute('INSERT INTO records VALUES (?,?)',(record['id'],json.dumps(record,ensure_ascii=False)))
    return record


def record_result(path,pid,result,source,confirmed,now=None):
    now=now or datetime.now(timezone.utc)
    item=next((x for x in load(path) if x['id']==pid),None)
    if item is None:raise ValueError('예측 ID를 찾을 수 없습니다.')
    if item['result'] or not source.strip() or not confirmed or now<timestamp(item['row']['kickoff']):raise ValueError('공식 종료 확인·출처·시각 필요. 결과 덮어쓰기 불가')
    outcome=settle_outcome(item['row'],result)
    item['result']={'official':result,'settlement_outcome':outcome,'source':source,'recorded_at':now.isoformat()}
    with sqlite3.connect(path) as db:db.execute('UPDATE records SET payload=? WHERE id=?',(json.dumps(item,ensure_ascii=False),pid))


def audited_records(records,now=None):
    now=now or datetime.now(timezone.utc)
    accepted=[];excluded=[];seen=set()
    for x in records:
        try:
            row=x['row'];created=timestamp(x['created_at']);result=x.get('result')
            if not result: raise ValueError('공식 종료 결과 미확보')
            if validate([row],created)[0]['errors'] or not analyzable(row,validate([row],created)[0]):
                raise ValueError('입력·근거 검수 실패')
            if not timestamp(row['as_of'])<=timestamp(row['collected_at'])<=created<timestamp(row['deadline'])<=timestamp(row['kickoff']):
                raise ValueError('예측 시각 누수')
            for k in ['minute','home_score','away_score']:
                if float(row['params'].get(k,0))!=0: raise ValueError('경기 중 상황이 사전 기록에 포함됨')
            if not timestamp(row['kickoff'])<=timestamp(result['recorded_at'])<=now or not result.get('source'):
                raise ValueError('종료 결과 시각·출처 오류')
            prediction=x['prediction'];keys=outcomes(row)
            if not prediction.get('version') or set(prediction['probabilities'])!=set(keys):raise ValueError('모형 버전·선택지 오류')
            vals=np.array([prediction['probabilities'][k] for k in keys],float)
            if not np.isfinite(vals).all() or (vals<0).any() or (vals>1).any() or abs(vals.sum()-1)>1e-9:
                raise ValueError('확률 범위·합계 오류')
            if prediction['params']!={k:float(v) for k,v in row['params'].items()}:
                raise ValueError('기록 입력과 계산 입력 불일치')
            if prediction['market']!=row['market'] or str(prediction.get('line',''))!=str(row.get('line','')) or tuple(prediction['scope'])!=tuple(row[k] for k in ['competition','season','division']):
                raise ValueError('예측 상품·대회 불일치')
            if settle_outcome(row,result['official'])!=result['settlement_outcome']:
                raise ValueError('공식 결과와 정산 결과 불일치')
            identity=(*group(row),*fixture(row),row['kind'])
            if identity in seen:raise ValueError('중복 평가 표본')
            seen.add(identity);accepted.append(x)
        except (KeyError,ValueError,TypeError,OverflowError) as exc:
            excluded.append({'id':x.get('id','미확인'),'사유':str(exc)})
    return accepted,excluded


def evaluate(records,now=None):
    buckets={}
    accepted,_=audited_records(records,now)
    for x in accepted:
        row=x['row']
        key=(*group(row),row['kind'],x['prediction']['version'])
        buckets.setdefault(key,[]).append(x)
    out={}
    for key,items in buckets.items():
        items.sort(key=lambda x:timestamp(x['row']['kickoff']))
        def metrics(xs):
            if not xs:return {'n':0}
            probs=[];targets=[];markets=[];profits=[]
            for x in xs:
                keys=outcomes(x['row']);p=[x['prediction']['probabilities'][k] for k in keys];y=[float(k==x['result']['settlement_outcome']) for k in keys]
                odds=np.array([x['row']['odds'][k] for k in keys],float);inv=1/odds
                probs.append(p);targets.append(y);markets.append(inv/inv.sum())
                if x['row']['kind']=='real' and x['row']['rules_verified'] and x['row'].get('odds_available_verified'):
                    pick=int(np.argmax(p));profits.append(1000*(odds[pick]*y[pick]-1))
            p=np.array(probs);y=np.array(targets)
            def score(v):return {'Brier':float(((v-y)**2).sum(axis=1).mean()),'log_loss':float(-(y*np.log(np.clip(v,1e-15,1))).sum(axis=1).mean())}
            equity=np.r_[0,np.cumsum(profits)]
            bins=[]
            for i in range(5):
                mask=(p>=i/5)&(p<((i+1)/5) if i<4 else p<=1)
                bins.append({'구간':f'{i*20}~{(i+1)*20}%','건수':int(mask.sum()),'평균 예측':float(p[mask].mean()) if mask.any() else None,'실제 비율':float(y[mask].mean()) if mask.any() else None})
            return {'n':len(xs),'period':[kst(xs[0]['row']['kickoff']),kst(xs[-1]['row']['kickoff'])],'model':score(p),'market':score(np.array(markets)),'uniform':score(np.full_like(p,1/p.shape[1])),'calibration':bins,'settled_n':len(profits),'roi':sum(profits)/(1000*len(profits)) if profits else None,'max_drawdown':float((np.maximum.accumulate(equity)-equity).max()) if profits else None}
        # 같은 시작 시각의 경기는 분할 경계를 넘기지 않음. 학습 실행은 아님.
        times=sorted({timestamp(x['row']['kickoff']) for x in items})
        n=len(times);first=set(times[:int(n*.6)]);second=set(times[int(n*.6):int(n*.8)])
        out[' / '.join(map(str,key))]={'전체':metrics(items),'학습 참고 60% (학습 없음)':metrics([x for x in items if timestamp(x['row']['kickoff']) in first]),'검증 20%':metrics([x for x in items if timestamp(x['row']['kickoff']) in second]),'별도 평가 20%':metrics([x for x in items if timestamp(x['row']['kickoff']) not in first|second])}
    return out
