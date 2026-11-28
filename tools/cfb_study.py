"""College football checks by season (research, information only).

2026-11-28: three README rows came from one-off scripts -- unders on low
totals (rejected: 38.3% in 2024), rivalry-week favourites (no fade) and the
season verdict. This reproduces them from two kinds of history file:
  * the strategy lab's ncaaf.json (work/strategy_lab/football/ncaaf.json,
    2022-24; odds keys h_ml / a_ml / h_sp / total / under), and
  * tools/nba_history.py output (LEAGUE=football/college-football; odds keys
    home / away / home_spread / total / under).

  python3 tools/cfb_study.py FILE [FILE ...]
"""
import datetime as dt
import json
import math
import sys


def dec(a):
    return 1 + (a / 100 if a > 0 else 100 / -a)


def no_vig(a, b):
    """Home chance from two American moneylines, margin removed."""
    imp = lambda x: -x / (-x + 100) if x < 0 else 100 / (x + 100)
    pa, pb = imp(a), imp(b)
    return pa / (pa + pb)


def season_of(day):
    return day[:4] if day[5:7] >= "06" else str(int(day[:4]) - 1)


def games(G):
    """[dict(season, day, margin, spread, p_home, total, under)] from either
    file layout; games without a final score are left out."""
    out = []
    for g in (G.values() if isinstance(G, dict) else G):
        o = g.get("odds") or {}
        try:
            margin = g["home"]["score"] - g["away"]["score"]
        except (KeyError, TypeError):
            continue
        hm, am = (o.get("h_ml"), o.get("a_ml")) if "h_ml" in o else (o.get("home"), o.get("away"))
        out.append(dict(season=str(g.get("season") or season_of(g["day"])), day=g["day"], margin=margin,
                        points=g["home"]["score"] + g["away"]["score"],
                        spread=o.get("h_sp", o.get("home_spread")),
                        p_home=no_vig(hm, am) if hm is not None and am is not None else None,
                        total=o.get("total"), under=o.get("under")))
    return out


def rivalry(day):
    d = dt.date.fromisoformat(day)
    return d.month == 11 and d.day >= 22


def low_total_unders(rows, below=45):
    """{season: (n, under win %, flat return %)} for unders at totals under `below`."""
    out = {}
    for s in sorted({r["season"] for r in rows}):
        x = [r for r in rows if r["season"] == s and r["total"] is not None and r["under"]
             and r["total"] < below and r["points"] != r["total"]]
        if x:
            u = [r["points"] < r["total"] for r in x]
            ret = sum(dec(r["under"]) - 1 if w else -1 for r, w in zip(x, u)) / len(x)
            out[s] = (len(x), 100 * sum(u) / len(x), 100 * ret)
    return out


def favourites(rows, pick):
    """{season: (n, won, priced, z)} -- moneyline favourites in games pick(row) keeps."""
    out = {}
    for s in sorted({r["season"] for r in rows}):
        t = [r for r in rows if r["season"] == s and r["p_home"] is not None and r["margin"] != 0 and pick(r)]
        if not t:
            continue
        won = sum((r["margin"] > 0) == (r["p_home"] >= 0.5) for r in t)
        ex = sum(max(r["p_home"], 1 - r["p_home"]) for r in t)
        v = sum(r["p_home"] * (1 - r["p_home"]) for r in t)
        out[s] = (len(t), won, ex, (won - ex) / math.sqrt(v) if v else 0.0)
    return out


def merge(files):
    """Rows from several history files, each game once by ESPN id (the lab
    file and an nba_history.py pull overlap in 2025-26; 2026-11-28 the first
    rivalry-week count double-counted those seasons)."""
    seen, rows = set(), []
    for G in files:
        for raw in (G.values() if isinstance(G, dict) else G):
            gid = str(raw.get("id") or "")
            if gid and gid in seen:
                continue
            got = games([raw])
            if got:
                seen.add(gid)
                rows += got
    return rows


def main(paths):
    rows = merge([json.load(open(p)) for p in paths])
    print(f"{len(rows)} games, seasons {', '.join(sorted({r['season'] for r in rows}))}")
    lt = low_total_unders(rows)
    print("unders at totals under 45: " + "; ".join(f"{s} {u:.1f}% on {n} ({r:+.1f}%)" for s, (n, u, r) in lt.items())
          + (" -- ahead in every season" if lt and all(r > 0 for _, _, r in lt.values()) else " -- not ahead in every season"))
    for name, pick in (("rivalry week (Nov 22-30)", lambda r: rivalry(r["day"])),
                       ("other weeks", lambda r: not rivalry(r["day"]))):
        f = favourites(rows, pick)
        print(f"favourites, {name}: " + "; ".join(f"{s} {w}/{n} vs {e:.1f} (z {z:+.2f})" for s, (n, w, e, z) in f.items()))


if __name__ == "__main__":
    main(sys.argv[1:])
