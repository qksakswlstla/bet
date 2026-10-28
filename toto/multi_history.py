import json
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
from .multisport import validate,analyzable,fixture,group,settle_outcome,outcomes,simulate
from .validation import timestamp


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
    item=next(x for x in load(path) if x['id']==pid)
    if item['result'] or not source.strip() or not confirmed or now<timestamp(item['row']['kickoff']):raise ValueError('공식 종료 확인·출처·시각 필요. 결과 덮어쓰기 불가')
    outcome=settle_outcome(item['row'],result)
    item['result']={'official':result,'settlement_outcome':outcome,'source':source,'recorded_at':now.isoformat()}
    with sqlite3.connect(path) as db:db.execute('UPDATE records SET payload=? WHERE id=?',(json.dumps(item,ensure_ascii=False),pid))


def evaluate(records):
    buckets={}
    for x in records:
        row=x['row']
        if not x['result']:continue
        if not timestamp(row['as_of'])<=timestamp(row['collected_at'])<=timestamp(x['created_at'])<timestamp(row['deadline'])<=timestamp(row['kickoff']):continue
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
            return {'n':len(xs),'period':[xs[0]['row']['kickoff'],xs[-1]['row']['kickoff']],'model':score(p),'market':score(np.array(markets)),'uniform':score(np.full_like(p,1/p.shape[1])),'calibration':bins,'settled_n':len(profits),'roi':sum(profits)/(1000*len(profits)) if profits else None,'max_drawdown':float((np.maximum.accumulate(equity)-equity).max())}
        n=len(items);out[' / '.join(map(str,key))]={'전체':metrics(items),'학습 참고 60% (학습 없음)':metrics(items[:int(n*.6)]),'검증 20%':metrics(items[int(n*.6):int(n*.8)]),'별도 평가 20%':metrics(items[int(n*.8):])}
    return out
