"""Soccer strategy lab: pre-match rules tested against real closing prices.

Data: football-data.co.uk season CSVs (data/*.csv, downloaded 2026-11-23).
Price: Pinnacle closing odds where all legs are present, else market-average
closing odds.  Implied chance = proportional de-vig of the same book's close.
Every feature (form, scoring, rest, promotion) uses matches dated strictly
before the match being bet.  League-selection rules are walk-forward: a league
is chosen for season s only from seasons before s.

    python3 -I lab.py            # writes results.json, results.txt
"""
import csv
import glob
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
PRICE = os.environ.get("PRICE", "pinnacle")
SEASONS = ["1920", "2021", "2122", "2223", "2324", "2425", "2526"]

BIG5 = {"E0", "D1", "SP1", "I1", "F1"}
T1O = {"N1", "B1", "P1", "T1", "G1", "SC0"}
T2 = {"E1", "D2", "SP2", "I2", "F2", "SC1", "SWZ-Challenge League"}
T3 = {"E2", "E3", "EC", "SC2", "SC3"}


def tier(lg):
    if lg in BIG5:
        return "T1-big5"
    if lg in T2:
        return "T2"
    if lg in T3:
        return "T3"
    return "T1-other"


def fl(x):
    try:
        v = float(x)
        return v if v > 1.0 else None
    except (TypeError, ValueError):
        return None


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def pdate(s):
    for f in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s.strip(), f)
        except ValueError:
            pass
    return None


def three(r, keys):
    o = [fl(r.get(k)) for k in keys]
    return o if all(o) else None


def build(r, lg, season, home, away, hg, ag, d):
    if d is None or hg is None or ag is None or not home or not away:
        return None
    ps = three(r, ("PSCH", "PSCD", "PSCA"))
    av = three(r, ("AvgCH", "AvgCD", "AvgCA"))
    if PRICE == "avg":
        ps = None                      # sensitivity: market-average close everywhere
    o, src = (ps, "P") if ps else (av, "A")
    m = dict(lg=lg, tier=tier(lg), season=season, date=d, home=home.strip(),
             away=away.strip(), hg=int(hg), ag=int(ag))
    if o:
        inv = [1 / x for x in o]
        s = sum(inv)
        m.update(o=o, p=[x / s for x in inv], src=src, over=s - 1)
    # opening Pinnacle (for steam)
    op = three(r, ("PSH", "PSD", "PSA"))
    if op and ps:
        m["open"] = op
    mx = three(r, ("MaxCH", "MaxCD", "MaxCA"))
    if mx and ps:
        m["max"] = mx
    # over/under 2.5
    ou = [fl(r.get("PC>2.5")), fl(r.get("PC<2.5"))]
    if not all(ou):
        ou = [fl(r.get("AvgC>2.5")), fl(r.get("AvgC<2.5"))]
    if all(ou):
        inv = [1 / x for x in ou]
        m["ou"] = ou
        m["oup"] = [x / sum(inv) for x in inv]
    # asian handicap (home line)
    line = num(r.get("AHCh"))
    ah = [fl(r.get("PCAHH")), fl(r.get("PCAHA"))]
    if not all(ah):
        ah = [fl(r.get("AvgCAHH")), fl(r.get("AvgCAHA"))]
    if line is not None and all(ah):
        inv = [1 / x for x in ah]
        m["ahl"] = line
        m["ah"] = ah
        m["ahp"] = [x / sum(inv) for x in inv]
    return m


def season_of_new(s):
    s = s.strip()
    if "/" in s:
        a, b = s.split("/")
        return a[2:] + b[2:]
    y = int(s)                         # calendar season Y -> (Y-1)/Y slot
    return "%02d%02d" % ((y - 1) % 100, y % 100)


def load():
    ms = []
    for f in glob.glob(os.path.join(DATA, "*_*.csv")):
        b = os.path.basename(f)
        if b.startswith("new_"):
            continue
        lg, s = b[:-4].split("_")
        with open(f, encoding="latin-1") as fh:
            for r in csv.DictReader(fh):
                m = build(r, lg, s, r.get("HomeTeam"), r.get("AwayTeam"),
                          num(r.get("FTHG")), num(r.get("FTAG")), pdate(r.get("Date") or ""))
                if m:
                    ms.append(m)
    for f in glob.glob(os.path.join(DATA, "new_*.csv")):
        c = os.path.basename(f)[4:-4]
        with open(f, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if (r.get("League") or "").strip() == "Copa De La Liga Profesional":
                    continue
                lg = "SWZ-Challenge League" if "Challenge" in (r.get("League") or "") else c
                try:
                    s = season_of_new(r["Season"])
                except (ValueError, KeyError):
                    continue
                m = build(r, lg, s, r.get("Home"), r.get("Away"), num(r.get("HG")),
                          num(r.get("AG")), pdate(r.get("Date") or ""))
                if m:
                    ms.append(m)
    ms.sort(key=lambda m: (m["date"], m["lg"], m["home"]))
    return ms


def features(ms):
    """Prior-match-only features per team within league-season."""
    hist = defaultdict(list)          # (lg, season, team) -> list of (date, gf, ga)
    teams = defaultdict(set)          # (lg, season) -> teams
    last_date = {}
    for m in ms:
        teams[(m["lg"], m["season"])].update((m["home"], m["away"]))
        k = (m["lg"], m["season"])
        last_date[k] = max(last_date.get(k, m["date"]), m["date"])
    lg_seasons = defaultdict(list)
    for (lg, s) in teams:
        lg_seasons[lg].append(s)
    prev_season = {}
    for lg, ss in lg_seasons.items():
        ss.sort()
        for a, b in zip(ss, ss[1:]):
            if int(b[:2]) == int(a[:2]) + 1:
                prev_season[(lg, b)] = a
    for m in ms:
        k = (m["lg"], m["season"])
        m["days_to_end"] = (last_date[k] - m["date"]).days
        ps = prev_season.get(k)
        for side, t, gf, ga in (("h", m["home"], m["hg"], m["ag"]), ("a", m["away"], m["ag"], m["hg"])):
            h = hist[(m["lg"], m["season"], t)]
            m[side + "_n"] = len(h)
            if h:
                m[side + "_rest"] = (m["date"] - h[-1][0]).days
                m[side + "_lastmargin"] = h[-1][1] - h[-1][2]
                m[side + "_tot"] = sum(x[1] + x[2] for x in h) / len(h)
                m[side + "_drawrate"] = sum(x[1] == x[2] for x in h) / len(h)
            m[side + "_promoted"] = (ps is not None and t not in teams[(m["lg"], ps)])
        hist[(m["lg"], m["season"], m["home"])].append((m["date"], m["hg"], m["ag"]))
        hist[(m["lg"], m["season"], m["away"])].append((m["date"], m["ag"], m["hg"]))
    return ms


# ---------------------------------------------------------------- bet makers
# A bet: dict(date, season, lg, parts=[(weight, p, odds, s)]) where s is 1/0
# for each part (pushes dropped).  Return per part: weight*(odds-1) or -weight.

def x12(m, i):
    """Back outcome i (0 home, 1 draw, 2 away) at the close."""
    s = int((i == 0 and m["hg"] > m["ag"]) or (i == 1 and m["hg"] == m["ag"]) or (i == 2 and m["hg"] < m["ag"]))
    return dict(parts=[(1.0, m["p"][i], m["o"][i], s)])


def dc(m, i, j):
    """Double chance by dutching the two 1X2 closing legs (exactly placeable)."""
    o = 1 / (1 / m["o"][i] + 1 / m["o"][j])
    p = m["p"][i] + m["p"][j]
    r = 0 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 2)
    return dict(parts=[(1.0, p, o, int(r in (i, j)))])


def ou(m, over):
    k = 0 if over else 1
    tot = m["hg"] + m["ag"]
    s = int(tot > 2.5) if over else int(tot < 2.5)
    return dict(parts=[(1.0, m["oup"][k], m["ou"][k], s)])


def ah(m, home):
    line = m["ahl"] if home else -m["ahl"]
    margin = (m["hg"] - m["ag"]) if home else (m["ag"] - m["hg"])
    k = 0 if home else 1
    q = round(line * 4) % 2 == 1          # quarter line -> split stake
    lines = [line - 0.25, line + 0.25] if q else [line]
    parts = []
    for ln in lines:
        v = margin + ln
        if abs(v) < 1e-9:
            continue                       # push: that half returns stake
        parts.append((1.0 / len(lines), m["ahp"][k], m["ah"][k], int(v > 0)))
    return dict(parts=parts) if parts else None


def mk(m, b):
    if b is None:
        return None
    b.update(date=m["date"], season=m["season"], lg=m["lg"])
    return b


# ---------------------------------------------------------------- evaluation

def summ(bets):
    n = len(bets)
    W = sum(w for b in bets for w, p, o, s in b["parts"])
    if not W:
        return dict(n=n)
    win = sum(w * s for b in bets for w, p, o, s in b["parts"])
    exp = sum(w * p for b in bets for w, p, o, s in b["parts"])
    var = sum(w * w * p * (1 - p) for b in bets for w, p, o, s in b["parts"])
    ret = sum((w * (o - 1) if s else -w) for b in bets for w, p, o, s in b["parts"])
    stake = len([1 for b in bets])           # each bet one unit staked
    return dict(n=n, win=round(100 * win / W, 2), imp=round(100 * exp / W, 2),
                roi=round(100 * ret / stake, 2), z=round((win - exp) / math.sqrt(var), 2) if var else 0)


def evaluate(name, bets, group=""):
    bets = [b for b in bets if b and b["season"] in SEASONS]
    bets.sort(key=lambda b: b["date"])
    out = dict(name=name, group=group, all=summ(bets))
    out["seasons"] = {s: summ([b for b in bets if b["season"] == s]) for s in SEASONS}
    h = len(bets) // 2
    out["half1"], out["half2"] = summ(bets[:h]), summ(bets[h:])
    if bets:
        out["split_date"] = bets[h]["date"].strftime("%Y-%m-%d") if h < len(bets) else ""
    ss = [out["seasons"][s] for s in SEASONS if out["seasons"][s]["n"] > 0]
    pos = sum(1 for x in ss if x.get("roi", -1) > 0)
    out["pos_seasons"] = "%d/%d" % (pos, len(ss))
    z1, z2 = out["half1"].get("z", 0), out["half2"].get("z", 0)
    if len(ss) == len(SEASONS) and pos == len(ss) and z1 >= 2.8 and z2 >= 2.8:
        v = "ADOPTED"
    elif ss and pos >= math.ceil(len(ss) * 2 / 3) and out["all"].get("roi", -1) > 0 and len(ss) >= 5 and out["all"]["n"] >= 100:
        v = "watch"
    else:
        v = "rejected"
    out["verdict"] = v
    return out


# ---------------------------------------------------------------- strategies

def walk_forward(ms, cands, maker, min_prior=150):
    """cands: key(m) -> group key (e.g. league). For each season, bet the groups
    whose pooled ROI over all PRIOR seasons (from 1819 on) is > 0 with
    >= min_prior bets.  maker(m) -> bet or None."""
    allb = defaultdict(lambda: defaultdict(list))   # group -> season -> rets
    for m in ms:
        b = maker(m)
        if b:
            g = cands(m)
            b = mk(m, b)
            allb[g][m["season"]].append(b)
    out = []
    order = sorted({s for g in allb for s in allb[g]})
    for g, bys in allb.items():
        for s in SEASONS:
            prior = [b for s2 in order if s2 < s for b in bys.get(s2, [])]
            if len(prior) < min_prior:
                continue
            r = sum((w * (o - 1) if x else -w) for b in prior for w, p, o, x in b["parts"])
            if r > 0:
                out.extend(bys.get(s, []))
    return out


def run():
    ms = features(load())
    odds = [m for m in ms if "o" in m]
    R = []

    def add(name, group, pred, maker):
        R.append(evaluate(name, [mk(m, maker(m)) for m in odds if pred(m)], group))

    fav = lambda m: 0 if m["p"][0] >= m["p"][2] else 2
    dog = lambda m: 2 if m["p"][0] >= m["p"][2] else 0
    tiers = ["T1-big5", "T1-other", "T2", "T3"]

    # 1. favourite-longshot
    for t in tiers + ["all"]:
        tp = (lambda m, t=t: t == "all" or m["tier"] == t)
        for lo, hi in ((0.65, 0.75), (0.75, 0.85), (0.85, 1.01), (0.65, 1.01)):
            add("Fav win %d-%d%% [%s]" % (lo * 100, min(hi, 1) * 100, t), "1 FLB",
                lambda m, lo=lo, hi=hi, tp=tp: tp(m) and lo <= m["p"][fav(m)] < hi, lambda m: x12(m, fav(m)))
        for lo, hi in ((0.0, 0.10), (0.10, 0.15), (0.15, 0.25)):
            add("Longshot win %d-%d%% [%s]" % (lo * 100, hi * 100, t), "1 FLB",
                lambda m, lo=lo, hi=hi, tp=tp: tp(m) and lo <= m["p"][dog(m)] < hi, lambda m: x12(m, dog(m)))

    # 2. draws
    for t in tiers + ["all"]:
        tp = (lambda m, t=t: t == "all" or m["tier"] == t)
        add("Draw all [%s]" % t, "2 Draw", tp, lambda m: x12(m, 1))
        for lo, hi in ((0, 0.22), (0.22, 0.26), (0.26, 0.29), (0.29, 0.32), (0.32, 1)):
            add("Draw p %d-%d%% [%s]" % (lo * 100, hi * 100, t), "2 Draw",
                lambda m, lo=lo, hi=hi, tp=tp: tp(m) and lo <= m["p"][1] < hi, lambda m: x12(m, 1))
        add("Draw evenly matched |pH-pA|<0.08 [%s]" % t, "2 Draw",
            lambda m, tp=tp: tp(m) and abs(m["p"][0] - m["p"][2]) < 0.08, lambda m: x12(m, 1))
    add("Draw when draw is the shortest price", "2 Draw",
        lambda m: m["o"][1] < min(m["o"][0], m["o"][2]), lambda m: x12(m, 1))
    add("Draw, both teams >=35% draws season-to-date (8+ games)", "2 Draw",
        lambda m: m["h_n"] >= 8 and m["a_n"] >= 8 and m.get("h_drawrate", 0) >= .35 and m.get("a_drawrate", 0) >= .35,
        lambda m: x12(m, 1))
    for lg in sorted({m["lg"] for m in odds}):
        add("Draw league %s" % lg, "2 Draw by league", lambda m, lg=lg: m["lg"] == lg, lambda m: x12(m, 1))
    R.append(evaluate("Draw, walk-forward leagues (prior-season draw ROI>0)", walk_forward(
        odds, lambda m: m["lg"], lambda m: x12(m, 1)), "2 Draw"))

    # 3. win-or-draw (double chance)
    for t in tiers + ["all"]:
        tp = (lambda m, t=t: t == "all" or m["tier"] == t)
        for lo, hi in ((0.60, 0.70), (0.70, 0.80), (0.80, 0.88), (0.88, 1.01)):
            add("Fav-or-draw %d-%d%% [%s]" % (lo * 100, min(hi, 1) * 100, t), "3 Win-or-draw",
                lambda m, lo=lo, hi=hi, tp=tp: tp(m) and lo <= m["p"][fav(m)] + m["p"][1] < hi,
                lambda m: dc(m, fav(m), 1))
        add("Dog-or-draw (any) [%s]" % t, "3 Win-or-draw", tp, lambda m: dc(m, dog(m), 1))
        add("Home-or-draw [%s]" % t, "3 Win-or-draw", tp, lambda m: dc(m, 0, 1))
        add("Away-or-draw [%s]" % t, "3 Win-or-draw", tp, lambda m: dc(m, 2, 1))
    R.append(evaluate("Fav-or-draw, walk-forward leagues", walk_forward(
        odds, lambda m: m["lg"], lambda m: dc(m, fav(m), 1)), "3 Win-or-draw"))
    R.append(evaluate("Dog-or-draw, walk-forward leagues", walk_forward(
        odds, lambda m: m["lg"], lambda m: dc(m, dog(m), 1)), "3 Win-or-draw"))

    # 4. home / away
    for t in tiers + ["all"]:
        tp = (lambda m, t=t: t == "all" or m["tier"] == t)
        add("Home win [%s]" % t, "4 Home/away", tp, lambda m: x12(m, 0))
        add("Away win [%s]" % t, "4 Home/away", tp, lambda m: x12(m, 2))
    for lg in sorted({m["lg"] for m in odds}):
        add("Home win league %s" % lg, "4 Home by league", lambda m, lg=lg: m["lg"] == lg, lambda m: x12(m, 0))
        add("Away win league %s" % lg, "4 Away by league", lambda m, lg=lg: m["lg"] == lg, lambda m: x12(m, 2))
    R.append(evaluate("Home win, walk-forward leagues", walk_forward(odds, lambda m: m["lg"], lambda m: x12(m, 0)), "4 Home/away"))
    R.append(evaluate("Away win, walk-forward leagues", walk_forward(odds, lambda m: m["lg"], lambda m: x12(m, 2)), "4 Home/away"))

    # 5. over / under 2.5
    oum = [m for m in odds if "ou" in m]

    def addou(name, pred, over):
        R.append(evaluate(name, [mk(m, ou(m, over)) for m in oum if pred(m)], "5 Over/under"))
    for t in tiers + ["all"]:
        tp = (lambda m, t=t: t == "all" or m["tier"] == t)
        addou("Over 2.5 [%s]" % t, tp, True)
        addou("Under 2.5 [%s]" % t, tp, False)
    for lg in sorted({m["lg"] for m in oum}):
        addou("Over 2.5 league %s" % lg, lambda m, lg=lg: m["lg"] == lg, True)
        addou("Under 2.5 league %s" % lg, lambda m, lg=lg: m["lg"] == lg, False)
    ok = lambda m: m["h_n"] >= 5 and m["a_n"] >= 5
    comb = lambda m: (m["h_tot"] + m["a_tot"]) / 2
    addou("Over: teams' season-to-date match goals avg >= 3.2", lambda m: ok(m) and comb(m) >= 3.2, True)
    addou("Over: avg >= 3.2 and market over < 55%", lambda m: ok(m) and comb(m) >= 3.2 and m["oup"][0] < .55, True)
    addou("Under: teams' season-to-date avg <= 2.2", lambda m: ok(m) and comb(m) <= 2.2, False)
    addou("Under: avg <= 2.2 and market under < 50%", lambda m: ok(m) and comb(m) <= 2.2 and m["oup"][1] < .50, False)
    addou("Over: market over 2.5 < 45% (long over)", lambda m: m["oup"][0] < .45, True)
    addou("Under: market under 2.5 < 40% (long under)", lambda m: m["oup"][1] < .40, False)
    R.append(evaluate("Under 2.5, walk-forward leagues", walk_forward(oum, lambda m: m["lg"], lambda m: ou(m, False)), "5 Over/under"))
    R.append(evaluate("Over 2.5, walk-forward leagues", walk_forward(oum, lambda m: m["lg"], lambda m: ou(m, True)), "5 Over/under"))

    # 6. asian handicap
    ahm = [m for m in odds if "ah" in m]

    def addah(name, pred, side, group="6 Asian handicap"):
        R.append(evaluate(name, [mk(m, ah(m, side(m))) for m in ahm if pred(m)], group))
    afav = lambda m: m["ahl"] < 0            # home gives goals -> home is fav
    for t in tiers + ["all"]:
        tp = (lambda m, t=t: t == "all" or m["tier"] == t)
        addah("AH favourite [%s]" % t, lambda m, tp=tp: tp(m) and m["ahl"] != 0, lambda m: afav(m))
        addah("AH underdog [%s]" % t, lambda m, tp=tp: tp(m) and m["ahl"] != 0, lambda m: not afav(m))
        addah("AH home [%s]" % t, tp, lambda m: True)
        addah("AH away [%s]" % t, tp, lambda m: False)
    for lo, hi in ((0.25, 0.75), (0.75, 1.25), (1.25, 1.75), (1.75, 9)):
        pr = lambda m, lo=lo, hi=hi: lo <= abs(m["ahl"]) < hi
        addah("AH favourite giving %.2f-%.2f" % (lo, hi), pr, lambda m: afav(m))
        addah("AH underdog getting %.2f-%.2f" % (lo, hi), pr, lambda m: not afav(m))

    # 7. after heavy loss; congestion
    for side, idx, nm in (("h", 0, "home"), ("a", 2, "away")):
        hl = lambda m, side=side: m.get(side + "_lastmargin", 0) <= -3
        add("Back %s team after 3+ goal loss (1X2)" % nm, "7 Heavy loss", hl, lambda m, idx=idx: x12(m, idx))
        add("Fade %s team after 3+ goal loss (opp or draw)" % nm, "7 Heavy loss", hl,
            lambda m, idx=idx: dc(m, 2 - idx, 1))
        addah("Back %s team after 3+ goal loss (AH)" % nm, hl, lambda m, idx=idx: idx == 0, "7 Heavy loss")
    hlany = lambda m: (m.get("h_lastmargin", 0) <= -3) != (m.get("a_lastmargin", 0) <= -3)
    lost = lambda m: 0 if m.get("h_lastmargin", 0) <= -3 else 2
    add("Back team after 3+ goal loss (either side)", "7 Heavy loss", hlany, lambda m: x12(m, lost(m)))
    addah("Back team after 3+ goal loss, AH (either side)", hlany, lambda m: lost(m) == 0, "7 Heavy loss")
    addah("Fade team after 3+ goal win, AH", lambda m: (m.get("h_lastmargin", 0) >= 3) != (m.get("a_lastmargin", 0) >= 3),
          lambda m: m.get("h_lastmargin", 0) < 3, "7 Heavy loss")
    for d in (3, 4):
        cong = lambda m, d=d: ((m.get("h_rest", 99) <= d and m.get("a_rest", 0) >= 6) or
                               (m.get("a_rest", 99) <= d and m.get("h_rest", 0) >= 6))
        rested = lambda m, d=d: 2 if m.get("h_rest", 99) <= d else 0
        add("Back rested team vs team on <=%d days (1X2)" % d, "7 Congestion", cong, lambda m, r=rested: x12(m, r(m)))
        addah("Back rested team vs team on <=%d days (AH)" % d, cong, lambda m, r=rested: r(m) == 0, "7 Congestion")
        add("Rested team or draw vs <=%d days" % d, "7 Congestion", cong, lambda m, r=rested: dc(m, r(m), 1))
    add("Congested favourite (<=3 days) to win", "7 Congestion",
        lambda m: m.get(("h" if fav(m) == 0 else "a") + "_rest", 99) <= 3, lambda m: x12(m, fav(m)))

    # 8. promoted, late season
    pro = lambda m: (m["h_promoted"] and m["h_n"] < 6) != (m["a_promoted"] and m["a_n"] < 6)
    pside = lambda m: 0 if (m["h_promoted"] and m["h_n"] < 6) else 2
    add("Back promoted team, first 6 matches (1X2)", "8 Promoted", pro, lambda m: x12(m, pside(m)))
    add("Promoted team or draw, first 6", "8 Promoted", pro, lambda m: dc(m, pside(m), 1))
    add("Opponent of promoted team, first 6 (1X2)", "8 Promoted", pro, lambda m: x12(m, 2 - pside(m)))
    addah("Back promoted team, first 6 (AH)", pro, lambda m: pside(m) == 0, "8 Promoted")
    addah("Opponent of promoted team, first 6 (AH)", pro, lambda m: pside(m) != 0, "8 Promoted")
    late = lambda m: m["days_to_end"] <= 28 and m["h_n"] >= 15
    add("Late season (last 4 weeks): draw", "8 Late season", late, lambda m: x12(m, 1))
    add("Late season: favourite win", "8 Late season", late, lambda m: x12(m, fav(m)))
    add("Late season: underdog win", "8 Late season", late, lambda m: x12(m, dog(m)))
    add("Late season: home win", "8 Late season", late, lambda m: x12(m, 0))
    addou("Late season: over 2.5", lambda m: late(m), True)
    addou("Late season: under 2.5", lambda m: late(m), False)
    addah("Late season: AH underdog", lambda m: late(m) and m["ahl"] != 0, lambda m: not afav(m), "8 Late season")
    early = lambda m: m["h_n"] < 3 and m["a_n"] < 3
    add("Opening 3 rounds: underdog win", "8 Early season", early, lambda m: x12(m, dog(m)))
    add("Opening 3 rounds: draw", "8 Early season", early, lambda m: x12(m, 1))

    # 9. other: steam (Pinnacle open -> close), best-price value
    st = [m for m in odds if "open" in m]
    for thr in (0.06, 0.10):
        for nm, sel in (("shortened", lambda m, i, thr: m["open"][i] / m["o"][i] - 1 >= thr),
                        ("drifted", lambda m, i, thr: m["o"][i] / m["open"][i] - 1 >= thr)):
            bets = []
            for m in st:
                for i in (0, 2):
                    if sel(m, i, thr):
                        bets.append(mk(m, x12(m, i)))
            R.append(evaluate("Back side whose Pinnacle price %s %d%%+ open->close" % (nm, thr * 100), bets, "9 Line move"))
    bets = []
    for m in [m for m in odds if "max" in m]:
        for i in range(3):
            if m["max"][i] * m["p"][i] > 1.03 and m["max"][i] < 10:
                b = x12(m, i)
                b["parts"] = [(1.0, m["p"][i], m["max"][i], b["parts"][0][3])]
                bets.append(mk(m, b))
    R.append(evaluate("Best market close beats Pinnacle no-vig by 3%+ (paid at Max close)", bets, "9 Best price"))
    return ms, R


def fmt(r):
    a = r["all"]
    if not a.get("win") and a.get("win") != 0:
        return "%-70s n=0" % r["name"]
    ss = " ".join("%6s" % ("%+.1f" % r["seasons"][s]["roi"] if r["seasons"][s].get("n") else "-") for s in SEASONS)
    return "%-70s %6d %5.1f/%5.1f %+6.2f | %s | z %+5.2f %+5.2f | %s %s" % (
        r["name"][:70], a["n"], a["win"], a["imp"], a["roi"], ss,
        r["half1"].get("z", 0), r["half2"].get("z", 0), r["pos_seasons"], r["verdict"])


if __name__ == "__main__":
    ms, R = run()
    src = defaultdict(lambda: [0, 0])
    for m in ms:
        if "o" in m and m["season"] in SEASONS:
            src[m["season"]][m["src"] == "P"] += 1
    lines = ["Matches with 1X2 close by season (avg-close, pinnacle-close): " +
             ", ".join("%s %d/%d" % (s, *src[s]) for s in SEASONS),
             "Leagues: " + " ".join(sorted({m["lg"] for m in ms})), "",
             "%-70s %6s %11s %6s | ROI%% by season %s | z half1 half2 | +seasons verdict" % (
                 "strategy", "n", "win/imp%", "ROI%", " ".join(SEASONS))]
    g0 = None
    for r in R:
        if r["group"] != g0:
            lines.append("\n== " + r["group"])
            g0 = r["group"]
        lines.append(fmt(r))
    lines.append("\nVerdicts: " + str({v: sum(r["verdict"] == v for r in R) for v in ("ADOPTED", "watch", "rejected")}))
    sfx = "" if PRICE == "pinnacle" else "_" + PRICE
    open(os.path.join(HERE, "results%s.txt" % sfx), "w").write("\n".join(lines) + "\n")
    json.dump(R, open(os.path.join(HERE, "results%s.json" % sfx), "w"), indent=1, default=str)
    print("\n".join(lines))
