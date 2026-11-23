"""College basketball strategy lab against ESPN closing lines (data/ncaab.json).
Every rule uses pre-game information only: the closing line itself, flags on
the schedule (neutral, conference game, date) and each team's results in
earlier games of the same season. Flat $1 at the closing price; pushes dropped.
    python ncaab_lab.py   -> results_ncaab.txt / results_ncaab.json"""
import collections
import json
import os

from common import evaluate, fmt, novig

HERE = os.path.dirname(os.path.abspath(__file__))
G = json.load(open(os.path.join(HERE, "data/ncaab.json")))


def season_of(day):
    y, m = int(day[:4]), int(day[5:7])
    return y if m >= 8 else y - 1


games = sorted(G.values(), key=lambda g: g["date"])
for g in games:
    g["s"] = season_of(g["day"])
SEASONS = sorted({g["s"] for g in games})
HALVES = [SEASONS[: len(SEASONS) // 2], SEASONS[len(SEASONS) // 2:]]


def ats(g, side):
    sp = (g.get("odds") or {}).get("spread")
    if not sp:
        return None
    other = "away" if side == "home" else "home"
    pts = sp["home_pts"] if side == "home" else -sp["home_pts"]
    m = g[side]["score"] - g[other]["score"] + pts
    res = None if m == 0 else int(m > 0)
    return (g["s"], sp[side], novig(sp[side], sp[other]), res)


def ml(g, side):
    o = (g.get("odds") or {}).get("ml")
    if not o:
        return None
    other = "away" if side == "home" else "home"
    return (g["s"], o[side], novig(o[side], o[other]), int(g[side]["score"] > g[other]["score"]))


def tot(g, side):
    t = (g.get("odds") or {}).get("total")
    if not t:
        return None
    s = g["home"]["score"] + g["away"]["score"]
    other = "under" if side == "over" else "over"
    res = None if s == t["line"] else int((s > t["line"]) == (side == "over"))
    return (g["s"], t[side], novig(t[side], t[other]), res)


def poss(t):
    if t.get("fga") is None or t.get("fta") is None:
        return None
    return t["fga"] + 0.44 * t["fta"]


# ---- pre-game team state, built strictly from earlier games -----------------
hist = collections.defaultdict(list)        # (season, team) -> [dict(margin, poss, ats)]
pre = {}
by_day = collections.defaultdict(list)
for g in games:
    by_day[g["day"]].append(g)
for day in sorted(by_day):
    gs = by_day[day]
    # league-wide pace distribution from teams with >= 5 earlier games (this season)
    s = gs[0]["s"]
    paces = sorted(sum(x["poss"] for x in h) / len(h) for (ss, _), h in hist.items()
                   if ss == s and len(h) >= 5 and all(x["poss"] for x in h))
    q25 = paces[len(paces) // 4] if len(paces) > 40 else None
    q75 = paces[3 * len(paces) // 4] if len(paces) > 40 else None
    for g in gs:
        st = {}
        for side in ("home", "away"):
            h = hist[(g["s"], g[side]["id"])]
            st[side] = dict(
                n=len(h), last=h[-1]["margin"] if h else None,
                pace=(sum(x["poss"] for x in h) / len(h)) if len(h) >= 5 and all(x["poss"] for x in h) else None,
                ats_streak=0)
            k = 0
            for x in reversed(h):
                if x["ats"] is None:
                    break
                if k == 0:
                    k = 1 if x["ats"] else -1
                elif (k > 0) == bool(x["ats"]):
                    k += 1 if k > 0 else -1
                else:
                    break
            st[side]["ats_streak"] = k
            w = 0
            for x in reversed(h):
                if w == 0:
                    w = 1 if x["margin"] > 0 else -1
                elif (w > 0) == (x["margin"] > 0):
                    w += 1 if w > 0 else -1
                else:
                    break
            st[side]["su_streak"] = w
        st["q25"], st["q75"] = q25, q75
        pre[g["id"]] = st
    for g in gs:     # update after the whole day's games are recorded as pre-game
        gp = [poss(g["home"]), poss(g["away"])]
        gposs = sum(gp) / 2 if None not in gp else None
        for side, other in (("home", "away"), ("away", "home")):
            a = ats(g, side)
            hist[(g["s"], g[side]["id"])].append(dict(
                margin=g[side]["score"] - g[other]["score"], poss=gposs, ats=a[3] if a else None))


def sides(g):
    return (("home", "away"), ("away", "home"))


RULES = collections.OrderedDict()


def rule(name):
    def deco(f):
        RULES[name] = f
        return f
    return deco


def home_pts(g):
    sp = (g.get("odds") or {}).get("spread")
    return sp["home_pts"] if sp else None


# 1. home underdogs by spread size (true home games only)
for lo, hi in ((0.5, 3.5), (4, 7.5), (8, 12.5), (13, 99)):
    @rule(f"Home dog +{lo}-{hi} ATS")
    def _(g, lo=lo, hi=hi):
        hp = home_pts(g)
        return [ats(g, "home")] if hp is not None and not g["neutral"] and lo <= hp <= hi else []

    @rule(f"Home dog +{lo}-{hi} moneyline")
    def _(g, lo=lo, hi=hi):
        hp = home_pts(g)
        return [ml(g, "home")] if hp is not None and not g["neutral"] and lo <= hp <= hi else []


# 2. big favourites
for lo, hi in ((15, 19.5), (20, 99), (15, 99)):
    @rule(f"Favourite -{lo}-{hi} ATS")
    def _(g, lo=lo, hi=hi):
        hp = home_pts(g)
        if hp is None or not lo <= abs(hp) <= hi:
            return []
        return [ats(g, "home" if hp < 0 else "away")]

    @rule(f"Underdog +{lo}-{hi} ATS")
    def _(g, lo=lo, hi=hi):
        hp = home_pts(g)
        if hp is None or not lo <= abs(hp) <= hi:
            return []
        return [ats(g, "away" if hp < 0 else "home")]


# 3. conference / non-conference, November vs later
for label, cond in (("conference", lambda g: g["conf_game"]), ("non-conference", lambda g: not g["conf_game"]),
                    ("November", lambda g: g["day"][5:7] == "11"), ("Dec-Mar", lambda g: g["day"][5:7] != "11")):
    @rule(f"Underdog ATS, {label}")
    def _(g, cond=cond):
        hp = home_pts(g)
        return [ats(g, "away" if hp < 0 else "home")] if hp and cond(g) else []

    @rule(f"Home team ATS, {label} (not neutral)")
    def _(g, cond=cond):
        return [ats(g, "home")] if home_pts(g) is not None and not g["neutral"] and cond(g) else []

    @rule(f"Under, {label}")
    def _(g, cond=cond):
        return [tot(g, "under")] if cond(g) else []

    @rule(f"Home dog ATS, {label}")
    def _(g, cond=cond):
        hp = home_pts(g)
        return [ats(g, "home")] if hp and hp > 0 and not g["neutral"] and cond(g) else []


# 4. after a blowout (previous game, same season)
for label, test in (("won by 20+", lambda m: m >= 20), ("lost by 20+", lambda m: m <= -20),
                    ("won by 30+", lambda m: m >= 30), ("lost by 30+", lambda m: m <= -30)):
    @rule(f"Team after it {label} ATS")
    def _(g, test=test):
        out = []
        for side, _o in sides(g):
            last = pre[g["id"]][side]["last"]
            if last is not None and test(last) and home_pts(g) is not None:
                out.append(ats(g, side))
        return out

    @rule(f"Fade team after it {label} ATS")
    def _(g, test=test):
        out = []
        for side, o in sides(g):
            last = pre[g["id"]][side]["last"]
            if last is not None and test(last) and home_pts(g) is not None:
                out.append(ats(g, o))
        return out


# 5. totals by pace (possessions proxy FGA + 0.44 FTA, season to date, >= 5 games)
def pace_both(g, which):
    st = pre[g["id"]]
    a, b = st["home"]["pace"], st["away"]["pace"]
    if a is None or b is None or st["q25"] is None:
        return False
    return (a <= st["q25"] and b <= st["q25"]) if which == "slow" else (a >= st["q75"] and b >= st["q75"])


for which in ("slow", "fast"):
    for side in ("under", "over"):
        @rule(f"{side.title()} when both teams {which} (pace quartile)")
        def _(g, which=which, side=side):
            return [tot(g, side)] if pace_both(g, which) else []


# 6. extras
for lo, hi in ((0, 129.5), (130, 139.5), (140, 149.5), (150, 999)):
    @rule(f"Under, total {lo}-{hi}")
    def _(g, lo=lo, hi=hi):
        t = (g.get("odds") or {}).get("total")
        return [tot(g, "under")] if t and lo <= t["line"] <= hi else []


@rule("Road favourite ATS (not neutral)")
def _(g):
    hp = home_pts(g)
    return [ats(g, "away")] if hp and hp > 0 and not g["neutral"] else []


for k in (3, 5):
    @rule(f"Fade team on {k}+ game ATS cover streak")
    def _(g, k=k):
        return [ats(g, o) for side, o in sides(g) if home_pts(g) is not None and pre[g["id"]][side]["ats_streak"] >= k]

    @rule(f"Back team on {k}+ game ATS loss streak")
    def _(g, k=k):
        return [ats(g, side) for side, o in sides(g) if home_pts(g) is not None and pre[g["id"]][side]["ats_streak"] <= -k]

    @rule(f"Fade team on {k}+ game win streak ATS")
    def _(g, k=k):
        return [ats(g, o) for side, o in sides(g) if home_pts(g) is not None and pre[g["id"]][side]["su_streak"] >= k]


@rule("Neutral-site underdog ATS")
def _(g):
    hp = home_pts(g)
    return [ats(g, "away" if hp < 0 else "home")] if hp and g["neutral"] else []


@rule("Moneyline dog +400 or longer")
def _(g):
    o = (g.get("odds") or {}).get("ml")
    if not o:
        return []
    return [ml(g, s) for s in ("home", "away") if o[s] >= 400]


def main():
    lines, res = [], []
    for name, f in RULES.items():
        bets = [b for g in games for b in f(g) if b]
        r = evaluate(name, bets, SEASONS, HALVES)
        res.append(r)
        lines.append(fmt(r, SEASONS))
    hdr = (f"NCAAB, seasons {SEASONS} (start year), halves {HALVES}; games {len(games)}, "
           f"with spread {sum(1 for g in games if (g.get('odds') or {}).get('spread'))}, "
           f"total {sum(1 for g in games if (g.get('odds') or {}).get('total'))}, "
           f"ml {sum(1 for g in games if (g.get('odds') or {}).get('ml'))}")
    open(os.path.join(HERE, "results_ncaab.txt"), "w").write(hdr + "\n" + "\n".join(lines) + "\n")
    json.dump(res, open(os.path.join(HERE, "results_ncaab.json"), "w"), indent=1)
    print(hdr)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
