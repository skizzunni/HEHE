#!/usr/bin/env python3
"""One pre-game brief for a day: our numbers, then the news, then the lines.

    python3 tools/pregame_brief.py              # today
    python3 tools/pregame_brief.py 2026-11-24

Three sections, each from its own tool, each allowed to fail on its own (a
dead feed prints a one-line note, the rest still prints):
  1. tools/slate_sheet.py      -- price-blind number first, then the DraftKings line
  2. tools/nba_injury_report.py -- the league's official injury report, incl. teams not yet submitted
  3. tools/nhl_goalies.py      -- starting goalies, confirmed or not, flagged when not the usual starter
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


SECTIONS = (("Our number first, then the line", _slate),
            ("Official NBA injury report", _injuries),
            ("NHL starting goalies", _goalies))


def brief(day, sections=SECTIONS):
    out = [f"Pre-game brief, {day} (as of {dt.datetime.now(ET):%I:%M %p} ET)"]
    for title, fn in sections:
        out += ["", f"## {title}"]
        try:
            out.append(fn(day))
        except Exception as e:                    # one dead feed must not sink the brief
            out.append(f"unavailable ({type(e).__name__})")
    return "\n".join(out)


if __name__ == "__main__":
    print(brief(sys.argv[1] if len(sys.argv) > 1 else dt.datetime.now(ET).date().isoformat()))
