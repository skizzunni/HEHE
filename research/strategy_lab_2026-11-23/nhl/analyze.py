"""NHL strategy lab: every strategy tested against ESPN closing prices.

    python analyze.py games.json raw/box.json > results.txt   (also writes results.json)

Inputs: games.json from nhl_history.py (ESPN games + closing ML / puck line /
total, odds matched by team id) and raw/box.json from nhl_box.py (NHL API
boxscores: starting goalies, shots on goal). Every feature for a game is built
from games strictly before it (by start time) in the same season.
Seasons are labelled by start year; 2026 = the current season (Oct 2026-).
Halves for the verdict: H1 = 2022-23 + 2023-24, H2 = 2024-25 + 2025-26.
"""
import collections, datetime as _dt, json, math, sys

games = json.load(open(sys.argv[1]))
box = json.load(open(sys.argv[2]))


def imp(a):
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def dec(a):
    return 1 + (a / 100 if a > 0 else 100 / -a)


# ---- map ESPN team ids to NHL tricodes by (date, scores) agreement ----
bykey = collections.defaultdict(list)
for b in box.values():
    bykey[(b["date"], b["home"]["score"], b["away"]["score"])].append(b)
votes = collections.defaultdict(collections.Counter)
for g in games.values():
    c = bykey.get((g["day"], g["home"]["score"], g["away"]["score"]), [])
    if len(c) == 1:
        votes[g["home"]["id"]][c[0]["home"]["tri"]] += 1
        votes[g["away"]["id"]][c[0]["away"]["tri"]] += 1
tri_sets = {k: {t for t, n in v.items() if n >= 3} for k, v in votes.items()}   # Utah renamed: ARI->UTA

boxidx = {(b["date"], b["home"]["tri"], b["away"]["tri"]): b for b in box.values()}
joined, unmatched = [], 0
for g in games.values():
    b = None
    for ht in tri_sets.get(g["home"]["id"], ()):
        for at in tri_sets.get(g["away"]["id"], ()):
            b = b or boxidx.get((g["day"], ht, at))
    if b is None or b["home"]["score"] != g["home"]["score"] or b["away"]["score"] != g["away"]["score"]:
        unmatched += 1
        continue
    joined.append((b, g.get("odds")))
joined.sort(key=lambda x: x[0]["start"])
print(f"ESPN games {len(games)}, NHL boxscores {len(box)}, joined {len(joined)}, unmatched {unmatched}, "
      f"with ML {sum(1 for _, o in joined if o)}")

# ---- pre-game state, built game by game ----
LG_SV = 0.900
bets = collections.defaultdict(list)     # strategy -> [(season, start, p, price, result)]


def bet(name, season, start, p, price, res):
    """res 1 win / 0 loss / None push. p = no-vig implied prob of the side."""
    bets[name].append((season, start, p, price, res))


def ml_side(o, side):
    """(no-vig p, price) for 'home'/'away' moneyline."""
    h, a = imp(o["home"]), imp(o["away"])
    return (h / (h + a), o["home"]) if side == "home" else (a / (a + h), o["away"])


state = {}
for b, o in joined:
    season = int(str(b["id"])[:4])
    if season not in state:
        state[season] = dict(team=collections.defaultdict(list),      # tri -> list of past game dicts
                             gstarts=collections.defaultdict(collections.Counter),
                             gsv=collections.defaultdict(lambda: [0, 0]),
                             glog=collections.defaultdict(list))     # goalie -> [(date, sv, sa)]
    S = state[season]
    info = {}
    for side, opp in (("home", "away"), ("away", "home")):
        t = b[side]
        st = [x for x in t["goalies"] if x["starter"]]
        info[side] = dict(tri=t["tri"], starter=st[0]["pid"] if len(st) == 1 else None,
                          past=S["team"][t["tri"]])
    # ---- features ----
    F = {}
    for side in ("home", "away"):
        I = info[side]
        past = I["past"]
        cnt = S["gstarts"][I["tri"]]
        no1 = None
        if len(past) >= 5 and cnt:
            top = cnt.most_common(2)
            if len(top) == 1 or top[0][1] > top[1][1]:
                no1 = top[0][0]
        F[side] = dict(n=len(past), no1=no1,
                       backup=(no1 is not None and I["starter"] is not None and I["starter"] != no1))
        sv, sa = S["gsv"][I["starter"]] if I["starter"] else (0, 0)
        F[side]["sv_raw"] = sv / sa if sa else None
        F[side]["sa"] = sa
        F[side]["sv_shr"] = (sv + LG_SV * 400) / (sa + 400)                 # shrunk toward league avg
        gl = S["glog"][I["starter"]] if I["starter"] else []
        last10 = past[-10:]
        if len(last10) == 10:
            sf = sum(x["sf"] for x in last10); sag = sum(x["sa"] for x in last10)
            gf = sum(x["gf"] for x in last10); ga = sum(x["ga"] for x in last10)
            F[side]["ss"] = sf / (sf + sag)
            F[side]["gs"] = gf / (gf + ga) if gf + ga else 0.5
        F[side]["prev"] = past[-1] if past else None
        streak = 0
        for x in reversed(past):
            if x["gf"] > x["ga"]:
                streak += 1
            else:
                break
        F[side]["wstreak"] = streak
        # goalie started the previous calendar day
        yday = (_dt.date.fromisoformat(b["date"]) - _dt.timedelta(days=1)).isoformat()
        F[side]["g_b2b"] = bool(gl) and gl[-1][0] == yday
        F[side]["team_b2b"] = bool(past) and past[-1]["date"] == yday
        hot = gl[-3:]
        F[side]["hot3"] = (len(hot) == 3 and sum(x[2] for x in hot) >= 60
                           and sum(x[1] for x in hot) / sum(x[2] for x in hot) >= 0.950)

    hs, as_ = b["home"]["score"], b["away"]["score"]
    res = {"home": 1 if hs > as_ else 0, "away": 1 if as_ > hs else 0}
    st_ = b["start"]

    if o:
        # 1. backup goalie starts
        for side, opp in (("home", "away"), ("away", "home")):
            p, pr = ml_side(o, side)
            if F[side]["backup"] and not F[opp]["backup"]:
                bet("1a back team starting backup", season, st_, p, pr, res[side])
                bet("1b fade team starting backup (bet opp)", season, st_, 1 - p, ml_side(o, opp)[1], res[opp])
            if F[side]["backup"] and F[opp]["no1"] is not None and not F[opp]["backup"]:
                pass
        # 1c opponent starts backup and you start your No.1 -> back you (same set as 1b) -- covered.
        # 2. goalie quality gap (shrunk season-to-date sv%), both starters with >=150 SA
        if F["home"]["sa"] >= 150 and F["away"]["sa"] >= 150:
            gap = F["home"]["sv_shr"] - F["away"]["sv_shr"]
            for thr, nm in ((0.008, "2a goalie sv% gap >= .008: back better goalie"),
                            (0.015, "2b goalie sv% gap >= .015: back better goalie")):
                if abs(gap) >= thr:
                    side = "home" if gap > 0 else "away"
                    p, pr = ml_side(o, side)
                    bet(nm, season, st_, p, pr, res[side])
        # 3. favourite -1.5 at plus money, by favourite ML band
        if "home_spread" in o and abs(o["home_spread"]) == 1.5 and o["home"] != o["away"]:
            fav = "home" if o["home"] < o["away"] else "away"
            fav_sp = o["home_spread"] if fav == "home" else -o["home_spread"]
            if fav_sp == -1.5:
                fpr = o["home_spread_price"] if fav == "home" else o["away_spread_price"]
                dpr = o["away_spread_price"] if fav == "home" else o["home_spread_price"]
                if fpr > 0:
                    margin = (hs - as_) if fav == "home" else (as_ - hs)
                    p = imp(fpr) / (imp(fpr) + imp(dpr))
                    ml = o[fav]
                    band = ("-100..-149" if ml > -150 else "-150..-199" if ml > -200 else "-200 or more")
                    bet(f"3 fav -1.5 at plus money, fav ML {band}", season, st_, p, fpr, 1 if margin >= 2 else 0)
                    bet("3 fav -1.5 at plus money, all", season, st_, p, fpr, 1 if margin >= 2 else 0)
                    if ml <= -200:      # the mirror: dog +1.5 against big favourites
                        bet("3m dog +1.5 vs fav ML -200 or more (mirror)", season, st_, 1 - p, dpr, 0 if margin >= 2 else 1)
        # 4. totals
        if "total" in o:
            T = o["total"]; tot = hs + as_
            pu = imp(o["under"]) / (imp(o["under"]) + imp(o["over"]))
            r_u = None if tot == T else (1 if tot < T else 0)
            r_o = None if r_u is None else 1 - r_u
            if T in (5.5, 6.5):
                bet(f"4a under {T}", season, st_, pu, o["under"], r_u)
                bet(f"4b over {T}", season, st_, 1 - pu, o["over"], r_o)
            ph, pa = F["home"]["prev"], F["away"]["prev"]
            if ph and pa and ph["gf"] + ph["ga"] >= 8 and pa["gf"] + pa["ga"] >= 8:
                bet("4c under after both teams' last game had 8+ goals", season, st_, pu, o["under"], r_u)
            if (ph and ph["gf"] + ph["ga"] >= 9) or (pa and pa["gf"] + pa["ga"] >= 9):
                bet("4d under after either team's last game had 9+ goals", season, st_, pu, o["under"], r_u)
        # 5. overreaction
        for side, opp in (("home", "away"), ("away", "home")):
            pv = F[side]["prev"]
            if pv and pv["ga"] - pv["gf"] >= 4:
                p, pr = ml_side(o, side)
                bet("5a back team after 4+ goal loss", season, st_, p, pr, res[side])
            if F[side]["wstreak"] >= 5:
                p, pr = ml_side(o, opp)
                bet("5b fade team on 5+ game win streak", season, st_, p, pr, res[opp])
        # 6. home underdogs
        if o["home"] > o["away"]:
            p, pr = ml_side(o, "home")
            bet("6 home underdog ML", season, st_, p, pr, res["home"])
        # 7. shot share vs results
        if "ss" in F["home"] and "ss" in F["away"]:
            for side, opp in (("home", "away"), ("away", "home")):
                dss = F[side]["ss"] - F[opp]["ss"]
                dgs = F[side]["gs"] - F[opp]["gs"]
                if dss >= 0.03 and dgs <= 0:
                    p, pr = ml_side(o, side)
                    bet("7a shots favour team, results don't (dSS>=.03, dGS<=0)", season, st_, p, pr, res[side])
                if dss - dgs >= 0.10:
                    p, pr = ml_side(o, side)
                    bet("7b shot share beats goal share by >= .10", season, st_, p, pr, res[side])
        # 8. other: goalie fatigue, hot goalie
        for side, opp in (("home", "away"), ("away", "home")):
            if F[side]["g_b2b"] and not F[opp]["g_b2b"]:
                p, pr = ml_side(o, opp)
                bet("8a fade goalie starting 2nd night in a row", season, st_, p, pr, res[opp])
            if F[side]["hot3"]:
                p, pr = ml_side(o, opp)
                bet("8b fade hot goalie (last 3 starts sv>=.950)", season, st_, p, pr, res[opp])
            if F[side]["backup"] and F[side]["team_b2b"] is False and not F[opp]["backup"]:
                p, pr = ml_side(o, opp)
                bet("8c fade backup when team is NOT on a back-to-back (unexpected backup)", season, st_, p, pr, res[opp])

    # ---- update state with this game's results ----
    for side, opp in (("home", "away"), ("away", "home")):
        t, u = b[side], b[opp]
        S["team"][t["tri"]].append(dict(date=b["date"], gf=t["score"], ga=u["score"],
                                        sf=t["sog"] or 0, sa=u["sog"] or 0))
        st = info[side]["starter"]
        if st:
            S["gstarts"][t["tri"]][st] += 1
        for gk in t["goalies"]:
            if gk["sa"]:
                S["gsv"][gk["pid"]][0] += gk["sv"]; S["gsv"][gk["pid"]][1] += gk["sa"]
            if gk["starter"]:
                S["glog"][gk["pid"]].append((b["date"], gk["sv"], gk["sa"]))


# ---- report ----
def stats(rows):
    rows = [r for r in rows if r[4] is not None]
    n = len(rows)
    if not n:
        return dict(n=0, win=0, imp=0, roi=0, z=0)
    w = sum(r[4] for r in rows); e = sum(r[2] for r in rows); v = sum(r[2] * (1 - r[2]) for r in rows)
    profit = sum((dec(r[3]) - 1) if r[4] else -1 for r in rows)
    return dict(n=n, win=w / n, imp=e / n, roi=profit / n, z=(w - e) / math.sqrt(v) if v else 0)


SEAS = [2022, 2023, 2024, 2025, 2026]
out = {}
for name in sorted(bets):
    rows = bets[name]
    allr = [r for r in rows if r[0] <= 2025]
    d = dict(all=stats(allr), by={s: stats([r for r in rows if r[0] == s]) for s in SEAS},
             h1=stats([r for r in rows if r[0] in (2022, 2023)]), h2=stats([r for r in rows if r[0] in (2024, 2025)]))
    full = [d["by"][s] for s in SEAS[:4]]
    if all(x.get("n") for x in full) and all(x["roi"] > 0 for x in full) and d["h1"]["z"] >= 2.8 and d["h2"]["z"] >= 2.8:
        verdict = "ADOPTED"
    elif all(x.get("n") for x in full) and sum(x["roi"] > 0 for x in full) >= 3 and d["all"]["roi"] > 0:
        verdict = "on watch"
    else:
        verdict = "rejected"
    d["verdict"] = verdict
    out[name] = d
    a = d["all"]
    print(f"\n== {name}  [{verdict}]")
    print(f"   2022-25: n={a['n']} win {a['win']:.3f} vs imp {a['imp']:.3f}  ROI {a['roi']*100:+.1f}%  z {a['z']:+.2f}"
          f" | H1 z {d['h1']['z']:+.2f} (ROI {d['h1']['roi']*100:+.1f}%)  H2 z {d['h2']['z']:+.2f} (ROI {d['h2']['roi']*100:+.1f}%)")
    for s in SEAS:
        x = d["by"][s]
        if x.get("n"):
            print(f"   {s}-{(s+1)%100:02d}: n={x['n']:4d} win {x['win']:.3f} vs {x['imp']:.3f}  ROI {x['roi']*100:+6.1f}%  z {x['z']:+.2f}")
json.dump(out, open("results.json", "w"), indent=1)
