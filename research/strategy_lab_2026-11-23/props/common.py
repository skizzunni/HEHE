"""Shared helpers for the props strategy lab. Reads props.json only."""
import json, math, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
MID = "2026-11-04"          # median date of graded props.json records: H1 < MID <= H2
SOCCER = {"epl", "esp", "ger", "ita", "fra", "mls", "ucl", "uel"}

def load_graded():
    book = json.load(open(os.path.join(ROOT, "props.json")))
    out = []
    for k, e in book.items():
        if e.get("status") in ("won", "lost") and isinstance(e.get("p"), (int, float)) and e.get("date"):
            e = dict(e); e["key"] = k; e["y"] = 1 if e["status"] == "won" else 0
            e["dec"] = dec(e.get("price")); out.append(e)
    return out

def dec(price):
    try:
        v = float(str(price).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if v <= -100: return 1 + 100 / -v
    if v >= 100: return 1 + v / 100
    return None

def stat(rows):
    n = len(rows)
    if not n: return dict(n=0)
    h = sum(r["y"] for r in rows); ex = sum(r["p"] for r in rows)
    var = sum(r["p"] * (1 - r["p"]) for r in rows)
    pr = [r for r in rows if r.get("dec")]
    roi = (sum(r["y"] * r["dec"] for r in pr) - len(pr)) / len(pr) if pr else None
    return dict(n=n, hit=round(100 * h / n, 1), said=round(100 * ex / n, 1),
                z=round((h - ex) / math.sqrt(var), 2) if var > 0 else None,
                roi=round(100 * roi, 1) if roi is not None else None, n_priced=len(pr))

def halves(rows):
    a = [r for r in rows if r["date"] < MID]; b = [r for r in rows if r["date"] >= MID]
    return stat(a), stat(b), stat(rows)

def verdict(h1, h2, all_):
    z1, z2 = h1.get("z"), h2.get("z")
    if z1 is None or z2 is None or h1["n"] < 10 or h2["n"] < 10:
        return "rejected (too few)"
    if (z1 <= -2.8 and z2 <= -2.8) or (z1 >= 2.8 and z2 >= 2.8):
        return "ADOPT"
    if (z1 < 0) == (z2 < 0) and min(abs(z1), abs(z2)) >= 1.0 and abs(all_.get("z") or 0) >= 2.0:
        return "watch"
    return "rejected"

def fmt(name, rows):
    h1, h2, al = halves(rows)
    v = verdict(h1, h2, al)
    def s(x):
        return f"{x['n']}: {x['hit']}% vs {x['said']}% z{x['z']:+} roi{x['roi']}" if x.get("n") and x.get("z") is not None else f"{x.get('n',0)}: -"
    return dict(name=name, h1=h1, h2=h2, all=al, verdict=v,
                line=f"{name:<48} | H1 {s(h1):<38} | H2 {s(h2):<38} | ALL {s(al):<38} | {v}")
