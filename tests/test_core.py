import math
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest
from toto.model import probabilities, implied, simulate, OUTCOMES
from toto.validation import validate, eligible, kst
from toto.demo import example_matches, example_history
from toto.input import read_csv, csv_text
from toto.combinations import compare, settle
from toto.history import save_prediction, save_result, load_history, evaluate


def test_poisson_known_cases_and_mass():
    p = probabilities(0, 0)
    assert [p[k] for k in OUTCOMES] == [0, 1, 0]
    p = probabilities(1.5, 1.5)
    assert p['home'] == pytest.approx(p['away'])
    for h,a in [(0,1),(1.6,1.1),(8,8),(0,0)]:
        p = probabilities(h,a,1,2.5)
        assert sum(p[k] for k in OUTCOMES) == pytest.approx(1)
        assert sum(p['handicap'].values()) == pytest.approx(1)
        assert sum(p['total'].values()) == pytest.approx(1)
        assert all(0<=p[k]<=1 for k in OUTCOMES)
    assert probabilities(0,0,1)['handicap']['home'] == 1
    assert probabilities(0,0,total=0)['total']['push'] == 1
    assert probabilities(1,0)['draw'] == pytest.approx(math.exp(-1))


@pytest.mark.parametrize('rate',[float('nan'),float('inf'),-1,9])
def test_bad_rates(rate):
    with pytest.raises(ValueError):
        probabilities(rate,1)


def test_market_margin():
    p = implied([2,3,4])
    assert p['margin'] == pytest.approx(1/12)
    assert sum(p['adjusted']) == pytest.approx(1)
    assert p['adjusted'][0] == pytest.approx((1/2)/(13/12))
    with pytest.raises(ValueError):
        implied([1,3,4])


def test_simulation_reproducible_and_conditional():
    x = simulate(1.6,1.1,100000,42)
    assert x == simulate(1.6,1.1,100000,42)
    for k in OUTCOMES:
        assert abs(x['probabilities'][k]-x['exact'][k]) < .01
    assert simulate(1.6,1.1,1000,2,90,(1,0))['probabilities']['home'] == 1
    assert simulate(1.6,1.1,1000,2,90,(0,0))['exact']['draw'] == 1
    assert simulate(1.6,1.1,1000,2,0,(0,0),.5,1)['exact']['home'] < x['exact']['home']


def test_csv_roundtrip_and_limits():
    rows = example_matches()
    parsed = read_csv('\ufeff'+csv_text(rows))
    assert parsed[0]['home'] == rows[0]['home']
    assert not validate(parsed)[0]['errors']
    for text in ['a,a\n1,2','a, a\n1,2','a,b\n1','a,b\n1,2,3','a\n'+'1\n'*101]:
        with pytest.raises(ValueError):
            read_csv(text)


@pytest.mark.parametrize('field,value',[
    ('home_odds',''),('draw_odds','NaN'),('away_xg',''),('home_xg','inf'),
    ('product','ASIAN_-0.25'),('kickoff','2026-11-01T19:00:00'),('kind','anything'),
])
def test_invalid_input(field,value):
    row=example_matches()[0]
    row[field]=value
    assert validate([row])[0]['errors']


def test_duplicate_teams_times_and_freshness():
    rows=example_matches()
    assert validate([rows[0],rows[0]])[1]['errors']
    dup=rows[0].copy(); dup['match_id']='different'
    assert validate([rows[0],dup])[1]['errors']
    rows[1]['home']=' 예시 홈팀 1 '
    assert validate(rows)[1]['errors']
    row=example_matches()[0]
    now=datetime.now(timezone.utc)
    row['collected_at']=(now+timedelta(days=3)).isoformat()
    assert validate([row])[0]['errors']
    row=example_matches()[0]
    report=validate([row],now+timedelta(days=4))[0]
    assert not eligible(row,report,now+timedelta(days=4))
    assert 'KST' in kst(row['kickoff'])


def test_comparison_budget_and_no_same_fixture():
    legs=[{'match_id':str(i),'label':str(i),'probability':.5,'low':.4,'high':.6,'odds':2.2} for i in range(3)]
    combos=compare(legs,2,10000)
    assert len(combos)==3
    x=combos[0]
    assert x['probability']==.25
    assert x['odds']==pytest.approx(4.84)
    assert x['expected_profit']==pytest.approx(2100)
    assert x['low_expected_profit'] < 0
    assert len(compare(legs,3))==1
    legs[1]['match_id']='0'
    assert len(compare(legs,3))==0


@pytest.mark.parametrize('statuses,expected',[
    (['win','win'],600),(['loss','win'],0),(['void','win'],300),(['void','void'],100),(['void','loss'],0)
])
def test_settlement(statuses,expected):
    result=settle([{'odds':2,'status':statuses[0]},{'odds':3,'status':statuses[1]}],100)
    assert result['return']==expected
    assert result['profit']==expected-100


def test_history_fixed_snapshot_and_leakage(tmp_path):
    path=tmp_path/'history.sqlite3'
    row=example_matches()[0]
    now=datetime.now(timezone.utc)
    saved=save_prediction(path,row,now)
    row['home_odds']='99'
    assert load_history(path)[0]['row']['home_odds'] != '99'
    with pytest.raises(ValueError):
        save_prediction(path,row,now)
    with pytest.raises(ValueError):
        save_prediction(tmp_path/'late.sqlite3',row,now+timedelta(days=3))
    with pytest.raises(ValueError):
        save_result(path,saved['id'],'finished',2,1,'official',True,now)
    save_result(path,saved['id'],'finished',2,1,'official',True,now+timedelta(days=3))
    with pytest.raises(ValueError):
        save_result(path,saved['id'],'finished',0,0,'official',True,now+timedelta(days=3))
    evaluated=evaluate(load_history(path),'example')
    assert evaluated['n']==1
    assert evaluated['all']['settled_n']==1


def test_evaluation_metrics_baselines_and_splits():
    items=example_history()
    result=evaluate(items,'example')
    assert result['n']==30
    assert [m['n'] for m in result['splits'].values()]==[18,6,6]
    assert result['all']['uniform']['brier']==pytest.approx(2/3)
    assert result['all']['uniform']['log_loss']==pytest.approx(math.log(3))
    assert sum(x['건수'] for x in result['all']['calibration'])==90
    assert result['all']['max_drawdown']>=0
    assert not result['validated']
    assert evaluate(items,'real')['n']==0
    leaked=deepcopy(items)
    leaked[0]['created_at']=leaked[0]['row']['kickoff']
    leaked[1]['probabilities']=[.6,.6,.2]
    leaked[2]['row']['as_of']=leaked[2]['row']['kickoff']
    result=evaluate(leaked,'example')
    assert result['n']==27
    assert len(result['excluded'])==3


def test_metrics_known_predictions_and_unconfirmed_odds():
    items=example_history()[:3]
    for x in items:
        r=x['result']; y=0 if r['home']>r['away'] else 1 if r['home']==r['away'] else 2
        x['probabilities']=[float(i==y) for i in range(3)]
        r['odds_and_rules_confirmed']=False
    result=evaluate(items,'example')['all']
    assert result['model']['brier']==0
    assert result['model']['log_loss']==0
    assert result['model']['accuracy']==1
    assert result['settled_n']==0
    assert result['roi'] is None
