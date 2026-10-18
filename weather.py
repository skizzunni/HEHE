"""Kickoff wind and football totals -- the one weather effect that held up.

tools/weather_lab.py, past seasons, the same rule scored on both halves of
the games (cut-offs from the first half): take the UNDER when the wind at
kickoff is strong and the OVER when it is calm --

    college football  53.6% (336 games)  then  54.5% (332 unseen)
    NFL               54.4% (68)         then  55.2% (67 unseen)
    MLB               47.7%              then  51.0%   -- no effect, not used

against 50% priced. So for an outdoor football game the forecast wind at the
venue at kickoff (Open-Meteo, free) nudges a total's chance by EDGE toward
the under when windy and toward the over when calm. Domes, unknown venues
and other sports are left alone. The data/weather_lab.json numbers are
re-read each rebuild, so the cut-offs follow the weekly re-run.
"""
import datetime as dt
import json
import math
import os
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache", "weather")
LEAGUES = {"ncaaf", "nfl"}
EDGE = 0.04          # the rule ran ~54-55% against 50% priced; take a bit less
TTL = 3 * 3600


def _cuts():
    try:
        d = json.load(open(os.path.join(HERE, "data", "weather_lab.json")))["leagues"]
    except (OSError, ValueError, KeyError):
        return {}
    out = {}
    for lg in LEAGUES:
        r = (d.get(lg) or {}).get("wind_rule") or {}
        f, t = r.get("fit") or {}, r.get("test") or {}
        if (f.get("hit") or 0) > 52.4 and (t.get("hit") or 0) > 52.4:   # held in BOTH halves
            out[lg] = (r["windy_at"], r["calm_at"])
    return out


CUTS = _cuts()


def _get(url, name):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, name)
    try:
        if time.time() - os.path.getmtime(f) < TTL:
            return json.load(open(f))
    except (OSError, ValueError):
        pass
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                    timeout=20) as r:
            d = json.load(r)
    except Exception:
        return None
    with open(f, "w") as fh:
        json.dump(d, fh)
    return d


def kickoff_wind(mkt):
    """Forecast wind (mph) at the venue at kickoff, or None."""
    if mkt.get("indoor") or not mkt.get("city") or not mkt.get("start"):
        return None
    g = _get("https://geocoding-api.open-meteo.com/v1/search?count=1&format=json&name="
             + urllib.parse.quote(mkt["city"]), f'geo-{mkt["city"]}.json'.replace("/", "_"))
    res = (g or {}).get("results") or []
    if not res:
        return None
    lat, lon = res[0]["latitude"], res[0]["longitude"]
    t = dt.datetime.fromisoformat(str(mkt["start"]).replace("Z", "+00:00"))
    w = _get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
             "&hourly=wind_speed_10m&wind_speed_unit=mph&timezone=UTC&forecast_days=10",
             f"fc-{lat:.2f}-{lon:.2f}-{t.date()}.json")
    h = (w or {}).get("hourly") or {}
    times = h.get("time") or []
    if not times:
        return None
    i = min(range(len(times)), key=lambda k: abs(
        dt.datetime.fromisoformat(times[k]).replace(tzinfo=dt.timezone.utc) - t))
    v = (h.get("wind_speed_10m") or [None])[i]
    return float(v) if v is not None else None


def _scale(p):
    """How much a shift in the expected total moves a line priced at p,
    relative to the main line the lab measured at (~50%): on a normal score
    phi(z) / phi(0). An alternate line at 77% moves about three quarters as
    much; one at 95% about a fifth. A flat EDGE overstated far lines."""
    from statistics import NormalDist
    p = min(max(p, 0.01), 0.99)
    z = NormalDist().inv_cdf(p)
    return math.exp(-z * z / 2)


def adjust(league, mkt, side, p=0.5):
    """Change in chance for an 'over'/'under' leg of this game (0 if none),
    `p` being the leg's chance before the wind."""
    if league not in CUTS or side not in ("over", "under"):
        return 0.0
    w = kickoff_wind(mkt or {})
    if w is None:
        return 0.0
    windy, calm = CUTS[league]
    e = EDGE * _scale(p)
    if w >= windy:
        return e if side == "under" else -e
    if w <= calm:
        return e if side == "over" else -e
    return 0.0
