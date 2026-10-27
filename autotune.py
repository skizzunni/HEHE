"""Self-tuning of the daily calls: the rules adapt to the record, nightly.

Two things are re-decided from the ledger every run (tools/autotune.py), and
written to review/autotune.json, which calls.py reads:

1. The selection rule. Every candidate rule (how many calls one sport may
   take; a minimum price) is replayed as the daily top 5 over the graded,
   priced history -- exhibition games left out -- and scored on the older
   and the newer half of the dates separately. A challenger replaces the
   current rule only if it returns more in BOTH halves AND the paired
   day-by-day bootstrap puts its gain above zero at the 90% level. Ties and
   near-misses keep the current rule: no chasing noise.

2. The bench. A sport whose recent picks are clearly losing to their own
   prices is left out of the calls until they are not: over the last
   BENCH_DAYS days, at least BENCH_MIN graded priced picks, and the 95%
   Wilson UPPER bound of its hit rate below the average chance its prices
   implied. A sport is benched only when even the most favourable reading
   of its record says the market is beating it, and is reinstated by the
   same test as soon as that no longer holds.

Nothing here can raise a stated chance or soften a standard: it can only
choose among picks the board already priced honestly, or leave some out.
"""
import collections
import datetime as dt
import json
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "review", "autotune.json")
TOP_N = 5
RULES = [dict(per_sport=p, min_dec=m) for p in (1, 2, 3, None) for m in (1.0, 1.15)]
DEFAULT = dict(per_sport=2, min_dec=1.0)
BENCH_DAYS = 28
BENCH_MIN = 20
CONFIDENCE = 0.90


def load(path=None):
    try:
        with open(path or PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def rule(path=None):
    return dict(DEFAULT, **((load(path).get("rule")) or {}))


def benched(path=None):
    return set(load(path).get("benched") or [])


def _dec(price):
    import venues
    return venues.dec(price)


def history(book):
    """Graded, priced, regular-season picks: (day, sport group, conf, dec, won)."""
    import calibration
    import calls
    out = []
    for e in calibration.graded(list(book.values())):
        d = _dec(e.get("price"))
        if not d:
            continue
        out.append(dict(day=calibration.day_of(e), group=calls._group(e["league"]), conf=e["conf"],
                        dec=d, won=e["status"] == "won"))
    return out


def pick(rows, r, n=TOP_N):
    """One day's calls under rule r: strongest first, the cap and floor applied."""
    out, per = [], collections.Counter()
    for x in sorted(rows, key=lambda x: -x["conf"]):
        if x["dec"] < r["min_dec"]:
            continue
        if r["per_sport"] and per[x["group"]] >= r["per_sport"]:
            continue
        out.append(x)
        per[x["group"]] += 1
        if len(out) == n:
            break
    return out


def _units(xs):
    return sum((x["dec"] - 1) if x["won"] else -1 for x in xs)


def score(hist, r, days):
    by = collections.defaultdict(list)
    for x in hist:
        by[x["day"]].append(x)
    picks = [x for d in days for x in pick(by[d], r)]
    n = len(picks)
    return dict(n=n, hit=round(100 * sum(x["won"] for x in picks) / n, 1) if n else None,
                roi=round(100 * _units(picks) / n, 2) if n else None)


def gain(hist, new, old, days, boots=2000, seed=11):
    """Paired day-by-day units gain of `new` over `old`: (total, lower bound)."""
    by = collections.defaultdict(list)
    for x in hist:
        by[x["day"]].append(x)
    diffs = [_units(pick(by[d], new)) - _units(pick(by[d], old)) for d in days]
    if not diffs:
        return 0.0, 0.0
    rnd = random.Random(seed)
    bs = sorted(sum(rnd.choice(diffs) for _ in diffs) for _ in range(boots))
    return round(sum(diffs), 2), round(bs[int((1 - CONFIDENCE) * boots)], 2)


def choose(hist, current):
    """(rule, evidence): the current rule unless a challenger wins both halves
    and its paired gain clears zero at CONFIDENCE."""
    days = sorted({x["day"] for x in hist})
    if len(days) < 14:
        return current, dict(reason="under 14 days of history", days=len(days))
    mid = days[len(days) // 2]
    halves = ([d for d in days if d < mid], [d for d in days if d >= mid])
    table = []
    for r in RULES:
        a, b = score(hist, r, halves[0]), score(hist, r, halves[1])
        table.append(dict(rule=r, first=a, second=b))
    cur = next(t for t in table if t["rule"] == current) if current in RULES else \
        dict(rule=current, first=score(hist, current, halves[0]), second=score(hist, current, halves[1]))
    best, best_gain = current, None
    for t in table:
        if t["rule"] == current or not t["first"]["n"] or not t["second"]["n"]:
            continue
        if t["first"]["roi"] > cur["first"]["roi"] and t["second"]["roi"] > cur["second"]["roi"]:
            total, lower = gain(hist, t["rule"], current, days)
            t["gain"], t["gain_lower"] = total, lower
            if lower > 0 and (best_gain is None or total > best_gain):
                best, best_gain = t["rule"], total
    return best, dict(days=len(days), dates=[days[0], days[-1]], split=mid, current=cur, table=table,
                      changed=best != current)


def _wilson_upper(k, n, z=1.96):
    p = k / n
    return (p + z * z / (2 * n) + z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def bench(hist, today):
    """{group: evidence} for sports whose recent record is clearly below their prices."""
    lo = (dt.date.fromisoformat(today) - dt.timedelta(days=BENCH_DAYS)).isoformat()
    by = collections.defaultdict(list)
    for x in hist:
        if x["day"] >= lo:
            by[x["group"]].append(x)
    out = {}
    for g, xs in sorted(by.items()):
        n = len(xs)
        k = sum(x["won"] for x in xs)
        implied = sum(1 / x["dec"] for x in xs) / n if n else 0
        ev = dict(n=n, won=k, hit=round(100 * k / n, 1) if n else None, implied=round(100 * implied, 1),
                  upper95=round(100 * _wilson_upper(k, n), 1) if n else None,
                  roi=round(100 * _units(xs) / n, 1) if n else None)
        ev["benched"] = bool(n >= BENCH_MIN and _wilson_upper(k, n) < implied)
        out[g] = ev
    return out


# Value bets (value_bets.py) are benched by slice -- venue and price band --
# when even the best case of their record cannot break even at their prices:
# the 95% Wilson upper bound of the hit rate below the average break-even
# chance (1 / decimal payout), over at least VALUE_MIN graded bets. Longshots
# get their own slice because that is where a fair price is most often too
# generous: on 18,735 settled Kalshi legs, "value" contracts under 30c won
# 18.4% / 15.5% against 19.6% / 20.8% fair in the two halves of the dates.
VALUE_MIN = 30


def value_slice(f):
    """'<venue> longshot|middle|favourite, confirmed|single' for a value bet:
    its payout band, and whether its fair chance was confirmed by a second,
    independent reference (Polymarket's liquid price, or a source proven
    better). 2026-10-27: single-source bets (DraftKings' Shin fair alone)
    returned -17.6% on 82, confirmed ones +0.8% on 78."""
    imp = 1 / f["dec"] if f.get("dec") else 0
    band = "longshot" if imp < 0.30 else "favourite" if imp >= 0.60 else "middle"
    src = f.get("fair_source") or ""
    conf = "confirmed" if ("Polymarket" in src or "proven" in src) else "single"
    return f'{f.get("venue")} {band}, {conf}'


def value_bench(finds):
    by = collections.defaultdict(list)
    for f in finds:
        if f.get("kind") == "value" and f.get("status") in ("won", "lost") and f.get("dec"):
            by[value_slice(f)].append(f)
    out = {}
    for k, fs in sorted(by.items()):
        n = len(fs)
        w = sum(f["status"] == "won" for f in fs)
        be = sum(1 / f["dec"] for f in fs) / n
        roi = sum((f["dec"] - 1) if f["status"] == "won" else -1 for f in fs) / n
        out[k] = dict(n=n, won=w, hit=round(100 * w / n, 1), breakeven=round(100 * be, 1),
                      upper95=round(100 * _wilson_upper(w, n), 1), roi=round(100 * roi, 1),
                      benched=bool(n >= VALUE_MIN and _wilson_upper(w, n) < be))
    return out


def value_benched(path=None):
    return set(load(path).get("value_benched") or [])


def run(book, today, path=None):
    prev = load(path)
    hist = history(book)
    current = dict(DEFAULT, **(prev.get("rule") or {}))
    new, evidence = choose(hist, current)
    groups = bench(hist, today)
    try:
        with open(os.path.join(HERE, "value.json")) as fh:
            vs = value_bench((json.load(fh).get("finds") or {}).values())
    except (OSError, ValueError):
        vs = {}
    out = dict(updated=today, rule=new, benched=sorted(g for g, v in groups.items() if v["benched"]),
               evidence=evidence, groups=groups,
               value_slices=vs, value_benched=sorted(k for k, v in vs.items() if v["benched"]),
               log=(prev.get("log") or [])[-30:])
    for k in sorted(set(out["value_benched"]) ^ set(prev.get("value_benched") or [])):
        out["log"].append(dict(day=today, what="value benched" if k in out["value_benched"] else "value reinstated",
                               group=k, evidence=vs.get(k)))
    if new != current:
        out["log"].append(dict(day=today, what="rule", old=current, new=new))
    was = set(prev.get("benched") or [])
    for g in sorted(set(out["benched"]) ^ was):
        out["log"].append(dict(day=today, what="benched" if g in out["benched"] else "reinstated", group=g,
                               evidence=groups.get(g)))
    os.makedirs(os.path.dirname(path or PATH), exist_ok=True)
    with open(path or PATH, "w") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    return out
