"""UFC study: walk-forward Elo rating vs DraftKings prices (ufc_history.json from tools/ufc_history.py + ufc_enrich.py). Run: python tools/ufc_study_rating.py"""
import sys, math
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
import ufc_model as M
b = M.load()
def imp(a):
    if a is None: return None
    a = float(a); return 100/(a+100) if a > 0 else -a/(-a+100)
def dec(a):
    a = float(a); return 1 + (a/100 if a > 0 else 100/-a)
R, N, rows = {}, {}, []
for cid, f in sorted(b.items(), key=lambda kv: (kv[1].get("date") or "", kv[0])):
    a, c = f["a"], f["b"]
    if a["won"] == c["won"]: continue
    ra, rc = R.get(a["id"], 1500), R.get(c["id"], 1500); p = M.expected(ra, rc)
    ml = ((f.get("odds") or {}).get("ml")) or {}
    xa, xc = ml.get(a["id"]), ml.get(c["id"])
    if xa is not None and xc is not None:
        ia, ic = imp(xa), imp(xc)
        rows.append(dict(d=f["date"], p=p, q=ia/(ia+ic), won=a["won"], na=N.get(a["id"], 0), nc=N.get(c["id"], 0), xa=xa, xc=xc))
    s = 1.0 if a["won"] else 0.0
    R[a["id"]] = ra + 40*(s-p); R[c["id"]] = rc + 40*((1-s)-(1-p))
    N[a["id"]] = N.get(a["id"], 0)+1; N[c["id"]] = N.get(c["id"], 0)+1
print(len(rows), "fights with odds")
fav = sum((r["q"] >= .5) == r["won"] for r in rows); mod = sum((r["p"] >= .5) == r["won"] for r in rows)
print(f"market favourite right {fav}/{len(rows)} ({100*fav/len(rows):.1f}%), rating right {mod} ({100*mod/len(rows):.1f}%)")
def bet(rows, pick_a, label):
    n = w = 0; pl = 0.0
    for r, pa in zip(rows, pick_a):
        if pa is None: continue
        n += 1; won = r["won"] == pa; price = r["xa"] if pa else r["xc"]
        pl += (dec(price)-1) if won else -1; w += won
    if n: print(f"{label}: {w}/{n} won ({100*w/n:.0f}%), ROI at real prices {100*pl/n:+.1f}%")
mid = sorted(r["d"] for r in rows)[len(rows)//2]
for half, X in (("first half", [r for r in rows if r["d"] < mid]), ("second half", [r for r in rows if r["d"] >= mid])):
    print("--", half, len(X))
    bet(X, [r["q"] >= .5 for r in X], "every favourite")
    bet(X, [r["q"] < .5 for r in X], "every underdog")
    D = [r for r in X if (r["p"] >= .5) != (r["q"] >= .5) and min(r["na"], r["nc"]) >= 2]
    bet(D, [r["p"] >= .5 for r in D], "rating's pick where it disagrees (both 2+ UFC fights)")
    E = [r for r in X if min(r["na"], r["nc"]) >= 2 and abs(r["p"] - r["q"]) >= .15]
    bet(E, [r["p"] > r["q"] for r in E], "side the rating rates 15+ pts above market")
    for nm, f in (("fighter in 1st/2nd UFC fight", lambda r: r["na"] <= 1 and r["nc"] >= 3), ):
        Y = [r for r in X if f(r)]
        if Y:
            w = sum(r["won"] for r in Y); e = sum(r["q"] for r in Y)
            print(f"{nm} vs a veteran: won {w}/{len(Y)} against {e:.1f} priced")
            bet(Y, [True]*len(Y), "  betting the newcomer")
