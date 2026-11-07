"""Ladder watcher: one line per ladder leg whose result changed, and one when
the ticket settles. Run it in a loop next to a checkout that the board bot
keeps up to date; the last state is kept in a file so a restart never misses
or repeats a change.

    python tools/ladder_watch.py STATE_FILE      # prints CHANGE / SETTLED lines
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


def changes(before, after):
    """Lines for every leg whose state moved, plus the settle line."""
    if "SETTLED" in after:
        return [] if before.get("SETTLED") == after["SETTLED"] else [f"SETTLED: {after['SETTLED']}"]
    return [f"CHANGE: {k} = {v}" for k, v in after.items() if before and before.get(k) != v]


def main(state_path):
    import ladder
    try:
        with open(state_path) as fh:
            before = json.load(fh)
    except (OSError, ValueError):
        before = {}
    after = snapshot(ladder.report())
    for line in changes(before, after):
        print(line, flush=True)
    with open(state_path, "w") as fh:
        json.dump(after, fh)
    return 0 if "SETTLED" not in after else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
