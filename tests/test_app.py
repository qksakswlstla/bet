from pathlib import Path
from streamlit.testing.v1 import AppTest

APP=Path(__file__).resolve().parents[1]/'app.py'


def test_app_demo_scenario_combinations_history(tmp_path,monkeypatch):
    monkeypatch.setenv('BET_DATA_DIR',str(tmp_path))
    at=AppTest.from_file(str(APP),default_timeout=30).run()
    assert not at.exception
    assert len(at.tabs)==6
    assert any('예시 데이터' in x.value for x in at.error)
    at.selectbox(key='leg0').set_value('home')
    at.selectbox(key='leg1').set_value('away')
    at.run()
    assert not at.exception
    assert any('총 배당' in frame.value.columns for frame in at.dataframe)
    # 같은 입력 난수 시드와 조건을 UI로 변경해도 전 화면 렌더링이 완료됨.
    next(x for x in at.slider if x.label.startswith('관측 또는')).set_value(90)
    at.run()
    assert not at.exception
    next(x for x in at.radio if x.label=='평가 자료').set_value('예시 데이터: 합성 과거 30경기')
    at.run()
    assert not at.exception
    assert any('30개' in x.value for x in at.markdown)


def test_app_manual_invalid_then_valid(tmp_path,monkeypatch):
    from toto.demo import example_matches
    monkeypatch.setenv('BET_DATA_DIR',str(tmp_path))
    at=AppTest.from_file(str(APP),default_timeout=30).run()
    at.sidebar.radio[0].set_value('내 CSV / 붙여넣기 / 직접 입력').run()
    next(x for x in at.radio if x.label=='입력 방법').set_value('CSV 붙여넣기').run()
    at.text_area[0].set_value('match_id,home\nbad,팀').run()
    assert not at.exception
    assert any('누락' in x.value for x in at.error)
    from toto.input import csv_text
    at.text_area[0].set_value(csv_text(example_matches())).run()
    assert not at.exception
    assert len(at.selectbox(key='detail').options)==3
