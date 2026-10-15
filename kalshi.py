"""Find each ticket leg's exact Kalshi market, so a stack can be rebuilt as a
Kalshi combo in a minute.

Probed 2026-10-15 from GitHub's runners (api.elections.kalshi.com, public):

  * per league, three series of game markets, one event per game:
        KX{L}GAME    "Toronto wins"                       (soccer adds "Tie")
        KX{L}TOTAL   "Over 3.5 goals scored", one market per line
        KX{L}SPREAD  "Toronto wins by over 2.5 goals", one per line per team
  * event tickers end in the game's date and both team codes:
        KXNHLTOTAL-26OCT15BUFTOR
  * combos are Kalshi "multivariate" markets; the collection that holds game
    legs (KXMVESPORTSMULTIGAMEEXTENDED) lists these same events. Creating a
    combo needs a logged-in account, so it is built in Kalshi's app; this
    file names every leg exactly as Kalshi words it, with the side to buy.

How our legs map:
    Over L            -> TOTAL market at strike L, YES
    Under L           -> TOTAL market at strike L, NO
    X to win          -> GAME market for X, YES
    No: X wins by > L -> SPREAD market for X at L, NO
    X -L              -> SPREAD market for X at L, YES
    X +L / X or draw  -> the other side's market, NO
"""
import datetime as dt
import json
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache", "kalshi.json")
API = "https://api.elections.kalshi.com/trade-api/v2"
TTL = 240
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/json"}

# board league key -> Kalshi series prefix. Series that do not exist simply
# return no events.
PREFIX = {"nhl": "NHL", "nfl": "NFL", "ncaaf": "NCAAF", "nba": "NBA",
          "ncaab": "NCAAMB", "wnba": "WNBA", "mlb": "MLB", "epl": "EPL",
          "ucl": "UCL", "uel": "UEL", "mls": "MLS", "esp": "LALIGA",
          "ger": "BUNDESLIGA", "ita": "SERIEA", "fra": "LIGUE1"}
KINDS = ("GAME", "TOTAL", "SPREAD")
MONTHS = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}


def _get(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r)
    except Exception:
        return None


def _price(m, side):
    """Ask in dollars for buying `side`, from whichever field the API fills."""
    for k in (f"{side}_ask_dollars", f"{side}_ask"):
        v = m.get(k)
        if v in (None, "", 0, "0"):
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        return v / 100 if v > 1 else v
    return None


def _series(ticker):
    out, cursor = [], ""
    for _ in range(5):
        d = _get(f"{API}/events?series_ticker={ticker}&status=open"
                 f"&with_nested_markets=true&limit=200" + (f"&cursor={cursor}" if cursor else ""))
        if not d:
            break
        out.extend(d.get("events") or [])
        cursor = d.get("cursor") or ""
        if not cursor:
            break
    return out


def load():
    """{league: {game_key: {kind: [market]}, ...}}, cached for TTL seconds.
    game_key is the event ticker's tail, e.g. 26OCT15BUFTOR."""
    try:
        if time.time() - os.path.getmtime(CACHE) < TTL:
            with open(CACHE) as fh:
                return json.load(fh)
    except (OSError, ValueError):
        pass
    jobs = [(lg, kind, f"KX{p}{kind}") for lg, p in PREFIX.items() for kind in KINDS]
    with ThreadPoolExecutor(max_workers=12) as ex:
        res = list(ex.map(lambda j: _series(j[2]), jobs))
    out = {}
    for (lg, kind, ser), events in zip(jobs, res):
        for ev in events:
            tail = (ev.get("event_ticker") or "").split("-", 1)[-1]
            g = out.setdefault(lg, {}).setdefault(tail, {"title": ev.get("title"),
                                                         "sub": ev.get("sub_title")})
            g[kind] = [dict(ticker=m.get("ticker"), title=m.get("title"),
                            yes=m.get("yes_sub_title"), strike=m.get("floor_strike"),
                            yes_ask=_price(m, "yes"), no_ask=_price(m, "no"),
                            event=ev.get("event_ticker"), series=ser)
                       for m in ev.get("markets") or []]
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w") as fh:
            json.dump(out, fh)
    except OSError:
        pass
    return out


def _date_of(tail):
    m = re.match(r"(\d\d)([A-Z]{3})(\d\d)", tail or "")
    if not m or m.group(2) not in MONTHS:
        return None
    return dt.date(2000 + int(m.group(1)), MONTHS[m.group(2)], int(m.group(3)))


def _et_date(start):
    try:
        t = dt.datetime.strptime(start[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None
    return (t - dt.timedelta(hours=4)).date()


def _norm(x):
    return re.sub(r"[^a-z0-9 ]", "", (x or "").lower()).strip()


def find(book, league, mkt):
    """The Kalshi game for a board game: same date and both team codes, or
    both team names, never one side alone."""
    games = book.get(league) or {}
    day = _et_date(mkt.get("start"))
    ha, aa = (mkt.get("home_abbr") or "").upper(), (mkt.get("away_abbr") or "").upper()
    for tail, g in games.items():
        if day and _date_of(tail) not in (day, None):
            continue
        codes = tail[7:]
        if ha and aa and codes in (aa + ha, ha + aa):
            return g
    # names: Kalshi's GAME markets name each team ("Toronto", "Chelsea")
    hn, an = _norm(mkt.get("home")), _norm(mkt.get("away"))
    for tail, g in games.items():
        if day and _date_of(tail) not in (day, None):
            continue
        teams = [_norm(m.get("yes")) for m in g.get("GAME") or [] if _norm(m.get("yes")) != "tie"]
        if len(teams) == 2 and all(any(t and (t == n or n.startswith(t + " ")) for n in (hn, an))
                                   for t in teams) \
                and teams[0] != teams[1]:
            return g
    return None


def _team_market(g, kind, team, line=None):
    """The market in `kind` naming this team (and line, for spreads)."""
    tn = _norm(team)
    best = None
    for m in g.get(kind) or []:
        y = _norm(m.get("yes"))
        name = re.sub(r" wins.*$", "", y)
        if not name or not (tn == name or tn.startswith(name + " ")):
            continue
        if line is not None and (m.get("strike") is None or abs(float(m["strike"]) - line) > 1e-9):
            continue
        # prefer the longest name match ("los angeles c" over "los angeles")
        if best is None or len(name) > len(best[0]):
            best = (name, m)
    return best[1] if best else None


def leg(book, league, mkt, spec):
    """-> dict(ticker, side, words, price) for one leg, or None."""
    g = find(book, league, mkt)
    if not g:
        return None
    t = spec.get("t")
    def out(m, side):
        if not m:
            return None
        p = m["yes_ask"] if side == "YES" else m["no_ask"]
        return dict(ticker=m["ticker"], event=m["event"], series=m["series"], side=side,
                    words=f'{side} · {m.get("yes") or m.get("title")}', price=p)
    if t in ("over", "under"):
        m = next((m for m in g.get("TOTAL") or [] if m.get("strike") is not None
                  and abs(float(m["strike"]) - spec["line"]) < 1e-9), None)
        return out(m, "YES" if t == "over" else "NO")
    if t == "win":
        return out(_team_market(g, "GAME", spec["team"]), "YES")
    if t == "draw":
        m = next((m for m in g.get("GAME") or [] if _norm(m.get("yes")) == "tie"), None)
        return out(m, "YES")
    if t == "dc":           # this team or the draw = the other team does not win
        other = mkt["away"] if spec["team"] == mkt["home"] else mkt["home"]
        return out(_team_market(g, "GAME", other), "NO")
    if t == "nomargin":
        return out(_team_market(g, "SPREAD", spec["team"], spec["line"]), "NO")
    if t == "spread":
        L = spec["line"]
        if L < 0:           # must win by more than |L|
            return out(_team_market(g, "SPREAD", spec["team"], -L), "YES")
        other = mkt["away"] if spec["team"] == mkt["home"] else mkt["home"]
        return out(_team_market(g, "SPREAD", other, L), "NO")
    return None


def page_url(k):
    """Kalshi's market pages live under the series ticker."""
    return f"https://kalshi.com/markets/{k['series'].lower()}"


def attach(ticket, book, rows_by_id):
    """Add Kalshi legs to a stacks ticket: per-leg market, side and price, how
    many legs Kalshi lists, and what buying them one by one would cost."""
    found, cost = [], 1.0
    for L in ticket["legs"]:
        row = rows_by_id.get(L["gid"]) or {}
        k = leg(book, L["league"], row.get("mkt") or {}, L["spec"])
        L["kalshi"] = k
        if k:
            found.append(k)
            cost = cost * k["price"] if (cost is not None and k.get("price")) else None
        else:
            cost = None
    ticket["kalshi_n"] = len(found)
    # price of the legs bought separately at the ask: a reference point for
    # the combo, which Kalshi quotes on its own
    ticket["kalshi_cost"] = round(cost, 4) if (cost and len(found) == len(ticket["legs"])) else None
    return ticket


def extra_specs(book):
    """For stacks.candidates: every total and spread line Kalshi lists for a
    game, as legs the stack builder can choose from."""
    def fn(league, row, g):
        mkt = row.get("mkt") or {}
        game = find(book, league, mkt)
        if not game:
            return []
        unit = "goals" if g.kind == "poisson" else "points"
        out = []
        for m in game.get("TOTAL") or []:
            L = m.get("strike")
            if L is None:
                continue
            L = float(L)
            out += [("total", f"Over {L:g} {unit}", dict(t="over", line=L)),
                    ("total", f"Under {L:g} {unit}", dict(t="under", line=L))]
        for m in game.get("SPREAD") or []:
            L, y = m.get("strike"), _norm(m.get("yes"))
            if L is None:
                continue
            L = float(L)
            team = next((t for t in (mkt.get("home"), mkt.get("away"))
                         if t and (_norm(t) == re.sub(r" wins.*$", "", y)
                                   or _norm(t).startswith(re.sub(r" wins.*$", "", y) + " "))), None)
            if not team:
                continue
            out += [("side", f"No \u00b7 {team} wins by over {L:g} {unit}",
                     dict(t="nomargin", team=team, line=L)),
                    ("side", f"{team} wins by over {L:g} {unit}",
                     dict(t="spread", team=team, line=-L))]
        return out
    return fn


def keep_listed(book):
    """For stacks.candidates: only legs Kalshi lists."""
    def fn(league, row, spec):
        return leg(book, league, row.get("mkt") or {}, spec) is not None
    return fn
