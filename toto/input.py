import csv
import io
from .validation import REQUIRED, OPTIONAL


def read_csv(text):
    if len(text.encode('utf-8')) > 2_000_000:
        raise ValueError('CSV는 2MB 이하로 입력하세요.')
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    if not reader.fieldnames or len(reader.fieldnames) != len(set(k.strip() for k in reader.fieldnames)):
        raise ValueError('CSV 열 이름이 없거나 중복되었습니다.')
    parsed = []
    for i, record in enumerate(reader):
        if i >= 100:
            raise ValueError('한 번에 최대 100경기입니다.')
        if None in record or any(v is None for v in record.values()):
            raise ValueError('CSV 열 수가 맞지 않습니다.')
        parsed.append({k.strip(): v.strip() for k, v in record.items()})
    return parsed


def csv_text(records):
    out = io.StringIO()
    fields = list(dict.fromkeys([*REQUIRED, 'lineup_status', 'source_conflict', *OPTIONAL]))
    w = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore')
    w.writeheader()
    w.writerows(records)
    return out.getvalue()
