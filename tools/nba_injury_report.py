#!/usr/bin/env python3
"""The latest official NBA injury report, as rows.

The league posts a PDF every 15 minutes or so on game days
(ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HH_MMAM.pdf).
ESPN's injury labels lag it (2026-11-23: one still showed a player Out whom the
official report had Probable), so slate research reads the PDF itself:

    python3 tools/nba_injury_report.py              # today's latest report
    python3 tools/nba_injury_report.py OKC IND      # only those teams

latest() walks back from now in 15-minute steps to the newest posted file;
parse() turns its text (pdftotext -layout) into rows of
{date, matchup, team, player, status} and lists teams marked NOT YET SUBMITTED.
A player missing from the report is not listed as injured -- that is how the
league reports a healthy player, not missing data.
"""
import datetime as dt
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
URL = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{d}_{t}.pdf"
STATUSES = ("Out", "Doubtful", "Questionable", "Probable", "Available")
TEAMS = ("Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets", "Chicago Bulls",
         "Cleveland Cavaliers", "Dallas Mavericks", "Denver Nuggets", "Detroit Pistons", "Golden State Warriors",
         "Houston Rockets", "Indiana Pacers", "LA Clippers", "Los Angeles Lakers", "Memphis Grizzlies", "Miami Heat",
         "Milwaukee Bucks", "Minnesota Timberwolves", "New Orleans Pelicans", "New York Knicks",
         "Oklahoma City Thunder", "Orlando Magic", "Philadelphia 76ers", "Phoenix Suns", "Portland Trail Blazers",
         "Sacramento Kings", "San Antonio Spurs", "Toronto Raptors", "Utah Jazz", "Washington Wizards")
_PLAYER = re.compile(r"([A-Z][\w'.\-]*(?: [\w'.\-]+)*, [A-Z][\w'.\-]*(?: [\w'.\-]+)*)\s{2,}(" + "|".join(STATUSES) + r")\b")
_DATE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
_MATCH = re.compile(r"\b([A-Z]{3}@[A-Z]{3})\b")


def parse(text):
    """{"asof": str|None, "rows": [...], "not_submitted": [(date, matchup, team)]}."""
    asof = None
    rows, missing = [], []
    date = matchup = team = None
    for line in text.splitlines():
        m = re.search(r"Injury Report: (\S+ \S+ [AP]M)", line)
        if m:
            asof = asof or m.group(1)
            continue
        d = _DATE.search(line)
        if d:
            date = d.group(1)
        mm = _MATCH.search(line)
        if mm:
            matchup = mm.group(1)
        for t in TEAMS:
            if t in line:
                team = t
                break
        if "NOT YET SUBMITTED" in line and team:
            missing.append((date, matchup, team))
            continue
        for p in _PLAYER.finditer(line):
            rows.append(dict(date=date, matchup=matchup, team=team, player=p.group(1), status=p.group(2)))
    return dict(asof=asof, rows=rows, not_submitted=missing)


def _pdf_text(raw):
    with tempfile.TemporaryDirectory() as d:
        pdf = os.path.join(d, "r.pdf")
        with open(pdf, "wb") as f:
            f.write(raw)
        return subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True, timeout=60).stdout


def latest(now=None, back_hours=30, get=None):
    """(url, text) of the newest posted report at or before now, else (None, None)."""
    now = (now or dt.datetime.now(ET)).astimezone(ET)
    t = now.replace(minute=now.minute - now.minute % 15, second=0, microsecond=0)

    def fetch(u):
        try:
            with urllib.request.urlopen(u, timeout=20) as r:
                return r.read()
        except Exception:
            return None
    get = get or fetch
    for _ in range(int(back_hours * 4)):
        u = URL.format(d=t.strftime("%Y-%m-%d"), t=t.strftime("%I_%M%p"))
        raw = get(u)
        if raw and raw[:4] == b"%PDF":
            return u, _pdf_text(raw)
        t -= dt.timedelta(minutes=15)
    return None, None


def report(teams=(), day=None):
    u, text = latest()
    if not text:
        return "No official NBA injury report found in the last 30 hours."
    r = parse(text)
    day = day or dt.datetime.now(ET).strftime("%m/%d/%Y")
    want = [t.upper() for t in teams]
    keep = lambda mu: not want or any(w in (mu or "") for w in want)
    out = [f"Official NBA injury report, {r['asof']} ({u})"]
    for row in r["rows"]:
        if row["date"] == day and keep(row["matchup"]):
            out.append(f"  {row['matchup']} {row['team']}: {row['player']} -- {row['status']}")
    for d, mu, t in r["not_submitted"]:
        if d == day and keep(mu):
            out.append(f"  {mu} {t}: report NOT YET SUBMITTED")
    return "\n".join(out)


if __name__ == "__main__":
    print(report(sys.argv[1:]))
