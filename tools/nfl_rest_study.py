"""NFL rest edges against the closing moneyline and spread: each side's days
since its previous game (short week <= 5, off a bye >= 13), the rest-advantaged
side's win rate vs its no-vig price and a flat $1 at the close, by season.
python tools/nfl_rest_study.py NFL_HISTORY.json"""
import datetime as dt
import json
import sys


def imp(a):
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def dec(a):
    return 1 + (a / 100 if a > 0 else 100 / -a)


def rows(G):
    G = sorted((g for g in G.values() if g.get("odds")), key=lambda g: g["date"])
    last, out = {}, []
    for g in G:
        d = dt.date.fromisoformat(g["day"])
        rest = {}
        for s in ("home", "away"):
            p = last.get(g[s]["id"])
            rest[s] = (d - p).days if p else None
            last[g[s]["id"]] = d
        if None in rest.values():
            continue
        o = g["odds"]
        ph, pa = imp(o["home"]), imp(o["away"])
        if not 1.0 <= ph + pa <= 1.12 or g["home"]["score"] == g["away"]["score"]:
            continue
        season = g["day"][:4] if g["day"][5:7] >= "06" else str(int(g["day"][:4]) - 1)
        out.append(dict(season=season, rh=rest["home"], ra=rest["away"], p_home=ph / (ph + pa),
                        home_won=g["home"]["score"] > g["away"]["score"], oh=o["home"], oa=o["away"]))
    return out


def spot(r):
    """'bye' / 'short' for the side with the edge: (side, label) or None."""
    h, a = r["rh"], r["ra"]
    if (h >= 13) != (a >= 13):
        return ("home" if h >= 13 else "away", "off a bye v not")
    if (h <= 5) != (a <= 5):
        return ("away" if h <= 5 else "home", "rested v short week")
    return None


def table(R):
    out = {}
    for r in R:
        sp = spot(r)
        if not sp:
            continue
        side, lab = sp
        won = r["home_won"] if side == "home" else not r["home_won"]
        p = r["p_home"] if side == "home" else 1 - r["p_home"]
        price = r["oh"] if side == "home" else r["oa"]
        a = out.setdefault((lab, r["season"]), [0, 0, 0.0, 0.0])
        a[0] += won
        a[1] += 1
        a[2] += p
        a[3] += (dec(price) - 1) if won else -1
    lines = []
    for lab in sorted({k[0] for k in out}):
        cells = [f"{s} n{v[1]} won {100*v[0]/v[1]:.1f}% vs {100*v[2]/v[1]:.1f}% priced, {100*v[3]/v[1]:+.1f}%"
                 for (l, s), v in sorted(out.items()) if l == lab]
        lines.append(f"{lab}: " + " | ".join(cells))
    return lines


if __name__ == "__main__":
    print("\n".join(table(rows(json.load(open(sys.argv[1]))))))
