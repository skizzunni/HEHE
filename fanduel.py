"""FanDuel (New York) bet-slip links for the legs FanDuel's feed can identify.

Probed 2026-10-15 from GitHub's runners:

  * sbapi.ny.sportsbook.fanduel.com/api/content-managed-page?page=CUSTOM&
    customPageId={nfl,nhl,nba,ncaaf,mlb,wnba} returns each upcoming game with
    three markets -- MONEY_LINE, MATCH_HANDICAP_(2-WAY) and
    TOTAL_POINTS_(OVER/UNDER) -- each with market and selection ids.
  * Market ids are per state ("736." in New York, "717." in Illinois), so a
    link built here is for New York only.
  * No alternate lines on the game pages, and no soccer, UFC or tennis pages,
    so most stack legs (alt totals, "won't win by N") have no FanDuel id.

The link format is FanDuel's addToBetslip with indexed market/selection
pairs. It cannot be checked from a server -- the page is an app that answers
200 to anything -- so the first real tap on a phone is the test.
"""
import json
import os
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache", "fanduel.json")
STATE = "ny"
AK = "FhMFpcPWXMeyZxOx"
BASE = f"https://sbapi.{STATE}.sportsbook.fanduel.com/api"
TTL = 600
PAGES = {"nfl": "nfl", "nhl": "nhl", "nba": "nba", "ncaaf": "ncaaf",
         "mlb": "mlb", "wnba": "wnba", "ncaab": "ncaab"}
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/json"}


def _get(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)
    except Exception:
        return None


def norm(name):
    """'Tampa Bay Rays (G Jax)' -> 'tampa bay rays'; 'Miami (OH)' -> 'miami oh'.

    Parentheses holding a pitcher ('G Jax', 'TBD') are dropped; a short
    qualifier like '(OH)' is part of the school's name and is kept."""
    def paren(m):
        inner = m.group(1).strip()
        return " " + inner if len(inner) <= 3 and inner.isalpha() and inner != "TBD" else " "
    name = re.sub(r"\((.*?)\)", paren, name or "")
    name = re.sub(r"[^a-z0-9 ]", "", name.lower().replace("&", " and "))
    return " ".join(name.split())


# Words that make a different school when they follow a name: "Indiana" is
# not "Indiana State", "Miami" is not "Miami (OH)".
NOT_MASCOT = {"state", "st", "tech", "and", "am", "christian", "southern", "northern",
              "eastern", "western", "central", "international", "oh", "fl", "pa",
              "university", "college", "atlantic", "poly", "baptist", "methodist"}


def same_team(fd, espn):
    """FanDuel uses school names in college ('Ohio State') where ESPN adds the
    mascot ('Ohio State Buckeyes'). That counts only when what follows is a
    mascot of one or two words, not another school's qualifier."""
    a, b = norm(fd), norm(espn)
    if not a:
        return False
    if a == b:
        return True
    if not b.startswith(a + " "):
        return False
    rest = b[len(a) + 1:].split()
    return len(rest) <= 2 and rest[0] not in NOT_MASCOT


def load():
    """{league: [game]} with ids for each market, cached for TTL seconds."""
    try:
        if time.time() - os.path.getmtime(CACHE) < TTL:
            with open(CACHE) as fh:
                return json.load(fh)
    except (OSError, ValueError):
        pass
    out = {}
    for league, page in PAGES.items():
        d = _get(f"{BASE}/content-managed-page?page=CUSTOM&customPageId={page}"
                 f"&_ak={AK}&timezone=America%2FNew_York")
        att = (d or {}).get("attachments") or {}
        events = att.get("events") or {}
        games = {}
        for e in events.values():
            nm = e.get("name") or ""
            if " @ " not in nm:
                continue
            away, home = nm.split(" @ ", 1)
            games[str(e.get("eventId"))] = dict(away=away, home=home, ml={}, spread={},
                                                total={})
        for m in (att.get("markets") or {}).values():
            g = games.get(str(m.get("eventId")))
            if not g:
                continue
            t = m.get("marketType")
            for r in m.get("runners") or []:
                ref = f'{m.get("marketId")}:{r.get("selectionId")}'
                name, hc = r.get("runnerName") or "", r.get("handicap")
                if t == "MONEY_LINE":
                    g["ml"][name] = ref
                elif t == "MATCH_HANDICAP_(2-WAY)":
                    g["spread"][name] = [hc, ref]
                elif t == "TOTAL_POINTS_(OVER/UNDER)":
                    g["total"][name.split()[0].lower()] = [hc, ref]
        out[league] = list(games.values())
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w") as fh:
            json.dump(out, fh)
    except OSError:
        pass
    return out


def find(book, league, away, home):
    for g in book.get(league) or []:
        if same_team(g["away"], away) and same_team(g["home"], home):
            return g
    return None


def _runner(table, team):
    for name, v in table.items():
        if same_team(name, team) or same_team(team, name):
            return v
    return None


def ml_ref(book, league, away, home, team):
    g = find(book, league, away, home)
    return _runner(g["ml"], team) if g else None


def leg_ref(book, league, home, away, spec):
    """FanDuel id for a stacks leg, only where FanDuel posts that exact line."""
    g = find(book, league, away, home)
    if not g:
        return None
    t = spec.get("t")
    if t == "win":
        return _runner(g["ml"], spec["team"])
    if t in ("over", "under"):
        v = g["total"].get(t)
        if v and v[0] is not None and abs(float(v[0]) - spec["line"]) < 1e-9:
            return v[1]
    if t == "spread":
        v = _runner(g["spread"], spec["team"])
        if v and v[0] is not None and abs(float(v[0]) - spec["line"]) < 1e-9:
            return v[1]
    return None


def link(refs):
    """refs ['736.1:25589', ...] -> one addToBetslip URL, or None."""
    if not refs or any(not r for r in refs):
        return None
    q = "&".join(f"marketId[{i}]={r.split(':')[0]}&selectionId[{i}]={r.split(':')[1]}"
                 for i, r in enumerate(refs))
    return "https://sportsbook.fanduel.com/addToBetslip?" + q
