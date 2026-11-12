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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def safe_note(L):
    """For an open leg already decided on the field: 'line reached' for an N+
    prop, 'already over (T, line X)' for a game over, 'gone over ...
    -- lost' for a game or team under. '' otherwise."""
    import re
    if (L.get("status") or "open") != "open":
        return ""
    need = re.match(r"^\s*(\d+(?:\.\d+)?)\+\s*$", str(L.get("line") or ""))
    if need and L.get("so_far") is not None and float(L["so_far"]) >= float(need.group(1)):
        return "line reached"                # no running count: one alert, not one per stat
    if need and L.get("so_far") is not None and L.get("live"):
        try:                                 # past halftime and behind the pace the line needs
            import daily_review as dr
            F = dr._PERIODS.get(L.get("league") or "")
            el = dr._elapsed(str(L["live"]), *F) if F else None
            pp = dr.prop_pace(L)
            if el and el >= 0.5 * F[0] * F[1] and pp and "behind" in pp:
                return "behind pace after halftime"
        except Exception:
            pass
    m = re.match(r"^Over\s+([\d.]+)", str(L.get("label") or ""), re.I)
    pts = [int(x) for x in re.findall(r"-?\d+(?=\s*(?:-|$))", str(L.get("live_score") or ""))]
    if m and len(pts) >= 2 and pts[-2] + pts[-1] > float(m.group(1)):
        return f"already over ({pts[-2] + pts[-1]}, line {m.group(1)})"
    # a "to win" leg down big after halftime (basketball and football only:
    # a 10-point hole means little in hockey or soccer scoring)
    w = re.match(r"^(.+?)\s+to win$", str(L.get("label") or ""))
    if w and L.get("live") and L.get("league") in ("nba", "ncaab", "wnba", "nfl", "ncaaf"):
        try:
            import daily_review as dr
            F = dr._PERIODS.get(L.get("league") or "")
            el = dr._elapsed(str(L["live"]), *F) if F else None
            parts = re.split(r"\s+-\s+", str(L.get("live_score") or ""))
            mine = next((x for x in parts if x.startswith(w.group(1))), None)
            other = next((x for x in parts if not x.startswith(w.group(1))), None)
            a, b = (re.search(r"(-?\d+)\s*$", x or "") for x in (mine, other))
            if el and el >= 0.5 * F[0] * F[1] and a and b and int(b.group(1)) - int(a.group(1)) >= 10:
                return "down 10+ after halftime"
        except Exception:
            pass
    # a game or team total past halftime whose pace is on the wrong side
    if re.search(r"(^(Over|Under)\s|\s(over|under)\s)[\d.]+", str(L.get("label") or ""), re.I) and L.get("live"):
        try:
            import daily_review as dr
            F = dr._PERIODS.get(L.get("league") or "")
            el = dr._elapsed(str(L["live"]), *F) if F else None
            pt = dr.pace_text(L)
            if el and el >= 0.5 * F[0] * F[1] and pt and "behind the pace" in pt:
                return "off pace after halftime"
        except Exception:
            pass
    # an under that has already gone over is lost before the final
    u = re.match(r"^Under\s+([\d.]+)", str(L.get("label") or ""), re.I)
    if u and len(pts) >= 2 and pts[-2] + pts[-1] > float(u.group(1)):
        return f"gone over ({pts[-2] + pts[-1]}, line {u.group(1)}) -- lost"
    to = re.match(r"^(.+?)\s+over\s+([\d.]+)", str(L.get("label") or ""), re.I)
    if to:                                   # a team total over already cleared
        part = next((x for x in re.split(r"\s+-\s+", str(L.get("live_score") or "")) if x.startswith(to.group(1))), None)
        v = re.search(r"(-?\d+)\s*$", part or "")
        if v and int(v.group(1)) > float(to.group(2)):
            return f"already over ({v.group(1)}, line {to.group(2)})"
    t = re.match(r"^(.+?)\s+under\s+([\d.]+)", str(L.get("label") or ""), re.I)
    if t:
        part = next((x for x in re.split(r"\s+-\s+", str(L.get("live_score") or "")) if x.startswith(t.group(1))), None)
        v = re.search(r"(-?\d+)\s*$", part or "")
        if v and int(v.group(1)) > float(t.group(2)):
            return f"gone over ({v.group(1)}, line {t.group(2)}) -- lost"
    return ""


def snapshot(report):
    """{label: status/score} for today's legs, or {"SETTLED": "..."}."""
    t = report.get("today")
    if not t:
        last = report.get("last") or {}
        return {"SETTLED": f"{last.get('day')} {last.get('result')} bank {report.get('bank')}"}
    out = {}
    for L in t["legs"]:
        v = (L.get("status") or "open") + (f" | {L['score']}" if L.get("score") else "")
        note = safe_note(L)
        out[L["label"]] = v + (f" | {note}" if note else "")
    return out


def games_snapshot(book, day, league):
    """{"GAME <matchup>": "board pick <pick> = <status> | <score>"} for every
    board pick in `league` on `day` (ledger.json rows). league "all": every
    league, keyed "GAME <league> <matchup>", with the stated chance and, for a
    loss, the ledger's diagnosis (why it lost)."""
    out = {}
    for v in book.values():
        if not isinstance(v, dict) or v.get("date") != day or (league != "all" and v.get("league") != league):
            continue
        st = v.get("status") or "open"
        sc = v.get("scores") or {}
        key = f"GAME {v.get('league')} {v.get('matchup')}" if league == "all" else f"GAME {v.get('matchup')}"
        pick = v.get("pick") + (" or draw" if v.get("dc") else "")
        conf = f" ({round(v['conf'])}%)" if league == "all" and v.get("conf") is not None else ""
        why = f" | why: {v['diagnosis']}" if league == "all" and st == "lost" and v.get("diagnosis") else ""
        out[key] = (f"board pick {pick}{conf} = {st}"
                    + (" | " + ", ".join(f"{k} {n}" for k, n in sc.items()) if st != "open" and sc else "") + why)
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
    # a feed gap (live score briefly missing) must not undo a note already
    # seen: an open leg with no note keeps the note it had
    for k, v in list(after.items()):
        if v == "open" and str(before.get(k, "")).startswith("open | "):
            after[k] = before[k]
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
