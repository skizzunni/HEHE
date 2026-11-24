#!/usr/bin/env python3
"""Grade a saved list of researched picks against the final scores.

The research picks (the "25" lists) need a record of their own, separate from
the board's, so it can be judged on results rather than on how sure it sounded.

    python3 tools/grade_picks.py work/slate_nov23/final_picks.json

The file is a list of picks:
    {"id": "401910036", "lg": "nba", "kind": "spread", "team": "MEM", "line": -2.5, "price": -116}
    {"id": "401910040", "lg": "nba", "kind": "under", "line": 222.5, "price": -105}
    {"id": "401892773", "lg": "nhl", "kind": "ml", "team": "NJ", "price": -205}
kind is spread (team + line), ml (team), over or under (line). Each pick is
graded won / lost / push / open from ESPN's final score, and the file's
record and flat $1 return are printed.
"""
import json
import sys
import urllib.request

SPORT = {"nba": "basketball/nba", "nhl": "hockey/nhl", "nfl": "football/nfl", "ncaaf": "football/college-football",
         "ncaab": "basketball/mens-college-basketball"}
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/{}/summary?event={}"


def final(lg, gid, get=None, with_clock=False):
    """{abbr: score} and completed flag for one game, from ESPN (and the
    game clock text, e.g. "9:51 - 3rd", when with_clock)."""
    def fetch(u):
        try:
            return json.load(urllib.request.urlopen(u, timeout=30))
        except Exception:
            return None
    d = (get or fetch)(SUMMARY.format(SPORT[lg], gid)) or {}
    comp = ((d.get("header") or {}).get("competitions") or [{}])[0]
    done = bool(((comp.get("status") or {}).get("type") or {}).get("completed"))
    scores = {}
    for c in comp.get("competitors") or []:
        try:
            scores[c["team"]["abbreviation"]] = float(c["score"])
        except (KeyError, TypeError, ValueError):
            pass
    if with_clock:
        return scores, done, ((comp.get("status") or {}).get("type") or {}).get("shortDetail") or ""
    return scores, done


def standing(pick, scores):
    """How an unfinished pick stands right now, in plain words: the margin
    against its line so far ('ahead by 4.5', 'behind by 2', 'level')."""
    if len(scores) != 2:
        return "not started"
    total = sum(scores.values())
    if pick["kind"] == "over":
        need = pick["line"] - total
        return f"{total:g} so far, " + (f"needs {need:g} more" if need > 0 else "already over")
    if pick["kind"] == "under":
        room = pick["line"] - total
        return f"{total:g} so far, " + (f"{room:g} to spare before the line" if room > 0 else "already over the line -- lost")
    else:
        me = scores.get(pick["team"])
        if me is None:
            return "team not found"
        them = next(v for k, v in scores.items() if k != pick["team"])
        d = (me - them) + ((pick.get("line") or 0) if pick["kind"] == "spread" else 0)
        so_far = f"{me:g}-{them:g}"
    word = f"ahead by {d:g}" if d > 0 else f"behind by {-d:g}" if d < 0 else "level"
    return f"{so_far}, {word}"


def grade(pick, scores, done):
    if not done or len(scores) != 2:
        return "open"
    total = sum(scores.values())
    kind = pick["kind"]
    if kind in ("over", "under"):
        d = (total - pick["line"]) * (1 if kind == "over" else -1)
    else:
        me = scores.get(pick["team"])
        if me is None:
            return "open"
        them = next(v for k, v in scores.items() if k != pick["team"])
        d = (me - them) + ((pick.get("line") or 0) if kind == "spread" else 0)
    return "won" if d > 0 else "lost" if d < 0 else "push"


def payout(price):
    price = float(price)
    return price / 100 if price > 0 else 100 / -price


def summary(picks, results):
    done = [(p, r) for p, r in zip(picks, results) if r in ("won", "lost", "push")]
    w = sum(r == "won" for _, r in done)
    l = sum(r == "lost" for _, r in done)
    roi = sum(payout(p["price"]) if r == "won" else -1 if r == "lost" else 0 for p, r in done)
    return dict(won=w, lost=l, push=sum(r == "push" for _, r in done), open=len(picks) - len(done), units=round(roi, 2))


def main(path, get=None):
    picks = json.load(open(path))
    results = []
    for p in picks:
        scores, done = final(p["lg"], p["id"], get)
        results.append(grade(p, scores, done))
    return picks, results, summary(picks, results)


def live(path, get=None):
    """One line per pick: WON/LOST/PUSH when final, else the clock and where it stands."""
    out = []
    for p in json.load(open(path)):
        scores, done, clock = final(p["lg"], p["id"], get, with_clock=True)
        r = grade(p, scores, done)
        tail = "" if r != "open" else f" -- {clock}: {standing(p, scores)}" if scores and any(scores.values()) else f" -- {clock or 'not started'}"
        out.append(f"{r.upper():5} {p.get('label') or p}{tail}")
    return out


if __name__ == "__main__":
    if "--live" in sys.argv:
        print("\n".join(live([a for a in sys.argv[1:] if a != "--live"][0])))
        sys.exit(0)
    picks, results, s = main(sys.argv[1])
    for p, r in zip(picks, results):
        print(f"{r.upper():5} {p.get('label') or p}")
    print(f"Record {s['won']}-{s['lost']}" + (f"-{s['push']}" if s["push"] else "")
          + f", {s['open']} open, {s['units']:+.2f} units at $1 a pick")
