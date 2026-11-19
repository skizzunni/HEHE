"""How good is the 2+ touchdown estimate? (td_scorers.two_plus)

    python3 tools/td_two_plus_study.py

Every graded anytime-TD chance in data/td_history.json is turned back into
the expected-touchdown count it came from (lam = -ln(1 - p)) and into the
2+ chance the page now shows (1 - e^-lam (1 + lam)). The player's actual
touchdowns come from the ESPN box score (props_ledger), so the estimate is
checked on every game already graded -- no waiting for new games. Read
only: the history file is the bot's and is not written.
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import td_scorers  # noqa: E402


def two_plus_from_p(p):
    """The 2+ chance implied by an anytime chance p."""
    lam = -math.log(max(1e-9, 1 - min(p, 0.999)))
    return td_scorers.two_plus(lam)


def counts(book, summary=None, box=None):
    """{key: touchdowns} for graded entries, read from each game's box score
    once (props_ledger's resolver and touchdown market)."""
    import props_ledger as PL
    summary = summary or PL.summary
    box = box or PL.box_stats
    by_game = {}
    for k, e in book.items():
        if e.get("status") in ("won", "lost"):
            by_game.setdefault(e["gid"], []).append((k, e))
    out = {}
    for gid, es in by_game.items():
        league, eid = gid.split(":", 1)
        sm = summary(league, eid)
        if not sm or not sm.get("completed"):
            continue
        st = box(sm)
        fn = PL.MARKETS[league][td_scorers.MARKET]
        for k, e in es:
            s_, how = PL.resolve(st, dict(name=e["name"]))
            if s_ is None:
                continue
            v = fn(s_)
            if v is not None:
                out[k] = v
    return out


def study(book, tds):
    """By date half: players with 2+ touchdowns vs the summed 2+ estimate."""
    R = sorted(((e["date"], two_plus_from_p(e["p"]), tds[k]) for k, e in book.items()
                if k in tds and e.get("p") and e.get("date")), key=lambda r: r[0])
    if not R:
        return []
    h = len(R) // 2
    out = []
    for S in (R[:h], R[h:]):
        w = sum(t >= 2 for _, _, t in S)
        p = sum(q for _, q, _ in S)
        v = sum(q * (1 - q) for _, q, _ in S) or 1
        out.append(dict(n=len(S), two_plus=w, expected=round(p, 1), z=round((w - p) / math.sqrt(v), 2),
                        since=S[0][0], until=S[-1][0]))
    return out


if __name__ == "__main__":
    with open(os.path.join(ROOT, "data", "td_history.json")) as fh:
        book = json.load(fh)
    tds = counts(book)
    for half in study(book, tds):
        print(f"{half['since']} to {half['until']}: {half['two_plus']} of {half['n']} players scored 2+ "
              f"vs {half['expected']} expected (z {half['z']:+.2f})")
