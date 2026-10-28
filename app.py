import csv
import io
import json
import os
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import streamlit as st
from toto.multisport import COMPETITIONS,MARKETS,VERSIONS,EXAMPLE_PARAMS,demos,validate,analyzable,simulate,fixture,outcomes,pregame
from toto.validation import kst,timestamp
from toto.combinations import compare
from toto.multi_history import load,save,record_result,evaluate,audited_records

st.set_page_config(page_title='다섯 대회 분석 실험실',layout='wide')
st.title('다섯 대회 분석·시뮬레이션 실험실')
st.warning('실험용 · 실제 학습/과거 성능 미검증 · 추천할 조합 없음')
st.caption('공식 최신 시즌·대회 방식·베트맨 제공 상품·정산 규칙은 접근 제한으로 미확인입니다. 상품 이름은 계산 범위이며 실제 판매 여부를 뜻하지 않습니다.')
DB=Path(os.environ.get('BET_DATA_DIR',str(Path(__file__).parent/'data')))/'multi_history.sqlite3'
labels={'home':'홈 승','draw':'무승부','away':'원정 승','over':'오버','under':'언더'}
comp=st.sidebar.selectbox('대회',list(COMPETITIONS))
div=st.sidebar.selectbox('KOVO 부문',['남자부','여자부']) if comp=='KOVO' else '해당 없음'
sport=COMPETITIONS[comp]
param_labels={'pace':'경기 전체 팀당 예상 공격 횟수','pace_sd':'공통 공격 횟수의 표준편차','home_eff':'홈 공격 1회당 기대득점','away_eff':'원정 공격 1회당 기대득점','residual_sd':'팀 득점 잔차 표준편차','close_pace':'접전 시 후반 속도 배수','blowout_pace':'큰 점수 차 시 후반 속도 배수','overtime_fraction':'연장 1회 공격 횟수 / 정규경기 공격 횟수','rally_home':'한 랠리에서 홈이 이길 확률','fatigue_per_set':'세트마다 홈 랠리 확률 변화','substitution_delta':'교체 후 홈 랠리 확률 변화','substitution_after_point':'세트 내 합계 몇 점부터 교체 효과 적용','home_xg':'홈 경기 전체 기대득점','away_xg':'원정 경기 전체 기대득점','minute':'경과 시간(사전 기록은 0)','home_score':'현재 홈 점수(사전 기록은 0)','away_score':'현재 원정 점수(사전 기록은 0)'}
mode=st.sidebar.radio('데이터',['예시 데이터','실제/예시 자료 입력'])

def encode_csv(rows):
    buf=io.StringIO();w=csv.DictWriter(buf,fieldnames=list(demos()[0]));w.writeheader()
    for r in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list,bool)) else v for k,v in r.items() if k in w.fieldnames})
    return buf.getvalue().encode('utf-8-sig')

if 'example_snapshot' not in st.session_state:
    st.session_state.example_snapshot=demos()
st.sidebar.download_button('다섯 대회 예시 CSV',encode_csv(st.session_state.example_snapshot),'multi_example.csv')
st.sidebar.download_button('빈 CSV 양식',encode_csv([]),'multi_template.csv')
rows=st.session_state.example_snapshot if mode=='예시 데이터' else st.session_state.get('entered',[])
if mode!='예시 데이터':
    method=st.radio('입력 방법',['한 경기 직접 입력','CSV 업로드','CSV 붙여넣기'])
    if method=='한 경기 직접 입력':
        st.caption('팀 ID는 대회·시즌·남녀부 범위에서 같은 팀에 같은 값을 사용합니다. 공급원 이름이 달라도 동일 ID를 직접 지정하세요. 아래 숫자는 실제 자료에서 확인한 가정만 입력하세요.')
        with st.form('input'):
            r={'competition':comp,'division':div}
            for k,label in [('season','시즌 (공식 자료 확인 후 기입)'),('stage','대회 단계'),('match_id','경기 ID'),('home_id','홈 팀 ID'),('away_id','원정 팀 ID'),('home','홈 표시 이름'),('away','원정 표시 이름'),('provider','공급원 이름'),('kickoff','시작 시각'),('deadline','구매 마감'),('source','자료 출처'),('collected_at','수집 시각'),('as_of','정보 기준 시각'),('rules_version','정산 규칙 버전/식별자'),('rules_source','공식 규칙·베트맨 상품 근거 URL/자료명'),('basis','모형 입력 근거·표본 수·누락 항목')]:
                r[k]=st.text_input(label,help='시간은 2026-11-01T19:00:00+09:00 형식' if k in ['kickoff','deadline','collected_at','as_of'] else None)
            r['kind']=st.selectbox('실제/예시',['real','example'],format_func=lambda x:'실제 입력' if x=='real' else '예시 데이터')
            r['market']=st.selectbox('상품 계산 기준',MARKETS[sport]);r['line']=st.text_input('기준점 (승패는 빈칸, 홈 핸디캡은 부호 포함)')
            st.caption('선택한 상품의 배당만 채우세요. 승무패는 홈·무·원정, 승패는 홈·원정, 총득점은 오버·언더입니다.')
            odds_fields={k:st.text_input(labels[k]+' 배당') for k in labels}
            st.caption('모형 입력: 근거가 없으면 비워두세요. 필수 수치가 비어 있으면 입력은 보관하되 계산은 보류합니다.')
            param_fields={k:st.text_input(param_labels[k]) for k in EXAMPLE_PARAMS[sport]}
            evidence_text=st.text_area('근거 목록 JSON (미확보면 [])',value='[]',help='[{"type":"official 또는 report 또는 assumption","source":"출처","as_of":"시간대 포함 시각","collected_at":"시간대 포함 시각","note":"내용"}]')
            r['rules_verified']=st.checkbox('해당 시즌·단계의 경기 방식과 선택한 상품 정산 범위를 공식 자료로 확인했습니다')
            r['model_inputs_supported']=st.checkbox('수치 입력의 근거와 누락 항목을 기록했습니다 (학습 검증 완료를 의미하지 않음)')
            r['combination_verified']=st.checkbox('해당 상품의 실제 조합 가능 여부를 확인했습니다')
            r['odds_available_verified']=st.checkbox('입력 배당이 당시 실제 구매 가능했음을 확인했습니다')
            if st.form_submit_button('입력 목록에 추가'):
                try:
                    r.update(odds={k:float(odds_fields[k]) for k in outcomes(r)},params={k:float(v) for k,v in param_fields.items() if v.strip()},evidence=json.loads(evidence_text))
                    errors=validate([r])[0]['errors']
                    if errors:st.error(' / '.join(errors))
                    else:
                        st.session_state.entered=[*st.session_state.get('entered',[]),r];rows=st.session_state.entered;st.success('입력 완료')
                except (ValueError,TypeError):st.error('필수 배당·수치·근거 JSON을 확인하세요. 숫자에는 쉼표를 넣지 마세요.')
        st.caption('이 버전에서 수치 입력이 어려우면 예시 데이터로 구조를 확인하세요. 입력을 추측해서 채우지 마세요. 자동 데이터 수집은 연결되지 않았습니다.')
    else:
        text=''
        if method=='CSV 업로드':
            f=st.file_uploader('UTF-8 CSV (최대 2MB/100행)',type=['csv'])
            if f:
                try:text=f.getvalue().decode('utf-8-sig')
                except UnicodeDecodeError:
                    st.error('UTF-8 파일이 필요합니다. 이전 자료는 분석에서 제거했습니다.');rows=[];st.session_state.entered=[]
        else:text=st.text_area('CSV 내용')
        if text:
            try:
                if len(text.encode())>2_000_000:raise ValueError('2MB 초과')
                reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
                if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)):raise ValueError('열 중복/누락')
                parsed=[]
                for r in reader:
                    if len(parsed)>=100 or None in r or any(v is None for v in r.values()):raise ValueError('행 수/열 수 오류')
                    for k in ['params','odds','evidence','rules_verified','model_inputs_supported','combination_verified','odds_available_verified','source_conflict']:
                        if k in r:r[k]=json.loads(r[k])
                    parsed.append(r)
                rows=parsed;st.session_state.entered=rows
            except (ValueError,TypeError) as e:st.error(f'CSV 오류: {e}. 이전 자료는 분석에서 제거했습니다.');rows=[];st.session_state.entered=[]
    st.download_button('입력 목록 백업 CSV',encode_csv(rows),'my_matches.csv')
reports=validate(rows)
visible=[i for i,r in enumerate(rows) if r.get('competition')==comp and r.get('division')==div]
tabs=st.tabs(['1 경기 목록','2 경기 상세','3 시나리오 비교','4 조합 비교','5 검수 결과','6 성능 기록'])

@st.cache_data(show_spinner=False)
def cached_calculate(row,params=None,runs=5000,seed=42):return simulate(row,runs,seed,params)

def calculate(row,params=None,runs=5000,seed=42):
    try:return cached_calculate(row,params,runs,seed)
    except (ValueError,KeyError,TypeError) as exc:
        st.error(f'분석 불가: {exc}. 예시 결과로 대체하지 않습니다.');st.stop()

def choose(key):
    ids=[i for i in visible if analyzable(rows[i],reports[i])]
    if not ids:st.info('계산 가능한 자료 없음: 필수값·규칙·입력 근거를 확인하세요.');return None
    return st.selectbox('경기',ids,format_func=lambda i:f"{'[예시 데이터]' if rows[i]['kind']=='example' else '[실제 입력/실험용]'} {rows[i]['home']}–{rows[i]['away']} / {rows[i]['market']}",key=key)

with tabs[0]:
    st.subheader(f'{comp} {div}')
    st.info('일정·배당·선수 정보 자동 API: 전 대회 미연결. 입력 자료는 세션에 보관되며 자동 갱신하지 않습니다. 예시 시각은 합성 자료 생성 시각입니다.')
    st.dataframe([{'대회':c,'부문':d,'예시 데이터': '가능','실제 자료 수동 입력':'가능','기본 모형':'조건부 구현 (학습 없음)','과거 성능 검증':'미완료','추천 기준':'미충족'} for c in COMPETITIONS for d in (['남자부','여자부'] if c=='KOVO' else ['해당 없음'])],hide_index=True)
    for i in visible:
        r=rows[i];st.write(f"{'예시 데이터' if r.get('kind')=='example' else '실제 입력'} · {r.get('season')} · {r.get('stage')} · {r.get('home')} – {r.get('away')}")
        st.caption(f"출처: {r.get('source','미확보')} / 공급원: {r.get('provider','수동')} / 선수 정보: 사용자 근거 목록만 사용 (자동 수집 없음)")
        try:st.caption(f"시작 {kst(r['kickoff'])} / 마감 {kst(r['deadline'])} / 수집 {kst(r['collected_at'])} / 기준 {kst(r['as_of'])}")
        except (ValueError,KeyError):st.error('시간 형식 오류')
with tabs[4]:
    for i,r in enumerate(rows):
        st.write(f"{r.get('competition')} / {r.get('match_id')}")
        for e in reports[i]['errors']:st.error(e)
        for w in reports[i]['warnings']:st.warning(w)
    st.info('효율·선수·이동·날씨 등은 확보된 근거만 기록합니다. 자동 영향 계수·공식 뉴스 확인은 없습니다. 근거 유형 official=공식 발표, report=보도, assumption=분석자 가정.')
with tabs[1]:
    i=choose('detail')
    if i is not None:
        r=rows[i]
        if not pregame(r):st.warning('마감 지남 또는 경기 중 입력: 아래는 입력 시점의 조건부 계산이며 최신 사전 예측이 아닙니다.')
        p=calculate(r);st.warning('예시 데이터' if r['kind']=='example' else '실제 입력에 따른 실험용 결과')
        inv={k:1/float(v) for k,v in r['odds'].items()};s=sum(inv.values())
        st.dataframe([{'결과':labels[k],'확률':v,'마진 조정 배당 확률':inv[k]/s,'차이(%p)':100*(v-inv[k]/s)} for k,v in p['probabilities'].items()],hide_index=True)
        single_budget=st.number_input('단일 선택 대안 1개당 고정 예산',0,1000000,10000)
        st.dataframe([{'선택':labels[k],'배당':r['odds'][k],'기대순손익':single_budget*(v*float(r['odds'][k])-1)} for k,v in p['probabilities'].items()])
        st.caption('각 선택은 개별 대안이며 전부 구매하는 계획이 아닙니다. 적중 시 배당 반환·미적중 시 0 가정, 추정 오차 크기 미확보.')
        st.write('배당 마진:',s-1,'예상 총득점:',p['mean_total'])
        st.write('점수/세트 차 5·50·95 분위:',p['margin_quantiles'],'총득점 5·50·95 분위:',p['total_quantiles'])
        st.caption('분위는 가정 모형의 결과 분포이며 모형 정확도의 신뢰구간이 아닙니다. 배당 조정은 역배당을 합으로 나눕니다.')
        for key in ['score_distribution','set_score_distribution','sample_sets']:
            if key in p:st.write(key,p[key])
        with st.expander('점수 차·총득점 전체 분포'):st.json({'margin':p['margin_distribution'],'total':p['total_distribution']})
        st.write('근거:',r['basis']);st.write('출처:',r['source']);st.json(r.get('evidence',[]))
        st.caption('자료 충실도: 근거 항목 '+str(len(r.get('evidence',[])))+'개. 정확도 점수가 아닙니다. 근거 목록에 없는 항목은 미확보/미반영입니다.')
        if st.button('사전 예측 고정 저장'):
            try:save(DB,r);st.success('저장 완료')
            except ValueError as e:st.error(str(e))
with tabs[2]:
    i=choose('scenario')
    if i is not None:
        r=rows[i];sp=COMPETITIONS[r['competition']]
        scenarios={'basketball':['핵심 선수 결장·시간 제한','파울 트러블','속도 변화','접전·큰 점수 차 운영'],'volleyball':['공격수·세터 결장','리시브 불안·범실','세트 도중 교체','장기전 체력'],'football':['핵심 선수 결장·로테이션','이른 득점·실점','퇴장','진출 조건 운영']}
        st.info('조건 이름은 메모입니다. 결장·퇴장을 선택하는 것만으로 수치가 변하지 않습니다. 근거가 있는 효율·기대득점·랠리 승률 등을 아래에서 직접 변경해야 계산에 반영됩니다.')
        st.caption('농구 접전 5점/큰 차이 15점, 배구 듀스 구조·확률 제한(0.01~0.99), 축구 일정 득점률은 현재 모형 가정입니다. 검증된 선수/퇴장 효과 계수는 없습니다.')
        scenario=st.selectbox('조건',scenarios[sp]);st.warning('발생 확률 미확보: 이 조건이 발생했을 때의 결과만 계산합니다. 겹치는 시나리오는 합산하지 않습니다.')
        input_key=hashlib.sha256(json.dumps(r,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
        params={k:st.number_input(param_labels[k],value=float(v),key=f'scenario_{input_key}_{k}_{mode}') for k,v in r['params'].items()}
        reason=st.text_input('변경 근거·관측 시각 (공식/보도/가정 구분)',value='분석자 가정')
        runs=st.selectbox('실행 횟수',[1000,5000,20000],index=1);seed=st.number_input('난수 시드',0,2147483647,42)
        try:
            changed=simulate(r,runs,seed,params);base=calculate(r,None,runs,seed)
            st.dataframe([{'결과':labels[k],'변경 전':base['probabilities'][k],'변경 후':v,'차이(%p)':100*(v-base['probabilities'][k])} for k,v in changed['probabilities'].items()])
            changed.update(scenario=scenario,basis=reason,record=r,calculated_at=datetime.now(timezone.utc).isoformat(),occurrence_probability=None)
            st.download_button('재현용 JSON',json.dumps(changed,ensure_ascii=False,indent=2),'scenario.json')
        except (ValueError,KeyError,TypeError):st.error('변경 입력의 필수값·범위를 확인하세요.')
        st.caption('실행 횟수 증가는 모형 정확도 검증이 아닙니다. 농구·배구 실시간 모형은 없으며 경기 전 조건만 비교합니다. 축구는 minute/home_score/away_score를 직접 입력하는 단순 잔여시간 모형입니다. 진출 확률·승부차기 모형은 미구현입니다.')
with tabs[3]:
    st.error('추천할 조합 없음 · 대회 혼합 비교는 실험용')
    kind=st.radio('비교 자료',['example','real'],format_func=lambda x:'예시 데이터' if x=='example' else '실제 입력')
    budget=st.number_input('대안 1개당 고정 예산',0,1000000,10000);size=st.radio('경기 수',[2,3],horizontal=True)
    legs=[]
    for i,r in enumerate(rows):
        if r.get('kind')!=kind or not analyzable(r,reports[i]) or not pregame(r):continue
        if kind=='real' and (not r.get('combination_verified') or not r.get('odds_available_verified')):continue
        pick=st.selectbox(f"{r['competition']} {r['division']} {r['home']}–{r['away']} {r['market']}",['skip',*outcomes(r)],format_func=lambda x:'제외' if x=='skip' else labels[x],key=f'leg{i}')
        if pick=='skip':continue
        p=calculate(r)['probabilities'][pick]
        legs.append({'match_id':json.dumps(fixture(r),ensure_ascii=False),'label':f"{r['competition']} {r['home']} {labels[pick]}",'probability':p,'odds':float(r['odds'][pick])})
    if len(legs)<=10:
        combos=compare(legs,size,float(budget))
        st.dataframe([{'선택':x['selections'],'배당':x['odds'],'독립 가정 확률':x['probability'],'기대순손익':x['expected_profit']} for x in combos])
        st.write('비교 대안에서 경기 반복 횟수',dict(Counter(mid for x in combos for mid in x['match_ids'])))
    else:st.warning('최대 10개 선택만 비교합니다.')
    st.caption('같은 경기의 다른 상품 선택은 한 조합에 넣지 않습니다. 경기 간 독립 가정으로 곱하며 상관·공통 모형 오류·추정 오차의 크기는 미확보입니다. 기대손익=예산×(확률×배당−1), 모두 적중 시 배당곱 반환 가정. 한 대회 성능으로 다른 대회 추천을 정당화하지 않습니다. 자동 구매·증액 없음.')
with tabs[5]:
    records=load(DB);st.write('저장된 예측',len(records))
    st.caption('대회·시즌·남녀부·상품·기준점·규칙 버전·모형 버전·실제/예시별 독립 평가입니다. 학습/보정 학습은 수행하지 않았고, 시간순 60/20/20 보고만 구현했습니다. 과거 검증 완료 상태는 활성화하지 않습니다.')
    pending=[x for x in records if not x['result']]
    if pending:
        with st.form('result'):
            pid=st.selectbox('예측 ID',[x['id'] for x in pending])
            official=st.text_area('공식 결과 JSON',help='축구 {"regulation":[2,1]}, 농구 {"including_overtime":[90,88]}, 배구 {"sets":[[25,20],[25,21],[25,22]]}')
            source=st.text_input('공식 종료 결과 출처');confirmed=st.checkbox('공식 종료와 상품 정산 범위를 확인했습니다')
            if st.form_submit_button('결과 저장'):
                try:record_result(DB,pid,json.loads(official),source,confirmed);st.success('결과 저장. 화면을 새로고침하면 지표에 반영됩니다.')
                except (ValueError,KeyError,TypeError) as e:st.error(str(e))
    accepted,excluded=audited_records(records)
    st.dataframe([{'대회':c,'부문':d,'실제 사전 기록':sum(x['row']['kind']=='real' and x['row']['competition']==c and x['row']['division']==d for x in records),'유효 종료 표본':sum(x['row']['kind']=='real' and x['row']['competition']==c and x['row']['division']==d for x in accepted),'기간/지표': '종료 표본이 있을 때 아래 집단별 표시'} for c in COMPETITIONS for d in (['남자부','여자부'] if c=='KOVO' else ['해당 없음'])],hide_index=True)
    st.caption('최소 표본 기준은 아직 설계·검증되지 않았습니다. 필요한 추가 표본 수를 임의로 정하지 않습니다. 종료 표본 0개면 기간·Brier·log loss·보정·ROI 모두 산출 불가입니다.')
    if excluded:
        st.write('평가 제외 기록과 사유');st.dataframe(excluded,hide_index=True)
    metrics=evaluate(records)
    if not metrics:st.info('평가 표본 없음 · 실제 과거 성능 검증 미완료')
    for key,m in metrics.items():
        with st.expander(key):
            if ' / example / ' in key:st.warning('예시 데이터 성능이며 실제 성능이 아닙니다.')
            for segment,values in m.items():
                st.write(segment)
                if values['n']:
                    st.write('평가 기간 (KST)',values['period'],'표본',values['n'])
                    st.dataframe([{'기준':name,**values[name]} for name in ['model','market','uniform']],hide_index=True)
                    st.dataframe(values['calibration'],hide_index=True)
                    st.write('당시 배당 확인 표본',values['settled_n'],'ROI',values['roi'],'최대 낙폭',values['max_drawdown'])
                else:st.info('표본 0개: 지표 산출 불가')
    st.caption('Brier·log loss는 낮을수록 좋습니다. 보정 표는 예측 확률과 실제 비율 비교입니다. ROI는 배당/정산 확인된 실제 기록에 경기당 고정 1,000원·최대 확률 선택 가정, 세금·취소·연기 상품 미지원. 기존 축구 v1 기록은 별도 DB에 보존되며 대회를 추측해 새 기록에 합치지 않습니다.')
    st.download_button('기록 내보내기',json.dumps(records,ensure_ascii=False,indent=2),'multi_history.json')
