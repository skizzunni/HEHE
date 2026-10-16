"""Weather lab: does kickoff weather beat the closing total?

    python3 tools/weather_lab.py      # on GitHub's runners

For every finished outdoor NFL, college football and MLB game in the
backtest windows: the closing total (DraftKings, from ESPN's odds feed), the
final score, and the weather at the venue at the scheduled start (Open-Meteo's
free historical archive: wind, gusts, temperature, rain), located from the
venue's city via Open-Meteo's geocoder. Domes are left out.

The question is narrow: given the closing total, does the weather still say
which side wins? A logistic model of P(under) on [wind, gusts, cold, rain] is
fitted on the older half of games and scored on the newer half ONLY, against
the close's own de-vigged under price. It is used live only if it picks
unders/overs better than the price on games it never saw.

Writes data/weather_lab.json.
"""
import datetime as dt
import json
import math
import os
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import backtest as B                                          # noqa: E402
import edge_lab as E                                          # noqa: E402

OUT = os.path.join(ROOT, "data", "weather_lab.json")
LEAGUES = {"nfl", "ncaaf", "mlb"}
GEO = "https://geocoding-api.open-meteo.com/v1/search?count=1&language=en&format=json&name="
ARCH = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}"
        "&start_date={d}&end_date={d}&hourly=temperature_2m,precipitation,wind_speed_10m,"
        "wind_gusts_10m&wind_speed_unit=mph&temperature_unit=fahrenheit&timezone=UTC")


def venues(key, sport, league, days):
    """event id -> (city, state, indoor, start ISO) from the cached scoreboards."""
    out = {}
    for d in days:
        tag = d.strftime("%Y%m%d")
        sb = B.cached(f"{key}-sb-{tag}.json",
                      f"{B.SITE}/{sport}/{league}/scoreboard?dates={tag}&limit=400")
        for ev in (sb or {}).get("events") or []:
            for c in ev.get("competitions") or []:
                v = c.get("venue") or {}
                a = v.get("address") or {}
                out[str(c.get("id"))] = (a.get("city"), a.get("state") or a.get("country"),
                                         bool(v.get("indoor")), c.get("date") or ev.get("date"))
    return out


def geo(city, state):
    q = f"{city}"
    d = B.cached(f"geo-{city}-{state}.json".replace("/", "_").replace(" ", "_"),
                 GEO + urllib.parse.quote(q))
    for r in (d or {}).get("results") or []:
        return r["latitude"], r["longitude"]
    return None


def weather(lat, lon, start):
    t = dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
    day = t.date().isoformat()
    d = B.cached(f"wx-{lat:.2f}-{lon:.2f}-{day}.json", ARCH.format(lat=lat, lon=lon, d=day))
    h = (d or {}).get("hourly") or {}
    times = h.get("time") or []
    if not times:
        return None
    i = min(range(len(times)), key=lambda k: abs(
        dt.datetime.fromisoformat(times[k]).replace(tzinfo=dt.timezone.utc) - t))
    def g(k):
        v = (h.get(k) or [None] * len(times))[i]
        return float(v) if v is not None else None
    return dict(wind=g("wind_speed_10m"), gust=g("wind_gusts_10m"), temp=g("temperature_2m"),
                rain=g("precipitation"))


def rows_for(key, sport, league, wins):
    days = B.dates(wins)
    games = B.finished_games(key, sport, league, days)
    ven = venues(key, sport, league, days)
    if len(games) > 1500:
        step = len(games) / 1500
        games = [games[int(i * step)] for i in range(1500)]

    def one(g):
        d, eid, home, away, hs, as_ = g
        v = ven.get(str(eid))
        if not v or v[2] or not v[0] or not v[3]:
            return None                                       # dome or unknown venue
        raw = B.cached(f"{key}-odds-{eid}.json",
                       f"{E.CORE}/{sport}/leagues/{league}/events/{eid}/competitions/{eid}/odds")
        for it in (raw or {}).get("items") or []:
            cl = it.get("close") or {}
            tot = E.num(((cl.get("total") or {}).get("american"))) or E.num(it.get("overUnder"))
            po = E.am(((cl.get("over") or {}).get("american")))
            pu = E.am(((cl.get("under") or {}).get("american")))
            if not tot or not po or not pu:
                continue
            pts = hs + as_
            if pts == tot:
                return None                                   # push
            loc = geo(v[0], v[1])
            if not loc:
                return None
            w = weather(loc[0], loc[1], v[3])
            if not w or w["wind"] is None:
                return None
            return dict(date=d.isoformat(), under=int(pts < tot), p_under=pu / (po + pu), **w)
        return None
    with ThreadPoolExecutor(max_workers=8) as ex:
        return sorted([r for r in ex.map(one, games) if r], key=lambda r: r["date"])


def feats(r):
    z = E.lg(r["p_under"])
    return [1.0, z, (r["wind"] or 0) / 10, max(0.0, (r.get("gust") or 0) - 20) / 10,
            max(0.0, 45 - (r["temp"] if r["temp"] is not None else 60)) / 10,
            min(r.get("rain") or 0.0, 5.0)]


def main():
    report = {}
    for key, sport, league, wins in B.WINDOWS:
        if key not in LEAGUES:
            continue
        rows = rows_for(key, sport, league, wins)
        if len(rows) < 150:
            report[key] = dict(games=len(rows), note="too few outdoor games with weather")
            print(key, report[key], flush=True)
            continue
        half = len(rows) // 2
        fit, test = rows[:half], rows[half:]
        base = E.score([dict(home_won=r["under"]) for r in test], [r["p_under"] for r in test])
        w = E.fit_logit([feats(r) for r in fit], [r["under"] for r in fit])
        probs = [1 / (1 + math.exp(-sum(a * b for a, b in zip(w, feats(r))))) for r in test]
        h, l = E.score([dict(home_won=r["under"]) for r in test], probs)
        flips = sum((p > 0.5) != (r["p_under"] > 0.5) for r, p in zip(test, probs))
        # the windiest quarter of unseen games: how often did the under hit?
        windy = sorted(test, key=lambda r: -(r["wind"] or 0))[:max(1, len(test) // 4)]
        calm = sorted(test, key=lambda r: (r["wind"] or 0))[:max(1, len(test) // 4)]
        rate = lambda rs: round(100 * sum(r["under"] for r in rs) / len(rs), 1)
        price = lambda rs: round(100 * sum(r["p_under"] for r in rs) / len(rs), 1)
        gained = round((h - base[0]) * len(test) / 100)
        # the simple rule, both halves: wind cut-offs from the FIT half's
        # quartiles; under when windy, over when calm
        ws = sorted(r["wind"] or 0 for r in fit)
        hi_w, lo_w = ws[3 * len(ws) // 4], ws[len(ws) // 4]
        def rule(rs):
            pk = [(r, r["under"]) for r in rs if (r["wind"] or 0) >= hi_w] + \
                 [(r, 1 - r["under"]) for r in rs if (r["wind"] or 0) <= lo_w]
            n = len(pk)
            return dict(n=n, hit=round(100 * sum(w for _, w in pk) / n, 1) if n else None)
        simple = dict(windy_at=hi_w, calm_at=lo_w, fit=rule(fit), test=rule(test))
        report[key] = dict(games=len(rows), test_games=len(test),
                           close=dict(hit=base[0], logloss=base[1]),
                           weather=dict(hit=h, logloss=l, weights=[round(x, 3) for x in w],
                                        picks_changed=flips, extra_wins=gained,
                                        significant=bool(flips and gained > math.sqrt(flips)
                                                         and l < base[1])),
                           windiest_quarter=dict(under_hit=rate(windy), under_price=price(windy),
                                                 min_wind=windy[-1]["wind"]),
                           calmest_quarter=dict(under_hit=rate(calm), under_price=price(calm)),
                           wind_rule=simple)
        print(key, json.dumps(report[key]), flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(dict(run=dt.date.today().isoformat(), leagues=report), fh, indent=1)


if __name__ == "__main__":
    main()
