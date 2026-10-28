"""독립 포아송 기준 모형. 입력 기대득점은 학습 추정치가 아니다."""
import math
import numpy as np

VERSION = 'independent-poisson-1.0'
OUTCOMES = ('home', 'draw', 'away')


def _rate(value):
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 8:
        raise ValueError('기대득점은 0~8의 유한한 수여야 합니다.')
    return value


def probabilities(home, away, handicap=0, total=2.5, score=(0, 0)):
    """잔여 득점의 정확 합산. 60골까지 절단; 입력 범위에서 꼬리 무시 가능."""
    home, away = _rate(home), _rate(away)
    if not math.isfinite(float(total)) or not math.isfinite(float(handicap)):
        raise ValueError('기준점은 유한해야 합니다.')
    if any(not isinstance(x, (int, np.integer)) or x < 0 for x in score):
        raise ValueError('점수는 음수가 아닌 정수여야 합니다.')
    def pmf(rate):
        return np.array([math.exp(-rate) * rate ** k / math.factorial(k) for k in range(61)])
    grid = np.outer(pmf(home), pmf(away))
    grid /= grid.sum()
    h, a = np.indices(grid.shape)
    h, a = h + score[0], a + score[1]
    diff, goals = h - a, h + a
    result = dict(zip(OUTCOMES, [float(grid[diff > 0].sum()), float(grid[diff == 0].sum()), float(grid[diff < 0].sum())]))
    result['handicap'] = dict(zip(OUTCOMES, [float(grid[diff + handicap > 0].sum()), float(grid[diff + handicap == 0].sum()), float(grid[diff + handicap < 0].sum())]))
    result['total'] = {'over': float(grid[goals > total].sum()), 'push': float(grid[goals == total].sum()), 'under': float(grid[goals < total].sum())}
    indices = np.argsort(grid.ravel())[-8:][::-1]
    result['scores'] = [{'score': f'{i // 61 + score[0]}:{i % 61 + score[1]}', 'probability': float(grid.ravel()[i])} for i in indices]
    return result


def implied(odds):
    arr = np.asarray(odds, dtype=float)
    if len(arr) != 3 or not np.isfinite(arr).all() or (arr <= 1).any():
        raise ValueError('승·무·패 배당 3개가 모두 1보다 커야 합니다.')
    raw = 1 / arr
    return {'raw': raw.tolist(), 'margin': float(raw.sum() - 1), 'adjusted': (raw / raw.sum()).tolist()}


def simulate(home, away, runs=20000, seed=42, minute=0, score=(0, 0), home_factor=1., away_factor=1.):
    if not 1000 <= runs <= 200000 or not 0 <= minute <= 90:
        raise ValueError('실행 횟수 1,000~200,000, 경과 시간 0~90분 범위입니다.')
    if any(not math.isfinite(x) or x < 0 for x in (home_factor, away_factor)):
        raise ValueError('득점 배수는 0 이상이어야 합니다.')
    h = _rate(_rate(home) * home_factor * (90-minute) / 90)
    a = _rate(_rate(away) * away_factor * (90-minute) / 90)
    exact = probabilities(h, a, score=score)
    rng = np.random.default_rng(seed)
    hg, ag = rng.poisson(h, runs) + score[0], rng.poisson(a, runs) + score[1]
    counts = [int((hg > ag).sum()), int((hg == ag).sum()), int((hg < ag).sum())]
    return {'version': VERSION, 'runs': runs, 'seed': seed, 'inputs': {'home': home, 'away': away, 'minute': minute, 'score': list(score), 'home_factor': home_factor, 'away_factor': away_factor}, 'probabilities': dict(zip(OUTCOMES, [n/runs for n in counts])), 'mc_standard_error': {k: math.sqrt((n/runs)*(1-n/runs)/runs) for k, n in zip(OUTCOMES, counts)}, 'exact': {k: exact[k] for k in OUTCOMES}}
