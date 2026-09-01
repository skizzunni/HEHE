"""One rating engine, any league. Walk-forward Elo with per-league validation.

    python3 anysport.py wnba --backtest      # prove it (or disprove it) first
    python3 anysport.py wnba                 # tonight's board
    python3 anysport.py nhl --date 20261010

Works on any two-sided league ESPN publishes: wnba, nba, nfl, ncaaf, nhl, mlb,
epl, mls, ncaab. Ratings are built strictly forward in time -- a game is always
predicted from results that preceded it -- so the backtest cannot leak.

Elo alone is a weak model. The backtest prints it against the two baselines
that actually matter (home team, better record) so you can see whether it has
found anything. On some leagues it will not have. That is a result, not a bug.
"""
import argparse
import datetime as dt
import os
import time
import json
import math
import ssl
import statistics
import sys
import urllib.request
from collections import defaultdict

BASE = "https://site.api.espn.com/apis/site/v2/sports"
LEAGUES = {
    "wnba":  ("basketball/wnba", "WNBA", (4, 10)),
    "nba":   ("basketball/nba", "NBA", (10, 6)),
    "ncaab": ("basketball/mens-college-basketball", "NCAA MBB", (11, 4)),
    "nfl":   ("football/nfl", "NFL", (9, 2)),
    "ncaaf": ("football/college-football", "NCAA FB", (8, 1)),
    "nhl":   ("hockey/nhl", "NHL", (10, 6)),
    "mlb":   ("baseball/mlb", "MLB", (3, 10)),
    "epl":   ("soccer/eng.1", "Premier League", (8, 5)),
    "mls":   ("soccer/usa.1", "MLS", (2, 11)),
    # Added because the board showed nothing on a day with 82 soccer fixtures --
    # EPL and MLS are both dark for the September international break.
    #
    # Every one of these was backtested first and NOT ONE beats "always pick the
    # home team" by more than its own standard error. The figure after each is
    # the model's edge over that baseline in percentage points. They are on the
    # board for coverage, not because an edge was found; the site marks them.
    "efl1":  ("soccer/eng.2", "Championship", (8, 5)),        # -1.2
    "efl3":  ("soccer/eng.4", "League Two", (8, 5)),          # +3.4
    "ksa":   ("soccer/ksa.1", "Saudi Pro Lg", (8, 5)),        # +0.3
    "bra2":  ("soccer/bra.2", "Brasileirao B", (1, 11)),      # +2.5
    "col":   ("soccer/col.1", "Colombia Primera A", (1, 11)), # +3.7
    "per":   ("soccer/per.1", "Peru Liga 1", (1, 11)),        # +1.3
    "ecu":   ("soccer/ecu.1", "Ecuador LigaPro", (1, 11)),    # +4.5
    "par":   ("soccer/par.1", "Paraguay Primera", (1, 11)),   # +0.0
    #
    # Dropped: eng.3 League One (-5.1), rsa.1 South Africa (-7.8) and aut.1
    # Austria (-22.4) all lose to the home baseline outright, so a pick there
    # would be worse than naming the home side.
}

_CTX = ssl.create_default_context()
try:
    _CTX.load_verify_locations("/root/.ccr/ca-bundle.crt")
except OSError:
    pass


def get(url):
    with urllib.request.urlopen(url, timeout=60, context=_CTX) as r:
        return json.load(r)


def season_dates(league, year=None):
    """Every date in the league's season window, oldest first."""
    _, _, (m0, m1) = LEAGUES[league]
    year = year or dt.date.today().year
    start = dt.date(year, m0, 1)
    if m1 < m0:                       # season crosses the new year
        start = dt.date(year - 1, m0, 1)
    end = min(dt.date.today(), dt.date(year if m1 >= m0 else year, m1, 28))
    out, d = [], start
    while d <= end:
        out.append(d.strftime("%Y%m%d"))
        d += dt.timedelta(days=1)
    return out


CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")


def fetch_games(league, dates, workers=14, cache=True):
    """Completed games with scores, deduped, chronological. Cached for an hour."""
    cf = os.path.join(CACHE, f"{league}.json")
    if cache and os.path.exists(cf) and time.time() - os.path.getmtime(cf) < 3600:
        with open(cf) as fh:
            return json.load(fh)
    from concurrent.futures import ThreadPoolExecutor
    path = LEAGUES[league][0]

    def one(ds):
        for attempt in range(3):
            try:
                return get(f"{BASE}/{path}/scoreboard?dates={ds}")
            except Exception:
                pass
        return {}

    seen = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for d in ex.map(one, dates):
            for ev in d.get("events", []):
                for c in ev.get("competitions", []):
                    if c.get("id") in seen:
                        continue
                    st = ((c.get("status") or {}).get("type") or {})
                    if not st.get("completed"):
                        continue
                    cs = c.get("competitors") or []
                    if len(cs) != 2:
                        continue
                    try:
                        side = {x["homeAway"]: x for x in cs}
                        h, a = side["home"], side["away"]
                        hs, as_ = int(h["score"]), int(a["score"])
                    except (KeyError, ValueError, TypeError):
                        continue
                    if hs == as_:
                        continue          # draws carry no Elo signal here
                    seen[c["id"]] = dict(
                        date=(c.get("date") or "")[:10],
                        home=(h.get("team") or {}).get("displayName"),
                        away=(a.get("team") or {}).get("displayName"),
                        hs=hs, as_=as_)
    games = [g for g in seen.values() if g["home"] and g["away"] and g["date"]]
    games.sort(key=lambda g: g["date"])
    if cache:
        os.makedirs(CACHE, exist_ok=True)
        with open(cf, "w") as fh:
            json.dump(games, fh)
    return games


def run_elo(games, K, hfa, predict_from=None, cap=None):
    """Walk forward on win/loss only. `cap` is accepted and ignored so every
    method shares one signature -- win-loss Elo has no margin to cap."""
    R, n = defaultdict(lambda: 1500.0), defaultdict(int)
    preds = []
    for g in games:
        h, a = g["home"], g["away"]
        eh = 1 / (1 + 10 ** ((R[a] - (R[h] + hfa)) / 400))
        if n[h] >= 3 and n[a] >= 3 and (predict_from is None or g["date"] >= predict_from):
            preds.append((eh, g["hs"] > g["as_"], g))
        R[h] += K * ((g["hs"] > g["as_"]) - eh)
        R[a] -= K * ((g["hs"] > g["as_"]) - eh)
        n[h] += 1
        n[a] += 1
    return preds, R, n



# --------------------------------------------------------------- margin models
def _phi(x):
    """Standard normal CDF."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def run_mov_elo(games, K, hfa, predict_from=None, cap=None):
    """Elo updated with a margin-of-victory multiplier (FiveThirtyEight form).

    The multiplier grows with margin but is damped by the favourite's rating
    edge, so a blowout by an already-strong team moves the rating less. Without
    that damping, MOV Elo runs away on garbage-time scorelines.
    """
    R, n = defaultdict(lambda: 1500.0), defaultdict(int)
    preds = []
    for g in games:
        h, a = g["home"], g["away"]
        diff = (R[h] + hfa) - R[a]
        eh = 1 / (1 + 10 ** (-diff / 400))
        hw = g["hs"] > g["as_"]
        if n[h] >= 3 and n[a] >= 3 and (predict_from is None or g["date"] >= predict_from):
            preds.append((eh, hw, g))
        mov = abs(g["hs"] - g["as_"])
        if cap:
            mov = min(mov, cap)
        winner_edge = diff if hw else -diff
        mult = ((mov + 3) ** 0.8) / (7.5 + 0.006 * winner_edge)
        R[h] += K * mult * (hw - eh)
        R[a] -= K * mult * (hw - eh)
        n[h] += 1
        n[a] += 1
    return preds, R, n


def run_power(games, lr, hfa, predict_from=None, cap=None, sigma=None):
    """Point-differential power ratings.

    Each team carries a rating in POINTS -- its expected margin against an
    average team on a neutral floor. Predicted margin is the rating gap plus
    home advantage; the rating moves by a fraction of the prediction error.
    Win probability comes from the normal CDF of the predicted margin over the
    residual spread, which is estimated from the games seen so far.
    """
    R, n = defaultdict(float), defaultdict(int)
    preds, resid = [], []
    run_power.sigma = None      # the scale this run settled on, for live callers
    for g in games:
        h, a = g["home"], g["away"]
        pred = R[h] - R[a] + hfa
        actual = g["hs"] - g["as_"]
        if cap:
            actual_upd = max(-cap, min(cap, actual))
        else:
            actual_upd = actual
        s = sigma or (statistics.pstdev(resid) if len(resid) > 40 else 12.0)
        if n[h] >= 3 and n[a] >= 3 and (predict_from is None or g["date"] >= predict_from):
            preds.append((_phi(pred / s), actual > 0, g))
        err = actual_upd - pred
        R[h] += lr * err
        R[a] -= lr * err
        resid.append(actual - pred)
        run_power.sigma = s
        n[h] += 1
        n[a] += 1
    return preds, R, n


METHODS = {
    "elo": ("win-loss Elo", run_elo, (8, 12, 16, 20, 24, 32)),
    "movelo": ("margin-of-victory Elo", run_mov_elo, (4, 6, 8, 12, 16, 20)),
    "power": ("point-differential power", run_power, (0.02, 0.04, 0.06, 0.09, 0.13)),
}


def score(preds):
    if not preds:
        return 0.0, 0.0, 0
    n = len(preds)
    acc = 100 * sum(1 for p, w, _ in preds if (p > 0.5) == w) / n
    brier = sum((p - w) ** 2 for p, w, _ in preds) / n
    return acc, brier, n


def backtest(league, split=0.55):
    """Tune each method on the first part of the season, score on the rest."""
    label = LEAGUES[league][1]
    print(f"Fetching {label} season...", file=sys.stderr)
    games = fetch_games(league, season_dates(league))
    if len(games) < 80:
        print(f"\n{label}: only {len(games)} completed games -- too few to validate.")
        return
    cut = games[int(len(games) * split)]["date"]
    margins = [abs(g["hs"] - g["as_"]) for g in games]
    print(f"\n{label} -- {len(games)} completed games "
          f"({games[0]['date']} to {games[-1]['date']})")
    print(f"tune on games before {cut}, score on games after "
          f"| median margin {statistics.median(margins):.0f}\n")

    results = {}
    for key, (name, fn, grid) in METHODS.items():
        best = None
        for k in grid:
            for hfa in ((0, 25, 50, 75, 100) if key != "power" else (0, 1.5, 2.5, 3.5, 5.0)):
                for cap in (None, 20):
                    tr, _, _ = fn(games, k, hfa, cap=cap)
                    tr = [p for p in tr if p[2]["date"] < cut]
                    _, br, nn = score(tr)
                    if nn > 30 and (best is None or br < best[0]):
                        best = (br, k, hfa, cap)
        _, k, hfa, cap = best
        te, R, n = fn(games, k, hfa, predict_from=cut, cap=cap)
        acc, brier, nn = score(te)
        results[key] = dict(name=name, acc=acc, brier=brier, n=nn,
                            k=k, hfa=hfa, cap=cap, R=R, played=n)

    # walk-forward baselines on the same holdout
    W, G, rec = defaultdict(int), defaultdict(int), []
    home = []
    for g in games:
        h, a = g["home"], g["away"]
        hw = g["hs"] > g["as_"]
        if g["date"] >= cut and G[h] >= 3 and G[a] >= 3:
            home.append(hw)
            ph, pa = W[h] / G[h], W[a] / G[a]
            if ph != pa:
                rec.append((ph > pa) == hw)
        W[h] += hw; W[a] += not hw; G[h] += 1; G[a] += 1
    rec_acc = 100 * sum(rec) / len(rec) if rec else 0.0
    home_acc = 100 * sum(home) / len(home) if home else 0.0

    print(f"  {'METHOD':<28}{'ACC':<9}{'BRIER':<9}{'PARAMS':<22}N")
    print("  " + "-" * 74)
    for key in ("elo", "movelo", "power"):
        r = results[key]
        p = f"k={r['k']}, hfa={r['hfa']}" + (f", cap={r['cap']}" if r["cap"] else "")
        print(f"  {r['name']:<28}{r['acc']:.1f}%{'':<3}{r['brier']:.4f}   {p:<22}{r['n']}")
    print(f"  {'-- better W-L record':<28}{rec_acc:.1f}%{'':<3}{'':<9}{'':<22}{len(rec)}")
    print(f"  {'-- always pick home':<28}{home_acc:.1f}%{'':<3}{'':<9}{'':<22}{len(home)}")

    baseline = max(rec_acc, home_acc)
    best_key = min(results, key=lambda k: results[k]["brier"])
    b = results[best_key]
    se = math.sqrt(0.25 / b["n"]) * 100
    edge = b["acc"] - baseline
    print(f"\n  best model: {b['name']} ({b['acc']:.1f}%)")
    print(f"  edge over best baseline: {edge:+.1f} pts, 1 s.e. = {se:.1f} pts -- "
          f"{'REAL' if edge > 2 * se else 'not distinguishable from noise'}")
    gain = b["acc"] - results["elo"]["acc"]
    print(f"  margin models vs win-loss Elo: {gain:+.1f} pts")
    return results


# Best method per league, chosen by held-out Brier score in --backtest.
# Margin helps where margins are large and informative (basketball); it hurts
# where they are small and noisy (hockey: empty-net goals; soccer: 1-0 games).
TUNED = {
    # Soccer additions -- each league's own backtest winner, read off that
    # league's run. An earlier version of this block copied one league's
    # parameters onto all eight, which gave the Championship hfa=1.5 GOALS and
    # made home advantage alone worth 79%.
    "efl1": ("power",  0.04,   0, None),   # Brier 0.2236
    "efl3": ("elo",      32,  50, None),   # Brier 0.2199
    "ksa":  ("elo",      32,  25, None),   # Brier 0.1723
    "bra2": ("elo",      32,  50, None),   # Brier 0.2074
    "col":  ("elo",      24, 100, None),   # Brier 0.2051
    "per":  ("elo",      32, 100, None),   # Brier 0.2194
    "ecu":  ("elo",      32,  75, None),   # Brier 0.2146
    "par":  ("movelo",   20,  75, None),   # Brier 0.2214
    "nba":   ("movelo", 20, 50, None),
    "wnba":  ("movelo", 20, 25, None),
    "ncaab": ("movelo", 20, 50, None),
    "nfl":   ("movelo", 20, 50, 20),
    "ncaaf": ("movelo", 20, 50, 20),
    "nhl":   ("power", 0.02, 0.0, None),
    "mlb":   ("movelo", 8, 25, None),
    "epl":   ("elo", 32, 50, None),
    "mls":   ("elo", 32, 50, None),
}


def board(league, date=None, method=None):
    label, path = LEAGUES[league][1], LEAGUES[league][0]
    key, k, hfa, cap = TUNED.get(league, ("elo", 20, 50, None))
    if method:
        key = method
        k, hfa = METHODS[key][2][len(METHODS[key][2]) // 2], hfa
    name, fn, _ = METHODS[key]
    games = fetch_games(league, season_dates(league))
    if len(games) < 40:
        print(f"{label}: only {len(games)} completed games -- ratings unreliable.")
    _, R, n = fn(games, k, hfa, cap=cap)
    date = date or dt.date.today().strftime("%Y%m%d")
    d = get(f"{BASE}/{path}/scoreboard?dates={date}")
    resid = 12.0
    rows = []
    for ev in d.get("events", []):
        for c in ev.get("competitions", []):
            cs = {x.get("homeAway"): x for x in (c.get("competitors") or [])}
            if "home" not in cs or "away" not in cs:
                continue
            h = (cs["home"].get("team") or {}).get("displayName")
            a = (cs["away"].get("team") or {}).get("displayName")
            if key == "power":
                margin = R[h] - R[a] + hfa
                eh = _phi(margin / resid)
            else:
                eh = 1 / (1 + 10 ** (-((R[h] + hfa) - R[a]) / 400))
                margin = None
            fav, conf = (h, eh) if eh >= 0.5 else (a, 1 - eh)
            rows.append((conf, f"{a} @ {h}", fav, min(n[a], n[h])))
    if not rows:
        print(f"\n{label}: nothing scheduled {date}.")
        return
    rows.sort(key=lambda r: -r[0])
    print(f"\n{label} -- {date}   ({len(rows)} games)   model: {name}")
    print(f"  {'MATCHUP':<46}{'LEAN':<28}CONF")
    print("  " + "-" * 84)
    for conf, m, fav, played in rows:
        thin = "  thin data" if played < 10 else ""
        print(f"  {m[:46]:<46}{fav[:28]:<28}{conf*100:5.1f}%{thin}")
    print("\n  Accuracy is not edge -- compare every number to the price.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("league", choices=sorted(LEAGUES))
    ap.add_argument("--date")
    ap.add_argument("--backtest", action="store_true")
    ap.add_argument("--method", choices=sorted(METHODS))
    a = ap.parse_args()
    if a.backtest:
        backtest(a.league)
    else:
        board(a.league, a.date, a.method)


if __name__ == "__main__":
    main()
