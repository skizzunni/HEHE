"""NBA strategy lab: pre-registered rules graded against ESPN closing prices.

    python3 strategies.py            # reads data/nba_{2022..2026}.json

Every feature is computed from games strictly before the one being bet
(the team-state update runs after the bet is recorded). Odds are matched
to teams by ESPN team id in fetch_history.py.  Research only: no bets.
"""
import csv
import json
import math
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SEASONS = [2022, 2023, 2024, 2025, 2026]
FULL = [2022, 2023, 2024, 2025]          # complete seasons; 2026 = current, since Oct 2026
WARM = [2021]                            # loaded only to warm up Elo; never graded

# arena location and UTC offset (standard time) by ESPN team id
LOC = {
    "1": (33.757, -84.396, -5), "2": (42.366, -71.062, -5), "17": (40.683, -73.976, -5),
    "30": (35.225, -80.839, -5), "4": (41.881, -87.674, -6), "5": (41.497, -81.688, -5),
    "6": (32.790, -96.810, -6), "7": (39.749, -105.008, -7), "8": (42.341, -83.055, -5),
    "9": (37.768, -122.388, -8), "10": (29.751, -95.362, -6), "11": (39.764, -86.156, -5),
    "12": (34.043, -118.267, -8), "13": (34.043, -118.267, -8), "29": (35.138, -90.051, -6),
    "14": (25.781, -80.188, -5), "15": (43.045, -87.917, -6), "16": (44.980, -93.276, -6),
    "3": (29.949, -90.082, -6), "18": (40.751, -73.993, -5), "25": (35.463, -97.515, -6),
    "19": (28.539, -81.384, -5), "20": (39.901, -75.172, -5), "21": (33.446, -112.071, -7),
    "22": (45.532, -122.667, -8), "23": (38.580, -121.500, -8), "24": (29.427, -98.438, -6),
    "28": (43.643, -79.379, -5), "26": (40.768, -111.901, -7), "27": (38.898, -77.021, -5),
}


def miles(a, b):
    la1, lo1, _ = LOC[a]
    la2, lo2, _ = LOC[b]
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3959 * 2 * math.asin(math.sqrt(h))


def imp(a):
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def dec(a):
    return 1 + (a / 100 if a > 0 else 100 / -a)


def novig(a, b):
    x, y = imp(a), imp(b)
    return x / (x + y)


def ordinal(d):
    y, m, dd = map(int, d.split("-"))
    import datetime as dt
    return dt.date(y, m, dd).toordinal()


def load():
    games = []
    for y in WARM + SEASONS:
        p = os.path.join(HERE, "data", f"nba_{y}.json")
        if not os.path.exists(p):
            continue
        for g in json.load(open(p)).values():
            g["season"] = y
            games.append(g)
    games.sort(key=lambda g: (g["date"], g["id"]))
    return games


class Team:
    def __init__(self):
        self.reset()

    def reset(self):
        self.results = []      # list of (won, margin)
        self.days = []         # ordinal days of games played
        self.locs = []         # arena team-id of each game played
        self.last_total_dev = None
        self.pts_for = []
        self.pts_against = []
        self.ats = []          # 1 covered / 0 not (pushes skipped)


def streak(t):
    s = 0
    for w, _ in reversed(t.results):
        if not s:
            s = 1 if w else -1
        elif (s > 0) == w:
            s += 1 if w else -1
        else:
            break
    return s


# ---------------------------------------------------------------- bet record
BETS = defaultdict(list)       # strategy -> list of dict(season, date, p, price, won)


def bet(name, g, p, price, won):
    """p = no-vig probability of the side bet; won = 1, 0, or None (push)."""
    if won is None or p is None or price is None or g["season"] not in SEASONS:
        return
    BETS[name].append(dict(season=g["season"], date=g["date"], p=p, price=price, won=won, gid=g["id"]))


def ml_side(g, side):
    o = g["odds"]
    a, b = (o["home"], o["away"]) if side == "home" else (o["away"], o["home"])
    hw = g["home"]["score"] > g["away"]["score"]
    return novig(a, b), a, int(hw if side == "home" else not hw)


def ats_side(g, side):
    o = g["odds"]
    if "home_spread" not in o:
        return None, None, None
    margin = g["home"]["score"] - g["away"]["score"]
    res = margin + o["home_spread"]            # >0 home covers
    hp, ap = o["home_spread_price"], o["away_spread_price"]
    if res == 0:
        won = None
    else:
        won = int(res > 0) if side == "home" else int(res < 0)
    if side == "home":
        return novig(hp, ap), hp, won
    return novig(ap, hp), ap, won


def tot_side(g, side):
    o = g["odds"]
    if "total" not in o:
        return None, None, None
    t = g["home"]["score"] + g["away"]["score"]
    if t == o["total"]:
        won = None
    else:
        won = int(t > o["total"]) if side == "over" else int(t < o["total"])
    a, b = (o["over"], o["under"]) if side == "over" else (o["under"], o["over"])
    return novig(a, b), a, won


def both(name, g, side):
    """Record the same pick at the moneyline and against the spread."""
    bet(name + " [ML]", g, *ml_side(g, side))
    bet(name + " [ATS]", g, *ats_side(g, side))


def other(side):
    return "away" if side == "home" else "home"


# ---------------------------------------------------------------- main loop
def run(games):
    teams = defaultdict(Team)
    elo = defaultdict(lambda: 1500.0)       # results-only Elo
    melo = defaultdict(lambda: 1500.0)      # margin Elo (for one extra rule)
    meet = {}                                # (season, frozenset ids) -> (winner id, margin)
    cur_season = None
    calib = []                               # (season, early, p_home, home_won)
    K, HFA = 20.0, 100.0
    for g in games:
        if g["season"] != cur_season:
            cur_season = g["season"]
            for t in teams.values():
                t.reset()
            for d in (elo, melo):
                for k in d:
                    d[k] = 1500 + 0.75 * (d[k] - 1500)
        h, a = g["home"]["id"], g["away"]["id"]
        if h not in LOC or a not in LOC:
            continue
        H, A = teams[h], teams[a]
        day = ordinal(g["day"])
        o = g.get("odds")
        if o:
            ph = novig(o["home"], o["away"])
            hw = int(g["home"]["score"] > g["away"]["score"])
            early = len(H.results) < 15 or len(A.results) < 15
            if g["season"] in SEASONS:
                calib.append((g["season"], early, ph, hw))
            sides = {"home": H, "away": A}
            ids = {"home": h, "away": a}

            # baselines (sanity): every game, home side / over / favourite
            bet("S0 baseline: home team [ATS]", g, *ats_side(g, "home"))
            bet("S0 baseline: over [TOT]", g, *tot_side(g, "over"))
            bet("S0 baseline: ML favourite [ML]", g, *ml_side(g, "home" if ph > 0.5 else "away"))

            # 1. streaks: fade win streaks, back losing streaks (skip if both qualify)
            sh, sa = streak(H), streak(A)
            for n in (3, 5):
                hot = [s for s, st in (("home", sh), ("away", sa)) if st >= n]
                if len(hot) == 1:
                    both(f"S1 fade team on {n}+ win streak", g, other(hot[0]))
                cold = [s for s, st in (("home", sh), ("away", sa)) if st <= -n]
                if len(cold) == 1:
                    both(f"S1 back team on {n}+ losing streak", g, cold[0])

            # 2. overreaction to last game's margin
            lastm = {s: (t.results[-1][1] if t.results else None) for s, t in sides.items()}
            bw = [s for s in sides if lastm[s] is not None and lastm[s] >= 20]
            bl = [s for s in sides if lastm[s] is not None and lastm[s] <= -20]
            if len(bw) == 1:
                both("S2 fade team off a 20+ pt win", g, other(bw[0]))
                # post-hoc: the reverse side, added after the fade row showed z -2.45
                bet("S2* back team off a 20+ pt win (POST-HOC reverse) [ATS]", g, *ats_side(g, bw[0]))
            if len(bl) == 1:
                both("S2 back team off a 20+ pt loss", g, bl[0])

            # 3. home dogs / road dogs by spread size (ATS)
            if "home_spread" in o:
                hs = o["home_spread"]
                for lo, hi, lab in ((0.5, 3.5, "0.5-3.5"), (4, 7.5, "4-7.5"), (8, 99, "8+")):
                    if lo <= hs <= hi:
                        bet(f"S3 home dog +{lab} [ATS]", g, *ats_side(g, "home"))
                    if lo <= -hs <= hi:
                        bet(f"S3 road dog +{lab} [ATS]", g, *ats_side(g, "away"))

            # 4. totals
            if "total" in o:
                devs = [t.last_total_dev for t in (H, A) if t.last_total_dev is not None]
                if devs and max(devs) >= 20 and min(devs) > -20:
                    bet("S4 under after a team's last game went 20+ over", g, *tot_side(g, "under"))
                if devs and min(devs) <= -20 and max(devs) < 20:
                    bet("S4 over after a team's last game went 20+ under", g, *tot_side(g, "over"))
                if len(H.pts_for) >= 10 and len(A.pts_for) >= 10:
                    league = [sum(t.pts_for + t.pts_against) / len(t.pts_for)
                              for t in teams.values() if len(t.pts_for) >= 10]
                    league.sort()
                    if len(league) >= 20:
                        top = league[-8]
                        bot = league[7]
                        ch = sum(H.pts_for + H.pts_against) / len(H.pts_for)
                        ca = sum(A.pts_for + A.pts_against) / len(A.pts_for)
                        if ch >= top and ca >= top:
                            bet("S4 over, two high-scoring (pace proxy) teams", g, *tot_side(g, "over"))
                        if ch <= bot and ca <= bot:
                            bet("S4 under, two low-scoring (pace proxy) teams", g, *tot_side(g, "under"))

            # 5. schedule density, travel, time zones
            def three_in_four(t):
                return len(t.days) >= 2 and day - t.days[-2] <= 3

            def trip(t, tid_here):
                return miles(t.locs[-1], tid_here) if t.locs else None

            def tz_shift(t, tid_here):
                return abs(LOC[t.locs[-1]][2] - LOC[tid_here][2]) if t.locs else None

            d3 = {s: three_in_four(t) for s, t in sides.items()}
            if d3["home"] != d3["away"]:
                tired = "home" if d3["home"] else "away"
                both("S5 fade team on 3rd game in 4 nights (opp not)", g, other(tired))
            tr = {s: trip(t, h) for s, t in sides.items()}
            if None not in tr.values():
                for s in sides:
                    if tr[s] >= 1500 and tr[other(s)] < 500:
                        both("S5 fade team after 1500+ mi trip (opp <500)", g, other(s))
            tz = {s: tz_shift(t, h) for s, t in sides.items()}
            if None not in tz.values():
                for s in sides:
                    if tz[s] >= 2 and tz[other(s)] == 0:
                        both("S5 fade team crossing 2+ time zones (opp 0)", g, other(s))

            # 6. revenge
            key = (g["season"], frozenset((h, a)))
            if key in meet:
                wid, mg = meet[key]
                loser = "away" if wid == h else "home"
                both("S6 back loser of previous meeting", g, loser)
                if mg >= 15:
                    both("S6 back loser of previous meeting by 15+", g, loser)

            # 7. early season (first 15 games for either team)
            if early:
                fav = "home" if ph > 0.5 else "away"
                both("S7 early: back the underdog", g, other(fav))
            else:
                fav = "home" if ph > 0.5 else "away"
                both("S7 later: back the underdog", g, other(fav))

            # 8. Elo blend: bet the side whose blended prob gives +EV at the actual price
            pe = 1 / (1 + 10 ** (-(elo[h] + HFA - elo[a]) / 400))
            for w in (0.05, 0.10, 0.20):
                pb = (1 - w) * ph + w * pe
                for s, ps in (("home", pb), ("away", 1 - pb)):
                    price = o[s]
                    if ps * dec(price) - 1 > 0:
                        bet(f"S8 Elo blend {int(w*100)}%, +EV side [ML]", g, *ml_side(g, s))
                        if early:
                            bet(f"S8 Elo blend {int(w*100)}%, +EV side, early only [ML]", g, *ml_side(g, s))

            # 9a. ATS form: fade team that covered 7+ of its last 10
            for s, t in sides.items():
                if len(t.ats) >= 10 and sum(t.ats[-10:]) >= 7 and not (len(sides[other(s)].ats) >= 10 and sum(sides[other(s)].ats[-10:]) >= 7):
                    bet("S9 fade team that covered 7+ of last 10 [ATS]", g, *ats_side(g, other(s)))
            # 9b. line movement open -> close (contrarian at the close)
            if "home_spread" in o and "home_spread_open" in o:
                mv = o["home_spread"] - o["home_spread_open"]     # <0 = moved toward home
                if mv <= -1.5:
                    bet("S9 back team the spread moved against (1.5+) [ATS]", g, *ats_side(g, "away"))
                    bet("S9 follow spread move (1.5+) [ATS]", g, *ats_side(g, "home"))
                elif mv >= 1.5:
                    bet("S9 back team the spread moved against (1.5+) [ATS]", g, *ats_side(g, "home"))
                    bet("S9 follow spread move (1.5+) [ATS]", g, *ats_side(g, "away"))
            if "total" in o and "total_open" in o:
                tm = o["total"] - o["total_open"]
                if tm >= 3:
                    bet("S9 under when total rose 3+ from open", g, *tot_side(g, "under"))
                elif tm <= -3:
                    bet("S9 over when total fell 3+ from open", g, *tot_side(g, "over"))
            # 9c. margin-Elo implied spread disagrees with the market by 4+ pts
            if "home_spread" in o and len(H.results) >= 10 and len(A.results) >= 10:
                exp_margin = (melo[h] + HFA - melo[a]) / 28.0
                edge = exp_margin + o["home_spread"]       # >0 model likes home vs line
                if edge >= 4:
                    bet("S9 margin-Elo vs spread, 4+ pt gap [ATS]", g, *ats_side(g, "home"))
                elif edge <= -4:
                    bet("S9 margin-Elo vs spread, 4+ pt gap [ATS]", g, *ats_side(g, "away"))

        # ---------------- update state with this game's result (after betting)
        hsc, asc = g["home"]["score"], g["away"]["score"]
        if hsc == asc:
            continue
        mh = hsc - asc
        H.results.append((mh > 0, mh))
        A.results.append((mh < 0, -mh))
        H.days.append(day)
        A.days.append(day)
        H.locs.append(h)
        A.locs.append(h)
        H.pts_for.append(hsc); H.pts_against.append(asc)
        A.pts_for.append(asc); A.pts_against.append(hsc)
        if o and "total" in o:
            dev = hsc + asc - o["total"]
            H.last_total_dev = A.last_total_dev = dev
        else:
            H.last_total_dev = A.last_total_dev = None
        if o and "home_spread" in o:
            r = mh + o["home_spread"]
            if r != 0:
                H.ats.append(int(r > 0))
                A.ats.append(int(r < 0))
        meet[(g["season"], frozenset((h, a)))] = (h if mh > 0 else a, abs(mh))
        pe = 1 / (1 + 10 ** (-(elo[h] + HFA - elo[a]) / 400))
        elo[h] += K * ((mh > 0) - pe)
        elo[a] -= K * ((mh > 0) - pe)
        pm = 1 / (1 + 10 ** (-(melo[h] + HFA - melo[a]) / 400))
        wd = (melo[h] + HFA - melo[a]) if mh > 0 else (melo[a] - melo[h] - HFA)
        mult = ((abs(mh) + 3) ** 0.8) / (7.5 + 0.006 * wd)
        melo[h] += K * mult * ((mh > 0) - pm)
        melo[a] -= K * mult * ((mh > 0) - pm)
    return calib


# ---------------------------------------------------------------- grading
def grade(bs):
    n = len(bs)
    if not n:
        return dict(n=0)
    w = sum(b["won"] for b in bs)
    e = sum(b["p"] for b in bs)
    v = sum(b["p"] * (1 - b["p"]) for b in bs)
    profit = sum((dec(b["price"]) - 1) if b["won"] else -1 for b in bs)
    return dict(n=n, wins=w, win_pct=round(100 * w / n, 1), implied_pct=round(100 * e / n, 1),
                roi_pct=round(100 * profit / n, 1), z=round((w - e) / math.sqrt(v), 2) if v else None)


def verdict(r):
    rois = [r["by_season"][y].get("roi_pct") for y in FULL]
    if any(x is None for x in rois):
        return "rejected (missing seasons)"
    cur = r["by_season"].get(2026, {})
    cur_ok = cur.get("n", 0) < 20 or cur.get("roi_pct", 0) > 0
    zs = [r["half1"].get("z"), r["half2"].get("z")]
    if all(x > 0 for x in rois) and cur_ok and all(z is not None and z >= 2.8 for z in zs):
        return "ADOPTED"
    if sum(x > 0 for x in rois) >= 3 and r["pooled"]["roi_pct"] > 0:
        return "on watch"
    return "rejected"


def calibration(calib):
    out = {}
    for lab, sel in (("early (either team <15 games)", True), ("later", False)):
        for y in SEASONS + ["2022-25"]:
            rows = [c for c in calib if c[1] == sel and (c[0] == y or (y == "2022-25" and c[0] in FULL))]
            if not rows:
                continue
            br = sum((p - w) ** 2 for _, _, p, w in rows) / len(rows)
            ll = -sum(math.log(p if w else 1 - p) for _, _, p, w in rows) / len(rows)
            # calibration slope: 1-D logistic regression of outcome on logit(p), Newton
            xs = [math.log(p / (1 - p)) for _, _, p, _ in rows]
            ys = [w for *_, w in rows]
            b0, b1 = 0.0, 1.0
            for _ in range(25):
                g0 = g1 = h00 = h01 = h11 = 0.0
                for x, yv in zip(xs, ys):
                    q = 1 / (1 + math.exp(-(b0 + b1 * x)))
                    g0 += yv - q; g1 += (yv - q) * x
                    wv = q * (1 - q)
                    h00 += wv; h01 += wv * x; h11 += wv * x * x
                det = h00 * h11 - h01 * h01
                if det <= 0:
                    break
                b0 += (h11 * g0 - h01 * g1) / det
                b1 += (-h01 * g0 + h00 * g1) / det
            out[f"{lab} | {y}"] = dict(n=len(rows), brier=round(br, 4), logloss=round(ll, 4),
                                       calib_slope=round(b1, 3), calib_intercept=round(b0, 3))
    return out


def main():
    games = load()
    calib = run(games)
    results = []
    for name, bs in sorted(BETS.items()):
        bs.sort(key=lambda b: (b["date"], b["gid"]))
        r = dict(strategy=name, by_season={y: grade([b for b in bs if b["season"] == y]) for y in SEASONS})
        pool = [b for b in bs if b["season"] in FULL]
        r["pooled"] = grade(pool)
        half = len(pool) // 2
        r["half1"], r["half2"] = grade(pool[:half]), grade(pool[half:])
        r["half_split_date"] = pool[half]["date"][:10] if pool else None
        r["verdict"] = verdict(r)
        results.append(r)
    with open(os.path.join(HERE, "bets.csv"), "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["strategy", "season", "date", "game_id", "p_novig", "price", "won"])
        for name, bs in sorted(BETS.items()):
            for b in bs:
                wr.writerow([name, b["season"], b["date"], b["gid"], round(b["p"], 4), b["price"], b["won"]])
    cal = calibration(calib)
    summ = dict(games=len(games), games_with_ml=sum(1 for g in games if g.get("odds")),
                with_spread=sum(1 for g in games if g.get("odds") and "home_spread" in g["odds"]),
                with_total=sum(1 for g in games if g.get("odds") and "total" in g["odds"]),
                with_spread_open=sum(1 for g in games if g.get("odds") and "home_spread_open" in g["odds"]),
                with_total_open=sum(1 for g in games if g.get("odds") and "total_open" in g["odds"]),
                by_season={y: sum(1 for g in games if g["season"] == y and g.get("odds")) for y in SEASONS})
    json.dump(dict(summary=summ, strategies=results, calibration=cal),
              open(os.path.join(HERE, "results.json"), "w"), indent=1, default=str)
    with open(os.path.join(HERE, "results.csv"), "w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["strategy", "verdict", "n_2022_25", "win_pct", "implied_pct", "roi_pooled", "z_pooled",
                     "z_half1", "z_half2", "split_date"] + [f"roi_{y}" for y in SEASONS] + [f"n_{y}" for y in SEASONS]
                    + [f"win_{y}" for y in SEASONS] + [f"impl_{y}" for y in SEASONS] + [f"z_{y}" for y in SEASONS])
        for r in results:
            p = r["pooled"]
            wr.writerow([r["strategy"], r["verdict"], p.get("n"), p.get("win_pct"), p.get("implied_pct"), p.get("roi_pct"),
                         p.get("z"), r["half1"].get("z"), r["half2"].get("z"), r["half_split_date"]]
                        + [r["by_season"][y].get("roi_pct") for y in SEASONS] + [r["by_season"][y].get("n") for y in SEASONS]
                        + [r["by_season"][y].get("win_pct") for y in SEASONS] + [r["by_season"][y].get("implied_pct") for y in SEASONS]
                        + [r["by_season"][y].get("z") for y in SEASONS])
    print(json.dumps(summ))
    for r in results:
        p = r["pooled"]
        print(f'{r["strategy"][:60]:60s} n={p.get("n",0):5} {p.get("win_pct")}/{p.get("implied_pct")} '
              f'roi={p.get("roi_pct")} z={p.get("z")} h={r["half1"].get("z")},{r["half2"].get("z")} '
              f'seas={[r["by_season"][y].get("roi_pct") for y in SEASONS]} -> {r["verdict"]}')
    for k, v in cal.items():
        print(k, v)


if __name__ == "__main__":
    main()
