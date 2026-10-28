from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import math

KST = ZoneInfo('Asia/Seoul')
REQUIRED = ('sport', 'match_id', 'league', 'home', 'away', 'kickoff', 'deadline', 'source', 'collected_at', 'as_of', 'kind', 'product', 'home_odds', 'draw_odds', 'away_odds', 'home_xg', 'away_xg', 'xg_basis')
OPTIONAL = ('recent_form', 'opponent_strength', 'home_away_form', 'goals_stats', 'advanced_stats', 'injuries', 'suspensions', 'lineup', 'rest_travel', 'weather_venue', 'odds_history')
OPTIONAL_LABELS = dict(zip(OPTIONAL, ('최근 성적', '상대 수준', '홈·원정 성적', '득실점 통계', '세부 지표', '부상', '징계', '라인업', '휴식·이동', '날씨·경기장', '배당 이력')))


def timestamp(s):
    d = datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('시간대(+09:00 등)를 포함하세요.')
    return d


def kst(s):
    return timestamp(s).astimezone(KST).strftime('%Y-%m-%d %H:%M KST')


def validate(rows, now=None):
    now = now or datetime.now(timezone.utc)
    reports, seen, aliases, fixtures = [], set(), {}, set()
    for row in rows:
        errors, warnings = [], []
        known = set(REQUIRED) | set(OPTIONAL) | {'lineup_status', 'source_conflict'}
        unknown = [k for k,v in row.items() if k not in known and str(v).strip()]
        if unknown:
            errors.append('지원하지 않는 열: ' + ', '.join(unknown) + '. 상품·기준점·경기 중 정보를 혼합하지 마세요.')
        if row.get('sport') != 'football':
            errors.append('첫 버전은 축구(football)만 지원합니다.')
        for key in REQUIRED:
            if str(row.get(key, '')).strip() == '':
                errors.append(f'필수 항목 누락: {key}')
        mid = str(row.get('match_id', '')).strip()
        if mid in seen:
            errors.append('중복 경기 식별자: 한 경기당 승무패 배당 한 묶음만 입력하세요.')
        seen.add(mid)
        for team in ('home', 'away'):
            name = str(row.get(team, ''))
            normalized = ''.join(name.lower().split())
            if normalized in aliases and aliases[normalized] != name:
                errors.append('팀 표기 불일치: 공백·대소문자를 통일하세요.')
            aliases[normalized] = name
        if ''.join(str(row.get('home', '')).lower().split()) == ''.join(str(row.get('away', '')).lower().split()):
            errors.append('홈팀과 원정팀이 같습니다.')
        fixture = (str(row.get('home')), str(row.get('away')), str(row.get('kickoff')))
        if fixture in fixtures:
            errors.append('팀·시작 시각이 같은 중복 경기입니다.')
        fixtures.add(fixture)
        if row.get('product') != '1X2_90':
            errors.append('지원 상품은 정규시간 90분 승무패(1X2_90)뿐입니다. 다른 상품·기준점 혼합 금지.')
        if row.get('kind') not in ('real', 'example'):
            errors.append('kind는 real 또는 example이어야 합니다.')
        if row.get('kind') == 'example':
            warnings.append('예시 데이터: 실제 경기 추천·성능 증거로 사용할 수 없습니다.')
        try:
            for key in ('home_odds', 'draw_odds', 'away_odds'):
                x = float(row.get(key, ''))
                if not math.isfinite(x) or not 1 < x <= 1000:
                    raise ValueError()
        except (ValueError, TypeError):
            errors.append('배당 3개 모두 1 초과~1000 이하의 숫자로 입력하세요.')
        try:
            for key in ('home_xg', 'away_xg'):
                x = float(row.get(key, ''))
                if not math.isfinite(x) or not 0 <= x <= 8:
                    raise ValueError()
        except (ValueError, TypeError):
            errors.append('기대득점은 0~8의 숫자여야 합니다. 미확보 시 분석 보류.')
        try:
            kickoff, deadline, collected, asof = [timestamp(row.get(k, '')) for k in ('kickoff', 'deadline', 'collected_at', 'as_of')]
            if deadline > kickoff:
                errors.append('구매 마감은 경기 시작보다 늦을 수 없습니다.')
            if asof > collected or collected > now:
                errors.append('기준 시각·수집 시각의 순서 또는 미래 시각이 잘못되었습니다.')
            if collected >= deadline or asof >= kickoff:
                errors.append('마감 후 수집 또는 시작 후 기준 정보: 사전 분석 입력에서 제외합니다.')
            if now >= deadline or now >= kickoff:
                warnings.append('마감 또는 시작 지남: 신규 사전 예측·조합 대상 제외.')
            if (now - collected).total_seconds() > 86400:
                warnings.append('수집 후 24시간 경과: 오래된 정보입니다(운영상 경고 기준).')
        except (ValueError, TypeError):
            errors.append('시각 형식 오류: 2026-11-01T19:00:00+09:00 형식으로 입력하세요.')
        missing = [k for k in OPTIONAL if not str(row.get(k, '')).strip()]
        if missing:
            warnings.append('미확보 정보는 모형에 반영되지 않습니다: ' + ', '.join(OPTIONAL_LABELS[k] for k in missing))
        if row.get('lineup_status') != 'confirmed':
            warnings.append('라인업 미확정 또는 미확보.')
        if row.get('source_conflict', '').lower() in ('true', '1', 'yes'):
            warnings.append('출처 충돌: 사용자가 원자료를 대조해야 합니다.')
        warnings.append('기대득점은 사용자 입력 가정입니다. 팀 별칭·기사 진위·출처 충돌을 자동 확인하지 않습니다.')
        reports.append({'match_id': mid, 'errors': errors, 'warnings': warnings, 'missing': missing, 'available_fields': len(OPTIONAL)-len(missing), 'total_fields': len(OPTIONAL)})
    return reports


def eligible(row, report, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        return not report['errors'] and now < timestamp(row['deadline']) and now < timestamp(row['kickoff'])
    except (ValueError, KeyError):
        return False
