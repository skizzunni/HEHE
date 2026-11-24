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


NHL = "https://api-web.nhle.com/v1/{}"


def _nhl(path):
    req = urllib.request.Request(NHL.format(path), headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except Exception:
        return None


def team_goalies(get=_nhl):
    """{team name: [(goalie full name, starts, save %)]} for this season, from
    the NHL's own stats; {} when it cannot be reached."""
    st = (get("standings/now") or {}).get("standings") or []
    out = {}
    for t in st:
        name, tri = (t.get("teamName") or {}).get("default"), (t.get("teamAbbrev") or {}).get("default")
        cs = get(f"club-stats/{tri}/now") or {}
        out[name] = [(f"{g['firstName']['default']} {g['lastName']['default']}", g.get("gamesStarted") or 0,
                      g.get("savePercentage")) for g in cs.get("goalies") or []]
    return out


SEARCH = "https://search.d3.nhle.com/api/v1/search/player?culture=en-us&limit=10&q={}"
CAREER_OK = 50          # career NHL games: an established goalie, not an unknown call-up


def career(goalie, get=None):
    """(career regular-season games, save %) for an NHL goalie by name, from the
    NHL's own search and player pages; None when not found."""
    import urllib.parse
    get = get or (lambda u: _nhl_url(u))
    hits = get(SEARCH.format(urllib.parse.quote(goalie))) or []
    pid = next((h.get("playerId") for h in hits if h.get("positionCode") == "G"
                and str(h.get("name", "")).lower() == goalie.lower()), None)
    if not pid:
        return None
    ct = ((get(NHL.format(f"player/{pid}/landing")) or {}).get("careerTotals") or {}).get("regularSeason") or {}
    gp = ct.get("gamesPlayed")
    return (gp, ct.get("savePctg")) if gp is not None else None


def _nhl_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except Exception:
        return None


def flag(goalie, roster, career_fn=None):
    """A note when the listed starter is not this team's usual one: absent from
    its season stats, or with fewer starts than another goalie. 2026-11-24:
    Minnesota's Gustavsson had no games this season and was flagged "verify";
    he is a 220-game NHL goalie, started, saved .917 and the Wild won 5-2 --
    so an absent goalie is now looked up by career before he is called a risk."""
    if not goalie or not roster:
        return ""
    by = {n.lower(): (n, gs, sv) for n, gs, sv in roster}
    top = max(roster, key=lambda r: r[1])
    me = by.get(goalie.lower())
    if not me:
        c = (career_fn or career)(goalie)
        if c and c[0] >= CAREER_OK:
            sv = f", .{round(1000 * c[1]):03d}" if c[1] else ""
            return (f" -- first game for this team this season, but an established NHL goalie "
                    f"({c[0]} career games{sv}); usual: {top[0]}, {top[1]} starts")
        exp = f"{c[0]} career NHL games" if c else "no NHL career found"
        return f" -- NOT among this team's goalies this season and {exp} (usual: {top[0]}, {top[1]} starts); verify"
    if me[1] < top[1]:
        sv = f", .{round(1000 * me[2]):03d}" if me[2] else ""
        return f" -- not the usual starter ({me[1]} starts{sv}; {top[0]} has {top[1]})"
    return ""


def leg_note(team, rows, rosters=None, career_fn=None):
    """The ticket's note for an NHL leg on `team` (full name): its listed
    starter, DailyFaceoff's status, and flag()'s warning; "" when the team is
    not listed. Information only -- no record yet says how much an
    unconfirmed or backup goalie moves a 75%+ favourite."""
    for r in rows or []:
        for side in ("away", "home"):
            if (r.get(side) or "").lower() == (team or "").lower() and r.get(side + "_goalie"):
                st = r.get(side + "_status") or "Unconfirmed"
                note = f" -- goalie: {r[side + '_goalie']} ({st})"
                try:
                    note += flag(r[side + "_goalie"], (rosters or {}).get(r[side]), career_fn)
                except Exception:
                    pass
                if st != "Confirmed":
                    note += "; check the confirmed starter before using it"
                return note
    return ""


def played_day_before(tri, day, get=_nhl):
    """True when NHL team `tri` (e.g. 'VGK') played on the day before `day`
    (ISO), from the NHL's own schedule (local game dates). For the ticket's
    back-to-back caution on NHL winners -- information only, not tested."""
    prev = (dt.date.fromisoformat(day) - dt.timedelta(days=1)).isoformat()
    week = get(f"club-schedule/{tri}/week/{prev}") or {}
    return any(g.get("gameDate") == prev for g in week.get("games") or [])


LINES = "https://www.dailyfaceoff.com/teams/{}/line-combinations"


def slug(team):
    """'Vegas Golden Knights' -> 'vegas-golden-knights' (DailyFaceoff's team URL); 'Montréal' -> 'montreal'."""
    import unicodedata
    t = unicodedata.normalize("NFKD", team or "").encode("ascii", "ignore").decode().lower().replace(".", "")
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def lineup(html):
    """{player name: note or ""} from a DailyFaceoff line-combinations page:
    "" for a skater in the projected even-strength lines, else why not
    (injured list, game-time decision). {} when the page cannot be read."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html or "", re.S)
    if not m:
        return {}
    try:
        c = json.loads(m.group(1))["props"]["pageProps"]["combinations"]
    except (KeyError, ValueError, TypeError):
        return {}
    out = {}
    for p in c.get("players") or []:
        n = p.get("name")
        if not n:
            continue
        if p.get("categoryIdentifier") == "oi" or p.get("injuryStatus"):
            out[n] = f"on the injured list ({p.get('injuryStatus') or 'out'})"
        elif p.get("gameTimeDecision"):
            out.setdefault(n, "a game-time decision")
        elif p.get("categoryIdentifier") == "ev":
            out.setdefault(n, "")
    src = c.get("sourceName")
    return dict(out, **({"__source__": src} if src else {}))


def fetch_lineup(team):
    req = urllib.request.Request(LINES.format(slug(team)), headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return lineup(r.read().decode("utf-8", "replace"))
    except Exception:
        return {}


def fetch(day):
    req = urllib.request.Request(URL.format(day), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def text(rows, rosters=None, career_fn=None):
    if not rows:
        return "No goalie data found on DailyFaceoff."
    rosters = rosters or {}
    f = lambda r, s: (f"{r[s + '_goalie'] or '?'} ({r[s + '_status']}" + (f", {r[s + '_at']} ET" if r[s + "_at"] else "") + ")"
                      + flag(r[s + "_goalie"], rosters.get(r[s]), career_fn))
    return "\n".join(f"{r['away']} @ {r['home']}: {f(r, 'away')} vs {f(r, 'home')}" for r in rows)


if __name__ == "__main__":
    day = __import__("build_ticket").resolve_day(sys.argv[1] if len(sys.argv) > 1 else None)
    print(text(parse(fetch(day)), team_goalies()))
