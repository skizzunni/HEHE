"""ESPN injury reports: shown beside each pick, and archived before play.

My own price-blind picks miss injuries (2026-11-04: mine 60.7% against the
market's 68.1% over 382 games, the gap largest in the NBA). To test an
injury-aware model later, the report must be kept as it stood BEFORE each
game: every build appends a snapshot to review/injuries/<ET date>.json when the
report changed, so a game can be matched to the last snapshot before its
start. Display only; no pick reads it.
"""
import datetime as dt
import json
import os
import urllib.request
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(HERE, "review", "injuries")      # committed by the board job with review/
ET = ZoneInfo("America/New_York")
PATHS = {"nba": "basketball/nba", "nhl": "hockey/nhl", "nfl": "football/nfl", "wnba": "basketball/wnba"}
SHOWN = ("Out", "Doubtful", "Questionable", "Day-To-Day")
KEEP_DAYS = 60


def parse(doc):
    """{team display name: [[player, status], ...]} for the statuses shown."""
    out = {}
    for t in (doc or {}).get("injuries") or []:
        rows = [[(i.get("athlete") or {}).get("displayName"), i.get("status")]
                for i in t.get("injuries") or [] if i.get("status") in SHOWN]
        rows = [r for r in rows if r[0]]
        if rows and t.get("displayName"):
            out[t["displayName"]] = rows
    return out


def fetch(leagues=PATHS, timeout=20):
    got = {}
    for lg, path in leagues.items():
        try:
            url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/injuries"
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "board"}), timeout=timeout) as r:
                got[lg] = parse(json.load(r))
        except Exception:
            continue
    return got


def snapshot(teams, now=None, root=None):
    """Append to today's file when the report changed; prune old days."""
    now = now or dt.datetime.now(dt.timezone.utc)
    d = root or DIR
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, now.astimezone(ET).date().isoformat() + ".json")
    try:
        with open(path) as fh:
            book = json.load(fh)
    except (OSError, ValueError):
        book = {"snapshots": []}
    last = book["snapshots"][-1]["teams"] if book["snapshots"] else None
    merged = dict(last or {}, **teams)       # a league that failed to load keeps its last report
    if merged != last:
        book["snapshots"].append(dict(t=now.isoformat(timespec="seconds"), teams=merged))
        with open(path, "w") as fh:
            json.dump(book, fh, separators=(",", ":"))
    cut = (now.astimezone(ET).date() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    for f in os.listdir(d):
        if f.endswith(".json") and f[:-5] < cut:
            os.remove(os.path.join(d, f))
    return merged


def before(day, start_iso, league, root=None):
    """The report as it stood at a game's start (the last snapshot before it)."""
    try:
        with open(os.path.join(root or DIR, day + ".json")) as fh:
            snaps = json.load(fh)["snapshots"]
    except (OSError, ValueError, KeyError):
        return {}
    start = dt.datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    ok = [s for s in snaps if dt.datetime.fromisoformat(s["t"]) <= start]
    return (ok[-1]["teams"].get(league) or {}) if ok else {}


def note(teams, league, home, away):
    """{'home': [...], 'away': [...]} of 'Name (Out)' for one game's teams."""
    T = teams.get(league) or {}
    f = lambda name: [f"{p} ({s})" for p, s in T.get(name) or []]
    return dict(home=f(home), away=f(away))
