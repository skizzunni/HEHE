#!/usr/bin/env python3
"""Did the legs whose price drifted lose more than the ones that firmed?

Reads every work/slate_*/price_log.jsonl (written by tools/recheck_ticket.py
at each re-check) and grades each saved ticket.json with tools/grade_picks.py.
A leg "drifted" when its last logged price implies at least DRIFT points less
chance than its first (e.g. -1300 -> -950: 92.9% -> 90.5%), "firmed" when at
least DRIFT more, else "flat". Prints won/lost by group. Information only:
too few days yet to test; the bar for acting is the usual both-halves z 2.8.

    python3 tools/price_drift.py
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRIFT = 0.01


def implied(price):
    try:
        a = float(str(price).replace("+", ""))
    except (TypeError, ValueError):
        return None
    return -a / (100 - a) if a < 0 else 100 / (100 + a)


def group(log_lines, label):
    """'drifted' / 'firmed' / 'flat' / None for one leg across its logged prices."""
    seen = [implied(r["prices"].get(label)) for r in log_lines if r.get("prices", {}).get(label) is not None]
    seen = [p for p in seen if p is not None]
    if len(seen) < 2:
        return None
    d = seen[-1] - seen[0]
    return "drifted" if d <= -DRIFT else "firmed" if d >= DRIFT else "flat"


def tally(rows):
    """rows: [(group, result)] -> {group: {won, lost, push}}"""
    out = {}
    for g, r in rows:
        if g and r in ("won", "lost", "push"):
            out.setdefault(g, {"won": 0, "lost": 0, "push": 0})[r] += 1
    return out


def main(root=ROOT, grade_fn=None):
    import grade_picks as G
    rows = []
    for log in sorted(glob.glob(os.path.join(root, "work", "slate_*", "price_log.jsonl"))):
        ticket = os.path.join(os.path.dirname(log), "ticket.json")
        if not os.path.exists(ticket):
            continue
        lines = [json.loads(x) for x in open(log) if x.strip()]
        picks, results, _ = (grade_fn or G.main)(ticket)
        rows += [(group(lines, p.get("label")), r) for p, r in zip(picks, results)]
    return tally(rows)


if __name__ == "__main__":
    t = main()
    if not t:
        print("No graded legs with a price history yet.")
    for g in ("firmed", "flat", "drifted"):
        if g in t:
            c = t[g]
            n = c["won"] + c["lost"]
            print(f"{g:8} {c['won']}-{c['lost']}" + (f" ({100 * c['won'] / n:.0f}%)" if n else "") + (f", {c['push']} void" if c["push"] else ""))
