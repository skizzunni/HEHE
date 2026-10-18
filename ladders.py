"""FanDuel's alternate ladders for every football game, kept until kickoff.

At the same FanDuel price, far NFL overs have hit 3-4 points more often than
far unders in both seasons of finished games (tools/totals_lab.py), but one
week of FanDuel ladders (probe round 30) cannot show FanDuel always prices
them that way, and ESPN keeps no alternate prices once a game is over. So
every rebuild writes each game's ladder here, overwriting it until kickoff;
what remains is the last pre-game price of every rung. tools/ladder_lab.py
grades them against final scores.
"""
import datetime as dt
import json
import os

import fanduel

HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY = os.path.join(HERE, "data", "ladder_history.json")
LEAGUES = ("nfl", "ncaaf")


def _load():
    try:
        with open(HISTORY) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _started(m, now):
    try:
        t = dt.datetime.fromisoformat(str(m.get("start")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return t <= now


def log(slots, now=None):
    """`slots`: board slots ({league: [row]}). Returns games whose ladder changed."""
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        FD = fanduel.load()
    except Exception:
        return 0
    book, n = _load(), 0
    for slot in slots:
        for league in LEAGUES:
            for row in (slot or {}).get(league) or []:
                m = row.get("mkt") or {}
                if not m.get("start") or _started(m, now):
                    continue                     # the last pre-game ladder stands
                g = fanduel.find(FD, league, m.get("away"), m.get("home"))
                if not g:
                    continue
                main = (g.get("total") or {}).get("over") or [None, None]
                rungs, spreads = {}, []
                for kind, team, side, L, ref, price, where in fanduel.load_alts(g):
                    if not price:
                        continue
                    if kind == "total":
                        rungs.setdefault(str(float(L)), {})[side] = price
                    elif kind == "spread":
                        spreads.append([team, float(L), price])
                if not rungs:
                    continue
                e = dict(league=league, start=m["start"], home=m.get("home"),
                         away=m.get("away"), total=main[0],
                         total_price=(g.get("px") or {}).get(main[1]),
                         ladder=rungs, spreads=sorted(spreads))
                old = dict(book.get(row["id"]) or {})
                old.pop("logged", None)
                if old == e:
                    continue                     # unchanged: no write, no commit
                book[row["id"]] = dict(e, logged=now.isoformat(timespec="minutes"))
                n += 1
    if n:
        os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
        with open(HISTORY, "w") as fh:
            json.dump(book, fh, indent=0, sort_keys=True)
    return n
