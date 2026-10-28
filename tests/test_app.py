from pathlib import Path
from streamlit.testing.v1 import AppTest
import pytest
APP=Path(__file__).resolve().parents[1]/'app.py'

@pytest.mark.parametrize('comp,division',[('KBL',None),('NBA',None),('KOVO','남자부'),('KOVO','여자부'),('J리그컵',None),('AFC 챔피언스리그 엘리트',None)])
def test_all_competition_screens(tmp_path,monkeypatch,comp,division):
    monkeypatch.setenv('BET_DATA_DIR',str(tmp_path))
    at=AppTest.from_file(str(APP),default_timeout=60).run()
    at.sidebar.selectbox[0].set_value(comp).run()
    if division:at.sidebar.selectbox[1].set_value(division).run()
    assert not at.exception
    assert len(at.tabs)==6
    assert any('예시 데이터' in x.value for x in at.warning)
    at.selectbox(key='leg0').set_value('home')
    at.selectbox(key='leg3').set_value('away').run()
    assert not at.exception
    assert any('배당' in df.value.columns for df in at.dataframe)

def test_real_input_csv_without_supported_model(tmp_path,monkeypatch):
    import csv,io,json
    from toto.multisport import demos
    monkeypatch.setenv('BET_DATA_DIR',str(tmp_path))
    row=demos()[0];row['kind']='real';row['params']={}
    buf=io.StringIO();writer=csv.DictWriter(buf,fieldnames=list(row));writer.writeheader()
    writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list,bool)) else v for k,v in row.items()})
    at=AppTest.from_file(str(APP),default_timeout=60).run()
    at.sidebar.radio[0].set_value('실제/예시 자료 입력').run()
    next(x for x in at.radio if x.label=='입력 방법').set_value('CSV 붙여넣기').run()
    next(x for x in at.text_area if x.label=='CSV 내용').set_value(buf.getvalue()).run()
    assert not at.exception
    assert not any(x.key=='detail' for x in at.selectbox)
    assert any('보류' in x.value for x in at.warning)

def test_demo_times_stable_and_bad_csv_does_not_restore_old_rows(tmp_path,monkeypatch):
    monkeypatch.setenv('BET_DATA_DIR',str(tmp_path))
    at=AppTest.from_file(str(APP),default_timeout=60).run()
    first=at.session_state['example_snapshot'][0]['collected_at']
    at.sidebar.selectbox[0].set_value('NBA').run()
    assert at.session_state['example_snapshot'][0]['collected_at']==first
    at.sidebar.radio[0].set_value('실제/예시 자료 입력').run()
    next(x for x in at.radio if x.label=='입력 방법').set_value('CSV 붙여넣기').run()
    at.session_state['entered']=[{'competition':'NBA','division':'해당 없음','kind':'real'}]
    next(x for x in at.text_area if x.label=='CSV 내용').set_value('a,a\n1,2').run()
    assert at.session_state['entered']==[]
    assert not at.exception
    assert not any(x.key=='detail' for x in at.selectbox)

def test_auto_missing_key_has_no_fake_games(tmp_path,monkeypatch):
    monkeypatch.setenv('BET_DATA_DIR',str(tmp_path))
    monkeypatch.delenv('APISPORTS_KEY',raising=False)
    at=AppTest.from_file(str(APP),default_timeout=60).run()
    at.sidebar.radio[0].set_value('자동 경기 불러오기').run()
    next(x for x in at.button if x.label=='공급원 대회·시즌 목록 조회').click().run()
    assert not at.exception
    assert any('조회 실패' in x.value for x in at.error)
    assert not any(x.key=='detail' for x in at.selectbox)

def test_auto_mocked_fixture_to_manual_flow(tmp_path,monkeypatch):
    from datetime import datetime,timezone,timedelta
    from toto.providers import FetchResult
    import toto.auto_ui as ui
    monkeypatch.setenv('BET_DATA_DIR',str(tmp_path))
    now=datetime.now(timezone.utc).isoformat()
    league={'id':'7','name':'합성 KBL 후보','country':'합성','type':'League','seasons':['2026'],'raw':{'id':7,'seasons':['2026']}}
    event={'provider':'API-Sports/basketball','provider_match_id':'10','provider_home_id':'1','provider_away_id':'2','league_id':'7','season':'2026','home':'합성 홈','away':'합성 원정','kickoff':(datetime.now(timezone.utc)+timedelta(days=2)).isoformat(),'stage':'합성 단계','status':{'short':'NS'},'scores':None,'goals':None,'source':'https://v1.basketball.api-sports.io/games','collected_at':now,'provider_updated_at':None,'data_as_of':None,'raw':{'synthetic_fixture':True}}
    monkeypatch.setattr(ui,'catalog',lambda sport:FetchResult('ok',[league]))
    monkeypatch.setattr(ui,'games',lambda *args:FetchResult('ok',[event]))
    at=AppTest.from_file(str(APP),default_timeout=60).run()
    at.sidebar.radio[0].set_value('자동 경기 불러오기').run()
    next(x for x in at.button if x.label=='공급원 대회·시즌 목록 조회').click().run()
    next(x for x in at.checkbox if x.label.startswith('선택 대회')).check().run()
    next(x for x in at.button if x.label=='경기 불러오기').click().run()
    assert not at.exception
    next(x for x in at.checkbox if x.label.startswith('원자료의 경기')).check().run()
    next(x for x in at.button if x.label=='확인한 일정으로 수동 입력 채우기').click().run()
    assert at.session_state['auto_prefill']['home']=='합성 홈'
    at.sidebar.radio[0].set_value('실제/예시 자료 입력').run()
    assert not at.exception
    assert next(x for x in at.text_input if x.label=='홈 표시 이름').value=='합성 홈'
    assert next(x for x in at.text_input if x.label=='구매 마감').value==''
    assert next(x for x in at.text_input if x.label=='홈 승 배당').value==''

def test_provider_error_details_visible(tmp_path,monkeypatch):
    from toto.providers import FetchResult
    import toto.auto_ui as ui
    monkeypatch.setenv('BET_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(ui,'catalog',lambda sport:FetchResult('api_error',errors={'plan':'Season not allowed'},request_context={'sport':sport,'league':'12','season':'2026-2027'},causes=['시즌/요금제 접근 제한']))
    at=AppTest.from_file(str(APP),default_timeout=60).run()
    at.sidebar.radio[0].set_value('자동 경기 불러오기').run()
    next(x for x in at.button if x.label=='공급원 대회·시즌 목록 조회').click().run()
    assert not at.exception
    assert any('시즌/요금제' in w.value for w in at.warning)
    assert any('Season not allowed' in str(j.value) for j in at.json)
