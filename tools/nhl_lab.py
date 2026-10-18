"""NHL lab: how many one-goal games does the empty net turn into two?

    python3 tools/nhl_lab.py      # on GitHub's runners

stacks.py prices hockey with independent Poisson scoring. On 1,312 NHL games
of 2025 its puck-line legs were off: "+1.5" said 87.5% and hit 81.4%, "-1.5"
said 12.5% and hit 18.6%. The likely cause is the empty net: a team down one
pulls its goalie and the leader often scores again.

For every finished NHL game in the backtest windows this prices, from the
closing moneyline and total, each team -1.5 and the total over, under a grid
of empty-net shares (stacks.HOCKEY_EN). The share is fitted on the OLDER half
of 2025 and judged on the newer half and on 2026, which the fit never saw.

Writes data/nhl_lab.json.
"""
import datetime as dt
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import backtest as B                                          # noqa: E402
import stacks as S                                            # noqa: E402

OUT = os.path.join(ROOT, "data", "nhl_lab.json")
GRID = [(e1, e2) for e1 in (0.0, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4) for e2 in (0.0, 0.1, 0.2)]


def games():
    key, sport, league, wins = next(w for w in B.WINDOWS if w[0] == "nhl")
    gs = B.finished_games(key, sport, league, B.dates(wins))
    with ThreadPoolExecutor(max_workers=24) as ex:
        odds = list(ex.map(lambda g: B.closing(key, sport, league, g[1]), gs))
    out = []
    for g, o in zip(gs, odds):
        if not o or o.get("total") is None:
            continue
        row, soccer = B.build(key, g, o)
        out.append(dict(date=g[0].isoformat(), row=row, home=g[2], away=g[3], hs=g[4], as_=g[5],
                        total=float(o["total"])))
    out.sort(key=lambda r: r["date"])
    return out


def price(args):
    """[(p home -1.5, p away -1.5, p over)] for every game at one share."""
    en, rows = args
    S.HOCKEY_EN = en
    out = []
    for r in rows:
        G = S.game_from_row(r["row"], "nhl", False)
        if G is None:
            out.append(None)
            continue
        h, a = r["home"], r["away"]
        ph = G.prob([S.predicate(dict(t="spread", team=h, line=-1.5), h, a)])
        pa = G.prob([S.predicate(dict(t="spread", team=a, line=-1.5), h, a)])
        po = G.prob([S.predicate(dict(t="over", line=r["total"]), h, a)])
        out.append((ph, pa, po))
    return out


def ll(ps, ys):
    return -sum(math.log(min(max(p if y else 1 - p, 1e-4), 1)) for p, y in zip(ps, ys)) / len(ps)


def score(rows, priced):
    pl, yl, po, yo = [], [], [], []
    for r, q in zip(rows, priced):
        if q is None or r["hs"] + r["as_"] == r["total"]:
            continue
        pl += [q[0], q[1]]
        yl += [r["hs"] - r["as_"] >= 2, r["as_"] - r["hs"] >= 2]
        po.append(q[2])
        yo.append(r["hs"] + r["as_"] > r["total"])
    return dict(n=len(po), ll_puck=round(ll(pl, yl), 4), ll_total=round(ll(po, yo), 4),
                said_minus=round(100 * sum(pl) / len(pl), 1), hit_minus=round(100 * sum(yl) / len(yl), 1),
                said_over=round(100 * sum(po) / len(po), 1), hit_over=round(100 * sum(yo) / len(yo), 1))


def main():
    rows = games()
    old = [r for r in rows if r["date"] < "2026-07-01"]
    new = [r for r in rows if r["date"] >= "2026-07-01"]
    fit, hold = old[:len(old) // 2], old[len(old) // 2:]
    print("games", len(rows), "fit", len(fit), "hold", len(hold), "2026", len(new), flush=True)
    with ProcessPoolExecutor() as ex:
        priced = dict(zip(GRID, ex.map(price, [(en, rows) for en in GRID])))
    idx = {id(r): i for i, r in enumerate(rows)}
    pick = lambda rs, en: [priced[en][idx[id(r)]] for r in rs]
    rep = dict(run=dt.date.today().isoformat(), games=len(rows), grid={})
    for en in GRID:
        f = score(fit, pick(fit, en))
        rep["grid"][f"{en[0]},{en[1]}"] = dict(fit=f, hold=score(hold, pick(hold, en)),
                                               new=score(new, pick(new, en)) if len(new) >= 30 else None)
        print(en, json.dumps(rep["grid"][f"{en[0]},{en[1]}"]), flush=True)
    best = min(GRID, key=lambda en: rep["grid"][f"{en[0]},{en[1]}"]["fit"]["ll_puck"]
               + rep["grid"][f"{en[0]},{en[1]}"]["fit"]["ll_total"])
    rep["best_on_fit"] = list(best)
    print("best on the fit half:", best, flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1)


if __name__ == "__main__":
    main()
