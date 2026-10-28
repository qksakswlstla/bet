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
