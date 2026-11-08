"""Ladder leg-ranking study, walk-forward on every saved Locks card: the top K
by stated chance against the top K by each kind's record so far (shrunk to
its stated chance with 10 pseudo-legs). Rerun as cards come in.

    python tools/ladder_study.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import locks  # noqa: E402


def study(book=None, sizes=(3, 4, 5), prior=10):
    b = book or locks.load()
    days = sorted(b["days"])
    out = {}
    for K in sizes:
        for mode in ("stated", "kind record"):
            won = n = 0
            pay = 0.0
            hist = {}
            for d in days:
                keys = b["days"][d]
                keys = keys.get("legs") if isinstance(keys, dict) else keys
                L = [b["legs"][k] for k in keys or [] if k in b["legs"]]
                def score(x):
                    w, m = hist.get(locks.kind_key(x), [0, 0])
                    return (w + prior * x["p"]) / (m + prior) if mode == "kind record" else x["p"]
                pick = sorted(L, key=lambda x: -score(x))[:K]
                if len(pick) == K and all(x.get("status") in ("won", "lost") for x in pick):
                    n += 1
                    won += all(x["status"] == "won" for x in pick)
                    pay += math.prod(locks._dec(x["price"]) for x in pick)
                for x in L:
                    if x.get("status") in ("won", "lost"):
                        h = hist.setdefault(locks.kind_key(x), [0, 0])
                        h[0] += x["status"] == "won"
                        h[1] += 1
            out[(K, mode)] = dict(won=won, n=n, pays=round(pay / n, 2) if n else None)
    return out


def calls_study(book=None, sizes=(2, 3, 4, 5, 6)):
    """The same idea from the board's calls: each day's top K calls by stated
    chance as one parlay, by date half -- {(K, half): dict(won, n, pays)}.
    2026-11-08: top 6 cashed 4/12 at 5.31x then 10/13 at 1.60x -- the recent
    top calls were heavy favourites paying under 2x, so the same trade-off."""
    import collections
    import ledger
    book = book if book is not None else ledger.load()
    def dec(a):
        a = float(str(a).replace("+", ""))
        return 1 + (a / 100 if a > 0 else 100 / -a)
    by = collections.defaultdict(list)
    for e in book.values():
        if e.get("status") in ("won", "lost") and e.get("conf") and e.get("price") and e.get("date"):
            try:
                by[e["date"]].append((e["conf"], e["status"] == "won", dec(e["price"])))
            except (TypeError, ValueError):
                continue
    days = sorted(by)
    if not days:
        return {}
    mid = days[len(days) // 2]
    out = {}
    for K in sizes:
        for half in ("first", "second"):
            n = w = 0
            pay = 0.0
            for d in days:
                if (d >= mid) != (half == "second"):
                    continue
                X = sorted(by[d], key=lambda r: -r[0])[:K]
                if len(X) < K:
                    continue
                n += 1
                w += all(r[1] for r in X)
                pay += math.prod(r[2] for r in X)
            out[(K, half)] = dict(won=w, n=n, pays=round(pay / n, 2) if n else None)
    return out


if __name__ == "__main__":
    for (K, half), r in calls_study().items():
        print(f"top {K} calls, {half} half: {r['won']}/{r['n']} cashed at {r['pays']}x")
    for (K, mode), r in study().items():
        print(f"{K} legs by {mode}: {r['won']}/{r['n']} cashed at {r['pays']}x")
