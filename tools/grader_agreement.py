#!/usr/bin/env python3
"""Does the ticket grader (tools/grade_picks.py) settle props the way the
board did? Re-grades the last N graded board props from ESPN and counts the
agreements -- a check before trusting the live tracker on a market.

2026-11-25: run before the first NFL props on a fallback ticket (GB @ LAR):
25 of 25 recent NFL Passing / Receiving Yards props agreed.

    python3 tools/grader_agreement.py nfl 25
    python3 tools/grader_agreement.py nba 40 "Pts + Reb + Ast"
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sample(props, league, n, market=None):
    """The last n graded (won/lost) board props for a league (and market)."""
    rows = [e for e in props.values() if isinstance(e, dict) and e.get("league") == league
            and e.get("status") in ("won", "lost") and e.get("gid") and e.get("market")
            and (market is None or e.get("market") == market)]
    rows.sort(key=lambda e: e.get("date") or "")
    return rows[-n:]


def agreement(rows, get=None):
    """(agree, [(name, market, line, board, ours)]) re-grading each row."""
    import grade_picks as G
    get = G._once(get)
    agree, bad = 0, []
    for e in rows:
        lt = str(e["line"])
        try:
            line = float(lt.rstrip("+"))
        except ValueError:
            continue
        lg, gid = e["gid"].split(":", 1)
        p = dict(lg=lg, id=gid, kind="prop", player=e["name"], stat="", market=e["market"], line=line, line_text=lt)
        scores, done, _, d = G.final(lg, gid, get, with_clock=True, raw=True)
        ours = G.grade(p, scores, done, d)
        if ours == e["status"]:
            agree += 1
        else:
            bad.append((e["name"], e["market"], lt, e["status"], ours))
    return agree, bad


if __name__ == "__main__":
    lg = sys.argv[1] if len(sys.argv) > 1 else "nba"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 25
    market = sys.argv[3] if len(sys.argv) > 3 else None
    rows = sample(json.load(open(os.path.join(ROOT, "props.json"))), lg, n, market)
    ok, bad = agreement(rows)
    print(f"{lg}{' ' + market if market else ''}: {ok} of {ok + len(bad)} agree with the board")
    for b in bad:
        print("  differs:", *b)
