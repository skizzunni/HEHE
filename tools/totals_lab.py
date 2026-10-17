"""Totals lab: do far unders and far overs hit equally often?

    python3 tools/totals_lab.py      # on GitHub's runners

The locks lean on alternate unders (NCAAF, NFL). On the Kalshi legs this
season unders ran below their stated chance and overs above it, but one
season of one book is thin. This asks every finished game in the backtest
windows (last season and this one): the closing total, the final score, and

  * the mean miss (final - close) and how often the main line went over
  * for each offset d: how often an under at close+d hit vs an over at
    close-d. A market that prices the two tails alike would see these equal;
    a gap that shows in BOTH seasons is a real lean, one that flips is noise
  * the same, split early season (first 6 weeks) vs the rest, because the
    gap on the Kalshi legs was all from August to October

Writes data/totals_lab.json.
"""
import datetime as dt
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import backtest as B                                          # noqa: E402
import stacks as S                                            # noqa: E402

OUT = os.path.join(ROOT, "data", "totals_lab.json")
LEAGUES = {"nfl": (3, 7, 10, 14), "ncaaf": (3, 7, 10, 14, 17), "nba": (5, 10, 15),
           "ncaab": (5, 10, 15), "nhl": (1, 2, 3), "mlb": (1, 2, 3), "wnba": (5, 10, 15)}
EARLY_DAYS = 42


def rows_for(key, sport, league, wins):
    out = []
    for i, w in enumerate(wins):
        games = B.finished_games(key, sport, league, B.dates([w]))
        start = dt.date.fromisoformat(w[0])

        def one(g):
            d, eid, home, away, hs, as_ = g
            o = B.closing(key, sport, league, eid)
            try:
                t = float((o or {}).get("total"))
            except (TypeError, ValueError):
                return None
            if t <= 0:
                return None
            r = dict(season=w[0][:4], date=d.isoformat(), close=t, final=hs + as_,
                     early=int((d - start).days < EARLY_DAYS), model={})
            # what OUR stacks model says for each alternate line, from the close
            try:
                row, soccer = B.build(key, g, o)
                G = S.game_from_row(row, key, soccer)
            except Exception:
                G = None
            if G is not None:
                for dd in LEAGUES[key]:
                    for side, line in (("under", t + dd), ("over", t - dd)):
                        try:
                            r["model"][f"{side}{dd}"] = round(G.prob_specs([dict(t=side, line=line)]), 4)
                        except Exception:
                            pass
            return r
        with ThreadPoolExecutor(max_workers=24) as ex:
            out += [r for r in ex.map(one, games) if r]
    return out


def summary(rs, offsets):
    if len(rs) < 30:
        return dict(n=len(rs))
    miss = [r["final"] - r["close"] for r in rs]
    m = sum(miss) / len(miss)
    sd = math.sqrt(sum((x - m) ** 2 for x in miss) / (len(miss) - 1))
    dec = [r for r in rs if r["final"] != r["close"]]
    out = dict(n=len(rs), mean_miss=round(m, 2), se=round(sd / math.sqrt(len(rs)), 2),
               sd=round(sd, 2), over_main=round(100 * sum(r["final"] > r["close"] for r in dec) / len(dec), 1),
               tails={})
    for d in offsets:
        u = sum(r["final"] < r["close"] + d for r in rs) / len(rs)      # alt under, line up by d
        o = sum(r["final"] > r["close"] - d for r in rs) / len(rs)      # alt over, line down by d
        out["tails"][str(d)] = dict(under=round(100 * u, 1), over=round(100 * o, 1),
                                    gap=round(100 * (u - o), 1),
                                    se=round(100 * math.sqrt((u * (1 - u) + o * (1 - o)) / len(rs)), 1))
    return out


def model_check(rs, offsets):
    """Our model's stated chance vs the hit rate, unders and overs apart."""
    out = {}
    for side in ("under", "over"):
        for d in offsets:
            k = f"{side}{d}"
            b = [(r["model"][k], (r["final"] < r["close"] + d) if side == "under"
                  else (r["final"] > r["close"] - d)) for r in rs if k in r.get("model", {})]
            if len(b) < 30:
                continue
            n = len(b)
            said = sum(p for p, _ in b) / n
            hit = sum(h for _, h in b) / n
            out[k] = dict(n=n, said=round(100 * said, 1), hit=round(100 * hit, 1),
                          se=round(100 * math.sqrt(said * (1 - said) / n), 1))
    return out


def main():
    rep = dict(run=dt.date.today().isoformat(), leagues={})
    for key, sport, league, wins in B.WINDOWS:
        if key not in LEAGUES:
            continue
        rs = rows_for(key, sport, league, wins)
        offs = LEAGUES[key]
        L = dict(all=summary(rs, offs), seasons={}, early=summary([r for r in rs if r["early"]], offs),
                 late=summary([r for r in rs if not r["early"]], offs))
        for s in sorted({r["season"] for r in rs}):
            L["seasons"][s] = summary([r for r in rs if r["season"] == s], offs)
            L["seasons"][s + " early"] = summary([r for r in rs if r["season"] == s and r["early"]], offs)
        L["model"] = {s: model_check([r for r in rs if r["season"] == s], offs)
                      for s in sorted({r["season"] for r in rs})}
        rep["leagues"][key] = L
        print(key, json.dumps(L), flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1)


if __name__ == "__main__":
    main()
