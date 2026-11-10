"""Favourite / underdog return by price band at the close, season by season,
on tools/nba_history.py output (any league). Answers: where, if anywhere, is
the underdog under-priced?   python tools/band_roi_study.py HISTORY.json"""
import json
import sys


def imp(a):
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def dec(a):
    return 1 + (a / 100 if a > 0 else 100 / -a)


def rows(G):
    out = []
    for g in G.values():
        o = g.get("odds")
        if not o:
            continue
        ph, pa = imp(o["home"]), imp(o["away"])
        if not 1.0 <= ph + pa <= 1.12:
            continue
        hw = g["home"]["score"] > g["away"]["score"]
        fav_home = ph >= pa
        p = (ph if fav_home else pa) / (ph + pa)
        season = g["day"][:4] if g["day"][5:7] >= "08" else str(int(g["day"][:4]) - 1)
        out.append(dict(season=season, p=p, fav_won=hw == fav_home, home_dog=fav_home is False,
                        fo=o["home"] if fav_home else o["away"], do=o["away"] if fav_home else o["home"]))
    return out


BANDS = ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 1.01))


def table(R):
    lines = []
    seasons = sorted({r["season"] for r in R})
    for lo, hi in BANDS:
        b = [r for r in R if lo <= r["p"] < hi]
        cells = []
        for s in seasons:
            x = [r for r in b if r["season"] == s]
            if not x:
                continue
            fr = 100 * sum((dec(r["fo"]) - 1) if r["fav_won"] else -1 for r in x) / len(x)
            dr = 100 * sum((dec(r["do"]) - 1) if not r["fav_won"] else -1 for r in x) / len(x)
            cells.append(f"{s} n{len(x)} fav {fr:+.1f}% dog {dr:+.1f}%")
        lines.append(f"fav {int(lo*100)}-{min(int(hi*100), 100)}%: " + " | ".join(cells))
    return lines


if __name__ == "__main__":
    R = rows(json.load(open(sys.argv[1])))
    print("all games"); print("\n".join(table(R)))
    print("home underdogs only"); print("\n".join(table([r for r in R if r["home_dog"]])))
