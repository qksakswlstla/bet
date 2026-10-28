"""실제 응답 캡처가 아닌 합성 스키마 테스트. 네트워크 호출하지 않음."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from urllib.error import HTTPError,URLError
import json
import pytest
from toto.providers import request,catalog,games,overseas_odds,odds_rows,FetchResult
from toto.auto_store import bind,save_fetch,read,to_manual,usable
from toto.multisport import validate,analyzable


def synthetic(sport):
    row={'id':10,'date':'2026-11-01T10:00:00+00:00','status':{'short':'NS'},'league':{'id':7,'name':'합성 대회','season':'2026'},'teams':{'home':{'id':1,'name':'합성 홈'},'away':{'id':2,'name':'합성 원정'}},'scores':{'home':{'total':None},'away':{'total':None}}}
    if sport=='football':
        row['fixture']={'id':row.pop('id'),'date':row.pop('date'),'status':row.pop('status')}
        row['score']={'fulltime':{'home':None,'away':None}};row['goals']={'home':None,'away':None}
    return {'errors':{},'response':[row]}


def sender(payload):return lambda url,headers:(deepcopy(payload),{'x-requests-remaining':'99'})


def test_no_key_no_network(monkeypatch):
    monkeypatch.delenv('APISPORTS_KEY',raising=False)
    def fail(*args):raise AssertionError('must not connect')
    assert catalog('basketball',fail).status=='missing_key'

@pytest.mark.parametrize('sport',['basketball','volleyball','football'])
def test_mapping_and_incomplete_analysis(tmp_path,monkeypatch,sport):
    monkeypatch.setenv('APISPORTS_KEY','synthetic-key-only')
    result=games(sport,'7','2026','2026-11-01','2026-11-01',sender(synthetic(sport)))
    assert result.status=='ok' and len(result.items)==1
    comp={'basketball':'KBL','volleyball':'KOVO','football':'J리그컵'}[sport]
    division='남자부' if sport=='volleyball' else '해당 없음'
    binding=bind(tmp_path/'db',comp,division,sport,{'id':'7'},'2026')
    row=to_manual(result.items[0],binding)
    assert row['odds']=={} and row['deadline']=='' and row['params']=={}
    assert row['as_of']=='' and row['auto_provenance']['provider_updated_at'] is None
    assert not analyzable(row,validate([row])[0])
    assert row['match_id']==f'apisports:{sport}:game:10'
    assert row['home_id']==f'apisports:{sport}:team:1'


def test_empty_vs_invalid_vs_error_and_no_secret(monkeypatch):
    monkeypatch.setenv('APISPORTS_KEY','never-store-this')
    assert request('basketball','/games',send=sender({'errors':{},'response':[]})).status=='empty'
    assert request('basketball','/games',send=sender({'message':'oops'})).status=='schema_error'
    assert request('basketball','/games',send=sender({'errors':{'key':'never-store-this'},'response':[]})).status=='api_error'
    result=request('basketball','/games',send=sender({'errors':{},'response':[{'echo':'never-store-this','apiKey':'never-store-this'}]}))
    assert 'never-store-this' not in json.dumps(result.__dict__)
    assert request('basketball','/games',send=sender({'errors':{},'response':[],'paging':{'total':2}})).status=='incomplete'

@pytest.mark.parametrize('code,status',[(401,'unauthorized'),(403,'forbidden'),(429,'rate_limited'),(500,'http_error')])
def test_http_states(monkeypatch,code,status):
    monkeypatch.setenv('ODDS_API_KEY','do-not-log-me')
    def send(url,headers):raise HTTPError(url,code,'do-not-log-me',{},None)
    r=request('odds','/sports',send=send)
    assert r.status==status and 'do-not-log-me' not in json.dumps(r.__dict__)


def test_wrong_league_season_and_kst_filter(monkeypatch):
    monkeypatch.setenv('APISPORTS_KEY','test')
    payload=synthetic('basketball')
    assert games('basketball',8,'2026','2026-11-01','2026-11-01',sender(payload)).status=='schema_error'
    assert games('basketball',7,'2025','2026-11-01','2026-11-01',sender(payload)).status=='schema_error'
    payload['response'][0]['date']='2026-10-31T16:00:00+00:00'
    assert games('basketball',7,'2026','2026-11-01','2026-11-01',sender(payload)).status=='ok'
    assert games('basketball',7,'2026','2026-11-02','2026-11-02',sender(payload)).status=='empty'


def test_refresh_does_not_promote_previous(tmp_path):
    path=tmp_path/'db';old=FetchResult('ok',[{'id':1}])
    save_fetch(path,'x',old)
    failed=save_fetch(path,'x',FetchResult('connection_error',message='failure'))
    assert failed['items']==[] and failed['previous_items']==[{'id':1}] and not usable(failed)
    empty=save_fetch(path,'x',FetchResult('empty'))
    assert empty['items']==[] and empty['previous_items']==[] and not usable(empty)
    old.collected_at=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
    assert not usable(save_fetch(path,'x',old))


def test_division_binding_conflict(tmp_path):
    path=tmp_path/'db'
    bind(path,'KOVO','남자부','volleyball',{'id':'7'},'2026')
    with pytest.raises(ValueError):bind(path,'KOVO','여자부','volleyball',{'id':'7'},'2026')
    with pytest.raises(ValueError):bind(path,'NBA','여자부','basketball',{'id':'8'},'2026')


def test_overseas_not_betman_and_stale(monkeypatch):
    monkeypatch.setenv('ODDS_API_KEY','synthetic-test-key')
    raw={'sport_key':'basketball_nba','id':'123','home_team':'합성 홈','away_team':'합성 원정','commence_time':'2026-11-01T12:00:00Z','bookmakers':[{'title':'합성 해외 북메이커','markets':[{'key':'h2h','outcomes':[{'name':'합성 홈','price':1.9}]}]}]}
    result=overseas_odds('basketball_nba',sender([raw]))
    assert result.status=='ok' and not result.items[0]['betman'] and not result.items[0]['match_confirmed']
    assert '사용 보류' in odds_rows(result.items[0])[0]['상태']
    assert 'synthetic-test-key' not in json.dumps(result.__dict__)

def test_credentials_not_forwarded_on_redirect():
    from urllib.request import Request
    from toto.providers import NoRedirect
    req=Request('https://v1.basketball.api-sports.io/leagues',headers={'x-apisports-key':'synthetic-key'})
    with pytest.raises(HTTPError):NoRedirect().redirect_request(req,None,302,'moved',{},'https://other.example/')


def test_invalid_overseas_price_is_not_usable():
    event={'bookmakers':[{'title':'synthetic','last_update':datetime.now(timezone.utc).isoformat(),'markets':[{'key':'h2h','outcomes':[{'name':'home','price':'nan'}]}]}]}
    assert '배당 형식 오류' in odds_rows(event)[0]['상태']

@pytest.mark.parametrize('errors,expected',[
 ({'plan':'Free plans do not have access to season 2026-2027'},'시즌/요금제'),
 ({'authentication':'Invalid API key'},'인증 실패'),
 ({'requests':'Request limit reached'},'호출 한도'),
 ({'season':'Season must be YYYY-YYYY'},'요청 조건'),
 ({'other':'Something happened'},'원인 미확인'),
])
def test_error_details_and_context(monkeypatch,tmp_path,errors,expected):
    monkeypatch.setenv('APISPORTS_KEY','test-secret')
    result=request('basketball','/games',{'league':12,'season':'2026-2027'},sender({'errors':errors}))
    assert result.errors==errors
    assert expected in ' '.join(result.causes)
    assert result.request_context=={'sport':'basketball','league':'12','season':'2026-2027'}
    saved=save_fetch(tmp_path/'db','failure',result)
    assert saved['errors']==errors and saved['request_context']==result.request_context


def test_error_secret_and_private_redaction(monkeypatch):
    monkeypatch.setenv('APISPORTS_KEY','secret+key/123')
    monkeypatch.setenv('ODDS_API_KEY','second-secret')
    errors={'plan':'Season 2026-2027 not available on free plan', 'details':['secret+key/123 secret%2Bkey%2F123 second-secret','Contact user@example.com 010-1234-5678 192.168.1.1','Authorization: Bearer unrelated-token'], 'headers':{'X-Api-Key':'third-secret'},'email':'private@example.org','full_name':'Private Person'}
    result=request('basketball','/games',send=sender({'errors':errors}))
    encoded=json.dumps(result.__dict__)
    for secret in ['secret+key/123','secret%2Bkey%2F123','second-secret','unrelated-token','third-secret','user@example.com','010-1234-5678','192.168.1.1','Private Person']:
        assert secret not in encoded
    assert result.errors['plan']==errors['plan']

def test_http_json_errors_are_preserved(monkeypatch):
    import io
    monkeypatch.setenv('APISPORTS_KEY','test-key')
    def send(url,headers):
        raise HTTPError(url,403,'forbidden',{},io.BytesIO(b'{"errors":{"plan":"Season not allowed on this plan"}}'))
    result=request('basketball','/games',{'league':12,'season':'2026-2027'},send)
    assert result.status=='forbidden'
    assert result.errors['plan']=='Season not allowed on this plan'
    assert '시즌/요금제' in result.causes[0]
