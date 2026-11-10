"""Ladder watcher: one line per ladder leg whose result changed, and one when
the ticket settles. Run it in a loop next to a checkout that the board bot
keeps up to date; the last state is kept in a file so a restart never misses
or repeats a change.

    python tools/ladder_watch.py STATE_FILE      # prints CHANGE / SETTLED lines
    python tools/ladder_watch.py STATE_FILE 2026-11-09 nba
        # also every board pick in that league on that day (GAME lines), for a
        # ticket of your own; exits 3 only once the ladder and those games settle
    python tools/ladder_watch.py STATE_FILE [DAY LEAGUE] --loop 120 [--branch B]
        # in a spare checkout: pull the branch, check, sleep, repeat until settled
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
    if not before:                       # first look: say what is being watched
        for k, v in after.items():
            print(f"WATCHING: {k} = {v}", flush=True)
    for line in changes(before, after):
        print(line, flush=True)
    with open(state_path, "w") as fh:
        json.dump(after, fh)
    return 3 if done(after) else 0


def loop(args, every, branch, run=None, pull=None, sleep=None):
    """Pull the branch, report changes, sleep; stop once main() says settled."""
    import subprocess
    import time
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pull = pull or (lambda: subprocess.run(
        f"timeout 120 git fetch -q --no-tags --depth=20 origin {branch} && git reset -q --hard FETCH_HEAD",
        shell=True, cwd=root, capture_output=True))
    run = run or (lambda: subprocess.run([sys.executable, os.path.abspath(__file__)] + list(args), cwd=root).returncode)
    sleep = sleep or time.sleep
    while True:
        pull()
        if run() == 3:
            print("DONE: the ladder ticket and the watched games have settled", flush=True)
            return 0
        sleep(every)


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--loop" in a:
        i = a.index("--loop")
        every = int(a[i + 1])
        branch = a[a.index("--branch") + 1] if "--branch" in a else "claude/mlb-picks-review-jlx9w1"
        rest = [x for j, x in enumerate(a) if j not in (i, i + 1) and x != "--branch"
                and not (j > 0 and a[j - 1] == "--branch")]
        sys.exit(loop(rest, every, branch))
    sys.exit(main(*a[:3]))
