from copy import deepcopy
from datetime import datetime,timezone,timedelta
import pytest
from toto.multisport import demos,simulate,validate,analyzable,settle_outcome,pregame
from toto.multi_history import save,load,record_result,evaluate,audited_records

@pytest.mark.parametrize('row',demos())
def test_numeric_strings_and_no_silent_defaults(row):
    expected=simulate(row,1000,7)
    row['params']={k:str(v) for k,v in row['params'].items()}
    assert simulate(row,1000,7)==expected
    with pytest.raises(ValueError):simulate(row,1000,7,{})
    row['params']['red_cards']=1
    assert not analyzable(row,validate([row])[0])
    with pytest.raises(ValueError):simulate(row,1000,7)

@pytest.mark.parametrize('index',[0,1,2,3,4,5])
def test_parameter_change_reaches_calculation(index):
    row=demos()[index];before=simulate(row,20000,42)
    changed=dict(row['params'])
    if index in [0,3]:changed['home_eff']*=1.3
    elif index in [1,2]:changed['rally_home']+=.1
    else:changed['home_xg']+=1.5
    after=simulate(row,20000,42,changed)
    assert after['probabilities']['home']>before['probabilities']['home']+.1


def test_scenario_secondary_effects():
    r=demos()[0];base=simulate(r,5000,42)
    p=dict(r['params']);p['pace']*=1.3
    assert simulate(r,5000,42,p)['mean_total']>base['mean_total']
    p=dict(r['params']);p['close_pace']=1.5;p['blowout_pace']=1.5
    assert simulate(r,5000,42,p)['mean_total']>base['mean_total']
    r=demos()[1];base=simulate(r,5000,42)
    for key in ['fatigue_per_set','substitution_delta']:
        p=dict(r['params']);p[key]=.1
        assert simulate(r,5000,42,p)['probabilities']['home']>base['probabilities']['home']
    r=demos()[4];p=dict(r['params']);p.update(minute=90,home_score=1,away_score=0)
    assert simulate(r,1000,42,p)['probabilities']['home']==1
    r['params']=p
    assert not pregame(r)


def test_evidence_timestamp_order_and_market_rejection():
    r=demos()[0];now=datetime.now(timezone.utc)
    r['evidence']=[{'type':'official','source':'test','as_of':now.isoformat(),'collected_at':(now-timedelta(days=1)).isoformat()}]
    assert validate([r])[0]['errors']
    r['market']='연장 포함 총득점';r['line']=160
    with pytest.raises(ValueError):settle_outcome(r,{'including_overtime':[90,70]})
    with pytest.raises(ValueError):simulate(r,1000)
    r['line']=160.5
    assert settle_outcome(r,{'including_overtime':[90,70]})=='under'
    r['market']='진출 여부'
    with pytest.raises(ValueError):simulate(r,1000)


def completed(tmp_path):
    now=datetime.now(timezone.utc);r=demos()[0];r.update(kind='real',rules_verified=True,model_inputs_supported=True)
    path=tmp_path/'audit.sqlite3';item=save(path,r,now)
    record_result(path,item['id'],{'including_overtime':[90,80]},'manual official source',True,now+timedelta(days=3))
    return load(path),now+timedelta(days=3)

@pytest.mark.parametrize('corrupt',['probability','outcome','result_time','evidence','params','market','duplicate'])
def test_corrupt_history_excluded(tmp_path,corrupt):
    records,now=completed(tmp_path);r=records[0]
    if corrupt=='probability':r['prediction']['probabilities']['home']=float('nan')
    if corrupt=='outcome':r['result']['settlement_outcome']='away'
    if corrupt=='result_time':r['result']['recorded_at']=r['created_at']
    if corrupt=='evidence':r['row']['evidence']=[{'type':'official','source':'x','as_of':now.isoformat(),'collected_at':now.isoformat()}]
    if corrupt=='params':r['prediction']['params']['pace']=42
    if corrupt=='market':r['prediction']['market']='90분 승무패'
    if corrupt=='duplicate':records.append(deepcopy(r))
    accepted,excluded=audited_records(records,now)
    assert len(excluded)==1
    assert len(accepted)==(1 if corrupt=='duplicate' else 0)


def test_metrics_no_odds_no_roi_and_known_scores(tmp_path):
    records,now=completed(tmp_path)
    result=next(iter(evaluate(records,now).values()))['전체']
    assert result['settled_n']==0 and result['roi'] is None and result['max_drawdown'] is None
    records[0]['prediction']['probabilities']={'home':1.,'away':0.}
    records[0]['row']['odds_available_verified']=True
    result=next(iter(evaluate(records,now).values()))['전체']
    assert result['model']['Brier']==0 and result['model']['log_loss']==0
    assert result['uniform']['Brier']==.5
    assert result['roi']==1

def test_unknown_combination_uncertainty_stays_unknown():
    from toto.combinations import compare
    legs=[{'match_id':str(i),'label':str(i),'probability':.5,'odds':2.2} for i in range(2)]
    result=compare(legs,2,10000)[0]
    assert result['probability']==.25
    assert result['expected_profit']==pytest.approx(2100)
    assert result['sensitivity_low'] is None and result['low_expected_profit'] is None
