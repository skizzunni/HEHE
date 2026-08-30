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
import json
import math
import ssl
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


def fetch_games(league, dates, workers=14):
    """Completed games with scores, deduped, chronological."""
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
    return games


def run_elo(games, K, hfa, predict_from=None):
    """Walk forward. Returns (predictions, final ratings, games played)."""
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


def score(preds):
    if not preds:
        return 0.0, 0.0, 0
    n = len(preds)
    acc = 100 * sum(1 for p, w, _ in preds if (p > 0.5) == w) / n
    brier = sum((p - w) ** 2 for p, w, _ in preds) / n
    return acc, brier, n


def backtest(league, split=0.55):
    label = LEAGUES[league][1]
    print(f"Fetching {label} season...", file=sys.stderr)
    games = fetch_games(league, season_dates(league))
    if len(games) < 80:
        print(f"\n{label}: only {len(games)} completed games -- too few to validate.")
        return
    cut = games[int(len(games) * split)]["date"]
    print(f"\n{label} -- {len(games)} completed games "
          f"({games[0]['date']} to {games[-1]['date']})")
    print(f"tuning on games before {cut}, scoring on games after\n")
    best = None
    for K in (8, 12, 16, 20, 24, 32):
        for hfa in (0, 25, 50, 75, 100):
            tr, _, _ = run_elo(games, K, hfa)
            tr = [p for p in tr if p[2]["date"] < cut]
            _, br, nn = score(tr)
            if nn > 30 and (best is None or br < best[0]):
                best = (br, K, hfa)
    _, K, hfa = best
    te, R, n = run_elo(games, K, hfa, predict_from=cut)
    acc, brier, nn = score(te)
    home = 100 * sum(1 for _, w, _ in te if w) / nn
    # better-record baseline, walk-forward
    W = defaultdict(int); G = defaultdict(int); rec = []
    for g in games:
        h, a = g["home"], g["away"]
        if g["date"] >= cut and G[h] >= 3 and G[a] >= 3:
            ph = W[h] / G[h]; pa = W[a] / G[a]
            if ph != pa:
                rec.append((ph > pa) == (g["hs"] > g["as_"]))
        W[h] += g["hs"] > g["as_"]; W[a] += g["as_"] > g["hs"]; G[h] += 1; G[a] += 1
    print(f"  best params: K={K}, home advantage={hfa} Elo\n")
    print(f"  {'METHOD':<26}{'ACCURACY':<12}N")
    print("  " + "-" * 46)
    print(f"  {'Elo (walk-forward)':<26}{acc:.1f}%{'':<6}{nn}")
    if rec:
        print(f"  {'better W-L record':<26}{100*sum(rec)/len(rec):.1f}%{'':<6}{len(rec)}")
    print(f"  {'always pick home':<26}{home:.1f}%{'':<6}{nn}")
    print(f"  {'Brier':<26}{brier:.4f}")
    edge = acc - max(home, (100*sum(rec)/len(rec)) if rec else 0)
    se = math.sqrt(0.25 / nn) * 100
    print(f"\n  edge over best baseline: {edge:+.1f} pts "
          f"(1 s.e. = {se:.1f} pts) -- "
          f"{'REAL' if edge > 2*se else 'NOT distinguishable from noise'}")
    return dict(K=K, hfa=hfa, acc=acc, n=nn)


def board(league, date=None):
    label, path = LEAGUES[league][1], LEAGUES[league][0]
    games = fetch_games(league, season_dates(league))
    if len(games) < 40:
        print(f"{label}: only {len(games)} completed games -- ratings unreliable.")
    K, hfa = 20, 50
    _, R, n = run_elo(games, K, hfa)
    date = date or dt.date.today().strftime("%Y%m%d")
    d = get(f"{BASE}/{path}/scoreboard?dates={date}")
    rows = []
    for ev in d.get("events", []):
        for c in ev.get("competitions", []):
            cs = {x.get("homeAway"): x for x in (c.get("competitors") or [])}
            if "home" not in cs or "away" not in cs:
                continue
            h = (cs["home"].get("team") or {}).get("displayName")
            a = (cs["away"].get("team") or {}).get("displayName")
            eh = 1 / (1 + 10 ** ((R[a] - (R[h] + hfa)) / 400))
            fav, conf = (h, eh) if eh >= 0.5 else (a, 1 - eh)
            rows.append((conf, f"{a} @ {h}", fav, R[a], R[h], n[a], n[h]))
    if not rows:
        print(f"\n{label}: nothing scheduled {date}.")
        return
    rows.sort(key=lambda r: -r[0])
    print(f"\n{label} -- {date}   ({len(rows)} games)")
    print(f"  {'MATCHUP':<44}{'ELO LEAN':<26}CONF   (elo away/home)")
    print("  " + "-" * 92)
    for conf, m, fav, ra, rh, na, nh in rows:
        thin = "  thin" if min(na, nh) < 10 else ""
        print(f"  {m[:44]:<44}{fav[:26]:<26}{conf*100:5.1f}%   "
              f"{ra:.0f}/{rh:.0f}{thin}")
    print("\n  Run --backtest for this league before trusting any of it.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("league", choices=sorted(LEAGUES))
    ap.add_argument("--date")
    ap.add_argument("--backtest", action="store_true")
    a = ap.parse_args()
    if a.backtest:
        backtest(a.league)
    else:
        board(a.league, a.date)


if __name__ == "__main__":
    main()
