"""Whole-ticket backtest on the pick ledger's own games.

Source: every graded, book-priced, straight-win ledger pick whose side was the
market favourite at the close, with DraftKings' closing no-vig chance of that
side (review/clv.json `close`) and the last price the board captured before
the start (the ledger's `price`, the executable price). All strategies select
at the same moment -- just before each game -- from the same legs, the same
prices and the same leg standard; nothing here is fitted, so there is no
training window. Results are split at the window's midpoint by date as well.

Per day, per payout target (2x, 3x, 5x total return) and leg standard:

    strongest   the current calls rule: the likeliest legs first, one per
                game, until the price product reaches the target
    optimizer   tickets.optimize: the combination with the highest chance
                that reaches the target (one leg per game, kind cap)

Reported: tickets made (coverage), cashed, cash rate against the chance
claimed, ROI on $1 a ticket, longest losing run, and a day-bootstrap 95%
interval for the difference in cashes on days both made a ticket.

Limits: selection at the close, not at 8:00 AM (the 8 AM price is archived
only from 2026-10-18); legs are straight-win favourites only (the price of
the other side is not in the ledger); price products are estimates of a
parlay's payout.

    python3 tools/ticket_backtest.py
"""
import json
import math
import os
import random
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import tickets as T                                       # noqa: E402

OUT = os.path.join(ROOT, "data", "ticket_backtest.json")
TARGETS = (2.0, 3.0, 5.0)
STANDARDS = (0.60, 0.70, 0.75)
MAX_LEGS = 6


def dec(american):
    try:
        v = int(str(american).replace("+", ""))
    except (TypeError, ValueError):
        return None
    return None if v == 0 else 1 + (v / 100 if v > 0 else 100 / -v)


def load_days():
    import ledger
    import calibration as C
    sys.path.insert(0, HERE)
    import clv
    L = ledger.load()
    book = clv.load()["picks"]
    days = defaultdict(list)
    for k, e in L.items():
        r = book.get(k)
        if not r or r.get("close") is None or e.get("dc") or e.get("status") not in ("won", "lost"):
            continue
        d = dec(e.get("price"))
        if not d or r["close"] < 0.5 or d >= 2.0:          # the favourite, at a favourite's price
            continue
        days[C.day_of(e)].append(dict(gid=k, p=r["close"], dec=d, won=e["status"] == "won",
                                      league=e["league"], label=e["pick"], spec=dict(t="win")))
    return days


def strongest(legs, target, min_p, max_legs=MAX_LEGS):
    pick, d = [], 1.0
    for L in sorted((x for x in legs if x["p"] >= min_p), key=lambda x: -x["p"]):
        if len(pick) >= max_legs:
            break
        pick.append(L)
        d *= L["dec"]
        if d >= target:
            return pick
    return None


def summary(rows):
    made = [(d, t) for d, t in rows if t]
    if not made:
        return dict(made=0)
    cashed = [all(L["won"] for L in t) for _, t in made]
    claimed = [math.prod(L["p"] for L in t) for _, t in made]
    pays = [math.prod(L["dec"] for L in t) for _, t in made]
    ret = [(p - 1) if c else -1 for p, c in zip(pays, cashed)]
    run = worst = 0
    bank = peak = dd = 0.0
    for c, r in zip(cashed, ret):
        run = 0 if c else run + 1
        worst = max(worst, run)
        bank += r
        peak = max(peak, bank)
        dd = max(dd, peak - bank)
    return dict(made=len(made), cashed=sum(cashed), cash_rate=round(100 * sum(cashed) / len(made), 1),
                claimed=round(100 * sum(claimed) / len(made), 1), avg_payout=round(sum(pays) / len(made), 2),
                avg_legs=round(sum(len(t) for _, t in made) / len(made), 2),
                roi=round(100 * sum(ret) / len(made), 1), max_drawdown_units=round(dd, 2),
                longest_losing_run=worst)


def paired(a, b, draws=2000, seed=5):
    diffs = []
    for (_, x), (_, y) in zip(a, b):
        if x and y:
            diffs.append(int(all(L["won"] for L in y)) - int(all(L["won"] for L in x)))
    if not diffs:
        return dict(days=0)
    rng = random.Random(seed)
    boot = sorted(sum(rng.choice(diffs) for _ in diffs) for _ in range(draws))
    return dict(days=len(diffs), diff=sum(diffs), ci95=[boot[int(.025 * draws)], boot[int(.975 * draws) - 1]],
                proven=boot[int(.025 * draws)] > 0)


def main():
    days = load_days()
    dates = sorted(days)
    cut = dates[len(dates) // 2]
    rep = dict(dates=[dates[0], dates[-1]], days=len(dates), legs=sum(len(v) for v in days.values()),
               later_from=cut, results=[])
    for target in TARGETS:
        for s in STANDARDS:
            old = [(d, strongest(days[d], target, s)) for d in dates]
            new = [(d, T.optimize(days[d], target, s, max_legs=MAX_LEGS)["legs"]) for d in dates]
            late = lambda rows: [(d, t) for d, t in rows if d >= cut]
            rep["results"].append(dict(target=target, standard=s, strongest=summary(old), optimizer=summary(new),
                                       paired=paired(old, new),
                                       later=dict(strongest=summary(late(old)), optimizer=summary(late(new)),
                                                  paired=paired(late(old), late(new)))))
    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1)
    print(f"{rep['legs']} legs over {rep['days']} days {rep['dates'][0]}..{rep['dates'][1]}")
    for r in rep["results"]:
        a, b, p = r["strongest"], r["optimizer"], r["paired"]
        print(f"{r['target']:.0f}x @{100 * r['standard']:.0f}%  strongest {a.get('cashed')}/{a.get('made')} "
              f"({a.get('cash_rate')}% v {a.get('claimed')}%, ROI {a.get('roi')}%, {a.get('avg_legs')} legs, dd {a.get('max_drawdown_units')})"
              f"  optimizer {b.get('cashed')}/{b.get('made')} ({b.get('cash_rate')}% v {b.get('claimed')}%, ROI {b.get('roi')}%, "
              f"{b.get('avg_legs')} legs, dd {b.get('max_drawdown_units')})  paired {p}")
    return rep


if __name__ == "__main__":
    main()
