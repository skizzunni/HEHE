#!/usr/bin/env python3
"""Re-check a saved ticket against the latest official NBA injury report.

The ticket is built at 8 AM from the morning report, but statuses move all
day: a prop player ruled out at 5 PM stays on a saved ticket unless someone
looks again. This reads the saved legs (build_ticket.py --save) and the
latest report, and prints every leg that now needs attention:

  * a prop on a player now Out / Doubtful / Questionable (build_ticket drops
    those at build time; here they are flagged, the ticket is the user's)
  * an NBA moneyline whose team now has a top-minutes player Out / Doubtful /
    Questionable (a caution: priced in on the record, README 2026-11-24)

    python3 tools/recheck_ticket.py work/slate_nov24/ticket.json [today]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BAD = ("Out", "Doubtful", "Questionable")


def recheck(legs, status_fn, team_out_fn=None):
    """[(leg label, note)] for legs that need a look. status_fn(display name)
    -> report status or None; team_out_fn(team abbr) -> [(name, min, status)]."""
    out = []
    for L in legs:
        if L.get("lg") != "nba":
            continue
        if L.get("kind") == "prop":
            st = status_fn(L.get("player") or "")
            if st in BAD:
                out.append((L.get("label"), f"{L.get('player')} is now {st} on the official report"))
        elif L.get("kind") == "ml" and team_out_fn:
            try:
                miss = team_out_fn(L.get("team"))
            except Exception:
                miss = []
            if miss:
                out.append((L.get("label"), "caution: " + ", ".join(f"{n} ({s})" for n, _, s in miss)))
    return out


def text(flags, asof=None):
    head = f"Ticket re-check against the official NBA injury report{f' of {asof}' if asof else ''}:"
    if not flags:
        return head + " no leg affected."
    return "\n".join([head] + [f"  {lab} -- {note}" for lab, note in flags])


def main(path, day):
    import datetime as dt
    import key_absences as K
    import nba_injury_report as R
    _, txt = R.latest()
    rep = R.parse(txt or "") if txt else {"rows": [], "asof": None}
    mmdd = dt.date.fromisoformat(day).strftime("%m/%d/%Y")
    status = {r["player"]: r["status"] for r in rep["rows"] if r["date"] == mmdd}   # report names are unique enough
    team_out = lambda abbr: K.key_missing(K.recent_minutes(abbr, day), status)
    legs = json.load(open(path))
    return text(recheck(legs, lambda n: status.get(K.report_name(n)), team_out), rep.get("asof"))


if __name__ == "__main__":
    import build_ticket as B
    print(main(sys.argv[1], B.resolve_day(sys.argv[2] if len(sys.argv) > 2 else None)))
