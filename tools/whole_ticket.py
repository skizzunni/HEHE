"""Whole-ticket backtest: does the optimizer cash more tickets than the
baseline at the same payout target? Individual hit rates do not count here.

    python3 tools/whole_ticket.py        # writes data/whole_ticket.json

Data: data/backtest_kalshi_legs.json -- settled Kalshi contracts on game lines
(spreads, totals, team totals) with the hourly pre-start quote. For every leg

    chance  = Kalshi's mid-price (ask less half the spread): the same-time
              market estimate both choosers see
    price   = 1 / (ask + fee): what $1 actually buys, fees included

Per date, per payout target (total return 2x, 3x, 5x) and leg standard, two
tickets from the same quotes, the same standard and the same leg cap:

    baseline   the site's cards today: within the Locks price window (-400 to
               -120), each game's likeliest qualifying line, likeliest first,
               until the payout is reached
    optimizer  tickets.optimize -- the combination with the highest chance
               that reaches the payout (one leg per game, kind cap)

Reported for each: tickets made (coverage), cashed, cash rate, the chance the
tickets claimed (product of leg chances) against what cashed -- the check on
treating legs from different games as independent -- return on $1 a ticket,
the longest losing run, and a day-bootstrap interval for the difference in
cashes on dates where both made a ticket. Dates split in half: the later half
is reported apart (nothing here is fitted, but the split shows stability).

Limits, stated: these are single Kalshi contracts combined as if one parlay
(payout = product of prices); quotes are the last hourly candle before each
game's start, not one morning decision time; 226 games / 38 dates.
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
import tickets as T                                       # noqa: E402

LEGS = os.path.join(ROOT, "data", "backtest_kalshi_legs.json")
OUT = os.path.join(ROOT, "data", "whole_ticket.json")
TARGETS = (2.0, 3.0, 5.0)
STANDARDS = (0.70, 0.75, 0.80)
MAX_LEGS = 6


def load_days():
    days = defaultdict(list)
    for r in json.load(open(LEGS)):
        w = r.get("width") or 0
        mid = r["cost"] - w / 2
        pay = r["cost"] + r["fee"]
        if not 0.02 < mid < 0.99 or pay >= 1:
            continue
        t = (r.get("spec") or {}).get("t")
        days[r["date"]].append(dict(gid=r["game"], label=r["ticker"] + r["side"], p=mid,
                                    dec=1 / pay, won=r["won"], league=r["game"].split(":")[0],
                                    spec=dict(t=t)))
    return days


LOCKS_WINDOW = (1.25, 1.834)      # -400 .. -120, the regular Locks card


def baseline(legs, target, min_p, max_legs=MAX_LEGS):
    """The site's way today: within the Locks price window, each game's
    likeliest qualifying line, likeliest first, until the payout is reached
    (the card's top-N slice)."""
    best = {}
    for L in sorted((x for x in legs if x["p"] >= min_p
                     and LOCKS_WINDOW[0] <= x["dec"] <= LOCKS_WINDOW[1]), key=lambda x: -x["p"]):
        best.setdefault(L["gid"], L)
    pick, d, kinds = [], 1.0, {}
    for L in sorted(best.values(), key=lambda x: -x["p"]):
        if len(pick) >= max_legs:
            break
        k = T.kind(L)
        if kinds.get(k, 0) >= T.KIND_CAP:
            continue
        kinds[k] = kinds.get(k, 0) + 1
        pick.append(L)
        d *= L["dec"]
        if d >= target:
            return pick
    return None


def summary(rows):
    """rows: [(day, ticket legs or None)]"""
    made = [(d, t) for d, t in rows if t]
    if not made:
        return dict(made=0)
    cashed = [all(L["won"] for L in t) for _, t in made]
    claimed = [math.prod(L["p"] for L in t) for _, t in made]
    pays = [math.prod(L["dec"] for L in t) for _, t in made]
    ret = sum((p - 1) if c else -1 for p, c in zip(pays, cashed))
    run = worst = 0
    for c in cashed:
        run = 0 if c else run + 1
        worst = max(worst, run)
    return dict(made=len(made), cashed=sum(cashed), cash_rate=round(100 * sum(cashed) / len(made), 1),
                claimed=round(100 * sum(claimed) / len(made), 1),
                avg_payout=round(sum(pays) / len(made), 2), avg_legs=round(sum(len(t) for _, t in made) / len(made), 2),
                roi=round(100 * ret / len(made), 1), longest_losing_run=worst)


def paired(a, b, draws=2000, seed=5):
    """Cashes new - old on dates where both made a ticket; day bootstrap."""
    diffs = []
    gained = lost = 0
    for (d, x), (_, y) in zip(a, b):
        if not x or not y:
            continue
        cx, cy = all(L["won"] for L in x), all(L["won"] for L in y)
        diffs.append(int(cy) - int(cx))
        gained += cy and not cx
        lost += cx and not cy
    if not diffs:
        return dict(dates=0)
    rng = random.Random(seed)
    boot = sorted(sum(rng.choice(diffs) for _ in diffs) for _ in range(draws))
    return dict(dates=len(diffs), diff=sum(diffs), new_cashed_old_missed=gained,
                old_cashed_new_missed=lost,
                ci95=[boot[int(0.025 * draws)], boot[int(0.975 * draws) - 1]],
                promote=boot[int(0.025 * draws)] > 0)


def main():
    days = load_days()
    dates = sorted(days)
    cut = dates[len(dates) // 2]
    rep = dict(source="data/backtest_kalshi_legs.json", dates=len(dates),
               games=len({L["gid"] for v in days.values() for L in v}), later_from=cut,
               max_legs=MAX_LEGS, kind_cap=T.KIND_CAP, results=[])
    for target in TARGETS:
        for s in STANDARDS:
            old = [(d, baseline(days[d], target, s)) for d in dates]
            new = [(d, T.optimize(days[d], target, s, max_legs=MAX_LEGS)["legs"]) for d in dates]
            later = lambda rows: [(d, t) for d, t in rows if d >= cut]
            rep["results"].append(dict(
                target=target, standard=s,
                baseline=summary(old), optimizer=summary(new),
                paired=paired(old, new),
                later=dict(baseline=summary(later(old)), optimizer=summary(later(new)),
                           paired=paired(later(old), later(new)))))
    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1)
    for r in rep["results"]:
        b, o, p = r["baseline"], r["optimizer"], r["paired"]
        print(f"{r['target']:.0f}x at {100 * r['standard']:.0f}%+  baseline {b.get('cashed')}/{b.get('made')} "
              f"({b.get('cash_rate')}% vs {b.get('claimed')}% claimed, ROI {b.get('roi')}%, {b.get('avg_legs')} legs)"
              f"  optimizer {o.get('cashed')}/{o.get('made')} ({o.get('cash_rate')}% vs {o.get('claimed')}%, "
              f"ROI {o.get('roi')}%, {o.get('avg_legs')} legs)  paired {p}")
    return rep


if __name__ == "__main__":
    main()
