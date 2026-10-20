"""Compare identical ledger windows; never fetch or invent historical quotes.

python tools/priced_record_audit.py --before ORIGINAL_LEDGER --out REPORT
"""
import argparse
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ledger
from record_eligibility import record_priced


def summarize(rows):
    w = sum(e['status'] == 'won' for e in rows)
    return dict(n=len(rows), won=w, lost=len(rows)-w,
                hit=round(100*w/len(rows), 2) if rows else None)


def compare(before, after):
    out = {}
    for name, lo, hi in [('all', '', '9999'), ('Oct20', '2026-10-20', '2026-10-20'),
                         ('Oct7-20', '2026-10-07', '2026-10-20')]:
        phases = {}
        for phase, book in [('before', before), ('after', after)]:
            rows = [e for e in book.values() if e.get('status') in ('won', 'lost')
                    and lo <= (e.get('played') or e.get('date') or '') <= hi]
            kept = rows if phase == 'before' else [e for e in rows if record_priced(e)]
            phases[phase] = dict(overall=summarize(kept), strong=summarize(
                [e for e in kept if (e.get('strong', False) if phase == 'before' else ledger._strong(e))]),
                excluded_graded=len(rows)-len(kept))
        out[name] = phases
    return out


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--before', required=True); p.add_argument('--out', required=True); p.add_argument('--after', help='Optional separate ledger; default compares the original snapshot with itself under the new rules')
    a = p.parse_args()
    with open(a.before) as f: before = json.load(f)
    after = before
    if a.after:
        with open(a.after) as f: after = json.load(f)
    with open(a.out, 'w') as f: json.dump(compare(before, after), f, indent=2); f.write('\n')
