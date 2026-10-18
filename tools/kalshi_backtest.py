"""Does Kalshi ever sell a leg cheaper than the sportsbooks say it is worth?

    python3 tools/kalshi_backtest.py        # runs on GitHub's runners

For every finished game Kalshi listed, this takes:

  * Kalshi's price to BUY each leg in the last hourly candle before kickoff
    (YES at the yes ask; NO at 1 - yes bid), plus Kalshi's taker fee;
  * the board's fair probability for that leg, from the score model fitted to
    DraftKings' CLOSING moneyline, spread and total (known before kickoff);
  * Kalshi's own settlement of the market (result yes / no) -- the same rule
    a combo leg is graded by.

A leg is "value" when the fair probability, after the per-sport haircut,
beats the all-in price by some margin. The question is whether buying those
legs made money. The margin is chosen on the first half of the dates and
scored on the second half only, so the reported result is out of sample.

Writes data/backtest_kalshi.json.
"""
from zoneinfo import ZoneInfo
import datetime as dt
import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import stacks as S                                            # noqa: E402
import backtest as B                                          # noqa: E402

K = "https://api.elections.kalshi.com/trade-api/v2"
CACHE = os.path.join(ROOT, ".cache", "kbt")
OUT = os.path.join(ROOT, "data", "backtest_kalshi.json")
# every priced leg, long shots included, for replaying lottery tickets
# (tools/lottery_backtest.py)
LEGS_OUT = os.path.join(ROOT, "data", "backtest_kalshi_legs.json")
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
MON = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

# (board key, ESPN sport, ESPN league, Kalshi prefix, date windows). Kalshi's
# game markets start in the 2025-26 seasons.
LEAGUES = [
    ("nhl", "hockey", "nhl", "NHL", [("2025-10-07", "2026-04-16"), ("2026-10-06", None)]),
    ("nfl", "football", "nfl", "NFL", [("2025-09-04", "2026-01-05"), ("2026-09-09", None)]),
    ("ncaaf", "football", "college-football", "NCAAF", [("2025-08-23", "2025-12-14"), ("2026-08-29", None)]),
    ("nba", "basketball", "nba", "NBA", [("2025-10-21", "2026-04-13")]),
    ("epl", "soccer", "eng.1", "EPL", [("2025-08-15", "2026-05-24"), ("2026-08-14", None)]),
]
MAX_GAMES = 450
P_RANGE = (0.10, 0.99)         # legs worth pricing, lottery long shots included
VALUE_RANGE = (0.55, 0.99)     # the value-leg study below, as it always was


# ------------------------------------------------------------- polite fetch
_lock = threading.Lock()
_last = [0.0]


def kget(path, name=None):
    """Kalshi GET, cached on disk, at most ~7 requests a second."""
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, name) if name else None
    if f and os.path.exists(f):
        try:
            with open(f) as fh:
                return json.load(fh)
        except ValueError:
            pass
    for attempt in range(5):
        with _lock:
            wait = 0.15 - (time.time() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        try:
            req = urllib.request.Request(K + path, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
            if f:
                with open(f, "w") as fh:
                    json.dump(d, fh)
            return d
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 + 3 * attempt)
                continue
            if e.code == 404:
                d = {}
                if f:
                    with open(f, "w") as fh:
                        json.dump(d, fh)
                return d
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return None


# ----------------------------------------------------------------- games
def games_with_start(key, sport, league, days):
    """[(date, eid, home, away, hs, as, home_abbr, away_abbr, start_iso)]"""
    out = []
    def one(d):
        tag = d.strftime("%Y%m%d")
        sb = B.cached(f"{key}-sb-{tag}.json",
                      f"{B.SITE}/{sport}/{league}/scoreboard?dates={tag}&limit=400")
        rows = []
        for ev in (sb or {}).get("events") or []:
            s = ev.get("season") or {}
            if s.get("slug") == "preseason" or s.get("type") == 1:
                continue
            for c in ev.get("competitions") or []:
                if not ((c.get("status") or {}).get("type") or {}).get("completed"):
                    continue
                side = {x.get("homeAway"): x for x in c.get("competitors") or []}
                try:
                    h, a = side["home"], side["away"]
                    rows.append((d, c["id"], h["team"]["displayName"], a["team"]["displayName"],
                                 int(h["score"]), int(a["score"]),
                                 h["team"].get("abbreviation"), a["team"].get("abbreviation"),
                                 c.get("date")))
                except (KeyError, TypeError, ValueError):
                    continue
        return rows
    with ThreadPoolExecutor(max_workers=16) as ex:
        for r in ex.map(one, days):
            out.extend(r)
    return out


def utc(iso):
    try:
        return dt.datetime.strptime(iso[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def tail_for(start, away_abbr, home_abbr):
    et = start.astimezone(ZoneInfo("America/New_York"))
    return f"{et.strftime('%y')}{MON[et.month - 1]}{et.day:02d}{away_abbr}{home_abbr}".upper()


def kalshi_game(prefix, tail):
    """{kind: [market]} for one game, or {} if Kalshi did not list it."""
    g = {}
    for kind in ("GAME", "TOTAL", "SPREAD"):
        ev = f"KX{prefix}{kind}-{tail}"
        d = kget(f"/markets?event_ticker={ev}&limit=100", f"m-{ev}.json") or {}
        ms = [m for m in d.get("markets") or [] if m.get("result") in ("yes", "no")]
        if ms:
            g[kind] = ms
    return g


def candle_price(series, ticker, start):
    """(yes ask, yes bid) in the last hourly candle that closed before start."""
    end = int(start.timestamp())
    d = kget(f"/series/{series}/markets/{ticker}/candlesticks?start_ts={end - 6 * 3600}"
             f"&end_ts={end}&period_interval=60", f"c-{ticker}.json") or {}
    best = None
    for c in d.get("candlesticks") or []:
        if (c.get("end_period_ts") or 0) <= end:
            best = c
    if not best:
        return None
    try:
        ask = float((best.get("yes_ask") or {}).get("close_dollars"))
        bid = float((best.get("yes_bid") or {}).get("close_dollars"))
    except (TypeError, ValueError):
        return None
    return ask, bid


def fee(price):
    """Kalshi taker fee per contract: 7% of P(1-P), rounded up to a cent."""
    return math.ceil(0.07 * price * (1 - price) * 100 - 1e-9) / 100


def code(m):
    t = (m.get("ticker") or "").rsplit("-", 1)[-1]
    out = ""
    for ch in t:
        if ch.isalpha():
            out += ch
        else:
            break
    return out


# --------------------------------------------------------------- one league
def legs_for_game(key, prefix, g, kg, home, away, ha, aa):
    """(spec, side, market) for every Kalshi market we can map to a leg."""
    out = []
    team_of = {ha.upper(): home, aa.upper(): away}
    for m in kg.get("TOTAL") or []:
        L = m.get("floor_strike")
        if L is None:
            continue
        L = float(L)
        out.append((dict(t="over", line=L), "YES", m, f"KX{prefix}TOTAL"))
        out.append((dict(t="under", line=L), "NO", m, f"KX{prefix}TOTAL"))
    for m in kg.get("SPREAD") or []:
        L, team = m.get("floor_strike"), team_of.get(code(m))
        if L is None or not team:
            continue
        L = float(L)
        out.append((dict(t="spread", team=team, line=-L), "YES", m, f"KX{prefix}SPREAD"))
        out.append((dict(t="nomargin", team=team, line=L), "NO", m, f"KX{prefix}SPREAD"))
    for m in kg.get("GAME") or []:
        c = code(m)
        if c == "TIE":
            out.append((dict(t="draw"), "YES", m, f"KX{prefix}GAME"))
            continue
        team = team_of.get(c)
        if team:
            out.append((dict(t="win", team=team), "YES", m, f"KX{prefix}GAME"))
    return out


def run_league(key, sport, league, prefix, wins):
    days = B.dates(wins)
    games = games_with_start(key, sport, league, days)
    if len(games) > MAX_GAMES:
        step = len(games) / MAX_GAMES
        games = [games[int(i * step)] for i in range(MAX_GAMES)]
    stats = dict(games=len(games), on_kalshi=0, no_odds=0, legs=0, priced=0)
    rows = []

    def one(gm):
        d, eid, home, away, hs, as_, ha, aa, start_iso = gm
        start = utc(start_iso)
        if not (start and ha and aa):
            return None
        kg = kalshi_game(prefix, tail_for(start, aa, ha))
        if not kg:
            return None
        o = B.closing(key, sport, league, eid)
        if not o:
            return ("noodds",)
        row, soccer = B.build(key, gm[:6], o)
        row["mkt"].update(home_abbr=ha, away_abbr=aa, start=start_iso)
        try:
            g = S.game_from_row(row, key, soccer)
        except Exception:
            g = None
        if not g:
            return ("noodds",)
        found = []
        for spec, side, m, series in legs_for_game(key, prefix, g, kg, home, away, ha, aa):
            p = g.prob_specs([spec])
            if p is None or not P_RANGE[0] <= p <= P_RANGE[1]:
                continue
            q = candle_price(series, m["ticker"], start)
            if not q:
                found.append(None)
                continue
            ask, bid = q
            cost = ask if side == "YES" else 1 - bid
            if not 0.02 <= cost <= 0.99 or ask <= bid:
                found.append(None)
                continue
            won = (m["result"] == "yes") == (side == "YES")
            found.append(dict(date=d.isoformat(), ticker=m["ticker"], side=side, spec=spec,
                              game=f"{key}:{eid}",
                              p=round(p, 4), q=round(S.haircut(p, key), 4),
                              cost=round(cost, 4), fee=fee(cost), width=round(ask - bid, 4),
                              won=int(won)))
        return ("ok", found)

    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in ex.map(one, games):
            if not r:
                continue
            if r[0] == "noodds":
                stats["no_odds"] += 1
                continue
            stats["on_kalshi"] += 1
            for x in r[1]:
                stats["legs"] += 1
                if x:
                    stats["priced"] += 1
                    rows.append(dict(x, league=key))
    return stats, rows


# --------------------------------------------------------------- analysis
def roi(rows):
    stake = sum(r["cost"] + r["fee"] for r in rows)
    ret = sum(r["won"] for r in rows)
    n = len(rows)
    if not n or not stake:
        return dict(n=n, roi=None)
    # the interval resamples whole games and recomputes this same ROI
    import resample
    rc = resample.roi_ci(rows, lambda r: r["cost"] + r["fee"])
    return dict(n=n, games=rc["games"], hit=round(100 * ret / n, 1),
                avg_cost=round(100 * stake / n, 1),
                roi=round(100 * (ret - stake) / stake, 2), ci95=rc["ci95"])


def calibration(rows, key):
    b = defaultdict(lambda: [0, 0, 0.0])
    for r in rows:
        x = b[min(int(r[key] * 20) / 20, 0.95)]
        x[0] += 1
        x[1] += r["won"]
        x[2] += r[key]
    return [dict(band=f"{int(k*100)}-{int(k*100)+5}%", n=v[0],
                 said=round(100 * v[2] / v[0], 1), hit=round(100 * v[1] / v[0], 1))
            for k, v in sorted(b.items()) if v[0] >= 20]


def main():
    report = dict(run=dt.date.today().isoformat(), leagues={})
    allrows = []
    for key, sport, league, prefix, wins in LEAGUES:
        stats, rows = run_league(key, sport, league, prefix, wins)
        report["leagues"][key] = stats
        allrows += rows
        print(f"{key}: {stats}", flush=True)
    allrows.sort(key=lambda r: r["date"])
    with open(LEGS_OUT, "w") as fh:
        json.dump(allrows, fh, separators=(",", ":"))
    allrows = [r for r in allrows if VALUE_RANGE[0] <= r["p"] <= VALUE_RANGE[1]]
    # split on a date: a row-count split put one game's lines on both sides
    dates = sorted({r["date"] for r in allrows})
    cut = dates[len(dates) // 2] if dates else ""
    fit, test = [r for r in allrows if r["date"] < cut], [r for r in allrows if r["date"] >= cut]
    edge = lambda r: r["q"] - (r["cost"] + r["fee"])
    thresholds = (0.0, 0.02, 0.04, 0.06, 0.08)
    by_t_fit = {t: roi([r for r in fit if edge(r) >= t]) for t in thresholds}
    # pick the margin on the first half only; require a real sample
    ok = [t for t in thresholds if (by_t_fit[t].get("n") or 0) >= 100 and by_t_fit[t]["roi"] is not None]
    chosen = max(ok, key=lambda t: by_t_fit[t]["roi"]) if ok else None
    report.update(
        legs=len(allrows),
        kalshi_calibration=calibration([dict(r, k=r["cost"]) for r in allrows], "k"),
        model_calibration=calibration(allrows, "q"),
        all_legs_roi=roi(allrows),
        fit_half=dict(range=[fit[0]["date"], fit[-1]["date"]] if fit else None,
                      by_threshold={str(t): v for t, v in by_t_fit.items()}),
        chosen_margin=chosen,
        test_half=dict(range=[test[0]["date"], test[-1]["date"]] if test else None,
                       chosen=(roi([r for r in test if edge(r) >= chosen]) if chosen is not None else None),
                       by_threshold={str(t): roi([r for r in test if edge(r) >= t])
                                     for t in thresholds}),
        by_league={k: roi([r for r in test if r["league"] == k and chosen is not None
                           and edge(r) >= chosen]) for k, *_ in LEAGUES},
        stack_band=dict(all=roi([r for r in allrows if 0.80 <= r["q"] <= 0.94]),
                        value=roi([r for r in test if 0.80 <= r["q"] <= 0.94 and chosen is not None
                                   and edge(r) >= chosen])))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(report, fh, indent=1)
    print(json.dumps({k: v for k, v in report.items() if k != "leagues"}, indent=1))


if __name__ == "__main__":
    main()
