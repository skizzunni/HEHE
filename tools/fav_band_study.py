"""Are mid-priced favourites under-priced? A pre-stated test.

Hypothesis (from the ledger, 2026-10-22, before this data was looked at):
favourites the closing line gives 70-80% (no-vig) win more often than that,
enough to profit at DraftKings' actual closing price. In the ledger, 192
such favourites won 80.7% against 74.2% stated (Wilson 74.6-85.7).

Data: every finished game in tools/backtest.py's windows for the two-way
leagues, DraftKings' closing moneylines from ESPN's odds feed (the same
loader as tools/edge_lab.py, up to 1,500 games per league). None of these
games are ledger picks' data, so the whole set is untouched for this
hypothesis. Reported per band and league: N, stated, hit, realized ROI per
$1 at the closing price, and a game-resampled 95% interval for the ROI;
also by date half, so a one-off season cannot carry it.

    python3 tools/fav_band_study.py      # writes data/fav_band_study.json
"""
import json
import math
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import backtest as B                                      # noqa: E402
import edge_lab as E                                      # noqa: E402

OUT = os.path.join(ROOT, "data", "fav_band_study.json")
BANDS = ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0))


def fav_rows():
    out = []
    for key, sport, league, wins in B.WINDOWS:
        if key not in E.LEAGUES:
            continue
        games = B.finished_games(key, sport, league, B.dates(wins))
        if len(games) > E.MAX_GAMES:
            step = len(games) / E.MAX_GAMES
            games = [games[int(i * step)] for i in range(E.MAX_GAMES)]
        with ThreadPoolExecutor(max_workers=8) as ex:
            rows = [r for r in ex.map(lambda g: E.row_for(key, sport, league, g), games) if r]
        for r in rows:
            ih, ia = r["ih"], r["ia"]                 # implied chances with the margin
            home_fav = ih >= ia
            imp = ih if home_fav else ia
            out.append(dict(league=key, date=r["date"], game=f'{key}:{r["eid"]}',
                            p=imp / (ih + ia), dec=1 / imp, won=int(r["home_won"] == int(home_fav))))
        print(key, len(rows), file=sys.stderr, flush=True)
    return out


def stats(rs, draws=1000, seed=3):
    n = len(rs)
    if not n:
        return None
    ret = [(r["dec"] - 1) if r["won"] else -1 for r in rs]
    rng = random.Random(seed)
    boot = sorted(sum(rng.choice(ret) for _ in ret) / n for _ in range(draws))
    return dict(n=n, stated=round(100 * sum(r["p"] for r in rs) / n, 1),
                hit=round(100 * sum(r["won"] for r in rs) / n, 1),
                roi=round(100 * sum(ret) / n, 2),
                roi95=[round(100 * boot[int(.025 * draws)], 2), round(100 * boot[int(.975 * draws) - 1], 2)])


def main():
    rows = fav_rows()
    rows.sort(key=lambda r: r["date"])
    cut = rows[len(rows) // 2]["date"]
    rep = dict(games=len(rows), dates=[rows[0]["date"], rows[-1]["date"]], half_from=cut, bands={})
    for lo, hi in BANDS:
        sel = [r for r in rows if lo <= r["p"] < hi]
        k = f"{int(100 * lo)}-{int(100 * hi)}"
        rep["bands"][k] = dict(all=stats(sel), older=stats([r for r in sel if r["date"] < cut]),
                               newer=stats([r for r in sel if r["date"] >= cut]),
                               leagues={lg: stats([r for r in sel if r["league"] == lg])
                                        for lg in sorted({r["league"] for r in sel})})
    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1)
    print(f"{rep['games']} favourites {rep['dates'][0]}..{rep['dates'][1]}")
    for k, v in rep["bands"].items():
        print(k, "all", v["all"], "| older", v["older"], "| newer", v["newer"])
        for lg, s in v["leagues"].items():
            if s and s["n"] >= 40:
                print("    ", lg, s)
    return rep


if __name__ == "__main__":
    main()
