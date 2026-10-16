"""Soccer lab: how often does the closing favourite actually win?

    python3 tools/soccer_lab.py      # on GitHub's runners

Soccer picks hit 47% on the board (214 graded) while claiming 57%. 61 of
113 losses were draws. This asks the market, on every finished league match
in the backtest windows, what a soccer pick can honestly promise:

  * the de-vigged 3-way close (DraftKings via ESPN), home/draw/away
  * by the favourite's outright chance, in bands: how often it won outright,
    how often it won or drew (double chance), what the price said
  * fit on the older half of matches, scored on the newer half ONLY, so a band
    is used live only if it held on matches it never saw

Writes data/soccer_lab.json.
"""
import datetime as dt
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import backtest as B                                          # noqa: E402

OUT = os.path.join(ROOT, "data", "soccer_lab.json")
BANDS = [(0.0, 0.45), (0.45, 0.55), (0.55, 0.65), (0.65, 0.75), (0.75, 1.01)]


def ip(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v == 0:
        return None
    return 100 / (v + 100) if v > 0 else -v / (-v + 100)


def rows_for(key, sport, league, wins):
    games = B.finished_games(key, sport, league, B.dates(wins))

    def one(g):
        d, eid, home, away, hs, as_ = g
        o = B.closing(key, sport, league, eid)
        if not o:
            return None
        ph, pd, pa = ip(o["home_ml"]), ip(o["draw_ml"]), ip(o["away_ml"])
        if None in (ph, pd, pa):
            return None
        s = ph + pd + pa
        ph, pd, pa = ph / s, pd / s, pa / s
        fav_home = ph >= pa
        res = "home" if hs > as_ else "away" if as_ > hs else "draw"
        fav = "home" if fav_home else "away"
        return dict(date=d.isoformat(), p_fav=max(ph, pa), p_draw=pd,
                    fav_won=int(res == fav), fav_or_draw=int(res in (fav, "draw")),
                    draw=int(res == "draw"), fav_home=int(fav_home),
                    vig=round(s - 1, 4))
    with ThreadPoolExecutor(max_workers=16) as ex:
        return sorted([r for r in ex.map(one, games) if r], key=lambda r: r["date"])


def table(rs):
    out = []
    for lo, hi in BANDS:
        b = [r for r in rs if lo <= r["p_fav"] < hi]
        if not b:
            continue
        n = len(b)
        out.append(dict(band=f"{int(lo*100)}-{min(int(hi*100), 100)}", n=n,
                        win=round(100 * sum(r["fav_won"] for r in b) / n, 1),
                        win_said=round(100 * sum(r["p_fav"] for r in b) / n, 1),
                        win_or_draw=round(100 * sum(r["fav_or_draw"] for r in b) / n, 1),
                        wod_said=round(100 * sum(r["p_fav"] + r["p_draw"] for r in b) / n, 1)))
    return out


def main():
    allrows, per = [], {}
    for key, sport, league, wins in B.WINDOWS:
        if sport != "soccer":
            continue
        rs = rows_for(key, sport, league, wins)
        per[key] = dict(matches=len(rs), draws=round(100 * sum(r["draw"] for r in rs) / max(1, len(rs)), 1))
        print(key, per[key], flush=True)
        allrows += rs
    allrows.sort(key=lambda r: r["date"])
    half = len(allrows) // 2
    fit, test = allrows[:half], allrows[half:]
    rep = dict(run=dt.date.today().isoformat(), matches=len(allrows), leagues=per,
               fit=table(fit), test=table(test), all=table(allrows))
    print(json.dumps(rep, indent=1), flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1)


if __name__ == "__main__":
    main()
