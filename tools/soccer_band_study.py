"""Soccer favourites by band at their real closing price (straight win).

Pre-stated from the ledger (2026-10-22): soccer straight-win favourites the
close gives 60-80% returned +8.6% and +10.8% per $1 on 89 graded picks, and
50-60% returned -25.6% on 40. Tested here on every finished league match in
tools/backtest.py's soccer windows (EPL, La Liga, Bundesliga, Serie A,
Ligue 1, MLS), DraftKings' 3-way close via tools/soccer_lab.rows_for; the
favourite's price is 1 / (its de-vigged chance x (1 + the margin)), which is
exactly the posted price under proportional de-vig. By band, with a
game-resampled 95% interval and the older / newer halves.

    python3 tools/soccer_band_study.py     # writes data/soccer_band_study.json
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import backtest as B                                      # noqa: E402
import soccer_lab as S                                    # noqa: E402

OUT = os.path.join(ROOT, "data", "soccer_band_study.json")
BANDS = ((0.4, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.0))


def stats(rs, draws=1000, seed=4):
    if not rs:
        return None
    ret = [(r["dec"] - 1) if r["fav_won"] else -1 for r in rs]
    rng = random.Random(seed)
    boot = sorted(sum(rng.choice(ret) for _ in ret) / len(ret) for _ in range(draws))
    return dict(n=len(rs), stated=round(100 * sum(r["p_fav"] for r in rs) / len(rs), 1),
                won=round(100 * sum(r["fav_won"] for r in rs) / len(rs), 1),
                roi=round(100 * sum(ret) / len(ret), 2),
                roi95=[round(100 * boot[int(.025 * draws)], 2), round(100 * boot[int(.975 * draws) - 1], 2)])


def main():
    rows = []
    for key, sport, league, wins in B.WINDOWS:
        if sport != "soccer":
            continue
        rs = S.rows_for(key, sport, league, wins)
        for r in rs:
            r["league"] = key
            r["dec"] = 1 / (r["p_fav"] * (1 + r["vig"]))
        rows.extend(rs)
        print(key, len(rs), file=sys.stderr, flush=True)
    rows.sort(key=lambda r: r["date"])
    cut = rows[len(rows) // 2]["date"]
    rep = dict(matches=len(rows), dates=[rows[0]["date"], rows[-1]["date"]], half_from=cut, bands={})
    for lo, hi in BANDS:
        sel = [r for r in rows if lo <= r["p_fav"] < hi]
        rep["bands"][f"{int(100 * lo)}-{int(100 * hi)}"] = dict(
            all=stats(sel), older=stats([r for r in sel if r["date"] < cut]),
            newer=stats([r for r in sel if r["date"] >= cut]))
    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1)
    print(rep["matches"], rep["dates"])
    for k, v in rep["bands"].items():
        print(k, v["all"], "| older", v["older"], "| newer", v["newer"])


if __name__ == "__main__":
    main()
