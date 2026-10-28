import json
import os
from datetime import datetime,timedelta
from .validation import kst,KST
from .providers import catalog,games,overseas_odds,odds_rows
from .auto_store import read,save_fetch,bind,usable,to_manual
from .multisport import COMPETITIONS


def render(st,path,competition,division):
    sport=COMPETITIONS[competition]
    st.subheader('자동 경기 불러오기 · 공급원 응답 확인 단계')
    st.info('자동 조회는 버튼을 누를 때만 실행합니다. 일정·점수 확보는 모형 학습 완료를 뜻하지 않습니다. 베트맨 배당·기준점·마감은 자동 연결하지 않습니다.')
    st.caption('키는 운영체제 환경변수 APISPORTS_KEY / ODDS_API_KEY에 설정하세요. 이 화면이나 CSV에 입력하지 마세요. 실제 API 성공은 원자료 대조 후 판단합니다.')
    st.write('API-Sports 키:', '설정됨 (권한 미확인)' if os.environ.get('APISPORTS_KEY') else '미설정')
    catalog_key='catalog:'+sport
    if st.button('공급원 대회·시즌 목록 조회'):
        save_fetch(path,catalog_key,catalog(sport))
    cat=read(path,'auto_snapshots',catalog_key)
    def show_status(snapshot):
        if not snapshot:return
        st.write('갱신 상태:',snapshot['status'],'/',snapshot['message'])
        st.caption('조회 시도 '+kst(snapshot['last_attempt_at'])+' / 마지막 성공 '+(kst(snapshot['last_success_at']) if snapshot.get('last_success_at') else '없음'))
        if snapshot.get('request_context'):st.write('요청 종목·대회 ID·시즌',snapshot['request_context'])
        for cause in snapshot.get('causes',[]):st.warning(cause)
        if snapshot.get('errors'):
            st.write('공급원 오류 항목·설명 (비밀값/개인정보 가림)');st.json(snapshot['errors'])
        if snapshot.get('quota'):st.write('응답에 표시된 잔여 호출 정보',snapshot['quota'])
        if snapshot['status'] not in ('ok','empty'):
            st.error('조회 실패입니다. 예시나 이전 자료를 최신 자료로 대체하지 않습니다.')
            if snapshot.get('previous_items'):st.caption(f"이전 성공 자료 {len(snapshot['previous_items'])}건 보관 중 · 이번 가져오기에는 사용 안 함")
    show_status(cat)
    if cat and cat['status']=='ok':
        if not usable(cat):st.warning('대회 목록 조회 후 24시간 경과: 다시 조회하세요.')
        query=st.text_input('대회 검색 (공급원 영문 이름 포함)',key='league_search_'+sport)
        candidates=[x for x in cat['items'] if query.casefold() in json.dumps(x,ensure_ascii=False).casefold()]
        st.caption('다른 대회는 목록 검색용으로만 보입니다. 가져오기 대상은 왼쪽에서 지정한 다섯 대회뿐입니다. 이름이 비슷해도 자동 확정하지 않습니다.')
        if candidates:
            selected=st.selectbox('공급원 대회 후보',range(len(candidates)),format_func=lambda i:f"{candidates[i]['name']} / ID {candidates[i]['id']} / {candidates[i].get('country')}")
            league=candidates[selected]
            st.json(league['raw'])
            seasons=league['seasons']
            season_values=[str(x.get('year',x.get('season',''))) if isinstance(x,dict) else str(x) for x in seasons]
            season_values=[x for x in season_values if x]
            if season_values:
                season=st.selectbox('공급원이 반환한 시즌 (현재 시즌 직접 확인)',season_values)
                confirmed=st.checkbox(f"선택 대회·시즌·정규/컵 구분이 {competition} / {division}에 맞음을 확인했습니다",key='bind_'+competition+division+league['id']+season)
                today=datetime.now(KST).date()
                start=st.date_input('조회 시작일 (KST)',today)
                end=st.date_input('조회 종료일 (KST)',today+timedelta(days=7))
                st.caption('최대 31일. 대회·시즌 응답을 받은 뒤 선택한 한국 시간 범위로 필터링합니다. 공급원 다중 페이지 응답은 전체 완료로 표시하지 않습니다.')
                key=json.dumps(['games',competition,division,sport,league['id'],season,str(start),str(end)],ensure_ascii=False)
                load_button=st.button('경기 불러오기',disabled=not confirmed or not usable(cat))
                refresh_button=st.button('새로고침',disabled=not confirmed or not usable(cat))
                binding=None
                if load_button or refresh_button:
                    try:
                        binding=bind(path,competition,division,sport,league,season)
                        save_fetch(path,key,games(sport,league['id'],season,str(start),str(end)))
                    except ValueError as exc:st.error(str(exc))
                snapshot=read(path,'auto_snapshots',key)
                show_status(snapshot)
                if snapshot and snapshot['status']=='ok':
                    if not usable(snapshot):st.warning('일정 조회 후 24시간 경과: 새로고침 전 가져오기 보류')
                    st.dataframe([{'공급원 경기 ID':x['provider_match_id'],'홈':x['home'],'원정':x['away'],'시작(KST)':kst(x['kickoff']),'상태':str(x['status']),'점수 원자료':str(x['scores'] or x['goals']),'출처':x['source'],'수집(KST)':kst(x['collected_at']),'공급원 갱신 시각':'미확보','매칭':'공급원 ID로 구분 / 베트맨 매칭 미확인'} for x in snapshot['items']],hide_index=True)
                    idx=st.selectbox('수동 입력으로 이어갈 경기',range(len(snapshot['items'])),format_func=lambda i:snapshot['items'][i]['home']+' – '+snapshot['items'][i]['away'])
                    event=snapshot['items'][idx]
                    with st.expander('반환된 경기 원자료 대조'):st.json(event['raw'])
                    st.download_button('자동 조회 결과·출처·시각 저장',json.dumps(snapshot,ensure_ascii=False,indent=2),'auto_snapshot.json')
                    verified=st.checkbox('원자료의 경기·팀·시작 시각을 확인했습니다. 베트맨 판매 경기와의 일치 여부는 별도 확인합니다.',key='event_'+key+event['provider_match_id'])
                    if st.button('확인한 일정으로 수동 입력 채우기',disabled=not verified or not usable(snapshot) or not confirmed):
                        try:
                            binding=bind(path,competition,division,sport,league,season)
                            st.session_state.auto_prefill=to_manual(event,binding)
                            st.success('입력 초안 준비 완료. 왼쪽에서 「실제/예시 자료 입력」 → 「한 경기 직접 입력」으로 이동하세요. 베트맨 배당·마감·자료 기준 시각·모형값은 직접 확인해야 합니다.')
                        except ValueError as exc:st.error(str(exc))
            else:st.warning('시즌 목록을 확보하지 못했습니다. 현재 시즌을 추측해 조회하지 않습니다.')
        else:st.info('검색 결과 0개. 해당 대회 지원을 확인하지 못했습니다.')
    with st.expander('해외 배당 참고 조회 · 베트맨 배당 아님'):
        st.write('The Odds API 키:', '설정됨 (권한 미확인)' if os.environ.get('ODDS_API_KEY') else '미설정')
        if st.button('해외 배당 공급원의 지원 종목 조회'):save_fetch(path,'odds_catalog',catalog('odds'))
        oc=read(path,'auto_snapshots','odds_catalog');show_status(oc)
        if oc and usable(oc):
            sports=oc['items']
            index=st.selectbox('대상 대회에 해당하는 sport key',range(len(sports)),format_func=lambda i:sports[i]['name']+' / '+sports[i]['id'])
            chosen=sports[index];st.json(chosen['raw'])
            mapped=st.checkbox(f'이 key가 선택한 {competition} / {division}에 해당함을 확인했습니다')
            st.caption('현재 시즌 정보가 없는 카탈로그입니다. 반환된 경기별 시간과 원자료를 확인하세요. 해외 북메이커의 h2h만 참고하며 연장·정산 범위는 확정하지 않습니다. 버튼 호출은 계정 크레딧을 사용할 수 있습니다.')
            key='odds:'+chosen['id']
            if st.button('해외 참고 배당 조회/새로고침',disabled=not mapped):save_fetch(path,key,overseas_odds(chosen['id']))
            snapshot=read(path,'auto_snapshots',key);show_status(snapshot)
            if snapshot and snapshot['status']=='ok':
                for event in snapshot['items']:
                    st.write(event['home'],'–',event['away'],'시작',kst(event['kickoff']))
                    st.caption('출처 '+event['source']+' / 수집 '+kst(event['collected_at'])+' / 매칭 미확정 · 모델/조합에 자동 입력하지 않음')
                    display=[]
                    for item in odds_rows(event):
                        updated=item.pop('provider_updated_at')
                        try:item['공급원 갱신(KST)']=kst(updated)
                        except (ValueError,TypeError):item['공급원 갱신(KST)']='미확보'
                        display.append(item)
                    st.dataframe(display,hide_index=True)
                    with st.expander('해외 배당 원자료 '+event['provider_match_id']):st.json(event['raw'])
    st.warning('베트맨 공식 제공/API·수집 허용 범위는 확인하지 못했습니다. 로그인·접근 제한 우회나 자동 스크래핑은 구현하지 않았습니다.')
