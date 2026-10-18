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

Links are ONE selection each (addToBetslip?marketId=..&selectionId=..), the
format The Odds API documents. FanDuel publishes no link that fills a
multi-leg slip; an indexed multi-selection version was tried here and did
not add the legs, so the page offers one add-leg link per leg instead.
"""
import json
import datetime as dt
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
# Soccer lives on FanDuel's soccer sport page (eventTypeId 1), not a custom
# page; its competitions, by FanDuel's name, mapped to the board's leagues
# (probe rounds 32-33, 2026-10-18). Fixtures read "Home v Away".
SOCCER_EVENT_TYPE = "1"
SOCCER_COMP = {
    "English Premier League": "epl", "Spanish La Liga": "esp", "German Bundesliga": "ger",
    "German Bundesliga 2": "ger2", "Italian Serie A": "ita", "French Ligue 1": "fra",
    "US MLS": "mls", "UEFA Champions League": "ucl", "UEFA Europa League": "uel",
    "UEFA Conference League": "uecl", "English Sky Bet Championship": "efl1",
    "Scottish Premiership": "sco", "Austrian Bundesliga": "aut", "Swiss Super League": "sui",
    "Danish Superliga": "den", "Norwegian Eliteserien": "nor", "Japanese J1 League": "jpn",
    "Argentinian Primera Division": "arg", "Chile - Primera Division": "chi",
    "Ecuador Serie A": "ecu", "Uruguayan Primera Division": "uru", "Colombian Primera A": "col",
    "Mexican Liga MX": "mex", "South Africa - Premier Division": "rsa",
    "Australian A-League Men's": "aus", "US National Women Soccer League": "nwsl",
    "German DFB Pokal": "dfb", "Brazilian Serie A": "bra",
    "UEFA Nations League A": "unl", "UEFA Nations League B": "unl", "UEFA Nations League C": "unl",
}
SOCCER = set(SOCCER_COMP.values())


def covered(league):
    """Does the board read FanDuel's lines for this league?"""
    return league in PAGES or league in SOCCER
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
                                                total={}, px={}, id=str(e.get("eventId")),
                                                start=e.get("openDate"))
        for m in (att.get("markets") or {}).values():
            g = games.get(str(m.get("eventId")))
            if not g:
                continue
            t = m.get("marketType")
            for r in m.get("runners") or []:
                ref = f'{m.get("marketId")}:{r.get("selectionId")}'
                name, hc = r.get("runnerName") or "", r.get("handicap")
                if t in ("MONEY_LINE", "MATCH_HANDICAP_(2-WAY)", "TOTAL_POINTS_(OVER/UNDER)"):
                    g["px"][ref] = _odds(r)        # American price, e.g. "+135"
                if t == "MONEY_LINE":
                    g["ml"][name] = ref
                elif t == "MATCH_HANDICAP_(2-WAY)":
                    g["spread"][name] = [hc, ref]
                elif t == "TOTAL_POINTS_(OVER/UNDER)":
                    g["total"][name.split()[0].lower()] = [hc, ref]
        out[league] = list(games.values())
    try:
        _load_soccer(out)
    except Exception:
        pass                                  # soccer never blocks the other sports
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w") as fh:
            json.dump(out, fh)
    except OSError:
        pass
    return out


START_SLACK_H = 3      # a doubleheader's second game starts 3+ hours after the first


def find(book, league, away, home, start=None):
    """FanDuel's game for this fixture. Teams must match, and where both
    sides carry a start time the nearest start within START_SLACK_H wins.
    Until 2026-10-18 the first team match was taken whatever its start, so a
    doubleheader or a repeated fixture could lend one game's prices to
    another. Two same-team games that cannot be told apart match nothing."""
    if league in SOCCER:
        return find_soccer(book, league, away, home, start)
    cands = [g for g in book.get(league) or []
             if same_team(g["away"], away) and same_team(g["home"], home)]
    t0 = _ts(start)
    if t0 and t0.tzinfo is None:
        t0 = t0.replace(tzinfo=dt.timezone.utc)
    timed = []
    for g in cands:
        t = _ts(g.get("start"))
        if t and t0:
            if t.tzinfo is None:
                t = t.replace(tzinfo=dt.timezone.utc)
            timed.append((abs((t - t0).total_seconds()), g))
    if timed:
        gap, g = min(timed, key=lambda x: x[0])
        return g if gap <= START_SLACK_H * 3600 else None
    return cands[0] if len(cands) == 1 else None


# ------------------------------------------------------------------ soccer
# FanDuel shortens club names ("Nottm Forest", "Man Utd", "Paris St-G") where
# ESPN spells them out, so a soccer match is found by its kickoff first and
# then by BOTH teams' names, token by token -- a wrong match would put one
# game's prices on another, so anything doubtful is left unmatched.
_ALIAS = {"man": "manchester", "utd": "united", "st": "saint", "nottm": "nottingham",
          "wolves": "wolverhampton", "spurs": "tottenham", "psg": "paris", "inter": "internazionale",
          "atl": "atletico", "dep": "deportivo", "ath": "athletic",
          # spellings that share no prefix (live misses, 2026-10-18)
          "mgladbach": "monchengladbach", "gladbach": "monchengladbach",
          "kobenhavn": "copenhagen", "koln": "cologne", "munchen": "munich",
          "wac": "wolfsberger", "ob": "odense", "praha": "prague", "lisboa": "lisbon", "bodo": "bodoglimt"}
_STOP = {"fc", "cf", "sc", "ac", "afc", "club", "de", "the", "cd", "fk", "sk", "as", "ss",
         "us", "calcio", "and", "of", "1", "04", "05", "ca", "sv", "vfb", "vfl", "tsg", "rc"}


def _toks(name):
    import unicodedata
    name = (name or "").translate(str.maketrans({"ø": "o", "Ø": "O", "æ": "ae", "ß": "ss", "ł": "l"}))
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    out = []
    for w in norm(name.replace("-", " ").replace(".", " ")).split():
        w = _ALIAS.get(w, w)
        if w not in _STOP and len(w) > 1:
            out.append(w)
    return out


def _tok_eq(a, b):
    if a == b:
        return True
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n >= 4


def _team_score(fd, espn):
    """Share of one name's tokens found in the other, the better direction."""
    a, b = _toks(fd), _toks(espn)
    if not a or not b:
        return 0.0
    share = lambda u, v: sum(any(_tok_eq(x, y) for y in v) for x in u) / len(u)
    return max(share(a, b), share(b, a))


def _ts(v):
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(".000+", "+"))
    except (TypeError, ValueError):
        return None


def find_soccer(book, league, away, home, start=None, slack_min=20):
    t0 = _ts(start)
    best, best_s = None, 0.0
    for g in book.get(league) or []:
        if t0 and _ts(g.get("start")) and abs((_ts(g["start"]) - t0).total_seconds()) > slack_min * 60:
            continue
        s = min(_team_score(g["home"], home), _team_score(g["away"], away))
        # the teams the other way round fit better: a reversed fixture
        # (Man City v Man Utd is not Man Utd v Man City), never this one
        if min(_team_score(g["home"], away), _team_score(g["away"], home)) > s:
            continue
        if s > best_s:
            best, best_s = g, s
    return best if best_s >= 0.5 else None


def _load_soccer(out):
    d = _get(f"{BASE}/content-managed-page?page=SPORT&eventTypeId={SOCCER_EVENT_TYPE}"
             f"&_ak={AK}&timezone=America%2FNew_York")
    att = (d or {}).get("attachments") or {}
    comps = {str(c.get("competitionId")): c.get("name") for c in (att.get("competitions") or {}).values()}
    games = {}
    for e in (att.get("events") or {}).values():
        nm = e.get("name") or ""
        lg = SOCCER_COMP.get(comps.get(str(e.get("competitionId"))) or "")
        if not lg or " v " not in nm:
            continue
        home, away = nm.split(" v ", 1)
        games[str(e.get("eventId"))] = (lg, dict(away=away, home=home, ml={}, spread={}, total={}, px={},
                                                 id=str(e.get("eventId")), start=e.get("openDate"),
                                                 soccer=True))
    for m in (att.get("markets") or {}).values():
        x = games.get(str(m.get("eventId")))
        if not x or m.get("marketType") != "WIN-DRAW-WIN":
            continue
        g = x[1]
        for r in m.get("runners") or []:
            ref = f'{m.get("marketId")}:{r.get("selectionId")}'
            g["ml"][r.get("runnerName") or ""] = ref
            g["px"][ref] = _odds(r)
    for lg, g in games.values():
        out.setdefault(lg, []).append(g)


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


# ------------------------------------------------------------ alternate lines
# The league page above carries only the main lines, which sit near 50%. The
# high-probability legs -- alternate spreads, totals and team totals -- live on
# each game's own page, "popular" tab (probed 2026-10-15). Runner names carry
# the line: "Philadelphia Flyers +2.5", "Over 4.5", "Over (30.5)".
EVENT_TTL = 600
ALT_TYPES = ("ALTERNATE_PUCK_LINE", "ALTERNATE_RUN_LINES", "ALTERNATE_HANDICAP",
             "ALTERNATE_SPREAD", "ALTERNATE_SPREADS", "ALTERNATE_TOTAL_GOALS",
             "ALTERNATE_TOTAL_RUNS", "ALTERNATE_TOTAL", "ALTERNATE_TOTAL_POINTS",
             "HOME_TEAM_ALTERNATE_TOTAL_GOALS", "AWAY_TEAM_ALTERNATE_TOTAL_GOALS",
             "HOME_TEAM_ALTERNATE_TOTAL", "AWAY_TEAM_ALTERNATE_TOTAL",
             "HOME_TEAM_ALTERNATE_TOTAL_RUNS", "AWAY_TEAM_ALTERNATE_TOTAL_RUNS")
_TOT = re.compile(r"^\s*(Over|Under)\s*\(?\s*(\d+(?:\.\d+)?)\s*\)?\s*$", re.I)
_HCP = re.compile(r"^\s*(.+?)\s*\(?\s*([+-]\d+(?:\.\d+)?)\s*\)?\s*$")


def _odds(r):
    o = ((r.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds")
    if o is None:
        return None
    return f"+{o}" if o > 0 else str(o)


def parse_alts(markets, g):
    """[(kind, team-or-None, side, line, ref, price, where)] for one game's page.

    `where` names the line the way FanDuel's page does ("Alternate Total
    Goals: Over 2.5"). FanDuel reuses selection ids across markets, and its
    addToBetslip link resolves an alternate line's id to a different line of
    the game (checked 2026-10-15: Over 2.5 came up as Over 6.5 +104), so an
    alternate leg is shown as text to find, not as a one-tap button."""
    out = []
    for m in (markets or {}).values():
        t = m.get("marketType") or ""
        if t not in ALT_TYPES:
            continue
        mid = m.get("marketId")
        side_team = g["home"] if t.startswith("HOME_") else g["away"] if t.startswith("AWAY_") else None
        for r in m.get("runners") or []:
            name = r.get("runnerName") or ""
            ref = f'{mid}:{r.get("selectionId")}'
            price = _odds(r)
            where = f'{m.get("marketName") or t}: {name}'
            mt = _TOT.match(name)
            if mt:
                kind = "teamtotal" if side_team else "total"
                out.append((kind, side_team, mt.group(1).lower(), float(mt.group(2)), ref, price, where))
                continue
            mh = _HCP.match(name)
            if mh and "TOTAL" not in t:
                out.append(("spread", mh.group(1), None, float(mh.group(2)), ref, price, where))
    return out


_SOC_TOT = re.compile(r"^OVER_UNDER_(\d)5$")
_SOC_TEAM = re.compile(r"^(HOME|AWAY)_TEAM_OVER/UNDER_(\d+\.5)$")
_SOC_HCP = re.compile(r"^(HOME|AWAY)_TEAM_-1\.5_GOALS$")
_GOALS = re.compile(r"^\s*(.+?)\s+([+-]\d+(?:\.\d+)?)\s+Goals?\s*$", re.I)


def parse_soccer(markets, g):
    """Soccer alternates in parse_alts' shape: double chance ("X And Draw"),
    full-match totals, team totals and the +-1.5 goal handicaps."""
    out = []
    for m in (markets or {}).values():
        t = m.get("marketType") or ""
        mid = m.get("marketId")
        for r in m.get("runners") or []:
            name = r.get("runnerName") or ""
            ref = f'{mid}:{r.get("selectionId")}'
            price = _odds(r)
            where = f'{m.get("marketName") or t}: {name}'
            if t == "DOUBLE_CHANCE":
                if name.lower().endswith(" and draw"):
                    out.append(("dc", name[:-len(" and draw")].strip(), None, None, ref, price, where))
            elif _SOC_TOT.match(t):
                mt = re.match(r"^\s*(Over|Under)\s+(\d+\.5)", name, re.I)
                if mt:
                    out.append(("total", None, mt.group(1).lower(), float(mt.group(2)), ref, price, where))
            elif _SOC_TEAM.match(t):
                side_team = g["home"] if t.startswith("HOME") else g["away"]
                if name.lower() in ("over", "under"):
                    out.append(("teamtotal", side_team, name.lower(), float(_SOC_TEAM.match(t).group(2)),
                                ref, price, where))
            elif _SOC_HCP.match(t):
                mh = _GOALS.match(name)
                if mh:
                    out.append(("spread", mh.group(1), None, float(mh.group(2)), ref, price, where))
    return out


def load_alts(g):
    """Alternate lines for one FanDuel game, cached EVENT_TTL seconds."""
    if not g.get("id"):
        return []
    f = os.path.join(os.path.dirname(CACHE), "fd_events", f'{g["id"]}.json')
    try:
        if time.time() - os.path.getmtime(f) < EVENT_TTL:
            with open(f) as fh:
                alts = [tuple(x) for x in json.load(fh)]
                if all(len(x) == 7 for x in alts):
                    return alts
    except (OSError, ValueError):
        pass
    base = (f"{BASE}/event-page?_ak={AK}&eventId={g['id']}"
            "&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
    if g.get("soccer"):
        mk = {}
        for tab in ("popular", "goals"):
            mk.update((((_get(base + "&tab=" + tab) or {}).get("attachments") or {}).get("markets")) or {})
        alts = parse_soccer(mk, g)
    else:
        d = _get(base + "&tab=popular")
        alts = parse_alts(((d or {}).get("attachments") or {}).get("markets"), g)
    try:
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, "w") as fh:
            json.dump(alts, fh)
    except OSError:
        pass
    return alts
