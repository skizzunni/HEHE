#!/usr/bin/env python3
"""Which NBA teams are missing key players today.

Nov 23, 2026: the Raptors (-450, without Leonard and Barrett) and the Thunder
(-190, without eight rotation players) both lost as favourites on the user's
ticket. A winner goes on the ticket only if none of its key players is out
or doubtful. "Key" here means among the team's top KEY_N players by minutes
over its last 10 games -- measured from the box scores, not from reputation.
A player out all season does not show up in recent minutes; the price already
assumes he is missing.

    python3 tools/key_absences.py              # today's NBA games
    python3 tools/key_absences.py 2026-11-24
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ET = ZoneInfo("America/New_York")
KEY_N = 6
LAST_GAMES = 10
MIN_PLAYED = 3        # games played (of the last LAST_GAMES) to count a player's minutes
SCHED = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{}/schedule"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={}"
SCORE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={}"
FLAG = ("Out", "Doubtful")
WATCH = ("Questionable",)


def _get(url):
    try:
        return json.load(urllib.request.urlopen(url, timeout=30))
    except Exception:
        return None


def _et_day(when):
    """ISO ET calendar day of an ESPN UTC timestamp ('2026-11-24T00:00Z' -> '2026-11-23').
    2026-11-24: comparing the raw UTC date left out the team's game from the
    night before (7 PM ET is the next day in UTC)."""
    import datetime as _dt
    if "T" not in str(when or ""):
        return str(when or "")[:10]                 # a bare date is already a calendar day
    try:
        return _dt.datetime.fromisoformat(str(when).replace("Z", "+00:00")).astimezone(ET).date().isoformat()
    except ValueError:
        return str(when or "")[:10]


def recent_minutes(abbr, before, get=_get):
    """{player display name: minutes per game PLAYED} over the team's last
    LAST_GAMES completed games before `before` (an ISO date), for players who
    played at least MIN_PLAYED of them. Per game played, not per team game:
    2026-11-23 audit -- Evan Mobley (Out, toe) had played 3 of Cleveland's last
    8, so his per-team-game average left him off the key list and the
    Cavaliers (-350) were not flagged; they lost by 14."""
    ev = [e for e in ((get(SCHED.format(abbr.lower())) or {}).get("events") or [])
          if ((e.get("competitions") or [{}])[0].get("status") or {}).get("type", {}).get("completed")
          and _et_day(e.get("date")) < before]
    ev = ev[-LAST_GAMES:]
    tot, played, n = {}, {}, 0
    for e in ev:
        box = (get(SUMMARY.format(e["id"])) or {}).get("boxscore") or {}
        for t in box.get("players") or []:
            if (t.get("team") or {}).get("abbreviation", "").upper() != abbr.upper():
                continue
            n += 1
            s = (t.get("statistics") or [{}])[0]
            for a in s.get("athletes") or []:
                st = dict(zip(s.get("labels") or [], a.get("stats") or []))
                try:
                    m = float(st.get("MIN") or 0)
                except ValueError:
                    m = 0.0
                nm = a["athlete"]["displayName"]
                tot[nm] = tot.get(nm, 0.0) + m
                played[nm] = played.get(nm, 0) + (1 if m > 0 else 0)
    return {k: v / played[k] for k, v in tot.items() if played.get(k, 0) >= MIN_PLAYED} if n else {}


def played_day_before(abbr, day, get=_get):
    """True when the team played on the calendar day before `day` (ISO, ET)
    -- the second night of a back-to-back. Priced in on the record (README,
    NBA back-to-backs, 3,695 games), so callers show it, not cut on it."""
    import datetime as _dt
    prev = (_dt.date.fromisoformat(day) - _dt.timedelta(1)).isoformat()
    for e in (get(SCHED.format(abbr.lower())) or {}).get("events") or []:
        when = str(e.get("date") or "")
        try:
            et = _dt.datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(ET).date().isoformat()
        except ValueError:
            continue
        if et == prev:
            return True
    return False


def report_name(display):
    """'Kawhi Leonard' -> 'Leonard, Kawhi' (the official report's order)."""
    parts = display.split(" ")
    if len(parts) > 2 and parts[-1].rstrip(".") in ("Jr", "Sr", "II", "III", "IV"):
        return f"{' '.join(parts[-2:])}, {' '.join(parts[:-2])}"
    return f"{parts[-1]}, {' '.join(parts[:-1])}" if len(parts) > 1 else display


def key_missing(minutes, statuses, n=KEY_N):
    """[(display name, avg min, status)] for top-n minute players whose
    report status is Out/Doubtful (missing) or Questionable (watch)."""
    top = sorted(minutes.items(), key=lambda kv: -kv[1])[:n]
    out = []
    for name, m in top:
        st = statuses.get(report_name(name))
        if st in FLAG + WATCH:
            out.append((name, round(m, 1), st))
    return out


def main(day, get=_get):
    import nba_injury_report as R
    _, text = R.latest()
    rows = R.parse(text or "")["rows"] if text else []
    mmdd = dt.date.fromisoformat(day).strftime("%m/%d/%Y")
    by_team = {}
    for r in rows:
        if r["date"] == mmdd:
            by_team.setdefault(r["team"], {})[r["player"]] = r["status"]
    out = []
    for e in (get(SCORE.format(day.replace("-", ""))) or {}).get("events") or []:
        for c in e["competitions"][0]["competitors"]:
            abbr, name = c["team"]["abbreviation"], c["team"]["displayName"]
            miss = key_missing(recent_minutes(abbr, day, get), by_team.get(name, {}))
            out.append(f"{e['shortName']} {name}: " + ("; ".join(f"{p} ({m} min) {s}" for p, m, s in miss) or "no key player out"))
    return out


if __name__ == "__main__":
    print("\n".join(main(__import__("build_ticket").resolve_day(sys.argv[1] if len(sys.argv) > 1 else None))))
