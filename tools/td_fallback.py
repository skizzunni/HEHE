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
    python3 tools/td_fallback.py today --save work/slate_nov26/ticket_td.json
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


# README 2026-11-25: on 2,500 graded NFL anytime-TD props the model ran low in
# both date halves (14.0% hit vs 11.7% stated, z +2.62; 13.7% vs 11.5%, z
# +2.54 -- just under the 2.8 bar), while FanDuel's own price was close
# (15.1% / 14.8%, z -1.20 / -1.28). Both are shown; neither is changed.
NOTE = ("(Model chances have run about 2 points low on 2,500 graded NFL TD props, in both halves; "
        "FanDuel's own price has been closer -- the true chance has sat between the two.)")


def text(games):
    lines = [NOTE] if games else []
    for g in games:
        lines.append(f"{g['match']} (total {g['total']:g}; {g['basis']})" if g.get("total") else f"{g['match']} ({g['basis']})")
        for p in g["players"]:
            fd = f", FanDuel {100 * p['imp']:.0f}%" if p.get("imp") else ""
            hurt = (f" -- {p['status']} on the injury report" + (", left off the saved list" if p["status"] in OFF else "")
                    if p.get("status") else "")
            lines.append(f"  {p['name']}: anytime {100 * p['p']:.0f}% ({p.get('price')}{fd}), 2+ {100 * p['p2']:.0f}%, "
                         f"first TD {100 * p['pfirst']:.0f}%{hurt}")
    return "\n".join(lines) or "No NFL anytime-TD market posted yet."


def main(day, rows_fn=rows, fd=None):
    import td_scorers
    import fanduel
    FD = fd if fd is not None else fanduel.load()
    return [g for g in (td_scorers.for_game(r, "nfl", FD) for r in rows_fn(day)) if g]


OFF = ("Out", "Doubtful", "Questionable")


def mark_injured(games, status_fn):
    """Attach each player's injury-report status (status_fn: name -> status or
    None); 2026-11-26: the TD list had no injury check at all."""
    for g in games:
        for p in g["players"]:
            try:
                st = status_fn(p["name"])
            except Exception:
                st = None
            if st:
                p["status"] = st
    return games


def legs(games, top=2):
    """The likeliest `top` anytime scorers per game as ticket legs, in
    grade_picks' file format (the board grades this market from the box
    score), so a saved list keeps its own record."""
    out = []
    for g in games:
        for p in [p for p in g["players"] if p.get("status") not in OFF][:top]:   # injured players left off
            out.append(dict(label=f"{p['name']}: anytime TD {p.get('price')} ({100 * p['p']:.0f}%)",
                            id=str(g["id"]).split(":")[-1], lg="nfl", kind="prop", player=p["name"], stat="TD",
                            market="Anytime Touchdown Scorer", line=1.0, line_text="1+", price=p.get("price")))
    return out


if __name__ == "__main__":
    import build_ticket as B
    args = sys.argv[1:]
    save = None
    if "--save" in args:
        i = args.index("--save")
        save = args[i + 1]
        del args[i:i + 2]
    day = B.resolve_day(args[0] if args else None)
    games = main(day)
    try:
        mark_injured(games, B._report_status(day))
    except Exception as ex:                       # the list still prints, and says so
        print(f"(injury report unavailable: {type(ex).__name__} -- check players before betting)")
    print(text(games))
    if save and games:
        if os.path.exists(save) and "--force" not in sys.argv:
            print(f"\nnot saved: {save} already exists")
        else:
            os.makedirs(os.path.dirname(save) or ".", exist_ok=True)
            json.dump(legs(games), open(save, "w"), indent=1)
            print(f"\nsaved: {save} (the top 2 anytime scorers per game; grade with tools/grade_picks.py)")
