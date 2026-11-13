"""Fixed ladder leg counts by date halves: every saved Locks card replayed as
if the ladder always used its top K legs, split at the median card date, with
each half's cash rate, average payout and the chance of the straight wins $1
-> target takes at that rate. Information only; the ticket rule is unchanged.

    python tools/ladder_count_study.py [max_legs=8]

2026-11-13: rejected (README) -- 2 legs best in the earlier half (1 in 321),
5 legs best in the later half (1 in 263).
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def reach(rate, pays, target=10000):
    """(wins needed from $1, chance of that many straight cashes) or None."""
    if not (pays > 1 and rate > 0 and target > 1):
        return None
    k = math.ceil(math.log(target) / math.log(pays) - 1e-9)
    return k, min(rate, 1.0) ** k


def halves(rows, target=10000):
    """rows: {K: [(day, cashed, pays)]} -> {K: [(won, n, avg_pays, reach), x2]}
    split at the median date of all cards."""
    days = sorted({d for r in rows.values() for d, _, _ in r})
    if len(days) < 2:
        return {}
    mid = days[len(days) // 2]
    out = {}
    for k, r in sorted(rows.items()):
        hs = []
        for h in (False, True):
            s = [x for x in r if (x[0] >= mid) == h]
            if not s:
                hs.append(None)
                continue
            w, x = sum(c for _, c, _ in s), sum(p for _, _, p in s) / len(s)
            hs.append((w, len(s), round(x, 2), reach(w / len(s), x, target)))
        out[k] = hs
    return out


def cards(book, hi=8):
    import ladder
    import locks
    rows = {}
    for k in range(1, hi + 1):
        for day in sorted(book.get("days", {})):
            legs = ladder.ticket(book, day, k)
            if not legs or any(L.get("status") not in ("won", "lost") for L in legs):
                continue
            try:
                pay = math.prod(locks._dec(L["price"]) for L in legs)
            except Exception:
                continue
            rows.setdefault(k, []).append((day, all(L["status"] == "won" for L in legs), pay))
    return rows


if __name__ == "__main__":
    import locks
    for k, hs in halves(cards(locks.load(), int(sys.argv[1]) if len(sys.argv) > 1 else 8)).items():
        print(k, " | ".join("-" if h is None else f"{h[0]}/{h[1]} at {h[2]}x -> "
                            + (f"1 in {round(1 / h[3][1]):,}" if h[3] and h[3][1] else "never") for h in hs))
