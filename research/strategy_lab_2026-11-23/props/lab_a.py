"""Strategies 1, 2, 4, 5, 6, 8 on props.json graded records (no box scores needed)."""
import collections, itertools, json, math, re
from common import *
g = load_graded()
OUT = []
def add(name, rows, sec):
    r = fmt(name, rows); r["sec"] = sec; OUT.append(r); print(r["line"])

def lgg(e):
    return "soccer" if e["league"] in SOCCER else e["league"]
def num(line):
    m = re.match(r"^(\d+(?:\.\d+)?)\+$", str(line)); return float(m.group(1)) if m else None

print("== 0. all graded props")
add("ALL props.json graded", g, "0")
add("Prop Locks legs (prop_lock=True)", [e for e in g if e.get("prop_lock")], "0")
print("== 1. market (league x market, n>=40)")
mk = collections.defaultdict(list)
for e in g: mk[(lgg(e), e["market"])].append(e)
for k, rows in sorted(mk.items(), key=lambda kv: -len(kv[1])):
    if len(rows) >= 40: add(f"mkt {k[0]} {k[1]}", rows, "1")
print("== 1b. side")
und = [e for e in g if str(e["line"]).startswith("u") or e["line"] == "No"]
add("side under/No", und, "1b"); add("side over / N+", [e for e in g if e not in und], "1b")
print("== 4. league")
for L in ["nba", "nhl", "nfl", "soccer", "ufc", "wnba", "mlb"]:
    add(f"league {L}", [e for e in g if lgg(e) == L], "4")
print("== 2. line height: lowest rung of its market vs higher")
lo = {}
for k, rows in mk.items():
    xs = [num(e["line"]) for e in rows if num(e["line"]) is not None]
    if xs: lo[k] = min(xs)
low = [e for e in g if num(e["line"]) is not None and num(e["line"]) == lo.get((lgg(e), e["market"]))]
high = [e for e in g if num(e["line"]) is not None and num(e["line"]) > lo.get((lgg(e), e["market"]), 1e9)]
add("lowest rung (1+ SOG, 5+ yds, 1+ 3PM...)", low, "2"); add("higher rungs", high, "2")
for k in [("nba", "Points"), ("nba", "Threes Made"), ("nba", "Assists"), ("nba", "Rebounds"), ("nhl", "Shots on Goal"),
          ("nfl", "Receiving Yards"), ("nfl", "Receptions"), ("nfl", "Rushing Yards")]:
    rows = mk[k]
    for ln in sorted({num(e["line"]) for e in rows if num(e["line"]) is not None}):
        sub = [e for e in rows if num(e["line"]) == ln]
        if len(sub) >= 25: add(f"  {k[0]} {k[1]} {int(ln)}+", sub, "2")
nfl_ry = mk[("nfl", "Receiving Yards")]
add("NFL rec yds lines <=10+", [e for e in nfl_ry if (num(e["line"]) or 99) <= 10], "2")
add("NFL rec yds lines 15+..25+", [e for e in nfl_ry if 15 <= (num(e["line"]) or 0) <= 25], "2")
add("NFL rec yds lines >=30+", [e for e in nfl_ry if (num(e["line"]) or 0) >= 30], "2")
print("== 5. stated chance bands (distance from 50%)")
for a, b in [(0, .5), (.5, .6), (.6, .7), (.7, .75), (.75, .8), (.8, .85), (.85, .9), (.9, 1.01)]:
    add(f"p in [{a:.2f},{b:.2f})", [e for e in g if a <= e["p"] < b], "5")
print("== 5b. very short prices")
for a, b, nm in [(1.0, 1.10, "price -1000 or shorter"), (1.10, 1.20, "-1000..-500"), (1.20, 1.333, "-500..-300"), (1.333, 2.0, "-300..-100"), (2.0, 99, "plus money")]:
    add(f"  {nm}", [e for e in g if e["dec"] and a <= e["dec"] < b], "5b")
heavy = [e for e in g if e["dec"] and e["dec"] <= 1.10]
add("  -1000 or shorter, dated >= CAP_SINCE 2026-10-27", [e for e in heavy if e["date"] >= "2026-10-27"], "5b")
print("== 8. stated vs book implied: our p minus imp")
gi = [e for e in g if e.get("imp")]
for a, b in [(-1, -.065), (-.065, -.045), (-.045, -.025), (-.025, 1)]:
    add(f"p-imp in [{a},{b})", [e for e in gi if a <= e["p"] - e["imp"] < b], "8")
print("== 8b. fair chance (p_fair) above stated by >=5 pts")
gf = [e for e in g if isinstance(e.get("p_fair"), (int, float))]
add("p_fair - p >= 0.05", [e for e in gf if e["p_fair"] - e["p"] >= .05], "8")
add("p_fair - p < 0.05", [e for e in gf if e["p_fair"] - e["p"] < .05], "8")
print("== 8c. name match quality")
add("matched fuzzy", [e for e in g if e.get("matched") == "fuzzy"], "8")

print("== 6. same-game / same-player pairs: P(both win) vs product of stated")
def pairs(pred):
    gm = collections.defaultdict(list)
    for e in g: gm[e["gid"]].append(e)
    P = []
    for rows in gm.values():
        for a, b in itertools.combinations(rows, 2):
            if pred(a, b): P.append((a, b))
    return P
def pstat(name, P):
    res = []
    for h in (0, 1, 2):
        Q = [(a, b) for a, b in P if h == 2 or ((a["date"] >= MID) == (h == 1))]
        if not Q: res.append(None); continue
        bw = sum(a["y"] * b["y"] for a, b in Q); ex = sum(a["p"] * b["p"] for a, b in Q)
        var = sum(a["p"] * b["p"] * (1 - a["p"] * b["p"]) for a, b in Q)
        bl = sum((1 - a["y"]) * (1 - b["y"]) for a, b in Q); exl = sum((1 - a["p"]) * (1 - b["p"]) for a, b in Q)
        # independence given realised marginals: E[both win] = sum of a_hat*b_hat? use observed marginal rates
        ha = sum(a["y"] for a, b in Q) / len(Q); hb = sum(b["y"] for a, b in Q) / len(Q)
        res.append(dict(n=len(Q), both_won=round(100 * bw / len(Q), 1), said=round(100 * ex / len(Q), 1),
                        z=round((bw - ex) / math.sqrt(var), 2), both_lost=bl, both_lost_exp=round(exl, 1)))
    v = verdict(res[0] or {}, res[1] or {}, res[2] or {}) if res[0] and res[1] else "rejected"
    OUT.append(dict(name=name, h1=res[0], h2=res[1], all=res[2], verdict=v, sec="6",
                    line=f"{name:<48} | H1 {res[0]} | H2 {res[1]} | ALL {res[2]} | {v}"))
    print(OUT[-1]["line"])
pstat("same player, same game (2 props)", pairs(lambda a, b: a["name"] == b["name"]))
pstat("same game, different players", pairs(lambda a, b: a["name"] != b["name"]))
# conditional: when one leg of a same-player pair lost, did the other?
P = pairs(lambda a, b: a["name"] == b["name"])
lost1 = [(a, b) for a, b in P if a["y"] == 0] + [(b, a) for a, b in P if b["y"] == 0]
print("  same player: other leg's hit when one lost:", stat([b for a, b in lost1]))
lostd = [(a, b) for a, b in pairs(lambda a, b: a["name"] != b["name"]) if a["y"] == 0]
print("  same game diff player: other leg's hit when one lost:", stat([b for a, b in lostd]))
json.dump(OUT, open("results_a.json", "w"), indent=1)
