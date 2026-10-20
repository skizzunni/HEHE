"""Forward shadow test of call tickets (calls.shadow_tickets).

Every day, once its calls are complete, calls.json archives -- before any
game starts, never revised -- the tickets each strategy would build:
likeliest-first (published) and the payout-target optimizer at 2x and 3x.
This grades them from the ledger and reports cashes, the chance claimed and
the ROI per strategy, with N and dates. A strategy is promoted only when the
day-bootstrap 95% interval of its cash difference against the published one
lies above zero on these forward days.

    python3 tools/shadow.py
"""
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "review", "shadow.json")


def grade(days, book):
    """{strategy: [(day, cashed or None if open/void, payout)]}"""
    import call_tickets as CT
    out = {}
    for day, rec in sorted(days.items()):
        sh = rec.get("shadow")
        if not sh or sh.get("skipped"):
            continue
        price = {c["id"]: CT.dec(c.get("price")) for c in rec.get("calls") or []}
        tickets = dict(sh)
        tickets.pop("t", None)
        strongest = tickets.pop("strongest", []) or []
        for i, ids in enumerate(strongest):
            tickets[f"strongest_{len(ids)}leg"] = ids
        for name, ids in tickets.items():
            if not ids:
                continue
            st = [(book.get(i) or {}).get("status") for i in ids]
            res = (False if "lost" in st else True if all(s == "won" for s in st) else None)
            out.setdefault(name, []).append((day, res, math.prod(price.get(i) or 1 for i in ids)))
    return out


def report(graded):
    rep = {}
    for name, rows in graded.items():
        done = [r for r in rows if r[1] is not None]
        rep[name] = dict(n=len(done), cashed=sum(r[1] for r in done),
                         roi=round(100 * sum((r[2] - 1) if r[1] else -1 for r in done) / len(done), 1) if done else None,
                         dates=[done[0][0], done[-1][0]] if done else None)
    return rep


def main():
    import calls
    import ledger
    rep = report(grade(calls.load_daily()["days"], ledger.load()))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1, sort_keys=True)
    print(json.dumps(rep))


if __name__ == "__main__":
    main()
