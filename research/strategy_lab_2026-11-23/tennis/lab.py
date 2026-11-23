"""Tennis strategy lab: every rule scored at the Pinnacle close (else market average),
season by season, 2018-2026 (2026 = Jan-Jun only). Features come from build.py
(point-in-time, earlier dates only).

Per strategy: n, win% vs no-vig implied, flat 1-unit ROI at the closing price,
z = (wins - expected)/sqrt(sum p(1-p)), per season and per chronological half.
ADOPTED : ROI > 0 in every season AND z >= 2.8 in both halves.
watch   : ROI > 0 in at least 2/3 of seasons with bets, overall ROI > 0, n >= 100
          (same "most seasons" convention as work/strategy_lab/soccer/lab.py).
rejected: everything else.
"""
import json, math, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SEASONS = list(range(2018, 2027))

s = pd.read_pickle(os.path.join(HERE, "sides.pkl"))
s = s[s.season.isin(SEASONS)].copy()
s["ret"] = np.where(s.won == 1, s.odds - 1, -1.0)

# ---------- derived pre-match features
s["fav"] = s.p > 0.5
s["log_rr"] = np.log(s.o_rank.clip(lower=1) / s["rank"].clip(lower=1))        # >0: I am better ranked
s["p_pts"] = 1 / (1 + np.exp(-(np.log(s.pts.clip(lower=1)) - np.log(s.o_pts.clip(lower=1))) * 0.8))
s["sdiff"] = s.wr_surf - s.wr_all
s["o_sdiff"] = s.o_wr_surf - s.o_wr_all
s["surf_ok"] = (s.n_surf >= 15) & (s.n_all >= 30) & (s.o_n_surf >= 15) & (s.o_n_all >= 30)
eb = (s.elo_all + s.elo_s) / 2
oeb = (s.o_elo_all + s.o_elo_s) / 2
s["p_elo"] = 1 / (1 + 10 ** ((oeb - eb) / 400))
s["elo_ok"] = (s.elo_n >= 20) & (s.o_elo_n >= 20)
s["full"] = s.last_sets >= s.last_bo        # previous match went the distance
s["rnd_early"] = s.rnd.isin([1, 2])
s["rnd_late"] = s.rnd >= 5
# absence: off-season gaps excluded (previous match Oct-Dec and this one Jan-Feb)
offseason = s.last_month.isin([10, 11, 12]) & s.date.dt.month.isin([1, 2])
s["absent60"] = (s.days >= 60) & ~offseason & (s.n_all >= 20)
s["absent120"] = (s.days >= 120) & ~offseason & (s.n_all >= 20)


def summ(d):
    n = len(d)
    if n == 0:
        return dict(n=0)
    var = float((d.p * (1 - d.p)).sum())
    return dict(n=n, win=round(100 * d.won.mean(), 2), imp=round(100 * d.p.mean(), 2),
                roi=round(100 * d.ret.mean(), 2),
                z=round(float((d.won.sum() - d.p.sum()) / math.sqrt(var)), 2) if var else 0.0)


def evaluate(name, group, d):
    d = d.sort_values("date", kind="stable")
    out = dict(name=name, group=group, all=summ(d))
    out["seasons"] = {y: summ(d[d.season == y]) for y in SEASONS}
    h = len(d) // 2
    out["half1"], out["half2"] = summ(d.iloc[:h]), summ(d.iloc[h:])
    out["split_date"] = str(d.iloc[h].date.date()) if h < len(d) else ""
    ss = [out["seasons"][y] for y in SEASONS if out["seasons"][y]["n"] > 0]
    pos = sum(1 for x in ss if x["roi"] > 0)
    out["pos_seasons"] = f"{pos}/{len(ss)}"
    z1, z2 = out["half1"].get("z", 0), out["half2"].get("z", 0)
    if len(ss) == len(SEASONS) and pos == len(ss) and z1 >= 2.8 and z2 >= 2.8:
        v = "ADOPTED"
    elif ss and pos >= math.ceil(len(ss) * 2 / 3) and out["all"].get("roi", -1) > 0 and out["all"]["n"] >= 100:
        v = "watch"
    else:
        v = "rejected"
    out["verdict"] = v
    return out


R = {}   # name -> (group, mask)


def add(group, name, mask):
    for tour in ("ATP", "WTA"):
        R[f"{tour} | {name}"] = (group, mask & (s.tour == tour))


# 1. favourite-longshot bias by price band
bands = [(1.0, 1.15), (1.15, 1.3), (1.3, 1.5), (1.5, 1.75), (1.75, 2.0), (2.0, 2.5), (2.5, 3.5), (3.5, 5), (5, 8), (8, 1000)]
for lo, hi in bands:
    add("1 price band", f"back price {lo:.2f}-{hi:.2f}", (s.odds > lo) & (s.odds <= hi))

# 2. surface specialists (prior matches only, >=15 on surface, >=30 overall, both players)
add("2 surface", "back surface specialist: my surf-minus-overall >= +10pts, opp's <= 0", s.surf_ok & (s.sdiff >= 0.10) & (s.o_sdiff <= 0))
add("2 surface", "back bigger specialist: (my - opp) surf-minus-overall >= 15pts", s.surf_ok & (s.sdiff - s.o_sdiff >= 0.15))
add("2 surface", "back bigger specialist >= 15pts AND market dog", s.surf_ok & (s.sdiff - s.o_sdiff >= 0.15) & ~s.fav)
add("2 surface", "back surface-win% leader by >= 15pts AND market dog", s.surf_ok & (s.wr_surf - s.o_wr_surf >= 0.15) & ~s.fav)
add("2 surface", "fade specialist: back opp of player with diff >= +10 vs opp <= 0", s.surf_ok & (s.o_sdiff >= 0.10) & (s.sdiff <= 0))
for surf in ("Clay", "Grass"):
    add("2 surface", f"{surf}: back bigger specialist >= 15pts", s.surf_ok & (s.surface == surf) & (s.sdiff - s.o_sdiff >= 0.15))

# 3. ranking gap against price
rk = s["rank"].notna() & s.o_rank.notna()
add("3 ranking", "back better-ranked player when he is the market dog", rk & (s.log_rr > 0) & ~s.fav)
add("3 ranking", "back better-ranked dog, rank ratio >= 2", rk & (s.log_rr >= math.log(2)) & ~s.fav)
add("3 ranking", "back worse-ranked favourite (ratio >= 2)", rk & (s.log_rr <= -math.log(2)) & s.fav)
add("3 ranking", "back much better-ranked (ratio >= 3), any price", rk & (s.log_rr >= math.log(3)))
add("3 ranking", "back much worse-ranked (ratio >= 3), any price", rk & (s.log_rr <= -math.log(3)))
add("3 ranking", "board points model (0.8 ln pts) edge >= 5pts over close", s.pts.notna() & s.o_pts.notna() & (s.p_pts - s.p >= 0.05))
add("3 ranking", "board points model edge >= 10pts over close", s.pts.notna() & s.o_pts.notna() & (s.p_pts - s.p >= 0.10))

# 4. fatigue (opponent-side bets: back the fresher player)
add("4 fatigue", "back opp of player who played yesterday, opp rested >= 2 days", (s.o_days == 1) & (s.days >= 2))
add("4 fatigue", "back opp of player whose last match went the distance <=2 days ago; mine straight sets",
    (s.o_days <= 2) & (s.o_last_sets >= s.o_last_bo) & (s.last_sets < s.last_bo) & (s.days <= 3))
add("4 fatigue", "back opp of player off a 5-setter (<=3 days), mine not 5 sets",
    (s.o_days <= 3) & (s.o_last_sets == 5) & (s.last_sets <= 4) & (s.days <= 3))
add("4 fatigue", "back opp of player whose last match >= 30 games yesterday, mine <= 22",
    (s.o_days == 1) & (s.o_last_games >= 30) & (s.last_games <= 22) & (s.bo == 3))
add("4 fatigue", "back fresher: opp's 14-day games >= mine + 40", s.o_load14 >= s.load14 + 40)
add("4 fatigue", "back the tired one (contrarian): played yesterday vs opp rested >= 2", (s.days == 1) & (s.o_days >= 2))

# 5. round, tier, best-of
for tier in ("GS", "1000", "500", "250"):
    for rn, rm in (("early (R1-R2)", s.rnd_early), ("late (QF+)", s.rnd_late)):
        add("5 round/tier", f"{tier} {rn}: favourite", (s.tier == tier) & rm & s.fav)
        add("5 round/tier", f"{tier} {rn}: underdog", (s.tier == tier) & rm & ~s.fav)
add("5 round/tier", "best-of-5: favourite priced <= 1.50", (s.bo == 5) & (s.odds <= 1.5))
add("5 round/tier", "best-of-5: favourite priced 1.50-2.00", (s.bo == 5) & (s.odds > 1.5) & s.fav)
add("5 round/tier", "best-of-5: underdog priced 2.0-4.0", (s.bo == 5) & (s.odds >= 2.0) & (s.odds <= 4.0))
add("5 round/tier", "finals: underdog", (s.rnd == 7) & ~s.fav)

# 6. return from long absence

# 7. home country
add("7 home", "back home player vs non-home player", (s.home == 1) & (s.o_home == 0) & s.o_ioc.notna())
add("7 home", "back home underdog", (s.home == 1) & (s.o_home == 0) & s.o_ioc.notna() & ~s.fav)
add("7 home", "back home favourite", (s.home == 1) & (s.o_home == 0) & s.o_ioc.notna() & s.fav)
add("7 home", "back home player in R1-R2 (wildcard-ish), rank > 100", (s.home == 1) & (s.o_home == 0) & s.rnd_early & (s["rank"] > 100))
add("7 home", "fade home player: back away opp", (s.o_home == 1) & (s.home == 0) & s.ioc.notna())

# 8. Elo blend with the close (surface-blended 538 Elo, warm-up 2015-17)
for w in (0.1, 0.2, 0.3):
    for thr in (0.0, 0.03):
        pb = (1 - w) * s.p + w * s.p_elo
        add("8 elo", f"Elo blend w={w}: bet if blended EV > {thr:.2f}", s.elo_ok & (pb * s.odds - 1 > thr))
add("8 elo", "Elo minus close >= 10pts", s.elo_ok & (s.p_elo - s.p >= 0.10))
add("8 elo", "Elo minus close >= 10pts, price <= 2.5", s.elo_ok & (s.p_elo - s.p >= 0.10) & (s.odds <= 2.5))

# 9. other
add("9 other", "fade last week's champion (won a final <= 9 days ago)", (s.o_last_final_win == 1) & (s.o_days <= 9))
add("9 other", "back last week's champion", (s.last_final_win == 1) & (s.days <= 9))
add("9 other", "fade player who retired in previous match (<= 30 days)", (s.o_last_ret_self == 1) & (s.o_days <= 30))
add("9 other", "B365 rates me >= 3pts above Pinnacle: back at Pinnacle", (s.src == "PS") & (s.pb365 - s.p >= 0.03))
add("9 other", "B365 rates me >= 3pts below Pinnacle: back at Pinnacle", (s.src == "PS") & (s.p - s.pb365 >= 0.03))
add("9 other", "left-hander vs right-hander", (s.hand == "L") & (s.o_hand == "R"))
add("9 other", "left-hander vs right-hander on grass", (s.hand == "L") & (s.o_hand == "R") & (s.surface == "Grass"))
add("9 other", "debutant-ish: back opp of player with < 5 prior tour matches", (s.o_n_all < 5) & (s.n_all >= 30))

# absence (needs opponent copies of absent flags)
amap60 = dict(zip(zip(s.mid, s.player), s.absent60))
amap120 = dict(zip(zip(s.mid, s.player), s.absent120))
s["o_absent60"] = [amap60.get((m, o), False) for m, o in zip(s.mid, s.opp)]
s["o_absent120"] = [amap120.get((m, o), False) for m, o in zip(s.mid, s.opp)]
add("6 absence", "fade player back from >= 60 days out (back opp)", s.o_absent60 & ~s.absent60)
add("6 absence", "fade player back from >= 120 days out (back opp)", s.o_absent120 & ~s.absent60)
add("6 absence", "back player back from >= 60 days out", s.absent60 & ~s.o_absent60)
add("6 absence", "fade returner >= 60 days who is the favourite", s.o_absent60 & ~s.absent60 & ~s.fav)
add("6 absence", "fade returner >= 60 days, returner rank <= 50", s.o_absent60 & ~s.absent60 & (s.o_rank <= 50))

res = []
for name, (group, mask) in R.items():
    d = s[mask.values if hasattr(mask, "values") else mask]
    if len(d) == 0:
        continue
    res.append(evaluate(name, group, d))

order = {"ADOPTED": 0, "watch": 1, "rejected": 2}
res.sort(key=lambda r: (r["group"], r["name"]))
json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=str)
lines = ["%-12s %-78s %6s %6s %6s %7s | ROI%% by season %s | z h1 h2 | +seas verdict" % (
    "group", "strategy", "n", "win%", "imp%", "ROI%", " ".join(str(y)[2:] for y in SEASONS))]
for r in res:
    a = r["all"]
    roi = " ".join(("%5.1f" % r["seasons"][y]["roi"]) if r["seasons"][y]["n"] else "  .  " for y in SEASONS)
    lines.append("%-12s %-78s %6d %6.2f %6.2f %7.2f | %s | %5.2f %5.2f | %s %s" % (
        r["group"], r["name"][:78], a["n"], a["win"], a["imp"], a["roi"], roi,
        r["half1"].get("z", 0), r["half2"].get("z", 0), r["pos_seasons"], r["verdict"]))
open(os.path.join(HERE, "results.txt"), "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
from collections import Counter
print(Counter(r["verdict"] for r in res), len(res), "rules")
