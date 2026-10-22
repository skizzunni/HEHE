"""More books, and a sharp reference, from The Odds API -- optional.

Off unless the environment has ODDS_API_KEY (a free key from the-odds-api.com,
stored as a GitHub Actions secret by the owner; never in this repository or
in a chat). With it, each covered sport's moneylines are fetched from
BOOKS -- Pinnacle, the sharpest book, among them -- so that:

    venues.compare   also lists BetMGM, Caesars, BetRivers, ESPN BET, Fanatics
    value_bets       takes the fair chance from Pinnacle's prices (Shin
                     de-vig) when Pinnacle lists the game, DraftKings' otherwise

Budget: the free tier is 500 credits a month; one moneyline call naming up
to 10 bookmakers costs one credit. A sport is refetched at most every
CACHE_MIN minutes and no more than MAX_CALLS_PER_DAY calls are made a day
(both overridable in the environment), sports with the most board games
first. The remaining quota from each response is kept in the cache file.
"""
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache", "oddsapi")
API = "https://api.the-odds-api.com/v4/sports"
BOOKS = ("pinnacle", "fanduel", "draftkings", "betmgm", "williamhill_us", "betrivers", "espnbet", "fanatics")
NAMES = {"pinnacle": "Pinnacle", "fanduel": "FanDuel", "draftkings": "DraftKings", "betmgm": "BetMGM",
         "williamhill_us": "Caesars", "betrivers": "BetRivers", "espnbet": "ESPN BET", "fanatics": "Fanatics"}
SPORTS = {"nfl": "americanfootball_nfl", "ncaaf": "americanfootball_ncaaf", "nba": "basketball_nba",
          "ncaab": "basketball_ncaab", "wnba": "basketball_wnba", "nhl": "icehockey_nhl",
          "mlb": "baseball_mlb", "epl": "soccer_epl", "esp": "soccer_spain_la_liga",
          "ger": "soccer_germany_bundesliga", "ita": "soccer_italy_serie_a", "fra": "soccer_france_ligue_one",
          "mls": "soccer_usa_mls", "ucl": "soccer_uefa_champs_league", "uel": "soccer_uefa_europa_league"}
CACHE_MIN = int(os.environ.get("ODDS_API_CACHE_MIN") or 360)
MAX_CALLS_PER_DAY = int(os.environ.get("ODDS_API_CALLS_PER_DAY") or 16)


def key():
    return (os.environ.get("ODDS_API_KEY") or "").strip() or None


def _usage():
    try:
        with open(os.path.join(CACHE, "usage.json")) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_usage(u):
    os.makedirs(CACHE, exist_ok=True)
    with open(os.path.join(CACHE, "usage.json"), "w") as fh:
        json.dump(u, fh)


def _fetch(sport_key, api_key):
    q = urllib.parse.urlencode(dict(apiKey=api_key, bookmakers=",".join(BOOKS), markets="h2h",
                                    oddsFormat="decimal"))
    req = urllib.request.Request(f"{API}/{sport_key}/odds/?{q}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r), r.headers.get("x-requests-remaining")


def load(leagues_by_games=None, now=None):
    """{league: [event]} for the covered leagues, within the budget."""
    k = key()
    if not k:
        return {}
    now = now or time.time()
    day = dt.datetime.fromtimestamp(now, dt.timezone.utc).date().isoformat()
    u = _usage()
    if u.get("day") != day:
        u = dict(day=day, calls=0, remaining=u.get("remaining"))
    order = sorted(SPORTS, key=lambda lg: -(leagues_by_games or {}).get(lg, 0))
    out = {}
    for lg in order:
        if leagues_by_games is not None and not leagues_by_games.get(lg):
            continue
        f = os.path.join(CACHE, f"{lg}.json")
        try:
            fresh = now - os.path.getmtime(f) < CACHE_MIN * 60
        except OSError:
            fresh = False
        if not fresh and u["calls"] < MAX_CALLS_PER_DAY:
            try:
                data, rem = _fetch(SPORTS[lg], k)
                os.makedirs(CACHE, exist_ok=True)
                with open(f, "w") as fh:
                    json.dump(data, fh)
                u["calls"] += 1
                u["remaining"] = rem
            except Exception:
                pass
        try:
            with open(f) as fh:
                out[lg] = json.load(fh)
        except (OSError, ValueError):
            pass
    _save_usage(u)
    return out


def _same(a, b):
    import fanduel
    return fanduel.same_team(a, b) or fanduel.same_team(b, a)


def event_for(book, league, mkt):
    """The Odds API event for a board game: both teams, start within 6 hours."""
    import freshness
    st = freshness.parse(mkt.get("start"))
    for ev in book.get(league) or []:
        t = freshness.parse(ev.get("commence_time"))
        if st and t and abs((t - st).total_seconds()) > 6 * 3600:
            continue
        if _same(ev.get("home_team") or "", mkt.get("home") or "") and \
                _same(ev.get("away_team") or "", mkt.get("away") or ""):
            return ev
    return None


def prices(book, league, mkt, team):
    """[{venue, dec, price}] for `team` to win, one per bookmaker."""
    ev = event_for(book, league, mkt)
    out = []
    for b in (ev or {}).get("bookmakers") or []:
        for m in b.get("markets") or []:
            if m.get("key") != "h2h":
                continue
            for o in m.get("outcomes") or []:
                if _same(o.get("name") or "", team):
                    d = float(o["price"])
                    out.append(dict(venue=NAMES.get(b.get("key"), b.get("title")), dec=round(d, 4),
                                    price=american(d), book_key=b.get("key")))
    return out


def sharp_fair(book, league, mkt, team, method="shin"):
    """Pinnacle's fair chance for `team` (Shin de-vig of all its outcomes), or None."""
    import devig
    ev = event_for(book, league, mkt)
    for b in (ev or {}).get("bookmakers") or []:
        if b.get("key") != "pinnacle":
            continue
        for m in b.get("markets") or []:
            if m.get("key") != "h2h":
                continue
            outs = m.get("outcomes") or []
            fv = devig.fair_decimal(*[float(o["price"]) for o in outs], method=method)
            if fv:
                for o, p in zip(outs, fv):
                    if _same(o.get("name") or "", team):
                        return p
    return None


def american(d):
    if not d or d <= 1:
        return None
    return f"+{round(100 * (d - 1))}" if d >= 2 else str(round(-100 / (d - 1)))
