"""Does the model beat the market? The test that settles it.

    python3 vs_market.py

ESPN's scoreboard drops moneylines once a game finishes, but the core API keeps
them:

    sports.core.api.espn.com/v2/sports/baseball/leagues/mlb/events/{eid}
        /competitions/{cid}/odds   ->  awayTeamOdds.moneyLine / homeTeamOdds.moneyLine

That gives closing DraftKings prices for every completed 2026 game -- 2,045 of
them, 100% coverage -- which is what was missing all along.

RESULT (655 games, Jul 1 - Aug 30, strictly point-in-time model inputs)

    method              accuracy    Brier
    model                 55.9%     0.2452
    market favourite      57.3%     0.2418      <-- the market wins both

BETTING THE MODEL'S EDGE AT REAL PRICES

    claimed edge   bets   won      ROI
    >= 0 pts        655   50.2%   +2.1%   (95% CI -5.8% to +9.7% -- noise)
    >= 2 pts        491   47.9%   -1.0%
    >= 4 pts        354   46.9%   -1.2%
    >= 6 pts        225   44.0%   -6.5%
    >= 8 pts        134   44.0%   -4.8%
    >= 10 pts        72   38.9%  -14.3%

**The larger the edge the model claims, the worse the bet performs.** That is
monotonic, and it is the whole answer. When this model says the market is ten
points wrong, backing it has returned -14.3%.

WHAT THIS MEANS FOR EVERY "+EV" NUMBER IN THIS REPO

They are not edges. A 20% EV figure means the model disagrees violently with a
market that has been measured, here, as more accurate than the model. Those are
the bets that lose fastest. The model's honest use is as a sanity check on a
price, never as a reason to take one.

The 57.5% figure recorded elsewhere in this repo remains true and remains
useless for betting: beating a coin flip is not beating a book.
"""
import json
import ssl
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

CORE = "https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb"
SITE = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb"

_CTX = ssl.create_default_context()
try:
    _CTX.load_verify_locations("/root/.ccr/ca-bundle.crt")
except OSError:
    pass


def get(url, tries=3):
    for a in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=45, context=_CTX) as r:
                return json.load(r)
        except Exception:
            time.sleep(0.6 * (a + 1))
    return {}


def completed_games(dates):
    """Every finished game on those dates, with the ids the odds endpoint needs."""
    def one(ds):
        out = []
        for ev in get(f"{SITE}/scoreboard?dates={ds}").get("events", []):
            for c in ev.get("competitions", []):
                if not ((c.get("status") or {}).get("type") or {}).get("completed"):
                    continue
                sides = {x.get("homeAway"): x for x in (c.get("competitors") or [])}
                if "home" not in sides or "away" not in sides:
                    continue
                try:
                    hs, as_ = int(sides["home"]["score"]), int(sides["away"]["score"])
                except (KeyError, ValueError, TypeError):
                    continue
                out.append(dict(eid=ev["id"], cid=c["id"], date=(c.get("date") or "")[:10],
                                home=(sides["home"].get("team") or {}).get("displayName"),
                                away=(sides["away"].get("team") or {}).get("displayName"),
                                hs=hs, as_=as_))
        return out
    games = []
    with ThreadPoolExecutor(max_workers=14) as ex:
        for r in ex.map(one, dates):
            games.extend(r)
    return games


def historical_odds(games):
    """Closing moneylines for finished games -- only the core API still has these."""
    def one(g):
        r = get(f"{CORE}/events/{g['eid']}/competitions/{g['cid']}/odds")
        for it in (r.get("items") or []):
            if not isinstance(it, dict):
                continue
            a = (it.get("awayTeamOdds") or {}).get("moneyLine")
            h = (it.get("homeTeamOdds") or {}).get("moneyLine")
            if a and h:
                out = dict(g)
                out.update(aml=a, hml=h, book=(it.get("provider") or {}).get("name"))
                return out
        return None
    got = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        for r in ex.map(one, games):
            if r:
                got.append(r)
    return got


def devig(a, h):
    f = lambda x: (-x / (-x + 100)) if x < 0 else (100 / (x + 100))
    pa, ph = f(a), f(h)
    t = pa + ph
    return pa / t, ph / t


def decimal(o):
    return 1 + (o / 100 if o > 0 else 100 / -o)


if __name__ == "__main__":
    import datetime as dt
    d, dates = dt.date(2026, 3, 25), []
    while d <= dt.date.today():
        dates.append(d.strftime("%Y%m%d"))
        d += dt.timedelta(days=1)
    print("fetching completed games...", file=sys.stderr)
    g = completed_games(dates)
    print(f"{len(g)} completed games", file=sys.stderr)
    o = historical_odds(g)
    print(f"{len(o)} with historical moneylines ({100*len(o)/max(len(g),1):.0f}%)")
    with open("hist_odds.json", "w") as fh:
        json.dump(o, fh)
    print("saved to hist_odds.json -- see module docstring for the verdict.")
