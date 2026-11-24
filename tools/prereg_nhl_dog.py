#!/usr/bin/env python3
"""Pre-registered forward test (2026-11-23): NHL underdog +1.5 against a big favourite.

The overnight strategy lab (README, 2026-11-23) found one NHL rule ahead of its
closing price in each of four past seasons (+10.1, +5.7, +2.4, +7.3%) but short of
the z 2.8 bar in the later half (z +2.86 / +1.76) and -22% on 49 games this season.
A rule found by looking at the data has to prove itself on games played after it
was written down, so the terms are fixed here, before any of those games:

  bet      the underdog +1.5 at its closing price
  when     the moneyline favourite closes at -200 or shorter, regular season
  price    one book's closing moneyline and puck line from ESPN's odds feed,
           matched to teams by team id; DraftKings first
  from     games on or after 2026-11-24
  decides  after 150 such games: "supports" if it won more than its no-vig
           puck-line price by z >= 2.0 and returned a profit, else "dropped".
           Either way the result goes to the user; nothing changes picks
           without their word.

  python3 tools/prereg_nhl_dog.py            # grade everything from the start date
"""
import datetime as dt
import json
import math
import os
import re
import sys
import urllib.request

SINCE = "2026-11-24"
NEED = 150
FAV_ML = -200
Z_BAR = 2.0
SITE = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates={}"
ODDS = "https://sports.core.api.espn.com/v2/sports/hockey/leagues/nhl/events/{0}/competitions/{0}/odds"
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "prereg_nhl_dog.json")


def _num(x):
    try:
        return float(str(x).replace("+", ""))
    except (TypeError, ValueError):
        return None


def imp(a):
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def dec(a):
    return 1 + (a / 100 if a > 0 else 100 / -a)


def _team_id(side):
    m = re.search(r"/teams/(\d+)", ((side.get("team") or {}).get("$ref") or ""))
    return m.group(1) if m else None


def parse_odds(item):
    """{team_id: (moneyline, puck line, puck-line price)} from one book's item,
    closing values first. Sides that do not fit together are dropped."""
    out = {}
    for k in ("awayTeamOdds", "homeTeamOdds"):
        s = item.get(k) or {}
        tid = _team_id(s)
        close = s.get("close") or {}
        ml = _num(((close.get("moneyLine") or {}).get("american")) if isinstance(close.get("moneyLine"), dict) else None)
        ml = ml if ml is not None else _num(s.get("moneyLine"))
        pt = _num((close.get("pointSpread") or {}).get("american")) if isinstance(close.get("pointSpread"), dict) else None
        pr = _num((close.get("spread") or {}).get("american")) if isinstance(close.get("spread"), dict) else None
        pr = pr if pr is not None else _num(s.get("spreadOdds"))
        if tid and ml is not None:
            out[tid] = (ml, pt, pr)
    return out


def bet(game, sides):
    """The rule's bet on one game, or None. game: home/away team ids and the
    final goals; sides: parse_odds output. Returns dict(p, price, won)."""
    h, a = sides.get(game["home_id"]), sides.get(game["away_id"])
    if not h or not a or not 1.0 <= imp(h[0]) + imp(a[0]) <= 1.12:
        return None
    fav, dog, fav_goals, dog_goals = ((h, a, game["hs"], game["as_"]) if h[0] < a[0]
                                      else (a, h, game["as_"], game["hs"]))
    if fav[0] > FAV_ML:
        return None
    # the favourite must be the side laying 1.5 (a swapped label is skipped)
    if fav[1] is None or dog[1] is None or fav[1] != -1.5 or dog[1] != 1.5 or fav[2] is None or dog[2] is None:
        return None
    if not 1.0 <= imp(fav[2]) + imp(dog[2]) <= 1.12:
        return None
    p = imp(dog[2]) / (imp(dog[2]) + imp(fav[2]))
    return dict(p=p, price=dog[2], won=(fav_goals - dog_goals) < 2)


def status(bets, need=NEED):
    n = len(bets)
    if not n:
        return dict(n=0, need=need, verdict="waiting")
    w = sum(b["won"] for b in bets)
    e = sum(b["p"] for b in bets)
    v = sum(b["p"] * (1 - b["p"]) for b in bets)
    roi = sum((dec(b["price"]) - 1) if b["won"] else -1 for b in bets) / n
    z = (w - e) / math.sqrt(v) if v else 0.0
    verdict = ("waiting" if n < need else "supports" if z >= Z_BAR and roi > 0 else "dropped")
    return dict(n=n, need=need, won=w, expected=round(e, 1), z=round(z, 2), roi=round(100 * roi, 1), verdict=verdict)


PRIOR_PER_DAY = 8 / 7   # qualifying games Nov 17-23, 2026 (checked 2026-11-24 with collect())


def eta(bets, today, need=NEED, since=SINCE):
    """Rough date the test reaches `need` games: its own pace once it has 5+
    games, else last week's (PRIOR_PER_DAY). 2026-11-24: about 1.1 qualifying
    games a day, so 150 takes months -- said plainly rather than left implied."""
    days = max(1, (today - dt.date.fromisoformat(since)).days)
    rate = len(bets) / days if len(bets) >= 5 else PRIOR_PER_DAY
    left = max(0, need - len(bets))
    return today + dt.timedelta(days=math.ceil(left / rate)) if rate > 0 else None


def _get(url):
    for _ in range(3):
        try:
            return json.load(urllib.request.urlopen(url, timeout=30))
        except Exception:
            pass
    return None


def collect(since=SINCE, until=None):
    until = dt.date.fromisoformat(until) if until else dt.date.today() - dt.timedelta(1)
    d = dt.date.fromisoformat(since)
    bets = []
    while d <= until:
        for ev in (_get(SITE.format(f"{d:%Y%m%d}")) or {}).get("events", []):
            c = ev["competitions"][0]
            if not c["status"]["type"].get("completed") or ev.get("season", {}).get("type") != 2:
                continue
            t = {x["homeAway"]: x for x in c["competitors"]}
            g = dict(id=ev["id"], date=d.isoformat(), home_id=t["home"]["team"]["id"], away_id=t["away"]["team"]["id"],
                     hs=int(t["home"]["score"]), as_=int(t["away"]["score"]))
            items = [i for i in ((_get(ODDS.format(ev["id"])) or {}).get("items") or [])
                     if "Live" not in ((i.get("provider") or {}).get("name") or "")]
            items.sort(key=lambda i: str((i.get("provider") or {}).get("id")) != "40")   # DraftKings first
            for it in items:
                b = bet(g, parse_odds(it))
                if b:
                    bets.append(dict(b, id=g["id"], date=g["date"]))
                    break
        d += dt.timedelta(1)
    return bets


def load(path=CACHE):
    """{"through": last graded day, "bets": [...]}; empty before the first run."""
    try:
        with open(path) as f:
            c = json.load(f)
        return c if isinstance(c, dict) else dict(through=None, bets=c)
    except (OSError, ValueError):
        return dict(through=None, bets=[])


def update(path=CACHE, today=None, collect_fn=None):
    """Grade only the days since the last run (yesterday at the latest) and save."""
    today = today or dt.date.today()
    c = load(path)
    start = (dt.date.fromisoformat(c["through"]) + dt.timedelta(1)).isoformat() if c.get("through") else SINCE
    end = (today - dt.timedelta(1)).isoformat()
    if start > end:
        return c
    new = (collect_fn or collect)(start, end)
    seen = {b["id"] for b in c["bets"]}
    c = dict(through=end, bets=c["bets"] + [b for b in new if b["id"] not in seen])
    with open(path, "w") as f:
        json.dump(c, f)
    return c


if __name__ == "__main__":
    print(json.dumps(dict(status(update()["bets"]), since=SINCE)))
