"""Strategies 3 (role/usage), 7 (last-5 at the line, prior games only), and a
cluster-level same-player check, using ESPN box scores in ./cache."""
import collections, json, math, os, sys, statistics
from common import *
sys.path.insert(0, ROOT)
import props_ledger as PL          # read-only use: box_stats, resolve, MARKETS, won
C = os.path.join(HERE, "cache")
g = [e for e in load_graded() if e["league"] in ("nba", "nhl", "nfl")]

def mins(s):
    try:
        if ":" in str(s):
            a, b = str(s).split(":"); return int(a) + int(b) / 60
        return float(s)
    except (TypeError, ValueError):
        return None

GAMES = {}     # gid -> dict(start, out(box_stats), role{aid:{...}})
for f in os.listdir(C):
    if f.startswith("sb-"): continue
    lg, eid = f[:-5].split("-", 1)
    sm = json.load(open(os.path.join(C, f)))
    try:
        comp = sm["header"]["competitions"][0]
        if not comp.get("status", {}).get("type", {}).get("completed", True):
            continue
        start = comp["date"]
    except (KeyError, IndexError):
        continue
    out = PL.box_stats(sm)
    role = {}
    for team in (sm.get("boxscore") or {}).get("players") or []:
        for grp in team.get("statistics") or []:
            keys = grp.get("keys") or []
            for a in grp.get("athletes") or []:
                aid = str((a.get("athlete") or {}).get("id") or "")
                if not aid: continue
                r = role.setdefault(aid, {"grp": set()})
                r["grp"].add(grp.get("name"))
                if a.get("starter") is not None: r["starter"] = bool(a.get("starter"))
                if a.get("didNotPlay"): r["dnp"] = True
                st = dict(zip(keys, a.get("stats") or []))
                if lg == "nba": r["min"] = mins(st.get("minutes"))
                if lg == "nhl" and "timeOnIce" in st: r["min"] = mins(st.get("timeOnIce"))
                if lg == "nfl":
                    if "receivingTargets" in st: r["tgt"] = mins(st["receivingTargets"])
                    if "rushingAttempts" in st: r["car"] = mins(st["rushingAttempts"])
    GAMES[f"{lg}:{eid}"] = dict(lg=lg, start=start, out=out, role=role)

def played(lg, r):
    if r.get("dnp"): return False
    if lg in ("nba", "nhl"): return (r.get("min") or 0) > 0
    return True

HIST = collections.defaultdict(list)      # (lg, aid) -> [(start, gid)]
for gid, G in GAMES.items():
    for aid, r in G["role"].items():
        if played(G["lg"], r): HIST[(G["lg"], aid)].append((G["start"], gid))
for v in HIST.values(): v.sort()

rows, miss = [], collections.Counter()
for e in g:
    G = GAMES.get(e["gid"])
    if not G: miss["no box"] += 1; continue
    st, how = PL.resolve(G["out"], e)
    if st is None: miss["unresolved"] += 1; continue
    aid = next((k for k, v in G["out"].items() if v is st and not k.startswith(("name:", "_"))), None)
    if aid is None: miss["no aid"] += 1; continue
    f = PL.MARKETS[e["league"]].get(e["market"])
    prior = [(s, gg) for s, gg in HIST[(e["league"], aid)] if s < G["start"]]
    vals = []
    for s, gg in prior:
        v = f(GAMES[gg]["out"].get(aid) or {})
        if v is not None:
            vals.append((PL.won(e["league"], e["market"], e["line"], v), GAMES[gg]["role"].get(aid, {})))
    e = dict(e); e["role"] = G["role"].get(aid, {}); e["prior"] = vals; e["aid_espn"] = aid
    rows.append(e)
print("joined", len(rows), "of", len(g), dict(miss))
OUT = []
def add(name, R, sec):
    r = fmt(name, R); r["sec"] = sec; OUT.append(r); print(r["line"])

print("== 7. last-5 hit rate at this exact line, prior games only (>=5 prior games)")
R5 = [e for e in rows if len(e["prior"]) >= 5]
for e in R5: e["l5"] = sum(1 for w, _ in e["prior"][-5:] if w)
add("has >=5 prior games", R5, "7")
add("fewer than 5 prior games", [e for e in rows if len(e["prior"]) < 5], "7")
for lab, pred in [("5/5", lambda k: k == 5), ("4/5", lambda k: k == 4), ("3/5", lambda k: k == 3), ("<=2/5", lambda k: k <= 2), ("<=3/5", lambda k: k <= 3)]:
    add(f"last5 at line {lab}", [e for e in R5 if pred(e["l5"])], "7")
for L in ("nba", "nhl", "nfl"):
    add(f"  {L} last5 <=3/5", [e for e in R5 if e["league"] == L and e["l5"] <= 3], "7")
    add(f"  {L} last5 5/5", [e for e in R5 if e["league"] == L and e["l5"] == 5], "7")
# last-5 rate minus stated chance
for lab, a, b in [("l5 rate - p <= -0.25", -9, -0.25), ("-0.25..-0.05", -0.25, -0.05), ("-0.05..+0.10", -0.05, 0.10), (">= +0.10", 0.10, 9)]:
    add(f"  {lab}", [e for e in R5 if a <= e["l5"] / 5 - e["p"] < b], "7")
# season-to-date rate at the line (all prior games, >=5)
for lab, a, b in [("season rate at line < p-0.15", -9, -0.15), ("season rate within +-0.15 of p", -0.15, 0.15), ("season rate > p+0.15", 0.15, 9)]:
    add(f"  {lab}", [e for e in R5 if a <= sum(w for w, _ in e["prior"]) / len(e["prior"]) - e["p"] < b], "7")

print("== 3. role / usage")
nba = [e for e in rows if e["league"] == "nba"]
add("NBA starter (this game)", [e for e in nba if e["role"].get("starter") is True], "3")
add("NBA bench (this game)", [e for e in nba if e["role"].get("starter") is False], "3")
def pavg(e, k, n=5):
    xs = [r.get(k) for _, r in e["prior"][-n:] if r.get(k) is not None]
    return sum(xs) / len(xs) if len(xs) >= 3 else None
for lab, a, b in [("<20", 0, 20), ("20-28", 20, 28), ("28-34", 28, 34), ("34+", 34, 99)]:
    add(f"NBA prior-5 avg minutes {lab}", [e for e in nba if pavg(e, "min") is not None and a <= pavg(e, "min") < b], "3")
nhl = [e for e in rows if e["league"] == "nhl"]
add("NHL defencemen", [e for e in nhl if "defenses" in e["role"].get("grp", ())], "3")
add("NHL forwards", [e for e in nhl if "forwards" in e["role"].get("grp", ())], "3")
for lab, a, b in [("<14", 0, 14), ("14-17", 14, 17), ("17-20", 17, 20), ("20+", 20, 99)]:
    add(f"NHL prior-5 avg TOI {lab}", [e for e in nhl if pavg(e, "min") is not None and a <= pavg(e, "min") < b], "3")
nfl = [e for e in rows if e["league"] == "nfl" and e["market"] in ("Receiving Yards", "Receptions")]
for lab, a, b in [("<3", 0, 3), ("3-5", 3, 5), ("5-7", 5, 7), ("7+", 7, 99)]:
    add(f"NFL rec props, prior-5 avg targets {lab}", [e for e in nfl if pavg(e, "tgt") is not None and a <= pavg(e, "tgt") < b], "3")
add("NFL rec yds <=10+ & prior targets <4", [e for e in nfl if e["market"] == "Receiving Yards" and (float(e["line"].rstrip("+")) <= 10) and pavg(e, "tgt") is not None and pavg(e, "tgt") < 4], "3")
rush = [e for e in rows if e["league"] == "nfl" and e["market"] == "Rushing Yards"]
add("NFL rush yds, prior-5 avg carries <8", [e for e in rush if pavg(e, "car") is not None and pavg(e, "car") < 8], "3")
add("NFL rush yds, prior-5 avg carries >=8", [e for e in rush if pavg(e, "car") is not None and pavg(e, "car") >= 8], "3")

print("== 6b. cluster check: per player-game with >=2 props, all-won vs product of stated")
pg = collections.defaultdict(list)
for e in load_graded(): pg[(e["gid"], e["name"])].append(e)
def clus(name, keep):
    res = []
    for h in (0, 1, 2):
        U = [v for v in pg.values() if len(v) >= 2 and keep(v) and (h == 2 or ((v[0]["date"] >= MID) == (h == 1)))]
        if not U: res.append(None); continue
        q = [math.prod(x["p"] for x in v) for v in U]; y = [all(x["y"] for x in v) for v in U]
        lost_all = sum(all(not x["y"] for x in v) for v in U); exl = sum(math.prod(1 - x["p"] for x in v) for v in U)
        res.append(dict(n=len(U), all_won=round(100 * sum(y) / len(U), 1), said=round(100 * sum(q) / len(U), 1),
                        z=round((sum(y) - sum(q)) / math.sqrt(sum(a * (1 - a) for a in q)), 2),
                        all_lost=lost_all, all_lost_exp=round(exl, 1)))
    v = verdict(res[0], res[1], res[2]) if res[0] and res[1] else "rejected"
    OUT.append(dict(name=name, h1=res[0], h2=res[1], all=res[2], verdict=v, sec="6b",
                    line=f"{name:<48} | H1 {res[0]} | H2 {res[1]} | ALL {res[2]} | {v}"))
    print(OUT[-1]["line"])
clus("same player-game, any markets", lambda v: True)
clus("same player-game, all different markets", lambda v: len({x["market"] for x in v}) == len(v))
json.dump(OUT, open("results_b.json", "w"), indent=1, default=list)
