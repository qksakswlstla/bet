import os
import json
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import streamlit as st
from toto.demo import example_matches, example_history
from toto.input import read_csv, csv_text
from toto.validation import OPTIONAL_LABELS, validate, eligible, kst
from toto.model import probabilities, implied, simulate, OUTCOMES, VERSION
from toto.combinations import compare, settle
from toto.history import save_prediction, load_history, save_result, evaluate

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get('BET_DATA_DIR', str(ROOT / 'data'))) / 'history.sqlite3'
LABELS = {'home': '홈 승', 'draw': '무승부', 'away': '원정 승'}
st.set_page_config(page_title='축구 분석 실험실', layout='wide')
st.title('축구 분석·시뮬레이션 실험실')
st.warning('실험용 · 성능 검증 미완료 · 실제 베트맨 데이터/API 연결 없음 · 자동 구매 없음')
st.caption('90분+추가시간 기준. 연장·승부차기 제외. 경기 중 실시간 연동은 작동하지 않습니다. 아래 상황 입력은 조건부 계산입니다.')
mode = st.sidebar.radio('데이터 선택', ['예시 데이터', '내 CSV / 붙여넣기 / 직접 입력'])
rows = []


st.sidebar.download_button('예시 CSV 내려받기', csv_text(example_matches()).encode('utf-8-sig'), 'example_matches.csv', 'text/csv')
st.sidebar.download_button('빈 입력 양식 내려받기', csv_text([]).encode('utf-8-sig'), 'matches_template.csv', 'text/csv')
if mode == '예시 데이터':
    rows = example_matches()
    st.error('예시 데이터 — 팀·경기·배당·기대득점·과거 결과는 모두 가상입니다.')
else:
    with st.expander('데이터 입력', expanded=True):
        method = st.radio('입력 방법', ['CSV 업로드', 'CSV 붙여넣기', '한 경기 직접 입력'], horizontal=True)
        text = ''
        if method == 'CSV 업로드':
            uploaded = st.file_uploader('UTF-8 CSV 파일 (최대 100경기, 2MB)', type=['csv'])
            if uploaded:
                try:
                    text = uploaded.getvalue().decode('utf-8-sig')
                except UnicodeDecodeError:
                    st.error('UTF-8 CSV로 저장한 후 다시 올려주세요.')
        elif method == 'CSV 붙여넣기':
            text = st.text_area('열 이름을 포함한 CSV 내용', height=180)
        else:
            st.caption('모든 시각에 +09:00 등 시간대를 포함하세요. 정보별 시각이 다르면 가장 보수적인 공통 시각을 사용하고 근거에 개별 출처·시각을 적으세요.')
            with st.form('manual'):
                data = {'sport': 'football'}
                descriptions = {'match_id':'경기 식별자', 'league':'리그', 'home':'홈팀', 'away':'원정팀', 'kickoff':'시작 시각', 'deadline':'구매 마감', 'source':'출처 (URL·자료명)', 'collected_at':'수집 시각', 'as_of':'경기 정보 기준 시각', 'home_odds':'홈 승 배당', 'draw_odds':'무 배당', 'away_odds':'원정 승 배당', 'home_xg':'홈 기대득점 (사용자 가정)', 'away_xg':'원정 기대득점 (사용자 가정)', 'xg_basis':'기대득점 근거·가정·개별 출처와 시각'}
                for key, label in descriptions.items():
                    data[key] = st.text_input(label)
                data['kind'] = st.selectbox('실제/예시 구분', ['real', 'example'], format_func=lambda x: '실제 입력' if x == 'real' else '예시 데이터')
                data['product'] = '1X2_90'
                data['lineup_status'] = st.selectbox('라인업 상태', ['unknown', 'expected', 'confirmed'], format_func=lambda x: {'unknown': '미확보', 'expected': '예상 (미확정)', 'confirmed': '공식 확정'}[x])
                if st.form_submit_button('입력 검수하기'):
                    st.session_state.manual = data
            rows = [st.session_state.manual] if 'manual' in st.session_state else []
        if text:
            try:
                rows = read_csv(text)
            except ValueError as e:
                st.error(str(e))
    st.info('실제 데이터는 사용자가 입력한 자료이며 공급원과의 자동 대조는 없습니다. 스크린샷 인식은 지원하지 않습니다.')

reports = validate(rows)
tabs = st.tabs(['1 경기 목록', '2 경기 상세', '3 시나리오 비교', '4 조합 비교', '5 검수 결과', '6 성능 기록'])
valid_indices = [i for i, r in enumerate(reports) if not r['errors']]


def choose(prefix):
    if not valid_indices:
        st.info('검수를 통과한 경기를 먼저 입력하세요.')
        return None
    i = st.selectbox('경기 선택', valid_indices, format_func=lambda j: f"{'[예시 데이터]' if rows[j]['kind']=='example' else '[실제 입력]'} {rows[j]['home']} – {rows[j]['away']}", key=prefix)
    return i


with tabs[0]:
    st.subheader('경기 목록')
    listing = []
    for row, report in zip(rows, reports):
        def show_time(key):
            try:
                return kst(row.get(key, ''))
            except ValueError:
                return '잘못된 시각'
        listing.append({'구분': '예시 데이터' if row.get('kind')=='example' else '사용자 입력 (실제 여부 검수 필요)', '경기': f"{row.get('home','')} – {row.get('away','')}", '시작(KST)': show_time('kickoff'), '마감(KST)': show_time('deadline'), '수집(KST)': show_time('collected_at'), '정보 기준(KST)': show_time('as_of'), '사전 분석': '가능 (실험용)' if eligible(row, report) else '보류 / 마감', '정보 입력 항목': f"{report['available_fields']}/{report['total_fields']}", '출처': row.get('source')})
    st.dataframe(listing, hide_index=True)
    st.caption('정보 입력 항목 수는 누락 현황이며 정확도·신뢰도 점수가 아닙니다. 입력값은 자동 갱신되지 않습니다.')

with tabs[4]:
    st.subheader('검수 결과 · 추천보다 먼저 확인하세요')
    for row, report in zip(rows, reports):
        st.write(f"{report['match_id']} · {row.get('home','')} – {row.get('away','')}")
        for error in report['errors']:
            st.error(error)
        for warning in report['warnings']:
            st.warning(warning)
    st.info('추천 보류: 모형의 별도 기간 성능·확률 보정·실제 조합 가능 여부·정산 규칙이 검증되지 않았습니다. 입력 항목이 많아도 추천을 활성화하지 않습니다.')

with tabs[1]:
    i = choose('detail')
    if i is not None:
        row, report = rows[i], reports[i]
        st.subheader('예시 데이터' if row['kind']=='example' else '사용자 입력 실제 자료 · 실험용')
        p = probabilities(float(row['home_xg']), float(row['away_xg']))
        market = implied([float(row[k]) for k in ('home_odds','draw_odds','away_odds')])
        st.dataframe([{'결과': LABELS[k], '모형 확률': f'{p[k]:.2%}', '배당 암시 확률(1/배당)': f"{market['raw'][j]:.2%}", '마진 조정 확률': f"{market['adjusted'][j]:.2%}", '차이(%p)': round((p[k]-market['adjusted'][j])*100, 2)} for j,k in enumerate(OUTCOMES)], hide_index=True)
        st.write(f"배당 마진: {market['margin']:.2%}. 역배당의 합으로 나누는 비례 정규화 방식이며 실제 확률을 보장하지 않습니다.")
        st.write(f"예상 득점 (입력 가정): 홈 {row['home_xg']}, 원정 {row['away_xg']}")
        st.dataframe([{'스코어': x['score'], '확률': f"{x['probability']:.2%}"} for x in p['scores']], hide_index=True)
        st.write('근거:', row['xg_basis'], ' / 출처:', row['source'])
        st.write('반영하지 못한 정보:', ', '.join(OPTIONAL_LABELS[k] for k in report['missing']) or '누락 항목 없음 (메모의 자동 영향 추정은 미지원)')
        st.caption('독립 포아송 모형: 두 팀 득점이 독립이고 경기 내 득점률이 일정하다고 가정합니다. 전술·저득점 상관·선수 효과를 학습하지 않았습니다.')
        with st.expander('단일 경기 선택지별 고정 예산 비교'):
            single_budget = st.number_input('단일 선택 1개 비교 고정 예산 (원)', 0, 1000000, 10000, step=1000)
            h, a = float(row['home_xg']), float(row['away_xg'])
            variants = [probabilities(h*hf, a*af) for hf in (.8, 1., 1.2) for af in (.8, 1., 1.2) if h*hf<=8 and a*af<=8]
            st.dataframe([{'선택': LABELS[k], '적용 배당': float(row[k+'_odds']), '추정 확률': f'{p[k]:.2%}', '민감도 범위': f"{min(x[k] for x in variants):.2%}~{max(x[k] for x in variants):.2%}", '기대순손익(원)': round(single_budget*(p[k]*float(row[k+'_odds'])-1))} for k in OUTCOMES], hide_index=True)
            st.caption('각 선택을 개별 대안으로 비교합니다. 전부 구매하는 계획은 아닙니다. 기대순손익=예산×(확률×배당−1), 적중 배당 반환·미적중 0 가정. 민감도는 각 기대득점 ±20% 가정(0~8 범위 내)의 범위이며 통계적 신뢰구간이 아닙니다. 실제 단일 구매 가능 여부·규칙은 미확인, 추천 보류입니다.')
        with st.expander('가상 상품 확률 계산 — 실제 구매 상품 연결 없음'):
            handicap = st.selectbox('홈 기준 정수 유럽식 3-way 핸디캡', [-2,-1,0,1,2], index=2)
            total = st.selectbox('언더오버 기준 (반골만 지원)', [.5,1.5,2.5,3.5,4.5], index=2)
            pp = probabilities(float(row['home_xg']), float(row['away_xg']), handicap, total)
            st.write({LABELS[k]: f'{v:.2%}' for k,v in pp['handicap'].items()})
            st.write({'오버': f"{pp['total']['over']:.2%}", '언더': f"{pp['total']['under']:.2%}"})
            st.caption('핸디캡은 홈 최종 득점에 정수를 더해 승·무·패를 판정합니다. 아시안·쿼터 라인·정수 U/O·환급 상품은 입력/조합/정산 미지원.')
        if st.button('이 시점의 사전 예측 저장', disabled=not eligible(row, report)):
            try:
                saved = save_prediction(DB, row)
                st.success(f"예측 저장 완료: {saved['id']}. 입력·배당·모형 버전·생성 시각이 고정됩니다.")
            except ValueError as e:
                st.error(str(e))

with tabs[2]:
    i = choose('scenario')
    if i is not None:
        row = rows[i]
        st.subheader('예시 데이터 · 조건부 시뮬레이션' if row['kind']=='example' else '실험용 조건부 시뮬레이션')
        scenario = st.selectbox('비교할 상황 (각각 별도 조건, 중복 합산 안 함)', ['핵심 선수 출전·결장', '라인업 변경', '이른 선제골', '이른 선제 실점', '퇴장', '체력 저하·일정 부담', '악천후·외부 조건'])
        st.warning('시나리오 발생 확률은 확보하지 못했습니다. 아래 배수는 사용자의 민감도 가정이며 선수·퇴장·날씨의 검증된 효과가 아닙니다.')
        hf = st.slider('홈 잔여 득점률 배수', 0., 2., 1., .05)
        af = st.slider('원정 잔여 득점률 배수', 0., 2., 1., .05)
        minute = st.slider('관측 또는 가정한 경과 시간 (분)', 0, 90, 0)
        hs = st.number_input('현재/가정 홈 점수', 0, 30, 0)
        aws = st.number_input('현재/가정 원정 점수', 0, 30, 0)
        hr = st.number_input('홈 퇴장 수 (메모용)', 0, 5, 0)
        ar = st.number_input('원정 퇴장 수 (메모용)', 0, 5, 0)
        evidence = st.text_input('관측 출처·관측 시각 또는 가정 근거', value='사용자 가정')
        st.caption('퇴장 수는 자동 계수로 변환하지 않습니다. 위 득점률 배수로 효과를 직접 가정하세요. 관측 점수·시간도 입력 내용의 진위를 자동 확인하지 않습니다.')
        runs = st.select_slider('몬테카를로 실행 횟수', [1000,10000,20000,100000,200000], value=20000)
        seed = st.number_input('난수 시드 (같은 입력이면 같은 결과)', 0, 2147483647, 42)
        try:
            base = probabilities(float(row['home_xg']), float(row['away_xg']))
            result = simulate(float(row['home_xg']), float(row['away_xg']), runs, seed, minute, (hs,aws), hf,af)
            st.dataframe([{'결과': LABELS[k], '경기 전 기준': f'{base[k]:.2%}', '조건부 정확 합산': f"{result['exact'][k]:.2%}", '차이(%p)': round(100*(result['exact'][k]-base[k]),2), '모의실험': f"{result['probabilities'][k]:.2%}", '표본오차(표준오차)': f"{result['mc_standard_error'][k]:.3%}"} for k in OUTCOMES], hide_index=True)
            result.update(scenario=scenario, evidence=evidence, red_cards={'home':hr,'away':ar}, occurrence_probability=None, data_kind=row['kind'], source=row['source'], match_id=row['match_id'], collected_at=row['collected_at'], as_of=row['as_of'], calculated_at=datetime.now(timezone.utc).isoformat())
            st.download_button('재현용 입력·결과 JSON 저장', json.dumps(result,ensure_ascii=False,indent=2), 'scenario.json', 'application/json')
        except ValueError as e:
            st.error(str(e))
        st.caption('표본오차는 난수 추출 오차이며 모형의 예측 오차가 아닙니다. 횟수를 늘려도 모형 정확도가 검증되지는 않습니다. 90분 기준 단순 잔여시간 비례이며 추가시간은 별도 추정하지 않습니다.')

with tabs[3]:
    st.subheader('조합 비교 · 실험용')
    st.error('추천할 조합 없음 — 성능과 실제 상품 규칙이 검증되지 않았습니다.')
    st.caption('단일 경기 확률은 상세 화면에서 확인하세요. 아래는 정규시간 승무패만 비교하며 실제 조합 가능 여부·상한·세금·취소 규칙은 연결하지 않았습니다.')
    fixed_budget = st.number_input('조합 1개 비교에 사용할 고정 예산 (원)', 0, 1000000, 10000, step=1000)
    size = st.radio('경기 수', [2,3], horizontal=True)
    data_kind = st.radio('조합 데이터 구분 (실제/예시 혼합 금지)', ['example','real'], format_func=lambda x: '예시 데이터' if x=='example' else '실제 입력', horizontal=True)
    legs=[]
    for i in valid_indices:
        row = rows[i]
        if row['kind'] != data_kind or not eligible(row,reports[i]):
            continue
        pick = st.selectbox(f"{row['home']} – {row['away']}", ['skip',*OUTCOMES], format_func=lambda x: '제외' if x=='skip' else LABELS[x], key=f'leg{i}')
        if pick == 'skip':
            continue
        h,a=float(row['home_xg']),float(row['away_xg'])
        p=probabilities(h,a)[pick]
        sensitivity=[probabilities(h*hf,a*af)[pick] for hf in (.8,1.,1.2) for af in (.8,1.,1.2) if h*hf<=8 and a*af<=8]
        legs.append({'match_id':row['match_id'],'label':f"{row['home']}–{row['away']} {LABELS[pick]}", 'probability':p,'low':min(sensitivity),'high':max(sensitivity),'odds':float(row[pick+'_odds'])})
    if len(legs)>10:
        st.warning('선택이 10경기를 초과했습니다. 10경기 이하로 줄여주세요.')
        output=[]
    else:
        output=compare(legs,size,fixed_budget)
    st.info('독립 가정으로 경기 확률을 곱합니다. 상관관계는 확보하지 못했으며 실제 결합 확률과 다를 수 있습니다. 범위는 두 팀 기대득점을 각각 ±20% 바꾼 9개 가정의 범위로, 통계적 신뢰구간이 아닙니다.')
    if output:
        counts=Counter(mid for x in output for mid in x['match_ids'])
        st.dataframe([{'선택':x['selections'],'총 배당':round(x['odds'],3),'적중 확률':f"{x['probability']:.2%}",'가정 민감도 범위':f"{x['sensitivity_low']:.2%}~{x['sensitivity_high']:.2%}",'기대순손익(원)':round(x['expected_profit']),'민감도 하한 손익':round(x['low_expected_profit']),'민감도 상한 손익':round(x['high_expected_profit'])} for x in output],hide_index=True)
        st.write('경기별 반복 횟수:',dict(counts))
        st.caption('각 행은 동일 예산으로 대안을 개별 비교한 것이며 모두 구매하는 계획이 아닙니다. 기대순손익 = 예산 × (확률 × 배당 − 1). 전부 적중 시 배당곱, 하나라도 미적중 시 0원 반환 가정. 민감도 하한이 양수여도 추천하지 않습니다.')
    else:
        st.info(f'{size}경기 이상에서 선택지를 골라 비교하세요. 오류·마감 경기는 제외됩니다.')
    with st.expander('가정 정산 계산기 — 실제 정산 규칙 연결 없음'):
        statuses=[]
        for j in range(3):
            status=st.selectbox(f'{j+1}번 선택 상태',['제외','적중','미적중','취소/적특'],key=f'status{j}')
            odd=st.number_input(f'{j+1}번 당시 배당',1.01,1000.,2.,key=f'odd{j}')
            if status!='제외':
                statuses.append({'odds':odd,'status':{'적중':'win','미적중':'loss','취소/적특':'void'}[status]})
        if statuses:
            settled=settle(statuses,float(fixed_budget))
            st.write(f"반환액 {settled['return']:,.0f}원 / 순손익 {settled['profit']:,.0f}원")
            st.caption('단순 가정: 취소/적특 배당 1, 전부 취소면 원금 반환. 실제 상품의 취소·연기 규칙은 직접 확인해야 합니다. 자동 구매·증액 기능은 없습니다.')

with tabs[5]:
    st.subheader('성능 기록 · 검증 완료 아님')
    history=load_history(DB)
    history_mode=st.radio('평가 자료',['내 실제 예측 기록','저장한 예시 기록','예시 데이터: 합성 과거 30경기'])
    selected_history=example_history() if history_mode.startswith('예시 데이터:') else history
    kind='real' if history_mode=='내 실제 예측 기록' else 'example'
    if kind=='example':
        st.error('예시 데이터 — 아래 지표·수익은 합성 결과이며 실제 성능 증거가 아닙니다.')
    relevant=[x for x in selected_history if x['row']['kind']==kind]
    st.dataframe([{'ID':x['id'],'경기':f"{x['row']['home']}–{x['row']['away']}",'시작(KST)':kst(x['row']['kickoff']),'예측 생성(KST)':kst(x['created_at']),'모형':x['model'],'결과':f"{x['result']['home']}:{x['result']['away']} ({x['result']['status']})" if x.get('result') else '미확보'} for x in relevant],hide_index=True)
    pending=[x for x in history if not x.get('result')]
    if pending:
        with st.expander('경기 종료 결과 기록 (덮어쓰기 불가)'):
            with st.form('result'):
                pid=st.selectbox('예측 ID',[x['id'] for x in pending])
                status=st.selectbox('상태',['finished','void'],format_func=lambda x:'공식 종료' if x=='finished' else '취소/적특')
                hg=st.number_input('최종 홈 득점 (정규시간)',0,99,0)
                ag=st.number_input('최종 원정 득점 (정규시간)',0,99,0)
                source=st.text_input('공식 결과 출처·확인 시각')
                finished_confirmed=st.checkbox('공식 경기 종료 또는 취소를 직접 확인했습니다')
                confirmed=st.checkbox('기록 배당이 당시 실제 구매 가능했고, 이 앱의 단순 정산 규칙이 해당 상품에 맞음을 직접 확인했습니다')
                if st.form_submit_button('결과 고정 저장'):
                    try:
                        if not finished_confirmed:
                            raise ValueError('공식 종료/취소를 먼저 확인하세요.')
                        save_result(DB,pid,status,int(hg),int(ag),source,confirmed)
                        st.success('결과 저장 완료. 다시 열면 평가에 반영됩니다.')
                    except ValueError as e:
                        st.error(str(e))
    evaluation=evaluate(selected_history,kind)
    st.write(f"평가 가능한 종료 경기 {evaluation['n']}개 / 제외 {len(evaluation['excluded'])}개")
    st.caption('고정 포아송 모형으로 학습은 실시하지 않았습니다. 시간순 60/20/20 분리는 참고·검증·별도 평가 구간 표시용이며, 별도 구간을 보고 모형을 바꾸면 새로운 미사용 기간이 필요합니다. 모형 버전별 조정 이력이나 미사용 기간을 자동 증명하지 않으므로 검증 완료로 표시하지 않습니다.')
    for name, metrics in [('전체',evaluation['all']),*evaluation['splits'].items()]:
        with st.expander(name,expanded=name=='전체'):
            if not metrics['n']:
                st.info('표본 없음: 성능 미검증')
                continue
            st.write(f"표본 {metrics['n']}개 / {kst(metrics['period'][0])} ~ {kst(metrics['period'][1])}")
            st.dataframe([{'기준':label,'Brier (낮을수록 좋음)':metrics[key]['brier'],'Log loss (낮을수록 좋음)':metrics[key]['log_loss'],'최대 확률 적중률':metrics[key]['accuracy']} for key,label in [('model','입력 기대득점 모형'),('market','배당 마진 조정'),('uniform','승무패 각 1/3')]],hide_index=True)
            st.caption('Brier: 세 결과 확률의 제곱오차 합 평균(0~2). Log loss: 실제 결과에 준 확률의 음의 자연로그 평균. 극단 확률은 계산용 1e-15로 제한합니다.')
            st.dataframe(metrics['calibration'],hide_index=True)
            st.caption('확률 보정 상태 (별도 보정 학습 미실시): 3개 결과를 20% 폭으로 묶어 평균 예측과 실제 발생 비율을 비교합니다. 건수는 경기 수가 아니라 경기×결과 수입니다. 표본이 적으면 해석을 보류하세요.')
            st.write({'정산 확인 표본':metrics['settled_n'],'가정 순손익(원)':metrics['profit'],'ROI(순손익/투입액)':metrics['roi'],'최대 낙폭(원)':metrics['max_drawdown']})
            st.caption('수익 비교는 매 경기 최대 확률 결과에 고정 1,000원 단일 선택을 한 가정이며 조합 전략 검증이 아닙니다. 당시 배당·규칙 확인된 종료 경기만 포함, 취소 경기는 평가·투입액에서 제외. 세금·한도·배당 변경 미반영. 최대 낙폭은 누적 순손익 최고점 대비 하락액입니다.')
            st.line_chart(metrics['equity'])
    if evaluation['excluded']:
        st.dataframe(evaluation['excluded'],hide_index=True)
    st.download_button('예측·결과 기록 내보내기 (시간은 ISO 시간대 포함)',json.dumps(relevant,ensure_ascii=False,indent=2),'history.json','application/json')
    st.caption('기록은 이 컴퓨터의 data/history.sqlite3에 저장됩니다. CSV 경기 입력 자체는 저장하지 않습니다. 브라우저/다른 컴퓨터 사이 자동 동기화는 없습니다. DB를 직접 수정하면 기록 무결성이 보장되지 않습니다.')

st.divider()
st.caption(f'모형 {VERSION} · 정보가 없으면 빈칸 유지 · 데이터 충실도와 예측 확률 별도 표시 · 감당할 수 있는 고정 예산 안에서만 비교하세요.')
