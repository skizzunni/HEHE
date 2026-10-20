"""Closing line value: the primary scoreboard.

For every graded book-priced pick, the closing no-vig chance of the side
called (DraftKings' final moneylines from ESPN's game summary, de-vigged as
the board de-vigs that league: devig.method_for) is logged beside the chance
published, and

    CLV = closing chance - published chance, in points

(positive: the market moved toward the call after it was published). The
published chance is the call as first published (the ledger's `first`).

    review/clv.json      every pick's closing chance and CLV (append-only),
                         the rolling report and the hard rule's verdict
    review/clv_weekly.json   per ISO week: % beating the close, mean CLV,
                         Brier and log-loss of published vs closing chances
                         on the same games, with N and dates

The hard rule: over the last RULE_N graded picks, if the published chances do
not beat the closing chances on Brier, the market is the model --
policy.model_weight and policy.home_edge return 0 everywhere and the board
says so. It is re-checked every run.

    python3 tools/clv.py [--limit 400]
"""
import argparse
import datetime as dt
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

OUT = os.path.join(ROOT, "review", "clv.json")
WEEKLY = os.path.join(ROOT, "review", "clv_weekly.json")
RULE_N = 300
RETRY = "retry"


def load(path=OUT):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"picks": {}}


def published(e):
    f = e.get("first") or {}
    v = f.get("conf", e.get("conf"))
    return float(v) / 100 if v else None


def closing(key, e, get=None):
    """Closing no-vig chance of the called side, None when the game has no
    closing line, RETRY when the summary could not be fetched."""
    import dashboard as D
    import devig
    lg, cid = key.split(":", 1)
    path = dict((k, p) for k, p, _ in D.LEAGUES).get(lg)
    if not path:
        return None
    get = get or (lambda u: D.get(u, tries=2, fresh=10 ** 9, stale=10 ** 9))
    d = get(f"{D.ESPN}/{path}/summary?event={cid}")
    if not d:
        return RETRY
    side = e.get("myside")
    if side not in ("away", "home"):
        # picks recorded before 2026-10-16 carry no side: match the name
        comp = ((d.get("header") or {}).get("competitions") or [{}])[0]
        side = next((x.get("homeAway") for x in comp.get("competitors") or []
                     if ((x.get("team") or {}).get("displayName") or "") == e.get("pick")), None)
        if side not in ("away", "home"):
            return None
    pc = [o for o in (d or {}).get("pickcenter") or [] if isinstance(o, dict)]
    pr = D.raw_prices(dict(odds=pc), 3 if lg in D.THREE_WAY else 2) if pc else None
    if not pr:
        return None
    fv = devig.fair_decimal(*[D.am_to_dec(p) for p in pr], method=devig.method_for(lg))
    if not fv:
        return None
    p = dict(zip(["away", "draw", "home"] if len(fv) == 3 else ["away", "home"], fv))
    return p[side] + (p.get("draw", 0) if e.get("dc") else 0)


def update(entries, book, limit=400, get=None):
    """Adds the closing chance of graded picks not yet logged (at most
    `limit` fetches a run, oldest first, so a backfill spreads over runs)."""
    import calibration as C
    todo = sorted((e for k, e in entries.items() if k not in book["picks"]
                   and C.graded([e]) and published(e)),
                  key=C.day_of)
    keys = {id(e): k for k, e in entries.items()}
    todo = todo[:limit]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:          # one summary per game
        closes = list(ex.map(lambda e: closing(keys[id(e)], e, get), todo))
    n = 0
    for e, c in zip(todo, closes):
        if c == RETRY:
            continue                                     # fetch failed: next run
        k = keys[id(e)]
        n += 1
        pub = published(e)
        book["picks"][k] = dict(day=C.day_of(e), league=e["league"], won=int(e["status"] == "won"),
                                call=bool(e.get("call")), published=round(pub, 4),
                                close=round(c, 4) if c is not None else None,
                                clv=round(100 * (c - pub), 2) if c is not None else None)
    return n


def report(rows):
    rows = [r for r in rows if r.get("close") is not None and 0 < r["close"] < 1]
    if not rows:
        return dict(n=0)
    n = len(rows)

    def ll(p, y):
        p = min(max(p, 1e-6), 1 - 1e-6)
        return -math.log(p if y else 1 - p)
    bp = sum((r["published"] - r["won"]) ** 2 for r in rows) / n
    bc = sum((r["close"] - r["won"]) ** 2 for r in rows) / n
    return dict(n=n, dates=[min(r["day"] for r in rows), max(r["day"] for r in rows)],
                beat_close_pct=round(100 * sum(r["clv"] > 0 for r in rows) / n, 1),
                mean_clv_pts=round(sum(r["clv"] for r in rows) / n, 2),
                brier_published=round(bp, 4), brier_close=round(bc, 4),
                logloss_published=round(sum(ll(r["published"], r["won"]) for r in rows) / n, 4),
                logloss_close=round(sum(ll(r["close"], r["won"]) for r in rows) / n, 4))


def rule(book):
    """The hard rule on the last RULE_N graded picks with a closing chance."""
    rows = sorted((r for r in book["picks"].values() if r.get("close") is not None), key=lambda r: r["day"])
    last = report(rows[-RULE_N:])
    beats = bool(last.get("n") and last["brier_published"] < last["brier_close"])
    return dict(last=last, beats_close=beats, market_is_model=not beats,
                enough=last.get("n", 0) >= RULE_N)


def weekly(book):
    by = {}
    for r in book["picks"].values():
        y, w, _ = dt.date.fromisoformat(r["day"]).isocalendar()
        by.setdefault(f"{y}-W{w:02d}", []).append(r)
    return {wk: dict(all=report(rs), calls=report([r for r in rs if r.get("call")]))
            for wk, rs in sorted(by.items())}


def main():
    import ledger
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400)
    a = ap.parse_args()
    book = load()
    n = update(ledger.load(), book, a.limit)
    book.update(rule(book), updated=dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(book, fh, indent=1, sort_keys=True)
    with open(WEEKLY, "w") as fh:
        json.dump(weekly(book), fh, indent=1, sort_keys=True)
    print(f"clv: {n} picks added; last {RULE_N}: {json.dumps(book['last'])}; "
          f"market is the model: {book['market_is_model']}")


if __name__ == "__main__":
    main()
