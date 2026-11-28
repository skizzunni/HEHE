"""Underdog / favourite against the closing point spread, by size of spread
and season, on tools/nba_history.py output with spreads (football).
Pushes are dropped; returns are a flat $1 at the closing spread price.

    python tools/spread_study.py HISTORY.json

Also reads the strategy lab's football files (work/strategy_lab/football/
nfl.json and ncaaf.json: odds keys h_sp / h_sp_pr / a_sp_pr, a list or a
dict, a 'season' field) -- 2026-11-28, the five-season NFL dog rows.
"""
import json
import sys


def dec(a):
    return 1 + (a / 100 if a > 0 else 100 / -a)


def _spread(o):
    """(home spread, home price, away price) from either layout, or None."""
    if o.get("home_spread") is not None:
        return o["home_spread"], o.get("home_spread_price"), o.get("away_spread_price")
    if o.get("h_sp") is not None:
        return o["h_sp"], o.get("h_sp_pr") or -110, o.get("a_sp_pr") or -110
    return None


def rows(G):
    out = []
    for g in (G.values() if isinstance(G, dict) else G):
        o = g.get("odds") or {}
        sp = _spread(o)
        if not sp:
            continue
        hs, hp, ap = sp
        if hs == 0:
            continue
        try:
            margin = g["home"]["score"] - g["away"]["score"]      # home points minus away points
        except (KeyError, TypeError):
            continue
        cover = margin + hs                                       # >0 home covers, <0 away covers
        if cover == 0:
            continue
        home_dog = hs > 0
        dog_cov = (cover > 0) == home_dog
        season = str(g.get("season") or (g["day"][:4] if g["day"][5:7] >= "06" else int(g["day"][:4]) - 1))
        out.append(dict(season=season, pts=abs(hs), dog_cov=dog_cov, home_dog=home_dog,
                        dp=hp if home_dog else ap, fp=ap if home_dog else hp))
    return out


BANDS = ((0.5, 3.5), (3.5, 7.5), (7.5, 14), (14, 21), (21, 99))


def verdict(rois):
    """' -- ahead in every season' when every season's flat return is above
    zero (the bar a band must clear before it is called a rule), else
    ' -- not ahead in every season'. 2026-11-28: college small dogs led in
    2023-24 and lost in 2025 and 2026; the line now says which kind it is."""
    if len(rois) < 2:
        return " -- one season only"
    return " -- ahead in every season" if all(r > 0 for r in rois) else " -- not ahead in every season"


def table(R):
    seasons = sorted({r["season"] for r in R})
    lines = []
    for lo, hi in BANDS:
        b = [r for r in R if lo <= r["pts"] < hi]
        cells, rois = [], []
        for s in seasons:
            x = [r for r in b if r["season"] == s]
            if not x:
                continue
            cov = 100 * sum(r["dog_cov"] for r in x) / len(x)
            roi = 100 * sum((dec(r["dp"]) - 1) if r["dog_cov"] else -1 for r in x) / len(x)
            rois.append(roi)
            cells.append(f"{s} n{len(x)} dog covered {cov:.1f}% roi {roi:+.1f}%")
        lines.append(f"dog getting {lo}-{hi}: " + " | ".join(cells) + (verdict(rois) if cells else ""))
    return lines


if __name__ == "__main__":
    R = rows(json.load(open(sys.argv[1])))
    print(len(R), "games against the spread")
    print("\n".join(table(R)))
    print("home dogs only"); print("\n".join(table([r for r in R if r["home_dog"]])))
    print("road dogs only"); print("\n".join(table([r for r in R if not r["home_dog"]])))
