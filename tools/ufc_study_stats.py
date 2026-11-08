"""UFC study: market price + rolling fight stats (strike differential, takedowns, win rate, reach, age), fit on the first half of fights, tested on the second at real prices. Run: python tools/ufc_study_stats.py"""
import sys, math, json, datetime as dt
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
import ufc_model as M
b = M.load(); ath = json.load(open(__import__("os").path.join(__import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))), "ufc_athletes.json")))
def imp(a): a=float(a); return 100/(a+100) if a>0 else -a/(-a+100)
def dec(a): a=float(a); return 1+(a/100 if a>0 else 100/-a)
def secs(f):
    try: m,s=(f.get("clock") or "0:00").split(":"); return ((f.get("round") or 1)-1)*300+int(m)*60+int(s)
    except Exception: return None
H = {}   # fighter -> list of per-fight dicts
def feats(i, day):
    h = H.get(i, [])
    if len(h) < 2: return None
    mins = sum(x["t"] for x in h)/60 or 1
    slpm = sum(x["sl"] for x in h)/mins; sapm = sum(x["sa"] for x in h)/mins
    td = sum(x["td"] for x in h)/len(h); tda = sum(x["tda"] for x in h)/len(h)
    win = sum(x["w"] for x in h)/len(h)
    bi = ath.get(i) or {}
    age = None
    if bi.get("dob"):
        try: age = (dt.date.fromisoformat(day) - dt.date.fromisoformat(bi["dob"])).days/365.25
        except Exception: pass
    return dict(slpm=slpm, sapm=sapm, td=td, tda=tda, win=win, reach=bi.get("reach"), age=age, n=len(h))
rows = []
for cid, f in sorted(b.items(), key=lambda kv: (kv[1].get("date") or "", kv[0])):
    a, c = f["a"], f["b"]; t = secs(f)
    if a["won"] == c["won"] or t is None: continue
    ml = (f.get("odds") or {}).get("ml") or {}
    if f.get("date","") >= "2021-01-01" and ml.get(a["id"]) is not None and ml.get(c["id"]) is not None:
        fa, fc = feats(a["id"], f["date"]), feats(c["id"], f["date"])
        if fa and fc and fa["reach"] and fc["reach"] and fa["age"] and fc["age"]:
            ia, ic = imp(ml[a["id"]]), imp(ml[c["id"]]); q = ia/(ia+ic)
            x = [math.log(q/(1-q)), (fa["slpm"]-fa["sapm"])-(fc["slpm"]-fc["sapm"]), fa["td"]-fc["td"],
                 fa["win"]-fc["win"], (fa["reach"]-fc["reach"])/5, (fa["age"]-fc["age"])/5]
            rows.append(dict(d=f["date"], x=x, q=q, y=1 if a["won"] else 0, xa=ml[a["id"]], xc=ml[c["id"]]))
    for x, o in ((a, c), (c, a)):
        s, so = x.get("stats") or {}, o.get("stats") or {}
        if s and so:
            H.setdefault(x["id"], []).append(dict(t=max(t, 30), sl=s.get("sigStrikesLanded") or 0, sa=so.get("sigStrikesLanded") or 0,
                                                  td=s.get("takedownsLanded") or 0, tda=so.get("takedownsLanded") or 0, w=x["won"]))
print(len(rows), "fights with odds + stats history + bio")
def fit(X, l2=1.0, it=400):
    k = len(X[0]["x"]) + 1; w = [0.0]*k
    for _ in range(it):
        g = [0.0]*k
        for r in X:
            xx = [1] + r["x"]; p = 1/(1+math.exp(-sum(a*b for a, b in zip(w, xx))))
            for i in range(k): g[i] += (r["y"]-p)*xx[i]
        w = [wi + 0.3*(gi/len(X) - l2*wi/len(X)) for wi, gi in zip(w, g)]
    return w
mid = sorted(r["d"] for r in rows)[len(rows)//2]
tr = [r for r in rows if r["d"] < mid]; te = [r for r in rows if r["d"] >= mid]
w = fit(tr); print("weights [bias, market, strike diff, takedowns, win%, reach/5in, age/5y]:", [round(v, 3) for v in w])
def pr(r, w): return 1/(1+math.exp(-sum(a*b for a, b in zip(w, [1]+r["x"]))))
ll_m = -sum(math.log(r["q"] if r["y"] else 1-r["q"]) for r in te)/len(te)
ll_s = -sum(math.log(pr(r, w) if r["y"] else 1-pr(r, w)) for r in te)/len(te)
print(f"test {len(te)} fights: log loss market {ll_m:.4f}, market+stats {ll_s:.4f} (lower is better)")
for edge in (0.03, 0.05, 0.08):
    n = won = 0; pl = 0.0; dogs = 0
    for r in te:
        p = pr(r, w)
        for side, pp, qq, price, hit in ((1, p, r["q"], r["xa"], r["y"] == 1), (0, 1-p, 1-r["q"], r["xc"], r["y"] == 0)):
            if pp - qq >= edge:
                n += 1; won += hit; pl += (dec(price)-1) if hit else -1; dogs += qq < .5
    if n: print(f"bet where model is {int(edge*100)}+ pts above market: {won}/{n} won ({100*won/n:.0f}%), {dogs} were underdogs, ROI {100*pl/n:+.1f}%")
