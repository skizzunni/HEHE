"""Underdog / favourite against the closing point spread, by size of spread
and season, on tools/nba_history.py output with spreads (football).
Pushes are dropped; returns are a flat $1 at the closing spread price.

    python tools/spread_study.py HISTORY.json
"""
import json
import sys


def dec(a):
    return 1 + (a / 100 if a > 0 else 100 / -a)


def rows(G):
    out = []
    for g in G.values():
        o = g.get("odds") or {}
        if "home_spread" not in o:
            continue
        hs = o["home_spread"]
        if hs == 0:
            continue
        margin = g["home"]["score"] - g["away"]["score"]          # home points minus away points
        cover = margin + hs                                       # >0 home covers, <0 away covers
        if cover == 0:
            continue
        home_dog = hs > 0
        dog_cov = (cover > 0) == home_dog
        season = g["day"][:4] if g["day"][5:7] >= "06" else str(int(g["day"][:4]) - 1)
        out.append(dict(season=season, pts=abs(hs), dog_cov=dog_cov, home_dog=home_dog,
                        dp=o["home_spread_price"] if home_dog else o["away_spread_price"],
                        fp=o["away_spread_price"] if home_dog else o["home_spread_price"]))
    return out


BANDS = ((0.5, 3.5), (3.5, 7.5), (7.5, 14), (14, 21), (21, 99))


def table(R):
    seasons = sorted({r["season"] for r in R})
    lines = []
    for lo, hi in BANDS:
        b = [r for r in R if lo <= r["pts"] < hi]
        cells = []
        for s in seasons:
            x = [r for r in b if r["season"] == s]
            if not x:
                continue
            cov = 100 * sum(r["dog_cov"] for r in x) / len(x)
            roi = 100 * sum((dec(r["dp"]) - 1) if r["dog_cov"] else -1 for r in x) / len(x)
            cells.append(f"{s} n{len(x)} dog covered {cov:.1f}% roi {roi:+.1f}%")
        lines.append(f"dog getting {lo}-{hi}: " + " | ".join(cells))
    return lines


if __name__ == "__main__":
    R = rows(json.load(open(sys.argv[1])))
    print(len(R), "games against the spread")
    print("\n".join(table(R)))
    print("home dogs only"); print("\n".join(table([r for r in R if r["home_dog"]])))
    print("road dogs only"); print("\n".join(table([r for r in R if not r["home_dog"]])))
