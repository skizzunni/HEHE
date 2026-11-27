#!/usr/bin/env python3
"""One pre-game brief for a day: our numbers, then the news, then the lines.

    python3 tools/pregame_brief.py              # today
    python3 tools/pregame_brief.py 2026-11-24
    python3 tools/pregame_brief.py 2026-11-24 --save work/slate_nov24   # also keep a timestamped copy

Saved copies are named brief_HHMM.txt (ET), so a day's checks can be compared
later: what was known at 1:45 PM against what was known at 6:40 PM.

Three sections, each from its own tool, each allowed to fail on its own (a
dead feed prints a one-line note, the rest still prints):
  1. tools/slate_sheet.py      -- price-blind number first, then the DraftKings line
  2. tools/nba_injury_report.py -- the league's official injury report, incl. teams not yet submitted
  3. tools/nhl_goalies.py      -- starting goalies, confirmed or not, flagged when not the usual starter
  4. tools/nfl_weather.py      -- kickoff weather for outdoor NFL games (information only)
     tools/other_side.py       -- the NFL 7.5-14 underdog card at the current line
  5. tools/recheck_ticket.py   -- the day's saved tickets (ticket.json and, when saved,
                                  ticket_safe.json) against the latest news and FanDuel prices
"""
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ET = ZoneInfo("America/New_York")


def _slate(day):
    import slate_sheet
    return "\n".join(slate_sheet.text(r) for r in slate_sheet.main(day)) or "No NBA, NHL or NFL games."


def _injuries(day):
    import nba_injury_report
    d = dt.date.fromisoformat(day)
    return nba_injury_report.report(day=d.strftime("%m/%d/%Y"))


def _goalies(day):
    import nhl_goalies
    return nhl_goalies.text(nhl_goalies.parse(nhl_goalies.fetch(day)), nhl_goalies.team_goalies())


def ticket_path(day, root=None):
    """work/slate_<mon><dd>/ticket.json for `day` (ISO), e.g. work/slate_nov24/ticket.json."""
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = dt.date.fromisoformat(day)
    return os.path.join(root, "work", f"slate_{d:%b%d}".lower(), "ticket.json")


def _ticket(day):
    """The saved ticket re-checked (tools/recheck_ticket.py): injury report,
    NHL lines, FanDuel prices. 2026-11-24: the afternoon and evening routines
    run this brief; the re-check was a separate step they did not name."""
    path = ticket_path(day)
    safe = os.path.join(os.path.dirname(path), "ticket_safe.json")
    found = [p for p in (safe, path) if os.path.exists(p)]
    if not found:
        return f"no saved ticket ({os.path.relpath(path)})"
    import recheck_ticket
    # --final: KEEP / CAUTION / DROP by game, drops recorded for the grader,
    # the morning 2x and stand-in at current prices, a fresh stand-in from
    # games not yet started (2026-11-25: the brief showed only raw flags).
    # 2026-11-26: the safest ticket became the main one; both are re-checked.
    parts = [(f"[{os.path.basename(p)}]\n" if len(found) > 1 else "") + recheck_ticket.main(p, day, final=True)
             for p in found]
    both = shared_players(found)
    if both:
        parts.append("On both tickets (one bad game sinks both -- 2026-11-26: Loveland, 1 target, lost on each): "
                     + ", ".join(both))
    return "\n\n".join(parts)


def shared_players(paths):
    """Players with a leg on every one of the saved tickets."""
    import json
    sets = []
    for p in paths:
        try:
            sets.append({L.get("player") for L in json.load(open(p)) if L.get("player")})
        except (OSError, ValueError):
            return []
    return sorted(set.intersection(*sets)) if len(sets) > 1 else []


def _other(day):
    """The other-side card (tools/other_side.py): NFL dogs getting 7.5-14, with
    the line as it stands now -- a moved line changes whether it qualifies."""
    import other_side
    import slate_sheet
    return other_side.text(other_side.dogs(slate_sheet.main(day)), other_side.forward_from_slates())


def _weather(day):
    import nfl_weather
    import slate_sheet
    return "\n".join(nfl_weather.lines(slate_sheet.main(day))) or "No NFL games."


SECTIONS = (("Our number first, then the line", _slate),
            ("Official NBA injury report", _injuries),
            ("NHL starting goalies", _goalies),
            ("NFL kickoff weather", _weather),
            ("Other side (NFL underdogs getting 7.5-14)", _other),
            ("Your saved ticket, re-checked", _ticket))


def brief(day, sections=SECTIONS):
    out = [f"Pre-game brief, {day} (as of {dt.datetime.now(ET):%I:%M %p} ET)"]
    for title, fn in sections:
        out += ["", f"## {title}"]
        try:
            out.append(fn(day))
        except Exception as e:                    # one dead feed must not sink the brief
            out.append(f"unavailable ({type(e).__name__})")
    return "\n".join(out)


def save(text, folder, now=None):
    """Write text to folder/brief_HHMM.txt (ET) and return the path."""
    now = now or dt.datetime.now(ET)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"brief_{now:%H%M}.txt")
    with open(path, "w") as f:
        f.write(text + "\n")
    return path


if __name__ == "__main__":
    args = sys.argv[1:]
    folder = None
    if "--save" in args:
        i = args.index("--save")
        folder = args[i + 1] if i + 1 < len(args) else "."
        del args[i:i + 2]
    out = brief(__import__("build_ticket").resolve_day(args[0] if args else None))
    print(out)
    if folder:
        print(f"\nsaved: {save(out, folder)}")
