"""키 값을 출력하지 않는 연결 점검. 예: python scripts/check_provider.py basketball"""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from toto.providers import catalog

if len(sys.argv)!=2 or sys.argv[1] not in ['basketball','volleyball','football','odds']:
    raise SystemExit('사용법: python scripts/check_provider.py basketball|volleyball|football|odds')
result=catalog(sys.argv[1])
print('status:',result.status)
print('source:',result.source)
print('message:',result.message)
print('catalog_count:',len(result.items))
print('quota:',result.quota)
print('이 결과는 대회 목록 조회이며 특정 대회의 현재 시즌 경기·배당 지원 검증이 아닙니다.')
raise SystemExit(0 if result.status in ('ok','empty') else 1)
