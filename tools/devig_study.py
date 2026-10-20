"""Ledger study for the de-vig change (README, accuracy plan item 3).

For every graded ledger pick, both sides' prices are taken from ESPN's
scoreboard for the game's date (the closing moneylines, the same feed the
ledger grades from; ESPN keeps them on finished games). The picked side's
chance is computed both ways:

    old   proportional, except college football and basketball (power) --
          what the board did until 2026-10-20
    new   devig.METHOD everywhere

and scored against the result: band hit rates (50-60 ... 90+), Brier and
log-loss, with N and dates. Nothing is fitted here; the method was chosen on
tools/edge_lab.py's older half (devig.py).

    python3 tools/devig_study.py [--from 2026-10-15] [--to 2026-10-19]
"""
import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import dashboard as D                                      # noqa: E402
import devig                                               # noqa: E402
import ledger                                              # noqa: E402

OUT = os.path.join(ROOT, "data", "devig_study.json")
OLD_POWER = {"ncaaf", "ncaab"}
BANDS = ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01))
PATHS = {k: p for k, p, _ in D.LEAGUES}


def close_prices(e, key):
    """Both (or all three) closing prices for the entry's game, or None.
    ESPN strips odds from finished games on the scoreboard; the game
    summary's pickcenter keeps the final moneylines."""
    lg, cid = key.split(":", 1)
    path = PATHS.get(lg)
    if not path:
        return None
    d = D.get(f"{D.ESPN}/{path}/summary?event={cid}", fresh=10 ** 9, stale=10 ** 9)
    pc = [o for o in d.get("pickcenter") or [] if isinstance(o, dict)]
    return D.raw_prices(dict(odds=pc), 3 if lg in D.THREE_WAY else 2) if pc else None


def side_chance(e, prices, method):
    decs = [D.am_to_dec(p) for p in prices]
    fv = devig.fair_decimal(*decs, method=method)
    if not fv:
        return None
    names = ["away", "draw", "home"] if len(fv) == 3 else ["away", "home"]
    p = dict(zip(names, fv))
    side = e.get("myside")
    if side not in ("away", "home"):
        return None
    return p[side] + (p.get("draw", 0) if e.get("dc") else 0)


def score(rows, k):
    n = len(rows)
    if not n:
        return dict(n=0, brier=None, logloss=None, bands=[])
    br = sum((r[k] - r["won"]) ** 2 for r in rows) / n
    ll = -sum(math.log(r[k] if r["won"] else 1 - r[k]) for r in rows) / n
    bands = []
    for lo, hi in BANDS:
        b = [r for r in rows if lo <= r[k] < hi]
        if b:
            w = sum(r["won"] for r in b)
            bands.append(dict(band=f"{int(100 * lo)}-{min(100, int(100 * hi))}", n=len(b),
                              stated=round(100 * sum(r[k] for r in b) / len(b), 1),
                              hit=round(100 * w / len(b), 1)))
    return dict(n=n, brier=round(br, 4), logloss=round(ll, 4), bands=bands)


def eligible(entries, lo, hi):
    from record_eligibility import record_priced
    return [(k, e) for k, e in sorted(entries.items())
            if e.get("status") in ("won", "lost") and lo <= (e.get("date") or "") <= hi
            and record_priced(e)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="lo", default="2026-10-15")
    ap.add_argument("--to", dest="hi", default="2026-10-19")
    a = ap.parse_args()
    rows, missing = [], 0
    todo = eligible(ledger.load(), a.lo, a.hi)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        prices = list(ex.map(lambda ke: close_prices(ke[1], ke[0]), todo))
    for (key, e), pr in zip(todo, prices):
        if not pr:
            missing += 1
            continue
        lg = e["league"]
        old = side_chance(e, pr, "power" if lg in OLD_POWER else "proportional")
        new = side_chance(e, pr, devig.METHOD)
        if old is None or new is None or not (0 < old < 1 and 0 < new < 1):
            missing += 1
            continue
        # the picked side as the favourite's chance, as published
        rows.append(dict(key=key, league=lg, date=e["date"], won=int(e["status"] == "won"),
                         old=old, new=new))
    for r in rows:
        r["moved"] = r["new"] - r["old"]
    fav = [r for r in rows if r["old"] >= 0.5]
    rep = dict(record_scope="captured-price-only-v1", window=[a.lo, a.hi], method=devig.METHOD, matched=len(rows), unmatched=missing,
               dates=[min(r["date"] for r in rows), max(r["date"] for r in rows)] if rows else None,
               mean_abs_move_pts=round(100 * sum(abs(r["moved"]) for r in rows) / len(rows), 2) if rows else None,
               mean_move_favourites_pts=round(100 * sum(r["moved"] for r in fav) / len(fav), 2) if fav else None,
               max_move_pts=round(100 * max(abs(r["moved"]) for r in rows), 2) if rows else None,
               old=score(rows, "old"), new=score(rows, "new"))
    rep["bootstrap_logloss_diff"] = boot(rows)
    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1)
    print(json.dumps(rep, indent=1))
    return rep


def boot(rows, draws=2000, seed=11):
    """Log-loss new - old, game-resampled 95% interval (negative = new better)."""
    if not rows:
        return dict(mean=None, ci95=None)
    import random
    rng = random.Random(seed)

    def ll(r, k):
        return -math.log(r[k] if r["won"] else 1 - r[k])
    d = [ll(r, "new") - ll(r, "old") for r in rows]
    bs = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(draws))
    return dict(mean=round(sum(d) / len(d), 5), ci95=[round(bs[int(.025 * draws)], 5),
                                                      round(bs[int(.975 * draws) - 1], 5)])


if __name__ == "__main__":
    main()
