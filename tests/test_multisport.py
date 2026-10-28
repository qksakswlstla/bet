from copy import deepcopy
from datetime import datetime,timezone,timedelta
import pytest
from toto.multisport import *
from toto.multi_history import save,load,record_result,evaluate
from toto.combinations import compare

@pytest.mark.parametrize('row',demos())
def test_models_reproducible(row):
    assert not validate([row])[0]['errors']
    a=simulate(row,1000,12);assert a==simulate(row,1000,12)
    assert sum(a['probabilities'].values())==pytest.approx(1)
    assert all(0<=v<=1 for v in a['probabilities'].values())
    if COMPETITIONS[row['competition']]=='volleyball':
        assert all(k in ['3:0','3:1','3:2','0:3','1:3','2:3'] for k in a['set_score_distribution'])
        official_set_result(a['sample_sets'])
    if COMPETITIONS[row['competition']]=='basketball':assert 'draw' not in a['probabilities']

@pytest.mark.parametrize('sets',[[[25,24]]*3,[[25,20]]*4,[[15,10]]*3,[[26,20]]*3,[[25,20]]*2])
def test_illegal_sets(sets):
    with pytest.raises(ValueError):official_set_result(sets)

def test_legal_deuce_and_fifth():
    wins,points=official_set_result([[27,25],[20,25],[25,20],[20,25],[17,15]])
    assert wins==[3,2] and sum(points)==219

def test_scopes_aliases_and_missing_model():
    rows=demos();assert len(set(scope(r) for r in rows))==6
    r=deepcopy(rows[0]);r['params']={}
    assert not analyzable(r,validate([r])[0])
    r=deepcopy(rows[0]);r['kind']='real'
    assert not analyzable(r,validate([r])[0])
    r['rules_verified']=True;r['model_inputs_supported']=True
    assert analyzable(r,validate([r])[0])
    other=deepcopy(r);other['match_id']='another';other['home_id']='different'
    assert validate([r,other])[1]['errors']
    other['season']='different-season'
    assert not validate([r,other])[1]['errors']
    assert validate([r,r])[1]['errors']

def test_no_same_fixture_combinations():
    r=demos()[0];r2=deepcopy(r);r2['market']='연장 포함 총득점'
    legs=[{'match_id':fixture(x),'label':'a','probability':.5,'low':0,'high':1,'odds':2.} for x in [r,r2]]
    assert compare(legs)==[]

def test_official_vs_product_settlement():
    rows=demos();f=next(x for x in rows if COMPETITIONS[x['competition']]=='football')
    assert settle_outcome(f,{'regulation':[1,1],'including_overtime':[2,1]})=='draw'
    b=rows[0]
    assert settle_outcome(b,{'regulation':[80,80],'including_overtime':[90,88]})=='home'
    with pytest.raises(ValueError):settle_outcome(b,{'including_overtime':[80,80]})

def test_history_groups_and_no_leakage(tmp_path):
    p=tmp_path/'h.sqlite3';now=datetime.now(timezone.utc)
    for row in demos():
        x=save(p,row,now)
        sport=COMPETITIONS[row['competition']]
        result={'regulation':[1,1]} if sport=='football' else {'including_overtime':[90,85]} if sport=='basketball' else {'sets':[[25,20]]*3}
        record_result(p,x['id'],result,'example source',True,now+timedelta(days=3))
    records=load(p);m=evaluate(records,now+timedelta(days=3))
    assert len(m)==6 and all(v['전체']['n']==1 for v in m.values())
    records[0]['created_at']=records[0]['row']['kickoff']
    assert len(evaluate(records,now+timedelta(days=3)))==5
    with pytest.raises(ValueError):save(p,demos()[0],now+timedelta(days=4))
