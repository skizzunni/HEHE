"""Board picks whose price moved against them between first log and close,
walk-forward by date halves: hit rate vs stated chance and flat-$1 return,
for moves of 2/3/5+ implied points against, against the rest.
Information only; no pick changes.

    python tools/move_study.py [ledger.json] [league|all ...]

2026-11-13: rejected (README) -- NHL samples tiny and mixed; all leagues
hit over stated in one half and under in the other.
"""
import json
import sys


def _imp(p):
    try:
        a = float(str(p).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if a == 0:
        return None
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def _pay(p):
    a = float(str(p).replace("+", ""))
    return a / 100 if a > 0 else 100 / -a


def move(v):
    """Implied points the close moved from the first logged price (negative = against)."""
    a, b = _imp(v.get("first_price")), _imp(v.get("price"))
    return None if a is None or b is None else 100 * (b - a)


def cell(s):
    """[won, n, stated %, flat-$1 ROI %] or None."""
    if not s:
        return None
    return [sum(v["status"] == "won" for v in s), len(s), sum(v.get("conf") or 0 for v in s) / len(s),
            100 * sum(_pay(v["price"]) if v["status"] == "won" else -1 for v in s) / len(s)]


def study(L, league="all", cuts=(2, 3, 5)):
    g = [v for v in L.values() if isinstance(v, dict) and (league == "all" or v.get("league") == league)
         and v.get("status") in ("won", "lost") and v.get("date") and move(v) is not None]
    days = sorted({v["date"] for v in g})
    if len(days) < 2:
        return None
    mid = days[len(days) // 2]
    out = {"mid": mid, "n": len(g)}
    for c in cuts:
        for h in ("A", "B"):
            hs = [v for v in g if (v["date"] < mid) == (h == "A")]
            out[f"{c}{h}"] = dict(against=cell([v for v in hs if move(v) <= -c]),
                                  rest=cell([v for v in hs if move(v) > -c]))
    return out


if __name__ == "__main__":
    L = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "ledger.json"))
    for lg in sys.argv[2:] or ["all"]:
        print(lg, json.dumps(study(L, lg)))
