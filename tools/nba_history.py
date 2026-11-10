"""NBA history for schedule studies: every regular-season game of the given
seasons from ESPN (date, teams, final score) and its closing moneyline
(DraftKings where posted, else the first book with both sides), cached.

    python tools/nba_history.py OUT.json 2022 2023 2024    # season start years

Odds are matched to teams by the team id in each side's $ref, never by
position (the UFC enrichment once mapped by position and invented an edge).
Network only; no picks are changed by this file.
"""
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import sys
import urllib.request

SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={}"
ODDS = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/{0}/competitions/{0}/odds"


def get(url, tries=3):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=25) as r:
                return json.load(r)
        except Exception:
            continue
    return None


def season_days(y):
    """Oct 15 of year y to Apr 20 of y+1."""
    d, end = dt.date(y, 10, 15), dt.date(y + 1, 4, 20)
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def games_on(day):
    j = get(SITE.format(day.strftime("%Y%m%d"))) or {}
    out = []
    for e in j.get("events", []):
        c = (e.get("competitions") or [{}])[0]
        if (e.get("season") or {}).get("type") != 2:          # regular season only
            continue
        if not ((c.get("status") or {}).get("type") or {}).get("completed"):
            continue
        side = {}
        for t in c.get("competitors", []):
            side[t["homeAway"]] = dict(id=t["team"]["id"], name=t["team"]["displayName"],
                                       score=int(float(t.get("score") or 0)))
        if "home" in side and "away" in side:
            out.append(dict(id=e["id"], date=e["date"], day=day.isoformat(), home=side["home"], away=side["away"]))
    return out


def _ml(o):
    if o is None:
        return None
    if isinstance(o, (int, float)):
        return float(o)
    try:
        return float(str(o).replace("+", ""))
    except ValueError:
        return None


def odds_for(g):
    j = get(ODDS.format(g["id"])) or {}
    items = [i for i in j.get("items", []) if "Live" not in ((i.get("provider") or {}).get("name") or "")]
    items.sort(key=lambda i: (str((i.get("provider") or {}).get("id")) != "40"))
    for it in items:
        by = {}
        for k in ("awayTeamOdds", "homeTeamOdds"):
            s = it.get(k) or {}
            m = re.search(r"/teams/(\d+)", ((s.get("team") or {}).get("$ref") or ""))
            close = ((s.get("close") or {}).get("moneyLine") or {})
            ml = _ml(close.get("american")) if isinstance(close, dict) else None
            ml = ml if ml is not None else _ml(s.get("moneyLine"))
            if m and ml is not None:
                by[m.group(1)] = ml
        if g["home"]["id"] in by and g["away"]["id"] in by:
            return dict(book=(it.get("provider") or {}).get("name"), home=by[g["home"]["id"]], away=by[g["away"]["id"]])
    return None


def main(out, years):
    try:
        with open(out) as fh:
            have = json.load(fh)
    except (OSError, ValueError):
        have = {}
    days = [d for y in years for d in season_days(y)]
    with cf.ThreadPoolExecutor(8) as ex:
        for gs in ex.map(games_on, days):
            for g in gs:
                have.setdefault(g["id"], g)
    todo = [g for g in have.values() if "odds" not in g]
    with cf.ThreadPoolExecutor(8) as ex:
        for g, o in zip(todo, ex.map(odds_for, todo)):
            g["odds"] = o
    with open(out, "w") as fh:
        json.dump(have, fh)
    print(len(have), "games;", sum(1 for g in have.values() if g.get("odds")), "with odds")


if __name__ == "__main__":
    main(sys.argv[1], [int(x) for x in sys.argv[2:]])
