"""Straight-win soccer picks in high-draw leagues, walk-forward on the board's
own ledger: league draw rates fitted on one half of the dates, straight-win
picks scored on the other (both ways). Information only; no pick changes.

    python tools/draw_league_study.py [ledger.json] [cut=0.25]

2026-11-13: rejected (README) -- the sign flips between halves and the
flagged leagues barely overlap.
"""
import json
import sys


def _pay(p):
    try:
        a = float(str(p).replace("+", ""))
    except (TypeError, ValueError):
        return None
    return a / 100 if a > 0 else (100 / -a if a else None)


def _drawn(v):
    return len(set(v["scores"].values())) == 1


def games(L):
    soc = {v.get("league") for v in L.values() if isinstance(v, dict) and v.get("dc")}
    return [v for v in L.values() if isinstance(v, dict) and v.get("league") in soc
            and v.get("status") in ("won", "lost") and v.get("date")
            and isinstance(v.get("scores"), dict) and len(v["scores"]) == 2]


def high_draw(vs, cut, min_n=12):
    c = {}
    for v in vs:
        a = c.setdefault(v["league"], [0, 0])
        a[0] += _drawn(v)
        a[1] += 1
    return {k for k, (d, n) in c.items() if n >= min_n and d / n >= cut}


def score(vs):
    """[won, n, stated %, flat-$1 ROI %, draws] for straight-win picks."""
    s = [v for v in vs if not v.get("dc")]
    if not s:
        return None
    pr = [(_pay(v.get("price")), v["status"]) for v in s]
    pr = [(p, st) for p, st in pr if p]
    roi = 100 * sum(p if st == "won" else -1 for p, st in pr) / len(pr) if pr else None
    return [sum(v["status"] == "won" for v in s), len(s), sum(v.get("conf") or 0 for v in s) / len(s),
            roi, sum(_drawn(v) for v in s)]


def study(L, cut=0.25, min_n=12):
    g = games(L)
    days = sorted({v["date"] for v in g})
    if len(days) < 2:
        return None
    mid = days[len(days) // 2]
    H = {"A": [v for v in g if v["date"] < mid], "B": [v for v in g if v["date"] >= mid]}
    out = {"mid": mid}
    for fit, test in (("A", "B"), ("B", "A")):
        hi = high_draw(H[fit], cut, min_n)
        out[test] = dict(leagues=sorted(hi), high=score([v for v in H[test] if v["league"] in hi]),
                         other=score([v for v in H[test] if v["league"] not in hi]))
    return out


if __name__ == "__main__":
    L = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "ledger.json"))
    print(json.dumps(study(L, float(sys.argv[2]) if len(sys.argv) > 2 else 0.25), indent=1))
