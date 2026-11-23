#!/usr/bin/env python3
"""The day's NHL starting goalies, confirmed or not (DailyFaceoff).

Goalies are the NHL's biggest pre-game unknown and are usually confirmed the
morning of the game; a projected starter is not a confirmed one (2026-11-23:
five of the night-before projections changed by midday). Slate research reads:

    python3 tools/nhl_goalies.py                # today
    python3 tools/nhl_goalies.py 2026-11-24

parse() reads the page's embedded Next.js data and returns one row per game:
away / home team, each goalie and its status as DailyFaceoff labels it
(Confirmed, Likely, Unconfirmed when it gives none), and when that was posted.
"""
import datetime as dt
import json
import re
import sys
import urllib.request
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
URL = "https://www.dailyfaceoff.com/starting-goalies/{}"


def _games(o):
    if isinstance(o, dict):
        if "homeGoalieName" in o or "awayGoalieName" in o:
            yield o
        for v in o.values():
            yield from _games(v)
    elif isinstance(o, list):
        for v in o:
            yield from _games(v)


def _et(ts):
    try:
        return dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(ET).strftime("%I:%M %p").lstrip("0")
    except (TypeError, ValueError):
        return None


def parse(html):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html or "", re.S)
    if not m:
        return []
    out = []
    for g in _games(json.loads(m.group(1))):
        row = dict(away=g.get("awayTeamName"), home=g.get("homeTeamName"))
        for side in ("away", "home"):
            row[side + "_goalie"] = g.get(side + "GoalieName")
            row[side + "_status"] = g.get(side + "NewsStrengthName") or "Unconfirmed"
            row[side + "_at"] = _et(g.get(side + "NewsCreatedAt"))
        out.append(row)
    return out


def fetch(day):
    req = urllib.request.Request(URL.format(day), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def text(rows):
    if not rows:
        return "No goalie data found on DailyFaceoff."
    f = lambda r, s: f"{r[s + '_goalie'] or '?'} ({r[s + '_status']}" + (f", {r[s + '_at']} ET" if r[s + "_at"] else "") + ")"
    return "\n".join(f"{r['away']} @ {r['home']}: {f(r, 'away')} vs {f(r, 'home')}" for r in rows)


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else dt.datetime.now(ET).date().isoformat()
    print(text(parse(fetch(day))))
