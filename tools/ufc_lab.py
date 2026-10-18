"""UFC lab: is the de-vigged favourite's price the best chance we can state?

    python3 tools/ufc_lab.py      # on GitHub's runners

UFC picks are the market favourite at its de-vigged price (picks.ufc_picks):
53-28 (65.4%) live against 67.1% stated. MMA is known for a favourite-
longshot lean -- heavy favourites winning more than their price says -- so
this replays every UFC card ESPN still has odds for, January 2025 on:

  * proportional de-vig (what the board does) vs power de-vig
  * a one-number stretch of the log-odds, fitted on the OLDER half of fights
    and scored on the NEWER half only
  * calibration by band, both halves

A change goes live only if it beats proportional on the newer half.
Writes data/ufc_lab.json.
"""
import datetime as dt
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import picks as PK                                            # noqa: E402

OUT = os.path.join(ROOT, "data", "ufc_lab.json")
START = dt.date(2025, 1, 1)


def ip(a):
    v = float(str(a).replace("+", ""))
    return 100 / (v + 100) if v > 0 else -v / (-v + 100)


def winners(day):
    d = PK.get(f"{PK.ESPN}/mma/ufc/scoreboard?dates={day}")
    out = {}
    for ev in d.get("events") or []:
        comps = list(ev.get("competitions") or [])
        for grp in ev.get("groupings") or []:
            comps.extend(grp.get("competitions") or [])
        for c in comps:
            if not ((c.get("status") or {}).get("type") or {}).get("completed"):
                continue
            names = [((x.get("athlete") or {}).get("displayName"), bool(x.get("winner")))
                     for x in c.get("competitors") or []]
            if len(names) == 2 and sum(w for _, w in names) == 1:
                out[frozenset(n for n, _ in names)] = next(n for n, w in names if w)
    return out


def day_rows(d):
    tag = d.strftime("%Y%m%d")
    try:
        fights = PK.ufc_picks(tag)
    except Exception:
        return []
    if not fights:
        return []
    won = winners(tag)
    rows = []
    for (a, b), f in fights.items():
        w = won.get(frozenset((a, b)))
        pr = f.get("prices") or {}
        if not w or len(pr) != 2:
            continue
        (n1, o1), (n2, o2) = pr.items()
        r1, r2 = ip(o1), ip(o2)
        lo, hi = 1.0, 3.0
        for _ in range(60):
            k = (lo + hi) / 2
            lo, hi = (k, hi) if r1 ** k + r2 ** k > 1 else (lo, k)
        fav = n1 if r1 >= r2 else n2
        rf, ro = max(r1, r2), min(r1, r2)
        rows.append(dict(date=d.isoformat(), fav=fav, p_prop=rf / (rf + ro),
                         p_pow=rf ** k / (rf ** k + ro ** k), vig=round(r1 + r2 - 1, 4),
                         won=int(w == fav)))
    return rows


def lg(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def sig(x):
    return 1 / (1 + math.exp(-x))


def ll(ps, ys):
    return round(-sum(math.log(max(1e-4, p if y else 1 - p)) for p, y in zip(ps, ys)) / len(ps), 4)


def bands(ps, ys):
    out = []
    for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01)):
        b = [(p, y) for p, y in zip(ps, ys) if lo <= p < hi]
        if b:
            out.append(dict(band=f"{int(lo*100)}-{min(int(hi*100), 100)}", n=len(b),
                            said=round(100 * sum(p for p, _ in b) / len(b), 1),
                            hit=round(100 * sum(y for _, y in b) / len(b), 1)))
    return out


def main():
    days = [START + dt.timedelta(days=i) for i in range((dt.date.today() - START).days)]
    with ThreadPoolExecutor(max_workers=12) as ex:
        rows = sorted((r for rs in ex.map(day_rows, days) for r in rs), key=lambda r: r["date"])
    print("fights with odds and a winner:", len(rows), flush=True)
    rep = dict(run=dt.date.today().isoformat(), fights=len(rows))
    if len(rows) < 100:
        print("too few fights to judge")
    else:
        half = len(rows) // 2
        fit, test = rows[:half], rows[half:]
        # one stretch factor a: p = sigmoid(a * logit(p_prop)), fitted on the older half
        best = min((sum(-math.log(max(1e-4, sig(a * lg(r["p_prop"])) if r["won"]
                                       else 1 - sig(a * lg(r["p_prop"])))) for r in fit), a)
                   for a in [0.8 + 0.01 * i for i in range(61)])
        a = round(best[1], 2)
        ys = [r["won"] for r in test]
        methods = dict(proportional=[r["p_prop"] for r in test], power=[r["p_pow"] for r in test],
                       stretch=[sig(a * lg(r["p_prop"])) for r in test])
        rep.update(stretch=a, test_fights=len(test), fit_from=fit[0]["date"], test_from=test[0]["date"],
                   methods={m: dict(logloss=ll(ps, ys), bands=bands(ps, ys)) for m, ps in methods.items()},
                   fit_bands=bands([r["p_prop"] for r in fit], [r["won"] for r in fit]),
                   fav_hit=dict(fit=round(100 * sum(r["won"] for r in fit) / len(fit), 1),
                                test=round(100 * sum(ys) / len(ys), 1)))
    print(json.dumps(rep, indent=1), flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1)


if __name__ == "__main__":
    main()
