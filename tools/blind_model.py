#!/usr/bin/env python3
"""Price-blind team model: our own number first, the market second.

The user asked for picks researched before looking at any line, so nobody
anchors on the price.  This builds a number from game results only: a ridge
fit of scoring margin on team strength plus home edge, weighted toward recent
games, and an offence/defence fit for the total.  No odds go in.

  python3 tools/blind_model.py fetch nba 2026-10-15   # cache ESPN results
  python3 tools/blind_model.py study                  # walk-forward vs market
  python3 tools/blind_model.py slate 2026-11-23       # today's blind numbers

`study` predicts each day only from earlier games, then compares with the
DraftKings no-vig price saved in ledger.json for the same game.  Result on
2026-11-23 (README): the blind number lost to the market in every league and
in both date halves, and no "agree / disagree / more confident" filter held
up in both halves, so it is information only and does not choose picks.
"""
import datetime
import json
import math
import os
import sys
import urllib.request

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPORT = {'nba': 'basketball/nba', 'nhl': 'hockey/nhl', 'nfl': 'football/nfl'}
# (ridge strength, recency half-life in days), chosen by walk-forward error
PARAMS = {'nba': (5, 60), 'nhl': (10, 999), 'nfl': (2, 60)}


def cache_path(lg):
    return os.path.join(ROOT, 'data', f'blind_{lg}_games.json')


def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def fit(games, asof, lam, half):
    """Team ratings from games strictly before `asof` (ISO date)."""
    G = [g for g in games if g['date'] < asof]
    if not G:
        return None
    teams = sorted({g['home'] for g in G} | {g['away'] for g in G})
    ix = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    a = datetime.date.fromisoformat(asof)
    X, y, w = [], [], []
    R, Y, WW = [], [], []
    for g in G:
        wt = 0.5 ** ((a - datetime.date.fromisoformat(g['date'])).days / half)
        r = np.zeros(n + 1)
        r[ix[g['home']]], r[ix[g['away']]] = 1, -1
        r[n] = 0 if g.get('neutral') else 1
        X.append(r)
        y.append(g['hs'] - g['as_'])
        w.append(wt)
        for sc, o, d, home in ((g['hs'], g['home'], g['away'], 1),
                               (g['as_'], g['away'], g['home'], 0)):
            q = np.zeros(2 * n + 2)
            q[ix[o]], q[n + ix[d]], q[2 * n] = 1, 1, 1
            q[2 * n + 1] = 1 if home and not g.get('neutral') else 0
            R.append(q)
            Y.append(sc)
            WW.append(wt)
    X, y, W = np.array(X), np.array(y, float), np.array(w)
    beta = np.linalg.solve(X.T @ (X * W[:, None]) + lam * np.diag([1] * n + [0.01]),
                           X.T @ (W * y))
    R, Y, WW = np.array(R), np.array(Y, float), np.array(WW)
    t = np.linalg.solve(R.T @ (R * WW[:, None]) + lam * np.diag([1] * (2 * n) + [1e-6, 0.01]),
                        R.T @ (WW * Y))
    resid = y - X @ beta
    sd = float(np.sqrt(np.average(resid ** 2, weights=W)))
    return dict(ix=ix, beta=beta, n=n, t=t, sd=max(sd, 1e-6), games=len(G))


def predict(m, home, away, neutral=False):
    """(home margin, total, home win chance) or None for an unseen team."""
    ix, b, n, t = m['ix'], m['beta'], m['n'], m['t']
    if home not in ix or away not in ix:
        return None
    mar = b[ix[home]] - b[ix[away]] + (0 if neutral else b[n])
    ph = t[2 * n] + t[ix[home]] + t[n + ix[away]] + (0 if neutral else t[2 * n + 1])
    pa = t[2 * n] + t[ix[away]] + t[n + ix[home]]
    return float(mar), float(ph + pa), phi(mar / m['sd'])


def walk_forward(games, lam, half, start_frac=0.3):
    dates = sorted({g['date'] for g in games})
    out = []
    for d in dates[int(len(dates) * start_frac):]:
        m = fit(games, d, lam, half)
        for g in (x for x in games if x['date'] == d):
            p = predict(m, g['home'], g['away'], g.get('neutral'))
            if p:
                out.append((d, g, p))
    return out


def _ip(a):
    a = float(a)
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def market_home(ledger, lg, gid):
    e = ledger.get(f'{lg}:{gid}') or {}
    pr = (e.get('first') or {}).get('prices') or {}
    try:
        h, a = _ip(pr['home']), _ip(pr['away'])
    except (KeyError, TypeError, ValueError):
        return None
    return h / (h + a)


def compare(rows):
    """rows: (market home chance, blind home chance, home won 0/1)."""
    R = np.array(rows, float)
    pm, pb, y = R.T
    dis = (pm > .5) != (pb > .5)
    return dict(n=len(R), brier_market=float(np.mean((pm - y) ** 2)),
                brier_blind=float(np.mean((pb - y) ** 2)),
                winner_market=float(np.mean((pm > .5) == y)),
                winner_blind=float(np.mean((pb > .5) == y)),
                disagree=int(dis.sum()),
                blind_right_when_disagree=(float(np.mean(((pb > .5) == y)[dis]))
                                           if dis.any() else None))


def fetch(lg, start, end=None):
    d0 = datetime.date.fromisoformat(start)
    d1 = datetime.date.fromisoformat(end) if end else datetime.date.today()
    games = []
    while d0 <= d1:
        u = (f'https://site.api.espn.com/apis/site/v2/sports/{SPORT[lg]}/scoreboard'
             f'?dates={d0:%Y%m%d}&limit=200')
        try:
            j = json.load(urllib.request.urlopen(u, timeout=30))
        except Exception as e:  # one bad day should not sink the cache
            print('skip', d0, e)
            j = {}
        for ev in j.get('events', []):
            c = ev['competitions'][0]
            if not c['status']['type'].get('completed') or ev.get('season', {}).get('type') != 2:
                continue
            t = {x['homeAway']: x for x in c['competitors']}
            games.append(dict(id=ev['id'], date=d0.isoformat(),
                              home=t['home']['team']['abbreviation'],
                              away=t['away']['team']['abbreviation'],
                              hs=int(t['home']['score']), as_=int(t['away']['score']),
                              neutral=bool(c.get('neutralSite'))))
        d0 += datetime.timedelta(1)
    games.sort(key=lambda g: (g['date'], g['id']))
    with open(cache_path(lg), 'w') as f:
        json.dump(games, f)
    return games


def main(argv):
    cmd = argv[1] if len(argv) > 1 else 'study'
    if cmd == 'fetch':
        print(len(fetch(argv[2], argv[3])), 'games')
        return 0
    if cmd == 'study':
        ledger = json.load(open(os.path.join(ROOT, 'ledger.json')))
        for lg, (lam, half) in PARAMS.items():
            if not os.path.exists(cache_path(lg)):
                continue
            rows = []
            for d, g, (mar, tot, ph) in walk_forward(json.load(open(cache_path(lg))), lam, half):
                pm = market_home(ledger, lg, g['id'])
                if pm is not None and g['hs'] != g['as_']:
                    rows.append((pm, ph, 1 if g['hs'] > g['as_'] else 0))
            if rows:
                print(lg, json.dumps(compare(rows)))
        return 0
    if cmd == 'slate':
        day = argv[2]
        for lg, (lam, half) in PARAMS.items():
            if not os.path.exists(cache_path(lg)):
                continue
            m = fit(json.load(open(cache_path(lg))), day, lam, half)
            u = (f'https://site.api.espn.com/apis/site/v2/sports/{SPORT[lg]}/scoreboard'
                 f'?dates={day.replace("-", "")}')
            for ev in json.load(urllib.request.urlopen(u, timeout=30)).get('events', []):
                t = {x['homeAway']: x['team']['abbreviation'] for x in ev['competitions'][0]['competitors']}
                p = predict(m, t['home'], t['away'])
                if p:
                    print(f"{lg} {t['away']} @ {t['home']}: home margin {p[0]:+.1f}, "
                          f"total {p[1]:.1f}, home win {p[2]:.0%}")
        return 0
    print(__doc__)
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
