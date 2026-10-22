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
# board league -> Polymarket sport code (two-way leagues only)
SPORTS = {"nba": "nba", "nhl": "nhl", "nfl": "nfl", "ncaaf": "cfb", "mlb": "mlb", "wnba": "wnba", "ncaab": "cbb"}


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


def _is(short, full):
    """Polymarket's short name ("Maple Leafs") within ESPN's full one."""
    s, f = (short or "").lower().strip(), (full or "").lower()
    return bool(s) and (f.endswith(" " + s) or f == s or f.startswith(s + " "))


def event_for(book, league, mkt):
    import freshness
    st = freshness.parse(mkt.get("start"))
    for e in book.get(league) or []:
        t = freshness.parse(e.get("start"))
        if st and t and abs((t - st).total_seconds()) > 6 * 3600:
            continue
        names = (e.get("title") or "").split(" vs. ")
        if len(names) == 2 and {_is(names[0], mkt.get("home")) or _is(names[0], mkt.get("away")),
                                _is(names[1], mkt.get("home")) or _is(names[1], mkt.get("away"))} == {True}:
            return e
    return None


def _liquid(m):
    try:
        return float(m.get("liquidity") or 0) >= MIN_LIQUIDITY
    except (TypeError, ValueError):
        return False


def fair(book, league, mkt, spec):
    """Polymarket's chance for a straight win, spread or total, or None.
    spec: dict(t="win", team) / dict(t="spread", team, line) / dict(t="over"|"under", line)."""
    e = event_for(book or {}, league, mkt)
    if not e:
        return None
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
