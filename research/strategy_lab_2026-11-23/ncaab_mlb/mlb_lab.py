"""MLB strategy lab against ESPN closing lines (data/mlb.json, with box scores).
Pre-game information only: the closing line, the scheduled start time, the
probable starter from the scoreboard (box-score starter if none listed), and
box-score lines from strictly earlier calendar days. Flat $1 at the closing
price; pushes dropped.
    python mlb_lab.py   -> results_mlb.txt / results_mlb.json"""
import collections
import datetime as dt
import json
import os

from common import evaluate, fmt, novig

HERE = os.path.dirname(os.path.abspath(__file__))
G = json.load(open(os.path.join(HERE, "data/mlb.json")))
games = sorted(G.values(), key=lambda g: g["date"])
for g in games:
    g["s"] = int(g["day"][:4])
SEASONS = sorted({g["s"] for g in games})
HALVES = [SEASONS[: len(SEASONS) // 2], SEASONS[len(SEASONS) // 2:]]

TZ = {**{t: -4 for t in "ATL BAL BOS CIN CLE DET MIA NYM NYY PHI PIT TB TOR WSH".split()},
      **{t: -5 for t in "CHC CHW CWS HOU KC MIL MIN STL TEX".split()},
      "COL": -6, "ARI": -7, **{t: -7 for t in "LAA LAD OAK ATH SD SF SEA".split()}}


def local_hour(g):
    off = TZ.get(g["home"]["abbr"])
    if off is None or g.get("neutral"):
        return None
    t = dt.datetime.strptime(g["date"], "%Y-%m-%dT%H:%MZ") + dt.timedelta(hours=off)
    return t.hour + t.minute / 60


def outs(ip):
    try:
        a, _, b = str(ip).partition(".")
        return int(a) * 3 + int(b or 0)
    except ValueError:
        return 0


def ival(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def other(side):
    return "away" if side == "home" else "home"


def ml(g, side):
    o = (g.get("odds") or {}).get("ml")
    if not o:
        return None
    return (g["s"], o[side], novig(o[side], o[other(side)]), int(g[side]["score"] > g[other(side)]["score"]))


def rl(g, side, want=None):
    sp = (g.get("odds") or {}).get("spread")
    if not sp or abs(sp["home_pts"]) != 1.5:
        return None
    # ESPN's MLB pointSpread sign is unreliable (home shows +1.5 in every game,
    # e.g. event 401421332: STL -155 home, '+1.5' at +125). The prices are
    # right, and books sometimes give a small home favourite +1.5, so the side
    # is read from the prices: -1.5 makes a side's chance lower than its
    # moneyline chance, +1.5 makes it higher.
    o = (g.get("odds") or {}).get("ml")
    if not o:
        return None
    p_rl, p_ml = novig(sp["home"], sp["away"]), novig(o["home"], o["away"])
    if abs(p_rl - p_ml) < 0.02:
        return None
    home_pts = -1.5 if p_rl < p_ml else 1.5
    pts = home_pts if side == "home" else -home_pts
    if want is not None and pts != want:
        return None
    m = g[side]["score"] - g[other(side)]["score"] + pts
    return (g["s"], sp[side], novig(sp[side], sp[other(side)]), int(m > 0))


def tot(g, side):
    t = (g.get("odds") or {}).get("total")
    if not t:
        return None
    s = g["home"]["score"] + g["away"]["score"]
    o = "under" if side == "over" else "over"
    res = None if s == t["line"] else int((s > t["line"]) == (side == "over"))
    return (g["s"], t[side], novig(t[side], t[o]), res)


# ---- pre-game state from strictly earlier days ------------------------------
starts = collections.defaultdict(list)      # pid -> [(date, outs, er, bb, k, hr)]
pen = collections.defaultdict(list)         # team -> [(date, bullpen outs)]
night = {}                                  # (team, date) -> played a night game that day
results = collections.defaultdict(list)     # (season, team) -> [win bool]
pre = {}
agree = [0, 0]
by_day = collections.defaultdict(list)
for g in games:
    by_day[g["day"]].append(g)


def sp_line(pid, day):
    d0 = day - dt.timedelta(days=365)
    rows = [r for r in starts.get(pid, []) if d0 <= r[0] < day]
    o = sum(r[1] for r in rows)
    if o < 90:                               # need >= 30 IP of prior starts
        return None
    ip = o / 3
    er, bb, k, hr = (sum(r[i] for r in rows) for i in (2, 3, 4, 5))
    return dict(era=9 * er / ip, fip=(13 * hr + 3 * bb - 2 * k) / ip + 3.10, ip=ip)


for dstr in sorted(by_day):
    day = dt.date.fromisoformat(dstr)
    for g in by_day[dstr]:
        st = {}
        box = g.get("box") or {}
        for side in ("home", "away"):
            tid = g[side]["id"]
            pid = g[side].get("probable")
            bs = [r["pid"] for r in box.get(tid, []) if r["starter"]]
            if pid and bs:
                agree[0] += pid == bs[0]
                agree[1] += 1
            pid = pid or (bs[0] if bs else None)
            pen3 = sum(o for d, o in pen.get(tid, []) if day - dt.timedelta(days=3) <= d < day) / 3
            yest = night.get((tid, day - dt.timedelta(days=1)))
            r = results[(g["s"], tid)]
            k = 0
            for w in reversed(r):
                if k == 0:
                    k = 1 if w else -1
                elif (k > 0) == w:
                    k += 1 if k > 0 else -1
                else:
                    break
            st[side] = dict(sp=sp_line(pid, day) if pid else None, pen3=pen3, yest_night=yest, streak=k)
        st["hour"] = local_hour(g)
        pre[g["id"]] = st
    for g in by_day[dstr]:
        box = g.get("box") or {}
        h = local_hour(g)
        for side in ("home", "away"):
            tid = g[side]["id"]
            rows = box.get(tid) or []
            for r in rows:
                if r["starter"]:
                    starts[r["pid"]].append((day, outs(r["ip"]), ival(r["er"]), ival(r["bb"]), ival(r["k"]), ival(r["hr"])))
            if rows:
                pen[tid].append((day, sum(outs(r["ip"]) for r in rows if not r["starter"])))
            if h is not None:
                night[(tid, day)] = night.get((tid, day), False) or h >= 17
            results[(g["s"], tid)].append(g[side]["score"] > g[other(side)]["score"])

RULES = collections.OrderedDict()


def rule(name):
    def deco(f):
        RULES[name] = f
        return f
    return deco


def price(g, side):
    o = (g.get("odds") or {}).get("ml")
    return o[side] if o else None


# 1. home underdogs
for lo, hi in ((100, 999), (100, 129), (130, 159), (160, 999)):
    @rule(f"Home dog ML +{lo}..+{hi}")
    def _(g, lo=lo, hi=hi):
        p = price(g, "home")
        return [ml(g, "home")] if p and lo <= p <= hi and not g["neutral"] else []

for lo, hi in ((100, 129), (130, 159), (160, 999)):
    @rule(f"Road dog ML +{lo}..+{hi}")
    def _(g, lo=lo, hi=hi):
        p = price(g, "away")
        return [ml(g, "away")] if p and lo <= p <= hi else []


# 2. big favourites vs the run line
for cut in (-200, -250):
    def fav(g, cut=cut):
        o = (g.get("odds") or {}).get("ml")
        if not o:
            return None
        for s in ("home", "away"):
            if o[s] <= cut:
                return s
        return None

    @rule(f"Favourite {cut} or shorter: fav -1.5 run line")
    def _(g, fav=fav):
        s = fav(g)
        return [rl(g, s, -1.5)] if s else []

    @rule(f"Favourite {cut} or shorter: dog +1.5 run line")
    def _(g, fav=fav):
        s = fav(g)
        return [rl(g, other(s), 1.5)] if s else []

    @rule(f"Favourite {cut} or shorter: fav moneyline")
    def _(g, fav=fav):
        s = fav(g)
        return [ml(g, s)] if s else []


# 3. unders by total band
for lo, hi in ((0, 7.5), (8, 8.5), (9, 9.5), (10, 99)):
    @rule(f"Under, total {lo}-{hi}")
    def _(g, lo=lo, hi=hi):
        t = (g.get("odds") or {}).get("total")
        return [tot(g, "under")] if t and lo <= t["line"] <= hi else []


# 4. starting pitcher gap (prior starts, trailing 365 days, >= 30 IP)
for stat_, gap in (("fip", 0.75), ("fip", 1.25), ("era", 1.0), ("era", 2.0)):
    for when in ("any price", "as underdog", "as favourite"):
        @rule(f"Better SP by {stat_.upper()} >= {gap}, {when}")
        def _(g, stat_=stat_, gap=gap, when=when):
            st = pre[g["id"]]
            a, b = st["home"]["sp"], st["away"]["sp"]
            if not a or not b or not (g.get("odds") or {}).get("ml"):
                return []
            d = b[stat_] - a[stat_]          # > 0: home starter better
            if abs(d) < gap:
                return []
            s = "home" if d > 0 else "away"
            p = price(g, s)
            if when == "as underdog" and p < 0 or when == "as favourite" and p > 0:
                return []
            return [ml(g, s)]


@rule("Both SPs FIP <= 3.50: under")
def _(g):
    st = pre[g["id"]]
    a, b = st["home"]["sp"], st["away"]["sp"]
    return [tot(g, "under")] if a and b and a["fip"] <= 3.5 and b["fip"] <= 3.5 else []


@rule("Both SPs FIP >= 4.75: over")
def _(g):
    st = pre[g["id"]]
    a, b = st["home"]["sp"], st["away"]["sp"]
    return [tot(g, "over")] if a and b and a["fip"] >= 4.75 and b["fip"] >= 4.75 else []


# 5. bullpen fatigue: bullpen innings over the previous 3 calendar days
for hi_, lo_ in ((10, 6), (12, 8)):
    @rule(f"Back rested pen (<= {lo_} IP) vs tired pen (>= {hi_} IP), ML")
    def _(g, hi_=hi_, lo_=lo_):
        st = pre[g["id"]]
        out = []
        for s in ("home", "away"):
            if st[s]["pen3"] >= hi_ and st[other(s)]["pen3"] <= lo_:
                out.append(ml(g, other(s)))
        return out

for t in (10, 12):
    @rule(f"Both pens >= {t} IP last 3 days: over")
    def _(g, t=t):
        st = pre[g["id"]]
        return [tot(g, "over")] if st["home"]["pen3"] >= t and st["away"]["pen3"] >= t else []

    @rule(f"Fade team with pen >= {t} IP last 3 days, ML")
    def _(g, t=t):
        st = pre[g["id"]]
        return [ml(g, other(s)) for s in ("home", "away") if st[s]["pen3"] >= t]


# 6. day game after a night game
@rule("Fade team in day game after night game (opp not), ML")
def _(g):
    st = pre[g["id"]]
    if st["hour"] is None or st["hour"] >= 17:
        return []
    return [ml(g, other(s)) for s in ("home", "away") if st[s]["yest_night"] and not st[other(s)]["yest_night"]]


@rule("Day game after night game, both teams: under")
def _(g):
    st = pre[g["id"]]
    if st["hour"] is None or st["hour"] >= 17:
        return []
    return [tot(g, "under")] if st["home"]["yest_night"] and st["away"]["yest_night"] else []


@rule("Day game, any: under")
def _(g):
    st = pre[g["id"]]
    return [tot(g, "under")] if st["hour"] is not None and st["hour"] < 17 else []


# 7. streaks (straight-up, this season)
for k in (5, 7):
    @rule(f"Fade team on {k}+ win streak, ML")
    def _(g, k=k):
        st = pre[g["id"]]
        return [ml(g, other(s)) for s in ("home", "away") if st[s]["streak"] >= k]

    @rule(f"Back team on {k}+ loss streak, ML")
    def _(g, k=k):
        st = pre[g["id"]]
        return [ml(g, s) for s in ("home", "away") if st[s]["streak"] <= -k]

    @rule(f"Back team on {k}+ win streak, ML")
    def _(g, k=k):
        st = pre[g["id"]]
        return [ml(g, s) for s in ("home", "away") if st[s]["streak"] >= k]


# extras
@rule("Home favourite -1.5 run line, fav -130..-199")
def _(g):
    p = price(g, "home")
    return [rl(g, "home", -1.5)] if p and -199 <= p <= -130 else []


@rule("Road dog +1.5 run line, dog +100..+150")
def _(g):
    p = price(g, "away")
    return [rl(g, "away", 1.5)] if p and 100 <= p <= 150 else []


def main():
    lines, res = [], []
    for name, f in RULES.items():
        bets = [b for g in games for b in f(g) if b]
        r = evaluate(name, bets, SEASONS, HALVES)
        res.append(r)
        lines.append(fmt(r, SEASONS))
    hdr = (f"MLB, seasons {SEASONS}, halves {HALVES}; games {len(games)}, with ml "
           f"{sum(1 for g in games if (g.get('odds') or {}).get('ml'))}, run line "
           f"{sum(1 for g in games if (g.get('odds') or {}).get('spread'))}, total "
           f"{sum(1 for g in games if (g.get('odds') or {}).get('total'))}, box "
           f"{sum(1 for g in games if g.get('box'))}; probable == box starter {agree[0]}/{agree[1]}")
    open(os.path.join(HERE, "results_mlb.txt"), "w").write(hdr + "\n" + "\n".join(lines) + "\n")
    json.dump(res, open(os.path.join(HERE, "results_mlb.json"), "w"), indent=1)
    print(hdr)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
