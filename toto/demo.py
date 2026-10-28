from datetime import datetime, timedelta, timezone
from .model import probabilities, OUTCOMES, VERSION


def example_matches():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    rows = []
    for i, (h, a) in enumerate(((1.6, 1.1), (1.2, 1.3), (2., .8))):
        rows.append({'match_id': f'DEMO-{i+1}', 'league': '가상 리그', 'home': f'예시 홈팀 {i+1}', 'away': f'예시 원정팀 {i+1}', 'kickoff': (now+timedelta(days=2, hours=i)).isoformat(), 'deadline': (now+timedelta(days=2, hours=i, minutes=-10)).isoformat(), 'source': '프로그램 생성 예시 (실제 경기 아님)', 'collected_at': now.isoformat(), 'as_of': now.isoformat(), 'kind': 'example', 'product': '1X2_90', 'home_odds': str(2.1+i*.1), 'draw_odds': '3.3', 'away_odds': '3.2', 'home_xg': str(h), 'away_xg': str(a), 'xg_basis': '화면 확인을 위한 임의 가정', 'lineup_status': 'unknown', 'source_conflict': 'false'})
    for row in rows:
        row['sport'] = 'football'
    return rows


def example_history():
    now = datetime.now(timezone.utc).replace(microsecond=0)
    items = []
    for i in range(30):
        row = example_matches()[i % 3].copy()
        kickoff = now - timedelta(days=40-i)
        row.update(match_id=f'PAST-DEMO-{i}', kickoff=kickoff.isoformat(), deadline=(kickoff-timedelta(minutes=10)).isoformat(), collected_at=(kickoff-timedelta(days=1)).isoformat(), as_of=(kickoff-timedelta(days=1)).isoformat())
        p = probabilities(float(row['home_xg']), float(row['away_xg']))
        h, a = ((2, 1), (0, 0), (0, 1), (1, 1), (3, 0))[i % 5]
        items.append({'id': row['match_id'], 'row': row, 'created_at': (kickoff-timedelta(hours=12)).isoformat(), 'model': VERSION, 'probabilities': [p[k] for k in OUTCOMES], 'odds': [float(row[k]) for k in ('home_odds', 'draw_odds', 'away_odds')], 'result': {'status': 'finished', 'home': h, 'away': a, 'source': '합성 예시 결과', 'recorded_at': (kickoff+timedelta(hours=3)).isoformat(), 'odds_and_rules_confirmed': True}})
    return items
