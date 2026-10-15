"""Replay the lottery on past games: would the tickets have hit?

    python3 tools/lottery_backtest.py      # needs data/backtest_kalshi_legs.json

Every leg comes from tools/kalshi_backtest.py: a finished NFL, college
football, NHL, NBA or EPL game, Kalshi's price to buy the leg an hour before
kickoff (plus its fee), the board's chance for it from DraftKings' closing
lines, and how Kalshi settled it. A ticket's payout is what those legs paid
together at Kalshi's prices; nothing here is known only after kickoff.

For each past day it builds one ticket per strategy and tier, exactly as the
lottery would have that morning, and counts hits. A strategy beats chance
only if it hits more often than its own prices said it would.

It also looks for the edges a lottery could stack:
  * return by price band (is there a favourite-longshot bias on Kalshi?)
  * return by model-vs-price disagreement, out of sample
  * ladder breaks: one game's lines priced out of order (Over 40.5 cheaper
    than Over 43.5), which is money for nothing if it happens

Writes data/backtest_lottery.json.
"""
import json
import math
import os
import random
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEGS = os.path.join(ROOT, "data", "backtest_kalshi_legs.json")
OUT = os.path.join(ROOT, "data", "backtest_lottery.json")
TIERS = {"100": dict(chance=0.01), "10k": dict(pay=10000.0)}
MAX_LEGS = 20


def cost(r):
    return r["cost"] + r["fee"]


def roi(rows):
    if not rows:
        return dict(n=0)
    st = sum(cost(r) for r in rows)
    per = [(r["won"] - cost(r)) / cost(r) for r in rows]
    m = sum(per) / len(per)
    sd = math.sqrt(sum((x - m) ** 2 for x in per) / max(len(per) - 1, 1))
    se = sd / math.sqrt(len(per))
    return dict(n=len(rows), hit=round(100 * sum(r["won"] for r in rows) / len(rows), 1),
                paid=round(100 * st / len(rows), 1),
                roi=round(100 * (sum(r["won"] for r in rows) - st) / st, 1),
                ci95=[round(100 * (m - 1.96 * se), 1), round(100 * (m + 1.96 * se), 1)])


# ------------------------------------------------------------- strategies
def s_random(legs, rng):
    legs = legs[:]
    rng.shuffle(legs)
    return legs


def s_model(legs, rng):
    """the lottery's rule: most model value kept per unit of payout"""
    def k(r):
        v = max(r["q"], 1e-4) / cost(r)
        return math.log(v) / -math.log(cost(r))
    return sorted(legs, key=lambda r: -k(r))


def s_favs(legs, rng):
    """shortest prices first (favourite-longshot bias)"""
    return sorted(legs, key=lambda r: -cost(r))


def s_trend(legs, rng, bias=None):
    """price bands that returned best on EARLIER days only"""
    b = bias or {}
    return sorted(legs, key=lambda r: -b.get(band(r), -1))


STRATS = dict(random=s_random, model=s_model, favourites=s_favs, trend=s_trend)


def band(r):
    return min(int(cost(r) * 10), 9)


def ticket(order, tier):
    used, pick, pay, chance = set(), [], 1.0, 1.0
    for r in order:
        if r["game"] in used:
            continue
        c = cost(r)
        if tier.get("chance") and chance * c < tier["chance"] * 0.9:
            continue
        used.add(r["game"])
        pick.append(r)
        pay /= c
        chance *= c
        if len(pick) >= MAX_LEGS:
            break
        if tier.get("pay") and pay >= tier["pay"]:
            break
        if tier.get("chance") and chance <= tier["chance"] * 1.1:
            break
    if tier.get("pay") and pay < tier["pay"]:
        return None
    if tier.get("chance") and not tier["chance"] * 0.9 <= chance <= tier["chance"] * 1.25:
        return None
    return dict(legs=len(pick), pay=pay, chance=chance, picked=pick,
                won=all(r["won"] for r in pick), legs_won=sum(r["won"] for r in pick))


def ladders(rows):
    """Lines of one game priced out of order at the same moment."""
    by = defaultdict(list)
    for r in rows:
        if r["spec"].get("t") == "over":
            by[r["game"]].append(r)
    breaks, checked = [], 0
    for g, rs in by.items():
        rs = sorted(rs, key=lambda r: r["spec"]["line"])
        for a, b in zip(rs, rs[1:]):
            checked += 1
            # over a lower line can never be less likely than over a higher one
            if a["cost"] + 1e-9 < b["cost"] - b["width"] - 0.005:
                breaks.append(dict(game=g, low=a["spec"]["line"], high=b["spec"]["line"],
                                   low_cost=a["cost"], high_cost=b["cost"]))
    return dict(pairs=checked, breaks=len(breaks), examples=breaks[:10])


def main():
    rows = json.load(open(LEGS))
    rows = [r for r in rows if 0.02 <= cost(r) <= 0.97]
    days = sorted({r["date"] for r in rows})
    half = days[len(days) // 2]
    report = dict(legs=len(rows), days=len(days), range=[days[0], days[-1]])

    # leg-level: price bands, all days and second half only
    report["by_price"] = {f"{10*b}-{10*b+10}c": roi([r for r in rows if band(r) == b])
                          for b in range(10)}
    # disagreement: margin chosen on the first half, scored on the second
    edge = lambda r: r["q"] - cost(r)
    report["by_edge_test_half"] = {str(t): roi([r for r in rows if r["date"] >= half and edge(r) >= t])
                                   for t in (-1, 0.0, 0.03, 0.06, 0.10, 0.15)}
    report["ladders"] = ladders(rows)

    # daily replay
    rng = random.Random(7)
    out = {}
    for name, fn in STRATS.items():
        for tname, tier in TIERS.items():
            res = []
            for d in days:
                legs = [r for r in rows if r["date"] == d]
                if name == "trend":
                    past = [r for r in rows if r["date"] < d]
                    bias = {}
                    for b in range(10):
                        x = roi([r for r in past if band(r) == b])
                        if x.get("n", 0) >= 50:
                            bias[b] = x["roi"]
                    order = s_trend(legs, rng, bias)
                else:
                    order = fn(legs, rng)
                t = ticket(order, tier)
                if t:
                    res.append(t)
            n = len(res)
            out[f"{name}/{tname}"] = dict(
                tickets=n, hits=sum(t["won"] for t in res),
                expected=round(sum(t["chance"] for t in res), 2),
                avg_pay=round(sum(t["pay"] for t in res) / n, 1) if n else None,
                avg_legs=round(sum(t["legs"] for t in res) / n, 1) if n else None,
                returned=round(sum(t["pay"] for t in res if t["won"]), 1), staked=n,
                avg_legs_won=round(sum(t["legs_won"] / t["legs"] for t in res) / n * 100, 1) if n else None,
                # hits are too rare to read in one season, so also: did the
                # legs this strategy picked beat their own prices?
                legs_roi=roi([r for t in res for r in t["picked"]]))
    report["replay"] = out
    with open(OUT, "w") as fh:
        json.dump(report, fh, indent=1)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
