"""자동 응답 스냅샷과 명시적 대회 매핑. 실제 입력/과거 예측 DB와 분리."""
import json
import sqlite3
from pathlib import Path
from dataclasses import asdict
from datetime import datetime,timezone
from .multisport import COMPETITIONS,MARKETS
from .validation import timestamp


def connect(path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS auto_snapshots (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS auto_bindings (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    return db


def read(path,table,key):
    if table not in ('auto_snapshots','auto_bindings'):raise ValueError('table')
    db=connect(path)
    try:
        row=db.execute(f'SELECT payload FROM {table} WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None
    finally:db.close()


def write(path,table,key,value):
    if table not in ('auto_snapshots','auto_bindings'):raise ValueError('table')
    db=connect(path)
    try:
        with db:db.execute(f'INSERT OR REPLACE INTO {table} VALUES (?,?)',(key,json.dumps(value,ensure_ascii=False)))
    finally:db.close()


def save_fetch(path,key,result):
    previous=read(path,'auto_snapshots',key)
    value=asdict(result)
    value['last_attempt_at']=result.collected_at
    value['last_success_at']=result.collected_at if result.status in ('ok','empty') else previous.get('last_success_at') if previous else None
    # 실패 자료와 마지막 성공 자료는 별도 필드로 구분. 최신 목록으로 승격하지 않음.
    value['previous_items']=previous['items'] if previous and previous['status'] in ('ok','empty') else previous.get('previous_items',[]) if previous else []
    if result.status in ('ok','empty'):value['previous_items']=[]
    write(path,'auto_snapshots',key,value)
    return value


def bind(path,competition,division,sport,league,season):
    if COMPETITIONS.get(competition)!=sport or division not in (['남자부','여자부'] if competition=='KOVO' else ['해당 없음']):raise ValueError('대회·종목·부문 불일치')
    if not league.get('id') or not str(season).strip():raise ValueError('대회 ID/시즌 필요')
    key=json.dumps([competition,division,season],ensure_ascii=False)
    db=connect(path)
    try:
        for (raw,) in db.execute('SELECT payload FROM auto_bindings'):
            old=json.loads(raw)
            if (old['sport'],old['league_id'],old['season'])==(sport,str(league['id']),str(season)) and (old['competition'],old['division'])!=(competition,division):
                raise ValueError('같은 공급원 대회·시즌이 다른 대회/남녀부에 이미 연결되어 있습니다.')
    finally:db.close()
    value={'competition':competition,'division':division,'sport':sport,'league_id':str(league['id']),'season':str(season),'catalog_entry':league,'confirmed_at':datetime.now(timezone.utc).isoformat(),'match_method':'사용자 대회·시즌 확인; 자동 이름 매칭 없음'}
    write(path,'auto_bindings',key,value)
    return value


def usable(snapshot,now=None):
    now=now or datetime.now(timezone.utc)
    if not snapshot or snapshot['status']!='ok':return False
    age=(now-timestamp(snapshot['collected_at'])).total_seconds()
    return 0<=age<=86400


def to_manual(event,binding):
    if (event['provider'],event['league_id'],event['season'])!=('API-Sports/'+binding['sport'],binding['league_id'],binding['season']):raise ValueError('공급원·대회·시즌 불일치')
    prefix='apisports:'+binding['sport']
    return {'competition':binding['competition'],'division':binding['division'],'season':binding['season'],'stage':event['stage'],'match_id':prefix+':game:'+event['provider_match_id'],'home_id':prefix+':team:'+event['provider_home_id'],'away_id':prefix+':team:'+event['provider_away_id'],'home':event['home'],'away':event['away'],'provider':event['provider'],'kickoff':event['kickoff'],'source':event['source']+' | 공급원 경기 ID '+event['provider_match_id'],'collected_at':event['collected_at'],'as_of':'','deadline':'','kind':'real','market':MARKETS[binding['sport']][0],'line':'','rules_version':'','rules_source':'','basis':'자동 확보: 일정·팀 ID·시작 시각. 공급원 갱신 시각·베트맨 상품·모형 입력은 미확보.','params':{},'odds':{},'evidence':[],'rules_verified':False,'model_inputs_supported':False,'combination_verified':False,'odds_available_verified':False,'source_conflict':False,'auto_provenance':{'provider':event['provider'],'provider_match_id':event['provider_match_id'],'provider_home_id':event['provider_home_id'],'provider_away_id':event['provider_away_id'],'league_id':event['league_id'],'source':event['source'],'collected_at':event['collected_at'],'provider_updated_at':event['provider_updated_at'],'data_as_of':event['data_as_of'],'scores':event['scores'],'goals':event['goals'],'mapping':binding}}
