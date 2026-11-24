#!/usr/bin/env python3
"""Grade a saved list of researched picks against the final scores.

The research picks (the "25" lists) need a record of their own, separate from
the board's, so it can be judged on results rather than on how sure it sounded.

    python3 tools/grade_picks.py work/slate_nov23/final_picks.json

The file is a list of picks:
    {"id": "401910036", "lg": "nba", "kind": "spread", "team": "MEM", "line": -2.5, "price": -116}
    {"id": "401910040", "lg": "nba", "kind": "under", "line": 222.5, "price": -105}
    {"id": "401892773", "lg": "nhl", "kind": "ml", "team": "NJ", "price": -205}
    {"id": "401910045", "lg": "nba", "kind": "prop", "player": "Keegan Murray", "stat": "PTS", "line": 5, "price": -4500}
kind is spread (team + line), ml (team), over or under (line), or prop: a
player reaching `line` or more of `stat` (PTS, REB, AST, 3PM, STL, BLK, or a
sum like PTS+AST) from the box score -- won as soon as he reaches it. Each pick is
graded won / lost / push / open from ESPN's final score, and the file's
record and flat $1 return are printed.
"""
import json
import os
import sys
import urllib.request

SPORT = {"nba": "basketball/nba", "nhl": "hockey/nhl", "nfl": "football/nfl", "ncaaf": "football/college-football",
         "ncaab": "basketball/mens-college-basketball"}
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/{}/summary?event={}"
VOID_STATES = ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED", "STATUS_SUSPENDED", "STATUS_FORFEIT")


def _num(v):
    try:
        return float(str(v).split("-")[0])
    except (TypeError, ValueError):
        return None


def player_stat(summary, player, stat):
    """A player's stat (or a sum like PTS+AST) from an ESPN summary's box
    score; 3PM is made threes. None when he is not in the box score."""
    for t in ((summary or {}).get("boxscore") or {}).get("players") or []:
        for cat in t.get("statistics") or []:
            row = {a["athlete"]["displayName"]: dict(zip(cat.get("labels") or [], a.get("stats") or []))
                   for a in cat.get("athletes") or []}
            if player not in row:
                continue
            got = row[player]
            if not got:
                return 0.0                      # listed, did not play
            total = 0.0
            for part in stat.upper().split("+"):
                v = _num(got.get("3PT")) if part == "3PM" else _num(got.get(part))
                if v is None:
                    return None
                total += v
            return total
    return None


def _dnp(summary, player):
    """True when the player is in the box score with no stats (did not play)."""
    for t in ((summary or {}).get("boxscore") or {}).get("players") or []:
        for cat in t.get("statistics") or []:
            for a in cat.get("athletes") or []:
                if (a.get("athlete") or {}).get("displayName") == player:
                    return bool(a.get("didNotPlay")) or not a.get("stats")
    return False


def final(lg, gid, get=None, with_clock=False, raw=False):
    """{abbr: score} and completed flag for one game, from ESPN (and the
    game clock text, e.g. "9:51 - 3rd", when with_clock)."""
    def fetch(u):
        try:
            return json.load(urllib.request.urlopen(u, timeout=30))
        except Exception:
            return None
    d = (get or fetch)(SUMMARY.format(SPORT[lg], gid)) or {}
    comp = ((d.get("header") or {}).get("competitions") or [{}])[0]
    stype = (comp.get("status") or {}).get("type") or {}
    done = bool(stype.get("completed"))
    scores = {}
    if stype.get("name") in VOID_STATES:
        # 2026-11-24: a postponed game never reads "completed", so --watch would
        # wait on it forever; books void such legs, so it settles as a push
        scores, done = {"_void": stype.get("name")}, True
    for c in comp.get("competitors") or []:
        try:
            scores[c["team"]["abbreviation"]] = float(c["score"])
        except (KeyError, TypeError, ValueError):
            pass
    if with_clock:
        clock = ((comp.get("status") or {}).get("type") or {}).get("shortDetail") or ""
        return (scores, done, clock, d) if raw else (scores, done, clock)
    return (scores, done, d) if raw else (scores, done)


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


def board_value(pick, summary):
    """(value, how) for a prop's player stat the way the board reads it
    (props_ledger's market -> stat map and player matching). value is None
    when the market is unknown or the player is not found; how is
    props_ledger's match note ('absent' = did not play)."""
    lg, market = pick.get("lg"), pick.get("market")
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import props_ledger
        fn = (props_ledger.MARKETS.get(lg) or {}).get(market)
    except Exception:
        return None, None
    if not fn or not summary:
        return None, None
    st, how = props_ledger.resolve(props_ledger.box_stats(summary), {"name": pick["player"]})
    if how == "absent" or st is None:
        return None, how
    if not st:
        # listed but no stats: dressed, did not play (ESPN didNotPlay, e.g. a
        # coach's decision). FanDuel voids such props; 2026-11-24 this graded LOST
        return None, "absent"
    try:
        return fn(st), how
    except Exception:
        return None, how


def board_prop(pick, summary):
    """('won'|'lost'|'void'|None) for a prop graded exactly as the board grades
    it (props_ledger: its market -> stat map, player matching, line rules);
    None when the pick carries no market the board knows. 2026-11-24: NHL
    'Shots on Goal' has no plain box-score label, so the label path returned
    nothing and a winning shots prop would have been graded LOST."""
    value, how = board_value(pick, summary)
    if how == "absent":
        return "void"
    if value is None:
        return None
    import props_ledger
    ok = props_ledger.won(pick.get("lg"), pick.get("market"), pick.get("line_text") or f"{pick['line']:g}+", value)
    return None if ok is None else ("won" if ok else "lost")


def grade(pick, scores, done, summary=None):
    if scores.get("_void"):
        return "push"
    if pick["kind"] == "prop" and pick.get("market"):
        r = board_prop(pick, summary)
        if r == "won":
            return "won"
        if r == "lost":
            return "lost" if done else "open"
        if r == "void":
            return "push" if done else "open"
    if pick["kind"] == "prop":
        if _dnp(summary, pick["player"]):
            return "push" if done else "open"
        v = player_stat(summary, pick["player"], pick["stat"])
        if v is not None and v >= pick["line"]:
            return "won"
        return "lost" if done else "open"
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
        scores, done, d = final(p["lg"], p["id"], get, raw=True)
        results.append(grade(p, scores, done, d))
    return picks, results, summary(picks, results)


def _once(get):
    """A fetch that reads each URL once per round: legs on the same game share
    one ESPN call (13 legs on 4 games were 13 calls every 2 minutes)."""
    seen = {}

    def fetch(u):
        if u not in seen:
            seen[u] = (get or _fetch)(u)
        return seen[u]
    return fetch


def _fetch(u):
    try:
        return json.load(urllib.request.urlopen(u, timeout=30))
    except Exception:
        return None


def live(path, get=None):
    """One line per pick: WON/LOST/PUSH when final, else the clock and where it stands."""
    out = []
    get = _once(get)
    for p in json.load(open(path)):
        scores, done, clock, d = final(p["lg"], p["id"], get, with_clock=True, raw=True)
        r = grade(p, scores, done, d)
        if p["kind"] == "prop" and r == "open":
            v = board_value(p, d)[0] if p.get("market") else None
            if v is None:
                v = player_stat(d, p["player"], p["stat"])
            have = "not in the box score yet" if v is None else f"{v:g} of {p['line']:g}"
            out.append(f"OPEN  {p.get('label') or p} -- {clock}: {have}")
            continue
        tail = "" if r != "open" else f" -- {clock}: {standing(p, scores)}" if scores and any(scores.values()) else f" -- {clock or 'not started'}"
        out.append(f"{r.upper():5} {p.get('label') or p}{tail}")
    return out


def watch(path, every=120, get=None, sleep=None, emit=print):
    """Print each pick once when it settles (WON / LOST / PUSH), then a last
    line when none is left open."""
    import time
    seen = {}
    while True:
        picks = json.load(open(path))
        open_n = 0
        fetch = _once(get)                      # fresh each round, shared within it
        for p in picks:
            scores, done, d = final(p["lg"], p["id"], fetch, raw=True)
            r = grade(p, scores, done, d)
            key = p.get("label") or json.dumps(p, sort_keys=True)
            if r == "open":
                open_n += 1
            elif seen.get(key) != r:
                seen[key] = r
                emit(f"{r.upper()} {key}")
        if not open_n:
            emit("all picks settled")
            return seen
        (sleep or time.sleep)(every)


if __name__ == "__main__":
    if "--watch" in sys.argv:
        watch([a for a in sys.argv[1:] if a != "--watch"][0], emit=lambda m: print(m, flush=True))
        sys.exit(0)
    if "--live" in sys.argv:
        print("\n".join(live([a for a in sys.argv[1:] if a != "--live"][0])))
        sys.exit(0)
    picks, results, s = main(sys.argv[1])
    for p, r in zip(picks, results):
        print(f"{r.upper():5} {p.get('label') or p}")
    print(f"Record {s['won']}-{s['lost']}" + (f"-{s['push']}" if s["push"] else "")
          + f", {s['open']} open, {s['units']:+.2f} units at $1 a pick")
