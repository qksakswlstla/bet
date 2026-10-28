import itertools
import math


def settle(legs, stake):
    """명시적 단순 정산: 적중=배당, 적특/취소=1, 미적중=0. 전부 void면 원금 반환."""
    if not math.isfinite(stake) or stake < 0:
        raise ValueError('고정 금액은 0 이상이어야 합니다.')
    factor = 1.
    if not legs:
        raise ValueError('선택이 없습니다.')
    for leg in legs:
        odds = float(leg['odds'])
        if not math.isfinite(odds) or odds <= 1:
            raise ValueError('배당 오류')
        status = leg['status']
        if status not in ('win', 'loss', 'void'):
            raise ValueError('정산 상태 오류')
        factor *= odds if status == 'win' else 0 if status == 'loss' else 1
    return {'return': stake*factor, 'profit': stake*(factor-1)}


def compare(legs, size=2, budget=10000):
    if size not in (2, 3) or budget < 0 or not math.isfinite(budget):
        raise ValueError('2~3경기와 0 이상의 고정 예산만 지원합니다.')
    if len(legs) > 10:
        raise ValueError('비교는 최대 10경기를 선택하세요 (최대 120개 조합).')
    output = []
    for group in itertools.combinations(legs, size):
        if len({g['match_id'] for g in group}) != size:
            continue
        for g in group:
            if not 0 <= g['probability'] <= 1 or not 0 <= g['low'] <= g['probability'] <= g['high'] <= 1 or not math.isfinite(g['odds']) or g['odds'] <= 1:
                raise ValueError('조합 확률·배당 범위 오류')
        odds = math.prod(g['odds'] for g in group)
        p = math.prod(g['probability'] for g in group)
        low = math.prod(g['low'] for g in group)
        high = math.prod(g['high'] for g in group)
        output.append({'selections': ' + '.join(g['label'] for g in group), 'match_ids': [g['match_id'] for g in group], 'odds': odds, 'probability': p, 'sensitivity_low': low, 'sensitivity_high': high, 'expected_profit': budget*(p*odds-1), 'low_expected_profit': budget*(low*odds-1), 'high_expected_profit': budget*(high*odds-1)})
    return output
