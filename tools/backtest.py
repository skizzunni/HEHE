"""Backtest stacks.py on real closing lines and real final scores.

    python3 tools/backtest.py            # runs on GitHub's runners (ESPN access)

For every finished game in the windows below it pulls the closing DraftKings
(or ESPN BET) moneyline, spread, total and over/under prices, builds the exact
score model the live board uses, prices every leg the board can offer, and
grades each against the final score. Nothing the model sees comes from after
kickoff: closing lines are set before the game starts.

Three questions, answered per sport:

  1. CALIBRATION -- when the model says 90%, does it hit 90%?
  2. HAIRCUT -- the live board inflates every leg's miss chance before using
     it. That factor is FITTED here on the first half of each sport's dates
     and CHECKED on the second half, never fitted on the half it is scored on.
  3. TICKETS -- the board's own ticket builder, run day by day on the second
     half: how often each ticket size actually came in against how often the
     board said it would.

Writes data/backtest_stacks.json, which stacks.py reads for its per-sport
haircut.
"""
import datetime as dt
import json
import math
import os
import sys
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import stacks as S                                            # noqa: E402

SITE = "https://site.api.espn.com/apis/site/v2/sports"
CORE = "https://sports.core.api.espn.com/v2/sports"
CACHE = os.path.join(ROOT, ".cache", "bt")
OUT = os.path.join(ROOT, "data", "backtest_stacks.json")
TODAY = dt.date.today()

# (model key, ESPN sport, ESPN league, [(first, last) date windows])
WINDOWS = [
    ("nhl", "hockey", "nhl", [("2025-10-07", "2026-04-16"), ("2026-10-06", None)]),
    ("nfl", "football", "nfl", [("2025-09-04", "2026-01-05"), ("2026-09-09", None)]),
    ("ncaaf", "football", "college-football", [("2025-08-23", "2025-12-14"), ("2026-08-29", None)]),
    ("nba", "basketball", "nba", [("2025-10-21", "2026-04-13")]),
    ("ncaab", "basketball", "mens-college-basketball", [("2025-11-03", "2026-03-15")]),
    ("wnba", "basketball", "wnba", [("2026-05-15", "2026-09-15")]),
    ("mlb", "baseball", "mlb", [("2026-03-26", "2026-10-14")]),
    ("epl", "soccer", "eng.1", [("2025-08-15", "2026-05-24"), ("2026-08-14", None)]),
    ("esp", "soccer", "esp.1", [("2025-08-15", "2026-05-24")]),
    ("ger", "soccer", "ger.1", [("2025-08-22", "2026-05-16")]),
    ("ita", "soccer", "ita.1", [("2025-08-23", "2026-05-24")]),
    ("fra", "soccer", "fra.1", [("2025-08-15", "2026-05-16")]),
    ("mls", "soccer", "usa.1", [("2026-02-21", "2026-10-14")]),
]
# Cap per league so a run stays a few thousand requests. Games are taken from
# evenly spaced dates across the windows, not the first N, so a whole season
# is represented.
MAX_GAMES = 900


def get(url, tries=3):
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception:
            continue
    return None


def cached(name, url):
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, name)
    if os.path.exists(f):
        try:
            with open(f) as fh:
                return json.load(fh)
        except ValueError:
            pass
    d = get(url)
    if d is not None:
        with open(f, "w") as fh:
            json.dump(d, fh)
    return d


def dates(windows):
    out = []
    for a, b in windows:
        d0 = dt.date.fromisoformat(a)
        d1 = dt.date.fromisoformat(b) if b else TODAY - dt.timedelta(days=1)
        d1 = min(d1, TODAY - dt.timedelta(days=1))
        while d0 <= d1:
            out.append(d0)
            d0 += dt.timedelta(days=1)
    return out


def finished_games(key, sport, league, ds):
    """[(date, event id, home, away, home score, away score)]"""
    def one(d):
        tag = d.strftime("%Y%m%d")
        sb = cached(f"{key}-sb-{tag}.json",
                    f"{SITE}/{sport}/{league}/scoreboard?dates={tag}&limit=400")
        out = []
        for ev in (sb or {}).get("events") or []:
            s = ev.get("season") or {}
            if s.get("slug") == "preseason" or s.get("type") == 1:
                continue
            for c in ev.get("competitions") or []:
                st = ((c.get("status") or {}).get("type") or {})
                if not st.get("completed"):
                    continue
                side = {x.get("homeAway"): x for x in c.get("competitors") or []}
                try:
                    h, a = side["home"], side["away"]
                    out.append((d, c["id"], h["team"]["displayName"], a["team"]["displayName"],
                                int(h["score"]), int(a["score"])))
                except (KeyError, TypeError, ValueError):
                    continue
        return out
    with ThreadPoolExecutor(max_workers=24) as ex:
        games = [g for day in ex.map(one, ds) for g in day]
    return games


def closing(key, sport, league, eid):
    d = cached(f"{key}-odds-{eid}.json",
               f"{CORE}/{sport}/leagues/{league}/events/{eid}/competitions/{eid}/odds")
    items = (d or {}).get("items") or []
    # DraftKings first, then whatever else carries a total
    items.sort(key=lambda it: (it.get("provider") or {}).get("id") != "100")
    for it in items:
        if it.get("overUnder") is None:
            continue
        aw, hm = it.get("awayTeamOdds") or {}, it.get("homeTeamOdds") or {}
        dr = (it.get("drawOdds") or {}).get("moneyLine")
        fav = "home" if hm.get("favorite") else "away" if aw.get("favorite") else None
        return dict(away_ml=aw.get("moneyLine"), home_ml=hm.get("moneyLine"), draw_ml=dr,
                    total=it.get("overUnder"), spread=it.get("spread"), fav=fav,
                    over=it.get("overOdds"), under=it.get("underOdds"))
    return None


def am(v):
    if v is None:
        return None
    try:
        v = int(float(v))
    except (TypeError, ValueError):
        return None
    return f"+{v}" if v > 0 else str(v)


def build(key, g, o):
    """A board-shaped row for stacks.game_from_row."""
    d, eid, home, away, hs, as_ = g
    legs = [dict(side="away", price=am(o["away_ml"])), dict(side="home", price=am(o["home_ml"]))]
    soccer = key not in S.SD_MARGIN and key not in S.POISSON and key not in S.NEGBIN
    if soccer:
        legs.insert(1, dict(side="draw", price=am(o["draw_ml"])))
    fav = o["fav"]
    if fav is None and o["home_ml"] is not None and o["away_ml"] is not None:
        fav = "home" if float(o["home_ml"]) < float(o["away_ml"]) else "away"
    row = dict(id=f"{key}:{eid}", label=f"{away} @ {home}", tip="",
               legs=legs, mkt=dict(home=home, away=away, total=o["total"],
                                   spread=o["spread"], fav=fav,
                                   over=am(o["over"]), under=am(o["under"])))
    return row, soccer


# ------------------------------------------------------------------ scoring
def band(p):
    return min(int(p * 20) / 20, 0.95)        # 5-point bands


def summarise(rows):
    """rows: [(p, hit)] -> calibration list and Brier."""
    b = defaultdict(lambda: [0, 0, 0.0])
    brier = 0.0
    for p, hit in rows:
        x = b[band(p)]
        x[0] += 1
        x[1] += hit
        x[2] += p
        brier += (p - hit) ** 2
    cal = [dict(band=f"{int(k*100)}-{int(k*100)+5}%", n=v[0],
                said=round(100 * v[2] / v[0], 1), hit=round(100 * v[1] / v[0], 1),
                se=round(100 * math.sqrt(max(v[2] / v[0] * (1 - v[2] / v[0]), 1e-9) / v[0]), 1))
           for k, v in sorted(b.items())]
    return cal, (round(brier / len(rows), 4) if rows else None)


def fit_miss(rows):
    """Miss factor k so that 1-(1-p)k matches: actual misses / predicted."""
    pred = sum(1 - p for p, _ in rows)
    act = sum(1 - h for _, h in rows)
    return (act / pred) if pred > 0 else None


BASE_TARGET = (S.TARGET, S.LEG_MAX)
TARGET_TRIALS = [(0.90, 0.94), (0.94, 0.975), (0.96, 0.985), (0.97, 0.99)]
TRIAL_SIZES = (2, 3, 4, 6, 8, 10, 15, 20)


def main():
    report = dict(run=TODAY.isoformat(), sports={})
    for key, sport, league, wins in WINDOWS:
        ds = dates(wins)
        games = finished_games(key, sport, league, ds)
        if len(games) > MAX_GAMES:
            step = len(games) / MAX_GAMES
            games = [games[int(i * step)] for i in range(MAX_GAMES)]
        with ThreadPoolExecutor(max_workers=24) as ex:
            odds = list(ex.map(lambda g: closing(key, sport, league, g[1]), games))
        recs = []                 # (date, row, soccer, home score, away score)
        for g, o in zip(games, odds):
            if not o:
                continue
            row, soccer = build(key, g, o)
            recs.append((g[0], row, soccer, g[4], g[5]))
        recs.sort(key=lambda r: r[0])
        half = len(recs) // 2
        markets, legs_fit, legs_test = [], [], []
        per_day = defaultdict(list)
        errors = 0
        for i, (d, row, soccer, hs, as_) in enumerate(recs):
            try:
                g = S.game_from_row(row, key, soccer)
            except Exception:
                errors += 1
                continue
            if not g:
                continue
            for group, label, spec in S.market_menu(g, key, row["mkt"]):
                p = g.prob_specs([spec])
                if p is None:
                    continue
                hit = int(S.predicate(spec, g.home, g.away)(hs, as_))
                markets.append((group, p, hit))
            # the same favourite rule as the live board (stacks.candidates);
            # ">= 0.5" picked the other side in soccer, where a draw exists
            fav_home = g.prob_specs([dict(t="win", team=g.home)]) >= \
                g.prob_specs([dict(t="win", team=g.away)])
            for grp, label, spec in S.leg_specs(g, key, fav_home):
                p = g.prob_specs([spec])
                if p is None or not 0.75 <= p <= 0.995:
                    continue
                hit = int(S.predicate(spec, g.home, g.away)(hs, as_))
                (legs_fit if i < half else legs_test).append((p, hit, label.split(" ")[0]))
            if i >= half:
                per_day[d].append((row, hs, as_))
        k = fit_miss([(p, h) for p, h, _ in legs_fit if 0.80 <= p <= 0.98]) or S.MISS_INFLATE
        k = max(1.0, round(k, 2))
        # holdout calibration: raw and after the fitted haircut
        raw_test = [(p, h) for p, h, _ in legs_test]
        cut_test = [(max(0.0, 1 - (1 - p) * k), h) for p, h, _ in legs_test]
        cal_raw, br_raw = summarise(raw_test)
        cal_cut, br_cut = summarise(cut_test)
        by_group = defaultdict(list)
        for grp, p, h in markets:
            by_group[grp].append((p, h))
        # tickets on the holdout days, built exactly as the board builds them
        S.MISS_BY_SPORT[S.sport_of(key)] = k
        tk = defaultdict(lambda: [0, 0, 0.0])
        trials = defaultdict(lambda: [0, 0, 0.0, 0.0])
        for d, games_d in sorted(per_day.items()):
            slot = {key: [r for r, _, _ in games_d]}
            score = {r["id"]: (hs, as_) for r, hs, as_ in games_d}
            cands = S.candidates(slot, set() if key in S.SD_MARGIN or key in S.POISSON
                                 or key in S.NEGBIN else {key})
            # the 10-leg ticket with legs aimed at different strengths: how
            # often each won on these unseen days, and what it paid
            for tgt, top in TARGET_TRIALS:
                S.TARGET, S.LEG_MAX = tgt, top
                c2 = S.candidates(slot, set() if key in S.SD_MARGIN or key in S.POISSON
                                  or key in S.NEGBIN else {key})
                for size, tks in S.build_tickets(c2, tiers=TRIAL_SIZES).items():
                    for t in tks:
                        ok = all(S.predicate(L["spec"], L["home"], L["away"])(*score[L["gid"]])
                                 for L in t["legs"])
                        x = trials[(size, tgt, top)]
                        x[0] += 1
                        x[1] += ok
                        x[2] += t["prob"]
                        x[3] += t["fair"] or 0
            S.TARGET, S.LEG_MAX = BASE_TARGET
            for n, tickets in S.build_tickets(cands, tiers=(2, 3, 4, 6, 8, 10)).items():
                for t in tickets:
                    ok = all(S.predicate(L["spec"], L["home"], L["away"])(*score[L["gid"]])
                             for L in t["legs"])
                    x = tk[n]
                    x[0] += 1
                    x[1] += ok
                    x[2] += t["prob"]
        report["sports"][key] = dict(
            games=len(recs), priced=len(recs) - errors, errors=errors,
            fitted_miss_factor=k,
            stack_legs=dict(fit=len(legs_fit), test=len(legs_test),
                            raw=cal_raw, raw_brier=br_raw,
                            haircut=cal_cut, haircut_brier=br_cut),
            markets={grp: dict(zip(("calibration", "brier"), summarise(v)))
                     for grp, v in by_group.items()},
            tickets=[dict(size=n, played=v[0], won=v[1], expected=round(v[2], 1))
                     for n, v in sorted(tk.items())],
            aim_trials=[dict(size=n, target=t, leg_max=m, played=v[0], won=v[1],
                             expected=round(v[2], 1),
                             avg_fair=round(v[3] / v[0], 2) if v[0] else None)
                        for (n, t, m), v in sorted(trials.items())])
        r = report["sports"][key]
        print(f"\n===== {key}: {r['games']} games, miss factor fitted {k}")
        print("  stack legs, HOLDOUT, after haircut:")
        for c in cal_cut:
            if c["n"] >= 20:
                print(f"    said {c['said']:5.1f}%  hit {c['hit']:5.1f}%  n={c['n']:<5} (±{c['se']})")
        print("  tickets, HOLDOUT:")
        for t in r["tickets"]:
            print(f"    {t['size']:>2}-leg  won {t['won']}/{t['played']}  expected {t['expected']}")
        for t in r["aim_trials"]:
            print(f"    {t['size']}-leg aimed {t['target']}: won {t['won']}/{t['played']}  "
                  f"expected {t['expected']}  pays ~{t['avg_fair']}x")
        sys.stdout.flush()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(report, fh, indent=1)
    print("\nwrote", OUT)


if __name__ == "__main__":
    main()
