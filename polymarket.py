"""Polymarket's game prices as a second, margin-free fair reference.

Polymarket's public API (gamma-api.polymarket.com, no key) lists each game
in the US leagues with a moneyline, spreads and totals; the deep markets
carry six- and seven-figure liquidity (Patriots @ Bears, 2026-10-22: $1.08M).
An exchange price has no bookmaker margin, so where a market is liquid
(MIN_LIQUIDITY) its price is an independent estimate of the fair chance --
the free stand-in for a sharp book.

It is used ONLY as a reference for value_bets (averaged with DraftKings'
Shin fair), never as a venue to bet: its fees and availability to US
bettors are not established here.
"""
import datetime as dt
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache", "polymarket")
API = "https://gamma-api.polymarket.com"
TTL = 600
MIN_LIQUIDITY = 10000
# board league -> Polymarket sport code. Soccer (from 2026-10-27): three
# yes/no markets per game -- each side to win, and the draw -- each about
# $20k deep in the Premier League; the single-source soccer value bets were
# the ones losing (-17.6% on 82), and this gives them a second reference.
SPORTS = {"nba": "nba", "nhl": "nhl", "nfl": "nfl", "ncaaf": "cfb", "mlb": "mlb", "wnba": "wnba", "ncaab": "cbb",
          "epl": "epl", "esp": "lal", "ger": "bun", "ita": "sea", "fra": "fl1", "mls": "mls",
          "ucl": "ucl", "uel": "uel"}
SOCCER = {"epl", "esp", "ger", "ita", "fra", "mls", "ucl", "uel"}


def _get(url):
    try:
        import ssl
        ctx = ssl.create_default_context()
        try:
            ctx.load_verify_locations("/root/.ccr/ca-bundle.crt")
        except OSError:
            pass
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
            return json.load(r)
    except Exception:
        return None


def load(now=None):
    """{league: [event]} with each event's markets, cached TTL seconds."""
    now = now or time.time()
    f = os.path.join(CACHE, "events.json")
    try:
        if now - os.path.getmtime(f) < TTL:
            with open(f) as fh:
                return json.load(fh)
    except (OSError, ValueError):
        pass
    sports = {x.get("sport"): x for x in (_get(f"{API}/sports") or []) if isinstance(x, dict)}
    out = {}
    soon = (dt.datetime.fromtimestamp(now, dt.timezone.utc) + dt.timedelta(days=3)).isoformat()
    for lg, code in SPORTS.items():
        s = sports.get(code)
        if not s or not s.get("series"):
            continue
        evs = _get(f"{API}/events?series_id={s['series']}&closed=false&limit=200") or []
        keep = []
        for e in evs:
            st = e.get("startTime") or e.get("endDate") or ""
            if not st or st > soon:
                continue
            keep.append(dict(title=e.get("title"), start=st, markets=[dict(
                question=m.get("question"), type=m.get("sportsMarketType"), outcomes=m.get("outcomes"),
                prices=m.get("outcomePrices"), line=m.get("line"), liquidity=m.get("liquidityNum") or m.get("liquidity"))
                for m in e.get("markets") or []]))
        out[lg] = keep
    try:
        os.makedirs(CACHE, exist_ok=True)
        with open(f, "w") as fh:
            json.dump(out, fh)
    except OSError:
        pass
    return out


def _js(x):
    if isinstance(x, str):
        try:
            return json.loads(x)
        except ValueError:
            return None
    return x


_CLUB = {"fc", "afc", "cf", "sc", "ac", "ssc", "as", "rc", "cd", "ud", "sd", "fk", "sk", "if", "bk", "vfb", "vfl", "tsg", "1."}


def _club(n):
    """'Manchester United FC' -> 'manchester united'; accents folded."""
    import unicodedata
    n = unicodedata.normalize("NFKD", n or "").encode("ascii", "ignore").decode().lower()
    return " ".join(w for w in n.replace(".", " ").split() if w not in _CLUB)


def _is(short, full):
    """Polymarket's name ("Maple Leafs", "Chelsea FC") is ESPN's ("Toronto
    Maple Leafs", "Chelsea"): a whole-word prefix or suffix either way, after
    dropping club tags (FC, AFC, CF ...)."""
    s, f = _club(short), _club(full)
    if not s or not f:
        return False
    return s == f or f.endswith(" " + s) or f.startswith(s + " ") or s.endswith(" " + f) or s.startswith(f + " ")


def events_for(book, league, mkt):
    """Every Polymarket event for one board game (a soccer game has several:
    the match, its corners, its players), start within 6 hours."""
    import freshness
    st = freshness.parse(mkt.get("start"))
    out = []
    for e in book.get(league) or []:
        t = freshness.parse(e.get("start"))
        if st and t and abs((t - st).total_seconds()) > 6 * 3600:
            continue
        names = [x.split(" - ")[0] for x in (e.get("title") or "").split(" vs. ")]
        if len(names) == 2 and {_is(names[0], mkt.get("home")) or _is(names[0], mkt.get("away")),
                                _is(names[1], mkt.get("home")) or _is(names[1], mkt.get("away"))} == {True}:
            out.append(e)
    return out


def event_for(book, league, mkt):
    ev = events_for(book, league, mkt)
    return ev[0] if ev else None


def _soccer_fair(markets, spec):
    """A soccer side's (or the draw's) chance from the three yes/no markets,
    normalised so the three sum to one; None unless all three are liquid."""
    yes = {}
    for m in markets:
        if m.get("type") != "moneyline" or not _liquid(m):
            continue
        outs, prices = _js(m.get("outcomes")), _js(m.get("prices"))
        if not outs or not prices or "Yes" not in outs:
            continue
        try:
            p = float(prices[outs.index("Yes")])
        except (TypeError, ValueError):
            continue
        q = m.get("question") or ""
        key = "draw" if "draw" in q.lower() else q
        yes[key] = (p, q)
    if len(yes) != 3:
        return None
    tot = sum(p for p, _ in yes.values())
    if not 0.9 < tot < 1.15:
        return None
    if spec["t"] == "draw":
        return yes["draw"][0] / tot
    for key, (p, q) in yes.items():
        if key != "draw" and q.lower().startswith("will ") and _is(q[5:].split(" win")[0], spec["team"]):
            return p / tot
    return None


def _liquid(m):
    try:
        return float(m.get("liquidity") or 0) >= MIN_LIQUIDITY
    except (TypeError, ValueError):
        return False


def fair(book, league, mkt, spec):
    """Polymarket's chance for a straight win, spread or total, or None.
    spec: dict(t="win", team) / dict(t="spread", team, line) / dict(t="over"|"under", line)."""
    evs = events_for(book or {}, league, mkt)
    if not evs:
        return None
    if league in SOCCER:
        if spec["t"] not in ("win", "draw"):
            return None
        return _soccer_fair([m for e in evs for m in e.get("markets") or []], spec)
    e = evs[0]
    for m in e.get("markets") or []:
        outs, prices = _js(m.get("outcomes")), _js(m.get("prices"))
        if not outs or not prices or len(outs) != 2 or not _liquid(m):
            continue
        try:
            ps = [float(x) for x in prices]
        except (TypeError, ValueError):
            continue
        if not all(0.01 < p < 0.99 for p in ps):
            continue
        t, q = m.get("type"), m.get("question") or ""
        if spec["t"] == "win" and t == "moneyline":
            for o, p in zip(outs, ps):
                if _is(o, spec["team"]):
                    return p
        elif spec["t"] in ("over", "under") and t == "totals" and f"O/U {spec['line']:g}" in q:
            return ps[0] if spec["t"] == "over" else ps[1]
        elif spec["t"] == "spread" and t == "spreads":
            # "Spread: Patriots (-1.5)": outcome 0 gives the points, outcome 1 gets them
            import re
            mm = re.search(r"\(([-+]?\d+(?:\.\d+)?)\)", q)
            if not mm:
                continue
            l0 = float(mm.group(1))
            if _is(outs[0], spec["team"]) and abs(spec["line"] - l0) < 1e-9:
                return ps[0]
            if _is(outs[1], spec["team"]) and abs(spec["line"] + l0) < 1e-9:
                return ps[1]
    return None
