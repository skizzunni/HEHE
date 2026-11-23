"""Football strategy lab: every rule below against the closing price.

    python study.py            # reads nfl.json, ncaaf.json (fetch.py, weather.py)

For each strategy: n (pushes dropped), win/cover % vs the no-vig implied
chance of the side bet, flat $1 ROI at the closing price, and
z = (wins - sum p) / sqrt(sum p(1-p)), per season 2022-2025, the 2026 season
so far, and by chronological half of 2022-2025.

Verdicts (fixed before looking):
  adopted  ROI > 0 in every season 2022-2025 AND z >= 2.8 in both halves
  on watch ROI > 0 in at least 3 of the seasons with bets (and >= 3 seasons),
           and overall ROI > 0, but short of the adopted bar
  rejected everything else
Only information known before kickoff is used to choose a bet; the previous
game's result is from earlier dates only. Odds were matched by team id.

Writes results.json and results.md.
"""
import datetime as dt
import json
import math
import os
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ET = ZoneInfo("America/New_York")
SEASONS = (2022, 2023, 2024, 2025)
DIV = {}
for d, ts in dict(AFCE="BUF MIA NE NYJ", AFCN="BAL CIN CLE PIT", AFCS="HOU IND JAX TEN", AFCW="DEN KC LV LAC",
                  NFCE="DAL NYG PHI WSH", NFCN="CHI DET GB MIN", NFCS="ATL CAR NO TB", NFCW="ARI LAR SF SEA").items():
    for t in ts.split():
        DIV[t] = d
WEST = {"SF", "LAR", "LAC", "SEA", "LV"}


def imp(a):
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def dec(a):
    return 1 + (a / 100 if a > 0 else 100 / -a)


def nv(a, b):
    """no-vig chance of the side priced a against b"""
    pa, pb = imp(a), imp(b)
    return pa / (pa + pb)


# ----------------------------------------------------------------- bet makers
def ats_(g, side):
    """bet `side` ('home'/'away') against the closing spread. None on push."""
    o = g["odds"]
    m = g["home"]["score"] - g["away"]["score"]
    c = m + o["h_sp"]
    if c == 0:
        return None
    won = (c > 0) if side == "home" else (c < 0)
    pr, op = (o["h_sp_pr"], o["a_sp_pr"]) if side == "home" else (o["a_sp_pr"], o["h_sp_pr"])
    return dict(won=won, p=nv(pr, op), price=pr)


def tot_(g, side):
    o = g["odds"]
    if o.get("total") is None or o.get("over") is None or o.get("under") is None:
        return None
    if not 1.0 <= imp(o["over"]) + imp(o["under"]) <= 1.12:
        return None
    s = g["home"]["score"] + g["away"]["score"]
    if s == o["total"]:
        return None
    won = (s > o["total"]) if side == "over" else (s < o["total"])
    pr, op = (o["over"], o["under"]) if side == "over" else (o["under"], o["over"])
    return dict(won=won, p=nv(pr, op), price=pr)


def fav_side(g):
    hs = g["odds"]["h_sp"]
    return None if hs == 0 else ("home" if hs < 0 else "away")


def other(s):
    return "away" if s == "home" else "home"


def et_hour(g):
    t = dt.datetime.fromisoformat(g["date"].replace("Z", "+00:00")).astimezone(ET)
    return t.hour + t.minute / 60, t.weekday()


# ------------------------------------------------------------- context added
def add_prev(G):
    """each side's previous game margin in the same season (earlier dates only)."""
    last = {}
    for g in sorted(G, key=lambda g: g["date"]):
        for s in ("home", "away"):
            g["prev_" + s] = last.get((g[s]["id"], g["season"]))
        mh = g["home"]["score"] - g["away"]["score"]
        last[(g["home"]["id"], g["season"])] = (mh, g["date"])
        last[(g["away"]["id"], g["season"])] = (-mh, g["date"])


# ----------------------------------------------------------------- strategies
def strategies(lg):
    S = []

    def add(name, fn):
        S.append((name, fn))

    big = 2.0 if lg == "nfl" else 3.0
    bigt = 2.0 if lg == "nfl" else 3.0

    def drift(g):
        o = g["odds"].get("mv")
        if not o:
            return None
        return o["h_sp"] - o["h_sp_open"]          # <0: home became more favoured

    def tdrift(g):
        o = g["odds"].get("mvt")
        if not o:
            return None
        return o["total"] - o["total_open"]

    def mv(g, key="mv"):                           # the game priced by the movement book
        return dict(g, odds=g["odds"][key])

    def mats(g, side):
        return ats_(mv(g), side)

    def mtot(g, side):
        return tot_(mv(g, "mvt"), side)

    # 1. line movement
    add("Spread moved >=0.5: back side it moved toward", lambda g: (
        lambda d: None if d is None or abs(d) < 0.5 else mats(g, "home" if d < 0 else "away"))(drift(g)))
    add(f"Spread moved >={big:g}: back side it moved toward", lambda g: (
        lambda d: None if d is None or abs(d) < big else mats(g, "home" if d < 0 else "away"))(drift(g)))
    add(f"Spread moved >={big:g}: fade the move", lambda g: (
        lambda d: None if d is None or abs(d) < big else mats(g, "away" if d < 0 else "home"))(drift(g)))
    add("Total moved >=0.5: follow the move", lambda g: (
        lambda d: None if d is None or abs(d) < 0.5 else mtot(g, "over" if d > 0 else "under"))(tdrift(g)))
    add(f"Total moved >={bigt:g}: fade the move", lambda g: (
        lambda d: None if d is None or abs(d) < bigt else mtot(g, "under" if d > 0 else "over"))(tdrift(g)))
    ats, tot = ats_, tot_
    # 2. key numbers
    for k in (2.5, 3.0, 3.5, 7.0):
        add(f"Closing spread exactly {k:g}: dog", lambda g, k=k: ats(g, other(fav_side(g))) if abs(g["odds"]["h_sp"]) == k else None)
        add(f"Closing spread exactly {k:g}: favourite", lambda g, k=k: ats(g, fav_side(g)) if abs(g["odds"]["h_sp"]) == k else None)
    # 3. weather
    add("Wind >=15 mph: under", lambda g: tot(g, "under") if (g.get("wx") or {}).get("wind", 0) >= 15 else None)
    add("Precip >=1mm in game window: under", lambda g: tot(g, "under") if (g.get("wx") or {}).get("precip", 0) >= 1.0 else None)
    add("Wind >=15 or precip >=1mm: under", lambda g: tot(g, "under") if g.get("wx") and (g["wx"]["wind"] >= 15 or g["wx"]["precip"] >= 1.0) else None)
    # 4. dogs / primetime
    if lg == "nfl":
        add("Divisional underdog ATS", lambda g: ats(g, other(fav_side(g))) if fav_side(g) and
            DIV.get(g["home"]["abbr"]) and DIV.get(g["home"]["abbr"]) == DIV.get(g["away"]["abbr"]) else None)
    add("Home underdog ATS", lambda g: ats(g, "home") if g["odds"]["h_sp"] > 0 and not g["neutral"] else None)
    if lg == "nfl":
        add("Primetime (kick >=7pm ET) under", lambda g: tot(g, "under") if et_hour(g)[0] >= 19 else None)
        add("Underdog getting 7.5-14 ATS (pre-registered)", lambda g: ats(g, other(fav_side(g))) if 7.5 <= abs(g["odds"]["h_sp"]) <= 14 else None)
        add("West-coast road team, kick <2pm ET, ATS", lambda g: ats(g, "away") if g["away"]["abbr"] in WEST and et_hour(g)[0] < 14 and not g["neutral"] else None)
    # 5. college
    if lg == "ncaaf":
        add("Underdog getting 0.5-3.5 ATS", lambda g: ats(g, other(fav_side(g))) if 0.5 <= abs(g["odds"]["h_sp"]) <= 3.5 else None)
        add("Favourite -20 or more ATS", lambda g: ats(g, fav_side(g)) if abs(g["odds"]["h_sp"]) >= 20 else None)
        add("Underdog getting 20+ ATS", lambda g: ats(g, other(fav_side(g))) if abs(g["odds"]["h_sp"]) >= 20 else None)
        add("Conference game: underdog ATS", lambda g: ats(g, other(fav_side(g))) if fav_side(g) and g["conf_game"] else None)
        add("Non-conference game: underdog ATS", lambda g: ats(g, other(fav_side(g))) if fav_side(g) and not g["conf_game"] else None)
        add("Conference game: under", lambda g: tot(g, "under") if g["conf_game"] else None)
        add("Primetime (kick >=7pm ET) under", lambda g: tot(g, "under") if et_hour(g)[0] >= 19 else None)
    # 6. after a blowout
    bl = 20 if lg == "nfl" else 28

    def after(g, sign, back):
        bets = []
        for s in ("home", "away"):
            p = g.get("prev_" + s)
            if p and sign * p[0] >= bl:
                bets.append(s if back else other(s))
        bets = list(set(bets))
        return ats(g, bets[0]) if len(bets) == 1 else None      # both sides flagged: skip
    add(f"Lost previous game by {bl}+: back them ATS", lambda g: after(g, -1, True))
    add(f"Won previous game by {bl}+: fade them ATS", lambda g: after(g, +1, False))
    # 7. extra
    add("Road favourite ATS", lambda g: ats(g, "away") if g["odds"]["h_sp"] > 0 and not g["neutral"] else None)
    return S


def summarise(bets):
    n = len(bets)
    if not n:
        return dict(n=0)
    w = sum(b["won"] for b in bets)
    e = sum(b["p"] for b in bets)
    v = sum(b["p"] * (1 - b["p"]) for b in bets)
    roi = sum((dec(b["price"]) - 1) if b["won"] else -1 for b in bets) / n
    return dict(n=n, win=round(100 * w / n, 1), implied=round(100 * e / n, 1), roi=round(100 * roi, 1),
                z=round((w - e) / math.sqrt(v), 2) if v else 0.0)


def run(lg, G):
    G = [g for g in G.values() if g.get("odds")]
    add_prev(G)
    G.sort(key=lambda g: g["date"])
    out = []
    for name, fn in strategies(lg):
        bets = []
        for g in G:
            try:
                b = fn(g)
            except (TypeError, KeyError):
                b = None
            if b:
                b["season"], b["date"] = g["season"], g["date"]
                bets.append(b)
        hist = [b for b in bets if b["season"] in SEASONS]
        h = len(hist) // 2
        r = dict(league=lg, strategy=name, all=summarise(hist),
                 seasons={s: summarise([b for b in bets if b["season"] == s]) for s in SEASONS},
                 s2026=summarise([b for b in bets if b["season"] == 2026]),
                 half1=summarise(hist[:h]), half2=summarise(hist[h:]))
        rois = [r["seasons"][s]["roi"] for s in SEASONS if r["seasons"][s]["n"]]
        full = len(rois) == len(SEASONS)
        if full and all(x > 0 for x in rois) and r["half1"].get("z", 0) >= 2.8 and r["half2"].get("z", 0) >= 2.8:
            v = "ADOPTED"
        elif len(rois) >= 3 and sum(x > 0 for x in rois) >= 3 and r["all"].get("roi", -1) > 0:
            v = "on watch"
        else:
            v = "rejected"
        r["verdict"], r["seasons_with_bets"] = v, len(rois)
        out.append(r)
    return out


def fmt(r):
    a = r["all"]
    if not a["n"]:
        return f"| {r['league']} | {r['strategy']} | 0 | - | - | - | - | rejected (no bets) |"
    ss = " / ".join(f"{r['seasons'][s]['roi']:+.1f}" if r['seasons'][s]['n'] else "-" for s in SEASONS)
    ss += f" // {r['s2026']['roi']:+.1f} (n{r['s2026']['n']})" if r["s2026"]["n"] else " // -"
    ns = "/".join(str(r['seasons'][s]['n']) for s in SEASONS)
    return (f"| {r['league']} | {r['strategy']} | {a['n']} ({ns}) | {a['win']} vs {a['implied']} | {a['roi']:+.1f} | "
            f"{ss} | {r['half1'].get('z', 0):+.2f} / {r['half2'].get('z', 0):+.2f} | {r['verdict']} |")


if __name__ == "__main__":
    res = []
    for lg in ("nfl", "ncaaf"):
        p = os.path.join(HERE, f"{lg}.json")
        if os.path.exists(p):
            res += run(lg, json.load(open(p)))
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    lines = ["| lg | strategy | n 22-25 (per season) | win% vs implied | ROI 22-25 | ROI 2022/23/24/25 // 2026 | z half1 / half2 | verdict |",
             "|---|---|---|---|---|---|---|---|"] + [fmt(r) for r in res]
    det = ["", "## Per season detail (n, win% vs implied, ROI, z)", ""]
    for r in res:
        cells = []
        for k, x in [(str(s), r["seasons"][s]) for s in SEASONS] + [("2026 so far", r["s2026"]),
                                                                    ("half 1", r["half1"]), ("half 2", r["half2"])]:
            cells.append(f"{k}: " + (f"n{x['n']} {x['win']}% vs {x['implied']}% roi {x['roi']:+.1f}% z {x['z']:+.2f}" if x["n"] else "-"))
        det.append(f"- **{r['league']} | {r['strategy']}** -- " + "; ".join(cells))
    open(os.path.join(HERE, "results.md"), "w").write("\n".join(lines + det) + "\n")
    print("\n".join(lines))
