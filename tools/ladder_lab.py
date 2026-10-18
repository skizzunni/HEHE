"""Ladder lab: at the same FanDuel price, do far overs beat far unders?

    python3 tools/ladder_lab.py      # on GitHub's runners

data/ladder_history.json (ladders.py) holds the last pre-game FanDuel price
of every alternate-total rung, every NFL and college football game. Each rung
is de-vigged across its own over and under, graded on the final score, and
grouped by side, league and distance from the main total. The question the
locks need answered: at the price a lock pays (fair 70-82%), which side hits
more often than FanDuel says? Older half of the games against the newer
half, so a lean only counts if it holds in both. Writes data/ladder_lab.json.
"""
import datetime as dt
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import backtest as B                                          # noqa: E402

OUT = os.path.join(ROOT, "data", "ladder_lab.json")
FEEDS = {"nfl": ("football", "nfl"), "ncaaf": ("football", "college-football")}
LOCK_BAND = (0.70, 0.82)
MIN_GAMES = 30


def imp(o):
    o = float(o)
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def finals(book):
    """gid -> final total points, for the logged games that are over."""
    want = defaultdict(set)
    for gid, e in book.items():
        d = dt.date.fromisoformat(e["start"][:10])
        want[e["league"]] |= {d - dt.timedelta(days=1), d}
    out = {}
    for lg, ds in want.items():
        sport, league = FEEDS[lg]
        for g in B.finished_games(lg, sport, league, sorted(ds)):
            out[f"{lg}:{g[1]}"] = g[4] + g[5]
    return out


def rows_for(book, fin):
    rows = []
    for gid, e in book.items():
        if gid not in fin or e.get("total") is None:
            continue
        T, final = float(e["total"]), fin[gid]
        for L, s in e["ladder"].items():
            L = float(L)
            if "over" not in s or "under" not in s or final == L:
                continue
            pu = imp(s["under"]) / (imp(s["under"]) + imp(s["over"]))
            for side, p, hit in (("under", pu, final < L), ("over", 1 - pu, final > L)):
                rows.append(dict(gid=gid, league=e["league"], start=e["start"], side=side,
                                 off=abs(L - T), p=p, hit=int(hit)))
    return rows


def table(rs):
    """Hit minus FanDuel's fair chance, averaged per game (rungs of one game
    move together, so the game is the unit), with its standard error."""
    by = defaultdict(list)
    for r in rs:
        by[r["gid"]].append(r["hit"] - r["p"])
    v = [sum(x) / len(x) for x in by.values()]
    if len(v) < 2:
        return dict(games=len(v))
    m = sum(v) / len(v)
    sd = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))
    return dict(games=len(v), rungs=len(rs), said=round(100 * sum(r["p"] for r in rs) / len(rs), 1),
                hit=round(100 * sum(r["hit"] for r in rs) / len(rs), 1),
                edge=round(100 * m, 1), se=round(100 * sd / math.sqrt(len(v)), 1))


def main():
    try:
        with open(os.path.join(ROOT, "data", "ladder_history.json")) as fh:
            book = json.load(fh)
    except (OSError, ValueError):
        print("no ladder history yet")
        return
    fin = finals(book)
    rows = rows_for(book, fin)
    games = sorted({r["gid"] for r in rows}, key=lambda g: book[g]["start"])
    print("graded games", len(games), "rungs", len(rows), flush=True)
    rep = dict(run=dt.date.today().isoformat(), games=len(games), leagues={})
    if len(games) < MIN_GAMES:
        print("not enough graded games yet")
    half = {g: i < len(games) // 2 for i, g in enumerate(games)}
    for lg in FEEDS:
        L = {}
        for side in ("under", "over"):
            base = [r for r in rows if r["league"] == lg and r["side"] == side]
            lock = [r for r in base if LOCK_BAND[0] <= r["p"] <= LOCK_BAND[1]]
            L[side] = dict(lock_band=table(lock),
                           lock_older=table([r for r in lock if half[r["gid"]]]),
                           lock_newer=table([r for r in lock if not half[r["gid"]]]),
                           by_offset={f"{a}-{b}": table([r for r in base if a <= r["off"] < b])
                                      for a, b in ((0, 4), (4, 8), (8, 12), (12, 16))})
        rep["leagues"][lg] = L
        print(lg, json.dumps(L), flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1)


if __name__ == "__main__":
    main()
