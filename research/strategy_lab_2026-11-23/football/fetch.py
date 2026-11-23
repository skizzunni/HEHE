"""Football history with OPEN and CLOSE lines (spread, total, moneyline) from ESPN.

    python fetch.py nfl  OUT.json 2022 2023 2024 2025 2026
    python fetch.py ncaaf OUT.json 2022 2023 2024 2025 2026

Every finished regular-season game (season type 2) from the daily scoreboard,
plus pre-game context: venue city/indoor, neutral site, conferenceCompetition,
kickoff time, week, national broadcasts. Odds come from the event's core odds
items (live-odds feeds skipped), one book per game: the first of DraftKings (40),
ESPN BET (58), then any other with a full closing spread. Every side is
matched to its team by the team id in its $ref, never by position.
Raw responses are cached under ./cache. At most 8 requests in flight.
"""
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
LG = {"nfl": "nfl", "ncaaf": "college-football"}


def get(url, path=None, tries=3):
    if path and os.path.exists(path):
        try:
            return json.load(open(path))
        except ValueError:
            pass
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=25) as r:
                j = json.load(r)
            if path:
                json.dump(j, open(path, "w"))
            return j
        except Exception:
            time.sleep(1 + k)
    return None


def num(x):
    try:
        return float(str(x).replace("+", ""))
    except (TypeError, ValueError):
        return None


def days(y):
    d, end = dt.date(y, 8, 20), min(dt.date(y + 1, 1, 20), dt.date.today() - dt.timedelta(days=1))
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def scoreboard(key, day):
    lg = LG[key]
    tag = day.strftime("%Y%m%d")
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/{lg}/scoreboard?dates={tag}&limit=400"
    if key == "ncaaf":
        url += "&groups=80"
    j = get(url, os.path.join(CACHE, f"{key}-sb-{tag}.json")) or {}
    out = []
    for e in j.get("events", []):
        if (e.get("season") or {}).get("type") != 2:
            continue
        c = (e.get("competitions") or [{}])[0]
        if not ((c.get("status") or {}).get("type") or {}).get("completed"):
            continue
        side = {}
        for t in c.get("competitors", []):
            side[t["homeAway"]] = dict(id=t["team"]["id"], name=t["team"].get("displayName"),
                                       abbr=t["team"].get("abbreviation"),
                                       score=int(float(t.get("score") or 0)))
        if "home" not in side or "away" not in side:
            continue
        v = c.get("venue") or {}
        a = v.get("address") or {}
        nat = [n for b in c.get("broadcasts") or [] if b.get("market") == "national" for n in b.get("names") or []]
        out.append(dict(id=e["id"], date=c.get("date") or e["date"], day=day.isoformat(),
                        season=(e.get("season") or {}).get("year"), week=(e.get("week") or {}).get("number"),
                        home=side["home"], away=side["away"], neutral=bool(c.get("neutralSite")),
                        conf_game=bool(c.get("conferenceCompetition")), indoor=bool(v.get("indoor")),
                        venue=v.get("fullName"), city=a.get("city"), state=a.get("state") or a.get("country"),
                        tv=nat))
    return out


def ok_pts(v):
    return v is not None and abs(v) <= 70 and (2 * v) % 1 == 0


def ok_price(v):
    return v is not None and (v <= -100 or v >= 100)


def side_lines(x):
    """open/close spread points, spread prices and moneylines of one side.
    Close falls back to 'current' (final for a finished game, e.g. DraftKings
    2022) and then the item's flat fields; 2022 ESPN BET 'close' carries the
    price in the pointSpread slot, so a value that is not a plausible line is
    treated as missing."""
    r = {}
    for when in ("open", "close", "current"):
        o = x.get(when) or {}
        pts = num((o.get("pointSpread") or {}).get("american"))
        pr = num((o.get("spread") or {}).get("american"))
        ml = num((o.get("moneyLine") or {}).get("american"))
        r[when] = dict(pts=pts if ok_pts(pts) else None, price=pr if ok_price(pr) else None,
                       ml=ml if ok_price(ml) else None)
    for k in ("pts", "price", "ml"):
        if r["close"][k] is None:
            r["close"][k] = r["current"][k]
    if r["close"]["price"] is None and ok_price(num(x.get("spreadOdds"))):
        r["close"]["price"] = num(x.get("spreadOdds"))
    if r["close"]["ml"] is None and ok_price(num(x.get("moneyLine"))):
        r["close"]["ml"] = num(x.get("moneyLine"))
    return r


def imp(a):
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def odds(key, g):
    lg = LG[key]
    url = f"https://sports.core.api.espn.com/v2/sports/football/leagues/{lg}/events/{g['id']}/competitions/{g['id']}/odds"
    j = get(url, os.path.join(CACHE, f"{key}-odds-{g['id']}.json")) or {}
    items = [i for i in j.get("items", []) if "Live" not in ((i.get("provider") or {}).get("name") or "")]
    pri = {"40": 0, "58": 1}
    items.sort(key=lambda i: pri.get(str((i.get("provider") or {}).get("id")), 9))
    main_ = next((o for o in (parse(it, g) for it in items) if o), None)
    if main_ is None:
        return None
    # line-movement book: the first (ESPN BET, then DraftKings, then others)
    # that carries both an open and a close spread; drift bets use its close
    items.sort(key=lambda i: {"58": 0, "40": 1}.get(str((i.get("provider") or {}).get("id")), 9))
    mv = next((o for o in (parse(it, g) for it in items) if o and o["h_sp_open"] is not None), None)
    mvt = next((o for o in (parse(it, g) for it in items)
                if o and o["total_open"] is not None and o["total"] is not None and o["over"] is not None), None)
    main_["mv"], main_["mvt"] = mv, mvt
    return main_


def parse(it, g):
    if True:
        by = {}
        for k in ("awayTeamOdds", "homeTeamOdds"):
            x = it.get(k) or {}
            m = re.search(r"/teams/(\d+)", ((x.get("team") or {}).get("$ref") or ""))
            if m:
                by[m.group(1)] = side_lines(x)
        h, a = by.get(g["home"]["id"]), by.get(g["away"]["id"])
        if not h or not a:
            return None
        hc, ac = h["close"], a["close"]
        flat = num(it.get("spread"))                   # the home side's line
        if (hc["pts"] is None or ac["pts"] is None) and ok_pts(flat):
            hc["pts"], ac["pts"] = flat, -flat
        if hc["pts"] is None or ac["pts"] is None or hc["pts"] != -ac["pts"] or None in (hc["price"], ac["price"]):
            return None
        if not 1.0 <= imp(hc["price"]) + imp(ac["price"]) <= 1.12:
            return None
        tc = (it.get("close") or {})
        tcur = (it.get("current") or {})
        to = (it.get("open") or {})

        def tv(*vs):
            for v in vs:
                v = num(v)
                if v is not None and 15 <= v <= 110:
                    return v
            return None

        def pv(*vs):
            for v in vs:
                v = num(v)
                if ok_price(v):
                    return v
            return None
        out = dict(book=(it.get("provider") or {}).get("name"),
                   h_sp=hc["pts"], h_sp_pr=hc["price"], a_sp_pr=ac["price"],
                   h_sp_open=h["open"]["pts"], a_sp_open=a["open"]["pts"],
                   h_ml=hc["ml"], a_ml=ac["ml"], h_ml_open=h["open"]["ml"], a_ml_open=a["open"]["ml"],
                   total=tv((tc.get("total") or {}).get("american"), (tcur.get("total") or {}).get("american"), it.get("overUnder")),
                   over=pv((tc.get("over") or {}).get("american"), (tcur.get("over") or {}).get("american"), it.get("overOdds")),
                   under=pv((tc.get("under") or {}).get("american"), (tcur.get("under") or {}).get("american"), it.get("underOdds")),
                   total_open=tv((to.get("total") or {}).get("american")))
        return out


def main(key, out, years):
    os.makedirs(CACHE, exist_ok=True)
    ds = [d for y in years for d in days(y)]
    G = {}
    with cf.ThreadPoolExecutor(8) as ex:
        for gs in ex.map(lambda d: scoreboard(key, d), ds):
            for g in gs:
                G.setdefault(g["id"], g)
    print(key, len(G), "games; fetching odds", flush=True)
    gl = list(G.values())
    with cf.ThreadPoolExecutor(8) as ex:
        for g, o in zip(gl, ex.map(lambda g: odds(key, g), gl)):
            g["odds"] = o
    json.dump(G, open(out, "w"))
    print(key, len(G), "games;", sum(1 for g in G.values() if g["odds"]), "with closing spread", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3:]])
