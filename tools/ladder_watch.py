"""Ladder watcher: one line per ladder leg whose result changed, and one when
the ticket settles. Run it in a loop next to a checkout that the board bot
keeps up to date; the last state is kept in a file so a restart never misses
or repeats a change.

    python tools/ladder_watch.py STATE_FILE      # prints CHANGE / SETTLED lines
    python tools/ladder_watch.py STATE_FILE 2026-11-09 nba
        # also every board pick in that league on that day (GAME lines), for a
        # ticket of your own; exits 3 only once the ladder and those games settle
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def snapshot(report):
    """{label: status/score} for today's legs, or {"SETTLED": "..."}."""
    t = report.get("today")
    if not t:
        last = report.get("last") or {}
        return {"SETTLED": f"{last.get('day')} {last.get('result')} bank {report.get('bank')}"}
    return {L["label"]: (L.get("status") or "open") + (f" | {L['score']}" if L.get("score") else "") for L in t["legs"]}


def games_snapshot(book, day, league):
    """{"GAME <matchup>": "board pick <pick> = <status> | <score>"} for every
    board pick in `league` on `day` (ledger.json rows)."""
    out = {}
    for v in book.values():
        if not isinstance(v, dict) or v.get("date") != day or v.get("league") != league:
            continue
        st = v.get("status") or "open"
        sc = v.get("scores") or {}
        out[f"GAME {v.get('matchup')}"] = (f"board pick {v.get('pick')} = {st}"
                                          + (" | " + ", ".join(f"{k} {n}" for k, n in sc.items()) if st != "open" and sc else ""))
    return out


def changes(before, after):
    """Lines for every leg or game whose state moved, plus the settle line."""
    out = [f"CHANGE: {k} = {v}" for k, v in after.items()
           if k != "SETTLED" and before and before.get(k) != v]
    if "SETTLED" in after and before.get("SETTLED") != after["SETTLED"]:
        out.append(f"SETTLED: {after['SETTLED']}")
    return out


def done(after):
    """The ladder has settled and no watched game is still open."""
    return "SETTLED" in after and not any(str(v).split(" | ")[0].endswith("= open")
                                         for k, v in after.items() if k.startswith("GAME "))


def main(state_path, day=None, league=None):
    import ladder
    try:
        with open(state_path) as fh:
            before = json.load(fh)
    except (OSError, ValueError):
        before = {}
    after = snapshot(ladder.report())
    if day and league:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            with open(os.path.join(root, "ledger.json")) as fh:
                after.update(games_snapshot(json.load(fh), day, league))
        except (OSError, ValueError):
            pass
    for line in changes(before, after):
        print(line, flush=True)
    with open(state_path, "w") as fh:
        json.dump(after, fh)
    return 3 if done(after) else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
