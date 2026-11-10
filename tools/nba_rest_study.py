"""Rest / back-to-back study on tools/nba_history.py output: home win rate
against the no-vig closing price, and flat-stake ROI for each side, by rest
spot and season.  python tools/nba_rest_study.py NBA_HISTORY.json"""
import json, datetime as dt, collections, sys
G = json.load(open(sys.argv[1]))
G = sorted([g for g in G.values() if g.get("odds")], key=lambda g: g["date"])
def imp(a): return 100/(a+100) if a > 0 else -a/(-a+100)
def dec(a): return 1 + (a/100 if a > 0 else 100/-a)
last = {}
rows = []
for g in G:
    d = dt.date.fromisoformat(g["day"])
    r = {}
    for s in ("home", "away"):
        t = g[s]["id"]; p = last.get(t)
        r[s] = (d - p).days if p else None
        last[t] = d
    ph, pa = imp(g["odds"]["home"]), imp(g["odds"]["away"])
    if ph + pa < 0.95 or ph + pa > 1.15: continue
    p = ph / (ph + pa)
    hw = g["home"]["score"] > g["away"]["score"]
    rows.append(dict(day=g["day"], season=g["day"][:4] if g["day"][5:7] >= "08" else str(int(g["day"][:4]) - 1),
                     rh=r["home"], ra=r["away"], p=p, hw=hw, oh=g["odds"]["home"], oa=g["odds"]["away"]))
print("games", len(rows))
fav = sum((r["p"] > .5) == r["hw"] for r in rows) / len(rows); print("favourite won", round(100*fav, 1))
def cat(r):
    h, a = r["rh"], r["ra"]
    if h is None or a is None or h > 6 or a > 6: return None
    hb, ab = h == 1, a == 1
    if hb and not ab: return "home on b2b, away not"
    if ab and not hb: return "away on b2b, home not"
    if hb and ab: return "both b2b"
    if h - a >= 2: return "home 2+ more rest"
    if a - h >= 2: return "away 2+ more rest"
    return "even rest"
def bet(rs, side):
    # flat $1 on `side` ("home"/"away") at the closing price
    pl = 0
    for r in rs:
        win = r["hw"] if side == "home" else not r["hw"]
        o = r["oh"] if side == "home" else r["oa"]
        pl += (dec(o) - 1) if win else -1
    return 100 * pl / len(rs)
seasons = sorted({r["season"] for r in rows})
by = collections.defaultdict(list)
for r in rows:
    c = cat(r)
    if c: by[c].append(r)
for c, rs in sorted(by.items()):
    line = [f"{c:24s} n={len(rs):4d} home won {100*sum(r['hw'] for r in rs)/len(rs):5.1f}% vs price {100*sum(r['p'] for r in rs)/len(rs):5.1f}%"]
    for s in seasons:
        ss = [r for r in rs if r["season"] == s]
        if ss: line.append(f"{s}: {100*sum(r['hw'] for r in ss)/len(ss)-100*sum(r['p'] for r in ss)/len(ss):+5.1f} pts (n {len(ss)}) home ROI {bet(ss,'home'):+5.1f}% away ROI {bet(ss,'away'):+5.1f}%")
    print(" | ".join(line))
# tired favourite: favourite on b2b vs rested dog
tf = [r for r in rows if cat(r) in ("home on b2b, away not", "away on b2b, home not")]
for s in seasons:
    fb = [r for r in tf if r["season"] == s and ((cat(r) == "home on b2b, away not") == (r["p"] > .5))]
    if fb:
        dogwin = sum((r["hw"]) != (r["p"] > .5) for r in fb) / len(fb); dogp = sum(1 - max(r["p"], 1-r["p"]) for r in fb) / len(fb)
        roi = 100*sum(((dec(r["oa"] if r["p"] > .5 else r["oh"]) - 1) if (r["hw"] != (r["p"] > .5)) else -1) for r in fb)/len(fb)
        print(f"tired favourite vs rested dog {s}: n={len(fb)} dog won {100*dogwin:.1f}% vs price {100*dogp:.1f}%, dog ROI {roi:+.1f}%")
