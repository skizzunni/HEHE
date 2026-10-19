"""The edge lab: can anything pick winners better than the closing favourite?

    python3 tools/edge_lab.py      # on GitHub's runners (ESPN is not reachable here)

The closing price is the market's last word, and picking its favourite in
every game is the bar (about 66-68% on this site's mix). The only way over it
is information the close has not fully priced. Three candidates, all known
before kickoff, are tested on every finished game of the past seasons in
tools/backtest.py's windows, using DraftKings' own OPEN and CLOSE lines from
ESPN's odds feed:

  drift     the move from open to close, in log-odds. If the market moves
            toward the truth but stops short, the move keeps going and
            leaning further the same way beats the close.
  spread    the win chance the closing POINT SPREAD implies, against the one
            the moneyline implies. Two prices for the same thing; where they
            disagree, does one know more?
  total     high-scoring games give underdogs more chances; does the
            moneyline under-price that?
  rest      days since each side last played, back-to-backs, and how long
            the away side has been on the road (from the full schedule).
  form      each side's results against its own prices over its last 8
            games: does the market catch up with hot and cold teams late?

Method: per league, games in date order; a logistic model on
[close log-odds, drift, spread signal, close x total] is fitted on the older
half and scored on the newer half ONLY, against simply picking the closing
favourite. Reported: hit rate of every game's pick, and log-loss. Nothing
here touches the live picks until it wins on the half it never saw.

Writes data/edge_lab.json.
"""
import datetime as dt
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import backtest as B                                          # noqa: E402

OUT = os.path.join(ROOT, "data", "edge_lab.json")
CORE = "https://sports.core.api.espn.com/v2/sports"
LEAGUES = ("nfl", "ncaaf", "nba", "ncaab", "wnba", "nhl", "mlb")
MAX_GAMES = 1500
# points per standard deviation of the final margin, to turn a spread into a
# win chance (the usual figures; the model refits the weight anyway)
SIGMA = {"nfl": 13.5, "ncaaf": 16.0, "nba": 12.0, "ncaab": 11.0, "wnba": 11.0,
         "nhl": 2.3, "mlb": 4.2}


def am(x):
    try:
        v = float(str(x).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if -100 < v < 100:
        return None
    return 100 / (v + 100) if v > 0 else -v / (-v + 100)


def num(x):
    try:
        return float(str(x).replace("+", ""))
    except (TypeError, ValueError):
        return None


def pick(side, when, what):
    o = (side or {}).get(when) or {}
    if what == "ml":
        return am(((o.get("moneyLine") or {}).get("american")))
    return num(((o.get("pointSpread") or {}).get("american")))


def lg(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def row_for(key, sport, league, g):
    d, eid, home, away, hs, as_ = g
    if hs == as_:
        return None
    raw = B.cached(f"{key}-odds-{eid}.json",
                   f"{CORE}/{sport}/leagues/{league}/events/{eid}/competitions/{eid}/odds")
    for it in (raw or {}).get("items") or []:
        h, a = it.get("homeTeamOdds") or {}, it.get("awayTeamOdds") or {}
        hc, ac, ho, ao = pick(h, "close", "ml"), pick(a, "close", "ml"), pick(h, "open", "ml"), pick(a, "open", "ml")
        if None in (hc, ac):
            continue
        pc = hc / (hc + ac)                             # de-vigged close, home
        po = ho / (ho + ao) if None not in (ho, ao) else pc
        sp = pick(h, "close", "spread")                 # home's spread, e.g. -7.5
        tot = num(((it.get("close") or {}).get("total") or {}).get("american")) or num(it.get("overUnder"))
        return dict(date=d.isoformat(), eid=str(eid), home=home, away=away, home_won=int(hs > as_), pc=pc, po=po,
                    ih=hc, ia=ac,
                    ps=ncdf(-sp / SIGMA[key]) if sp is not None else pc, total=tot or 0.0)
    return None


def fit_logit(X, y, l2=1.0, iters=60):
    """Newton's method for logistic regression with a small ridge."""
    k = len(X[0])
    w = [0.0] * k
    for _ in range(iters):
        g = [0.0] * k
        H = [[0.0] * k for _ in range(k)]
        for x, t in zip(X, y):
            z = sum(a * b for a, b in zip(w, x))
            p = 1 / (1 + math.exp(-max(min(z, 30), -30)))
            for i in range(k):
                g[i] += (p - t) * x[i]
                for j in range(k):
                    H[i][j] += p * (1 - p) * x[i] * x[j]
        for i in range(k):
            g[i] += l2 * w[i] * (i > 0)
            H[i][i] += l2 * (i > 0) + 1e-9
        # solve H d = g (Gaussian elimination)
        M = [H[i][:] + [g[i]] for i in range(k)]
        for c in range(k):
            piv = max(range(c, k), key=lambda r: abs(M[r][c]))
            M[c], M[piv] = M[piv], M[c]
            for r in range(k):
                if r != c and M[c][c]:
                    f = M[r][c] / M[c][c]
                    M[r] = [a - f * b for a, b in zip(M[r], M[c])]
        d = [M[i][k] / M[i][i] if M[i][i] else 0.0 for i in range(k)]
        w = [a - b for a, b in zip(w, d)]
        if max(abs(x) for x in d) < 1e-7:
            break
    return w


def add_rest(rows, all_games):
    """Days since each side's previous game and whether it is the second
    of a back-to-back, from the FULL schedule (not the sampled games), plus
    how many road games in a row the away side has played."""
    seen = {}
    for g in sorted(all_games, key=lambda g: g[0]):
        d, _, home, away = g[0], g[1], g[2], g[3]
        for t, at_home in ((home, True), (away, False)):
            seen.setdefault(t, []).append((d, at_home))
    def rest(team, day):
        ds = [x for x in seen.get(team, []) if x[0] < day]
        if not ds:
            return 7, 0
        gap = (day - ds[-1][0]).days
        road = 0
        for d_, h_ in reversed(ds):
            if h_:
                break
            road += 1
        return min(gap, 7), road
    for r in rows:
        day = dt.date.fromisoformat(r["date"])
        r["rest_h"], _ = rest(r["home"], day)
        r["rest_a"], r["road_a"] = rest(r["away"], day)


def add_travel(rows, key, sport, league, wins):
    """How far the road side came and across how many time zones, from each
    team's usual home venue (its most frequent home city) to this venue, and
    the kickoff hour on the road side's body clock. Venues and cities come
    from the cached scoreboards and Open-Meteo's geocoder (weather_lab)."""
    import weather_lab as W
    ven = W.venues(key, sport, league, B.dates(wins))
    homes = {}
    for r in rows:
        v = ven.get(r["eid"])
        if v and v[0]:
            homes.setdefault(r["home"], []).append((v[0], v[1]))
    loc = {}
    def where(city, state):
        k = (city, state)
        if k not in loc:
            loc[k] = W.geo(city, state)
        return loc[k]
    base = {}
    for team, cs in homes.items():
        c = max(set(cs), key=cs.count)
        base[team] = where(*c)
    for r in rows:
        v = ven.get(r["eid"])
        here = where(v[0], v[1]) if v and v[0] else None
        a = base.get(r["away"])
        if not here or not a:
            r["km"], r["tz_east"], r["body"] = 0.0, 0.0, 13.0
            continue
        la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], here[0], here[1]))
        h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
        r["km"] = 6371 * 2 * math.asin(math.sqrt(h))
        r["tz_east"] = (here[1] - a[1]) / 15.0          # hours moved east
        try:
            t = dt.datetime.fromisoformat(v[3].replace("Z", "+00:00"))
            r["body"] = (t.hour + t.minute / 60 + a[1] / 15.0) % 24   # road side's clock
        except (TypeError, ValueError):
            r["body"] = 13.0


def add_bias(rows, k=10.0):
    """Each side's season-long (result - market chance), shrunk toward zero by
    k phantom games: does the market keep mispricing the same teams?"""
    hist = {}
    for r in rows:                                  # rows are in date order
        for side in ("home", "away"):
            h = hist.get(r[side], [])
            r["bias_" + side[0]] = sum(h) / (len(h) + k)
        hist.setdefault(r["home"], []).append(r["home_won"] - r["pc"])
        hist.setdefault(r["away"], []).append((1 - r["home_won"]) - (1 - r["pc"]))


def add_form(rows, n=8):
    """Each side's average (result - market chance) over its previous n games:
    is a team beating its prices, and does the market catch up too slowly?"""
    hist = {}
    for r in rows:                                  # rows are in date order
        fh = hist.get(r["home"], [])[-n:]
        fa = hist.get(r["away"], [])[-n:]
        r["form_h"] = sum(fh) / len(fh) if fh else 0.0
        r["form_a"] = sum(fa) / len(fa) if fa else 0.0
        hist.setdefault(r["home"], []).append(r["home_won"] - r["pc"])
        hist.setdefault(r["away"], []).append((1 - r["home_won"]) - (1 - r["pc"]))


def feats(r, mean_total, use):
    zc = lg(r["pc"])
    x = [1.0, zc]
    if "form" in use:
        x.append(r.get("form_h", 0.0) - r.get("form_a", 0.0))
    if "rest" in use:
        x.append(min(r.get("rest_h", 3), 4) - min(r.get("rest_a", 3), 4))
        x.append((r.get("rest_h", 3) <= 1) - (r.get("rest_a", 3) <= 1))
        x.append(min(r.get("road_a", 0), 6))
    if "drift" in use:
        x.append(zc - lg(r["po"]))
    if "spread" in use:
        x.append(lg(r["ps"]) - zc)
    if "bias" in use:
        x.append(r.get("bias_h", 0.0) - r.get("bias_a", 0.0))
    if "travel" in use:
        km = r.get("km", 0.0) / 1000
        x.append(km)
        x.append(max(0.0, r.get("tz_east", 0.0)))           # flew east: body clock behind
        x.append(max(0.0, 12.0 - r.get("body", 13.0)) / 3)  # kicked off before noon, body time
    if "total" in use:
        x.append(zc * ((r["total"] - mean_total) / (mean_total or 1)))
    return x


# ---------------------------------------------------- margin removal methods
def dv_power(ih, ia):
    """Power method: raise both implied chances to k so they sum to 1. Puts
    more of the margin on the underdog, as books do."""
    lo, hi = 0.5, 3.0
    for _ in range(60):
        k = (lo + hi) / 2
        if ih ** k + ia ** k > 1:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    return ih ** k


def dv_shin(ih, ia):
    """Shin's method for two outcomes (insider-trading model of the margin)."""
    s = ih + ia
    best, bz = None, 0.0
    for i in range(1, 400):
        z = i / 2000
        def q(pi):
            return (math.sqrt(z * z + 4 * (1 - z) * pi * pi / s) - z) / (2 * (1 - z))
        tot = q(ih) + q(ia)
        if best is None or abs(tot - 1) < best:
            best, bz = abs(tot - 1), z
    z = bz
    qh = (math.sqrt(z * z + 4 * (1 - z) * ih * ih / s) - z) / (2 * (1 - z))
    qa = (math.sqrt(z * z + 4 * (1 - z) * ia * ia / s) - z) / (2 * (1 - z))
    return qh / (qh + qa)


def bands(rows, probs):
    """Favourite's stated chance vs how often it won, in bands."""
    out = []
    for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)):
        b = [(max(p, 1 - p), int((p >= 0.5) == bool(r["home_won"]))) for r, p in zip(rows, probs)
             if lo <= max(p, 1 - p) < hi]
        if b:
            out.append(dict(band=f"{int(lo*100)}-{min(int(hi*100), 100)}", n=len(b),
                            said=round(100 * sum(x for x, _ in b) / len(b), 1),
                            won=round(100 * sum(w for _, w in b) / len(b), 1)))
    return out


def score(rows, probs):
    n = len(rows)
    hit = sum((p > 0.5) == bool(r["home_won"]) for r, p in zip(rows, probs)) / n
    ll = -sum(math.log(p if r["home_won"] else 1 - p) for r, p in zip(rows, probs)) / n
    return round(100 * hit, 2), round(ll, 4)


def main():
    report = {}
    for key, sport, league, wins in B.WINDOWS:
        if key not in LEAGUES:
            continue
        ds = B.dates(wins)
        games = B.finished_games(key, sport, league, ds)
        all_games = list(games)
        if len(games) > MAX_GAMES:
            step = len(games) / MAX_GAMES
            games = [games[int(i * step)] for i in range(MAX_GAMES)]
        with ThreadPoolExecutor(max_workers=8) as ex:
            rows = [r for r in ex.map(lambda g: row_for(key, sport, league, g), games) if r]
        rows.sort(key=lambda r: r["date"])
        add_rest(rows, all_games)
        add_form(rows)
        add_bias(rows)
        try:
            add_travel(rows, key, sport, league, wins)
        except Exception as ex:                      # travel is optional
            print(key, "travel failed:", ex, flush=True)
        if len(rows) < 150:
            report[key] = dict(games=len(rows), note="too few games")
            print(key, report[key], flush=True)
            continue
        half = len(rows) // 2
        fit, test = rows[:half], rows[half:]
        mt = sum(r["total"] for r in fit) / len(fit)
        base = score(test, [r["pc"] for r in test])
        res = dict(games=len(rows), test_games=len(test),
                   test_range=[test[0]["date"], test[-1]["date"]],
                   close_favourite=dict(hit=base[0], logloss=base[1]),
                   open_favourite=dict(zip(("hit", "logloss"), score(test, [r["po"] for r in test]))),
                   spread_favourite=dict(zip(("hit", "logloss"), score(test, [r["ps"] for r in test]))))
        # "home": only a home-side adjustment on top of the close (intercept)
        for name, use in (("home", set()), ("drift", {"drift"}), ("spread", {"spread"}), ("total", {"total"}),
                          ("rest", {"rest"}), ("form", {"form"}), ("travel", {"travel"}),
                          ("bias", {"bias"}),
                          ("all", {"drift", "spread", "total", "rest", "form"})):
            w = fit_logit([feats(r, mt, use) for r in fit], [r["home_won"] for r in fit])
            probs = [1 / (1 + math.exp(-sum(a * b for a, b in zip(w, feats(r, mt, use)))))
                     for r in test]
            h, l = score(test, probs)
            flips = sum((p > 0.5) != (r["pc"] > 0.5) for r, p in zip(test, probs))
            # a change counts only if it is bigger than luck: the extra wins
            # among the flipped picks must clear two standard errors
            gained = round((h - base[0]) * len(test) / 100)
            res[name] = dict(hit=h, logloss=l, weights=[round(x, 3) for x in w],
                             picks_changed=flips, extra_wins=gained,
                             better=bool(l < base[1] and h >= base[0]),
                             # two standard errors of the net gain on the
                             # changed picks (it read sqrt/2 x 2 = one SE)
                             significant=bool(flips and gained >= 2 * math.sqrt(flips)
                                              and l < base[1]))
        # which way of removing the book's margin matches results best, on
        # games the comparison never tuned on (the test half; nothing is fit)
        dv = {}
        for name, f in (("proportional", lambda r: r["pc"]),
                        ("power", lambda r: dv_power(r["ih"], r["ia"])),
                        ("shin", lambda r: dv_shin(r["ih"], r["ia"]))):
            for part, rs in (("fit", fit), ("test", test)):
                pr = [f(r) for r in rs]
                h, l = score(rs, pr)
                dv.setdefault(name, {})[part] = dict(logloss=l, bands=bands(rs, pr))
        res["devig"] = dv
        pw = lambda r: dv_power(r["ih"], r["ia"])
        w = fit_logit([[1.0, lg(pw(r))] for r in fit], [r["home_won"] for r in fit])
        pr = [1 / (1 + math.exp(-(w[0] + w[1] * lg(pw(r))))) for r in test]
        h, l = score(test, pr)
        res["power_stretch"] = dict(weights=[round(x, 3) for x in w], test_logloss=l,
                                    power_logloss=dv["power"]["test"]["logloss"],
                                    bands=bands(test, pr))
        report[key] = res
        print(key, json.dumps(res), flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(dict(run=dt.date.today().isoformat(), leagues=report), fh, indent=1)


if __name__ == "__main__":
    main()
