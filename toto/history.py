"""생성 시각을 서버에서 기록하는 추가 전용 예측/결과 저장소."""
from datetime import datetime, timezone
import json
import sqlite3
import uuid
from pathlib import Path
from contextlib import contextmanager
import numpy as np
from .model import probabilities, implied, VERSION, OUTCOMES
from .validation import validate, eligible, timestamp
from .combinations import settle


@contextmanager
def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS predictions (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS results (prediction_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    try:
        with db:
            yield db
    finally:
        db.close()


def save_prediction(path, row, now=None):
    now = now or datetime.now(timezone.utc)
    report = validate([row], now)[0]
    if not eligible(row, report, now):
        raise ValueError('검수 오류 또는 마감/시작 후에는 사전 예측을 기록할 수 없습니다.')
    p = probabilities(float(row['home_xg']), float(row['away_xg']))
    snapshot = {'id': str(uuid.uuid4()), 'created_at': now.isoformat(), 'model': VERSION, 'row': dict(row), 'probabilities': [p[k] for k in OUTCOMES], 'odds': [float(row[k]) for k in ('home_odds','draw_odds','away_odds')]}
    with connect(path) as db:
        # 같은 경기 중복 예측이 평가 표본을 부풀리지 않도록 첫 예측만 유지.
        for (payload,) in db.execute('SELECT payload FROM predictions'):
            old = json.loads(payload)
            if old['row']['match_id'] == row['match_id'] and old['row']['kind'] == row['kind']:
                raise ValueError('이 경기의 예측이 이미 기록되어 있습니다. 첫 기록을 유지합니다.')
        db.execute('INSERT INTO predictions VALUES (?,?)', (snapshot['id'], json.dumps(snapshot, ensure_ascii=False)))
    return snapshot


def load_history(path):
    with connect(path) as db:
        results = {pid: json.loads(p) for pid, p in db.execute('SELECT prediction_id,payload FROM results')}
        output = []
        for pid, payload in db.execute('SELECT id,payload FROM predictions'):
            item = json.loads(payload)
            item['result'] = results.get(pid)
            output.append(item)
    return sorted(output, key=lambda x: timestamp(x['row']['kickoff']))


def save_result(path, pid, status, home, away, source, confirmed=False, now=None):
    now = now or datetime.now(timezone.utc)
    item = next((x for x in load_history(path) if x['id'] == pid), None)
    if not item or now < timestamp(item['row']['kickoff']) or not source.strip():
        raise ValueError('경기 시작 후 출처가 있는 결과만 기록할 수 있습니다.')
    if status not in ('finished', 'void') or any(not isinstance(v, int) or v < 0 for v in (home, away)):
        raise ValueError('정산 상태 또는 점수 오류')
    data = {'status': status, 'home': home, 'away': away, 'source': source, 'recorded_at': now.isoformat(), 'odds_and_rules_confirmed': bool(confirmed)}
    with connect(path) as db:
        try:
            db.execute('INSERT INTO results VALUES (?,?)', (pid, json.dumps(data, ensure_ascii=False)))
        except sqlite3.IntegrityError as exc:
            raise ValueError('결과가 이미 기록되었습니다. 앱에서 덮어쓰지 않습니다.') from exc


def evaluate(items, kind='real', stake=1000):
    """Brier는 3개 클래스 제곱오차의 합(0~2); log loss는 자연로그."""
    selected = sorted([x for x in items if x['row']['kind'] == kind], key=lambda x: timestamp(x['row']['kickoff']))
    valid, excluded = [], []
    for x in selected:
        try:
            row = x['row']
            probs = np.array(x['probabilities'], dtype=float)
            prior = timestamp(x['created_at']) < timestamp(row['deadline']) <= timestamp(row['kickoff'])
            prior = prior and timestamp(row['as_of']) <= timestamp(row['collected_at']) <= timestamp(x['created_at'])
            if not prior or len(probs) != 3 or not np.isfinite(probs).all() or (probs < 0).any() or (probs > 1).any() or abs(probs.sum()-1) > 1e-8:
                raise ValueError('시간 누수 또는 확률 오류')
            implied(x['odds'])
            result = x.get('result')
            if not result or result['status'] != 'finished':
                excluded.append({'id': x['id'], 'reason': '결과 미확보 또는 취소/적특'})
                continue
            if timestamp(result['recorded_at']) < timestamp(row['kickoff']):
                raise ValueError('결과 시각 오류')
            valid.append(x)
        except (ValueError, KeyError, TypeError):
            excluded.append({'id': x.get('id'), 'reason': '시간 누수·입력·확률 검수 실패'})
    n = len(valid)
    # 고정 모형이라 실제 학습은 없음. 마지막 20%는 별도 기간 보고용.
    cut1, cut2 = int(n*.6), int(n*.8)
    chunks = [('학습 참고 60% (학습 미실시)', valid[:cut1]), ('검증 20%', valid[cut1:cut2]), ('별도 평가 20%', valid[cut2:])]
    def metrics(group):
        if not group:
            return {'n': 0}
        p = np.array([x['probabilities'] for x in group])
        y = np.array([0 if x['result']['home'] > x['result']['away'] else 1 if x['result']['home'] == x['result']['away'] else 2 for x in group])
        target = np.eye(3)[y]
        market = np.array([implied(x['odds'])['adjusted'] for x in group])
        def score(pred):
            return {'brier': float(np.mean(np.sum((pred-target)**2, axis=1))), 'log_loss': float(-np.log(np.clip(pred[np.arange(len(y)), y], 1e-15, 1)).mean()), 'accuracy': float((pred.argmax(axis=1)==y).mean())}
        # 각 경기 최대 확률 선택에 같은 고정 금액을 사용한 비교 가정.
        profits, returns = [], []
        for x, actual in zip(group, y):
            if not x['result']['odds_and_rules_confirmed']:
                continue
            pick = int(np.argmax(x['probabilities']))
            settled = settle([{'odds': x['odds'][pick], 'status': 'win' if pick == actual else 'loss'}], stake)
            profits.append(settled['profit'])
            returns.append(settled)
        equity = np.r_[0, np.cumsum(profits)]
        drawdown = float((np.maximum.accumulate(equity)-equity).max())
        bins = []
        for i in range(5):
            mask = (p >= i/5) & ((p < (i+1)/5) if i < 4 else (p <= 1))
            bins.append({'확률 구간': f'{i*20}–{(i+1)*20}%', '건수': int(mask.sum()), '평균 예측': float(p[mask].mean()) if mask.any() else None, '실제 빈도': float(target[mask].mean()) if mask.any() else None})
        return {'n': len(group), 'period': [group[0]['row']['kickoff'], group[-1]['row']['kickoff']], 'model': score(p), 'market': score(market), 'uniform': score(np.full_like(p, 1/3)), 'calibration': bins, 'settled_n': len(profits), 'roi': sum(profits)/(len(profits)*stake) if profits and stake else None, 'profit': sum(profits), 'max_drawdown': drawdown, 'equity': equity.tolist()}
    return {'n': n, 'excluded': excluded, 'all': metrics(valid), 'splits': {name: metrics(group) for name, group in chunks}, 'validated': False}
