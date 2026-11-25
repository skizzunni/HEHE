#!/usr/bin/env python3
"""NFL touchdown scorers for a day the board did not build (workflows off).

td_scorers.for_game needs one row per game -- teams and the posted total --
which the board normally supplies. This builds those rows from ESPN's
scoreboard (DraftKings total via the game summary) and runs the board's own
model on FanDuel's anytime-TD market: anytime, 2+ and first-TD chances,
margin removed and scaled to the game's expected touchdowns.

2026-11-25: Thanksgiving (3 NFL games) with the board off; the user asked
for "who will score first touchdown, score 2+ touchdown" on NFL days.

    python3 tools/td_fallback.py tomorrow
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SB = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={}"
SUM = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={}"


def _get(u):
    try:
        return json.load(urllib.request.urlopen(u, timeout=30))
    except Exception:
        return None


def rows(day, get=_get):
    """td_scorers-shaped rows: {id, label, tip, mkt: {away, home, total}}."""
    out = []
    for ev in (get(SB.format(day.replace("-", ""))) or {}).get("events") or []:
        comp = ev["competitions"][0]
        t = {c["homeAway"]: c["team"] for c in comp["competitors"]}
        pc = ((get(SUM.format(ev["id"])) or {}).get("pickcenter") or [{}])[0]
        out.append(dict(id=f"nfl:{ev['id']}", label=ev.get("shortName"), tip=ev.get("date"),
                        mkt=dict(away=t["away"].get("displayName"), home=t["home"].get("displayName"),
                                 total=pc.get("overUnder"))))
    return out


def text(games):
    lines = []
    for g in games:
        lines.append(f"{g['match']} (total {g['total']:g}; {g['basis']})" if g.get("total") else f"{g['match']} ({g['basis']})")
        for p in g["players"]:
            lines.append(f"  {p['name']}: anytime {100 * p['p']:.0f}% ({p.get('price')}), 2+ {100 * p['p2']:.0f}%, "
                         f"first TD {100 * p['pfirst']:.0f}%")
    return "\n".join(lines) or "No NFL anytime-TD market posted yet."


def main(day, rows_fn=rows, fd=None):
    import td_scorers
    import fanduel
    FD = fd if fd is not None else fanduel.load()
    return [g for g in (td_scorers.for_game(r, "nfl", FD) for r in rows_fn(day)) if g]


if __name__ == "__main__":
    import build_ticket as B
    day = B.resolve_day(sys.argv[1] if len(sys.argv) > 1 else None)
    print(text(main(day)))
