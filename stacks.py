"""Daily "stack" parlays: many high-probability legs, the way the big Kalshi
combos are built.

    python3 stacks.py            # today's and tomorrow's stacks from the last rebuild
    python3 stacks.py report     # graded record of every stack leg and ticket

WHAT A STACK IS

The winning combos people post are not built from picks. They are built from
legs that are each very likely -- "Over 0.5 goals", "Over 3.5 goals" in the
NHL, "No: Sharks win by over 2.5", a college total set 10 points under the
book's number -- and then multiplied together. Every leg is 80-97%; the
ticket is long because each leg pays so little.

HOW EACH LEG IS PRICED

The book already prices each game three ways: who wins (moneyline), by how
much (spread) and how many points (total). Those three numbers pin down a
full distribution of final scores:

  * hockey, soccer -- two independent Poisson scoring rates, solved so the
    model reproduces the book's win probability and its total;
  * football, basketball -- final margin and total points as normals centred
    on the spread and the total, with spreads measured for each sport.

Any line can then be read off that distribution, including alternate lines
the feed never prices. A same-game pair (an over plus a margin leg) is priced
JOINTLY from the same distribution, not multiplied as if independent.

WHY THE PROBABILITIES ARE HAIRCUT

Poisson underrates blowouts in hockey (empty-net goals turn 2-goal leads into
3) and normals underrate fat tails. Both errors make a "won't win by 3" or
"over a low total" leg look safer than it is. So every leg's MISS chance is
inflated by 30% before it is used: a modelled 92% leg is carried as 89.6%.
The ledger grades every leg; when enough have settled the calibration table
in `report` shows whether that haircut is too much or too little.

WHAT IT CANNOT DO

It does not know Kalshi's prices. Each ticket carries its FAIR payout --
what it should pay if the probabilities are right. Kalshi paying more than
that is a good bet; paying less, a bad one. Check before buying.

A 20-leg ticket of 90% legs wins 12% of the time. These are long shots built
from short legs, not locks.
"""
from zoneinfo import ZoneInfo
import argparse
import datetime as dt
from collections import defaultdict
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "stacks.json")
STATE = os.path.join(HERE, ".cache", "last_board.json")

MISS_INFLATE = 1.30          # see "why the probabilities are haircut"
# A 97% leg pays almost nothing -- ten of them return 1.3x -- while the posted
# winning combos run legs of roughly 85-92% (a 23-leg ticket paying 16x is
# ~89% a leg). So legs are kept in a band and the one nearest TARGET is
# preferred, not the safest one.
LEG_MIN, LEG_MAX = 0.82, 0.94
TARGET = 0.90
TIERS = (2, 3, 4, 6, 8, 10, 15, 20)
# Per-size leg aim, from tools/backtest.py's aim_trials: every ticket size
# built three ways on unseen days (legs aimed at 90 / 94 / 96%). Stronger legs
# won more at every size -- 6 legs 56% -> 71%, 10 legs 42% -> 51%, 15 legs
# 23% -> 42%, 20 legs 21% -> 36% -- for a smaller payout. The 4-leg ticket
# takes 94% (77%, ~1.35x) so it still pays something; 2 and 3 legs untested.
TIER_AIM = {4: (0.94, 0.975), 6: (0.96, 0.985), 8: (0.96, 0.985),
            10: (0.96, 0.985), 15: (0.96, 0.985), 20: (0.96, 0.985)}
# The weekly backtest re-runs those trials on new games. Each size then takes
# the aim that won most often on unseen days -- among aims whose ticket still
# pays at least AIM_MIN_PAY (fair), so a size never collapses into a -400
# "sure thing" with nothing to win -- and only with AIM_MIN_N tickets behind it.
AIM_MIN_PAY = 1.25
AIM_MIN_N = 60


def _tune_aims():
    try:
        with open(os.path.join(HERE, "data", "backtest_stacks.json")) as fh:
            bt = json.load(fh)
    except (OSError, ValueError):
        return
    pooled = defaultdict(lambda: [0, 0, 0.0])
    for v in (bt.get("sports") or {}).values():
        for t in v.get("aim_trials") or []:
            x = pooled[(t["size"], t["target"], t["leg_max"])]
            x[0] += t["played"]
            x[1] += t["won"]
            x[2] += (t.get("avg_fair") or 0) * t["played"]
    best = {}
    for (n, aim, top), (played, won, pay) in pooled.items():
        if played < AIM_MIN_N or pay / played < AIM_MIN_PAY:
            continue
        rate = won / played
        if n not in best or rate > best[n][0]:
            best[n] = (rate, aim, top)
    for n, (_, aim, top) in best.items():
        if n in TIERS:
            TIER_AIM[n] = (aim, top)


_tune_aims()
VARIANTS = 3                 # different tickets per size

# Standard deviation of (final margin - spread) and (final total - posted
# total), per sport. Margin figures are the ones the repo already uses
# (oddsdesk.SIGMA). Totals are set on the wide side of published estimates on
# purpose: a wider spread makes far-off alternate lines LESS likely, which errs
# toward caution.
SD_MARGIN = {"nfl": 13.5, "ncaaf": 16.5, "nba": 12.0, "ncaab": 11.0, "wnba": 11.0}
SD_TOTAL = {"nfl": 10.5, "ncaaf": 14.5, "nba": 18.0, "ncaab": 16.0, "wnba": 15.0}
POISSON = {"nhl"}            # plus every soccer league (passed in)
# Baseball runs are far more spread out than a Poisson allows (a team's runs
# vary about twice as much as their mean), so MLB uses a negative binomial:
# variance = mean + mean^2 / MLB_R. MLB_R = 4 matches a team mean near 4.5
# runs with a standard deviation near 3.1. Extra innings settle a level score
# the way overtime does in hockey. tools/backtest.py measures how well it holds.
NEGBIN = {"mlb"}
MLB_R = 4.0

# alternate lines offered, as offsets from the posted number
ALT = {
    "nfl":   dict(over=(7, 10, 14), under=(7, 10, 14), fav=(7, 10, 14), dog=(3, 7, 10)),
    "ncaaf": dict(over=(10, 14, 17), under=(10, 14, 17), fav=(10, 14, 17), dog=(7, 10, 14)),
    "nba":   dict(over=(8, 12, 16), under=(8, 12, 16), fav=(8, 12, 16), dog=(4, 8, 12)),
    "ncaab": dict(over=(8, 12, 16), under=(8, 12, 16), fav=(8, 12, 16), dog=(4, 8, 12)),
    "wnba":  dict(over=(8, 12, 16), under=(8, 12, 16), fav=(8, 12, 16), dog=(4, 8, 12)),
}


# ------------------------------------------------------------------ maths
def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def nquant(p):
    """Inverse normal CDF by bisection; plenty for this use."""
    lo, hi = -8.0, 8.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if ncdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def pois(lam, kmax=15):
    out, p = [], math.exp(-lam)
    for k in range(kmax + 1):
        out.append(p)
        p *= lam / (k + 1)
    return out


def nbin(mean, r, kmax=25):
    """Negative binomial pmf with this mean and dispersion r."""
    q = mean / (r + mean)
    out, p = [], (r / (r + mean)) ** r
    for k in range(kmax + 1):
        out.append(p)
        p *= (k + r) / (k + 1) * q
    return out


def grid(lh, la, kmax=15, r=None):
    """{(home, away): probability} for independent scoring: Poisson, or
    negative binomial when a dispersion r is given."""
    if r:
        ph, pa = nbin(lh, r, kmax), nbin(la, r, kmax)
    else:
        ph, pa = pois(lh, kmax), pois(la, kmax)
    return {(h, a): ph[h] * pa[a] for h in range(kmax + 1) for a in range(kmax + 1)}


def _pwin(g, ot):
    """P(home wins). In hockey a level score goes to OT/shootout, split by
    the scoring rates; in soccer a draw is not a win."""
    win = sum(p for (h, a), p in g.items() if h > a)
    if ot:
        tie = sum(p for (h, a), p in g.items() if h == a)
        win += tie * ot
    return win


def fit_poisson(p_home, total, p_draw=None, hockey=False, p_over=0.5, r=None):
    """Scoring rates (home, away) reproducing the book's numbers.

    Least squares on the win probability, the draw probability (soccer) and
    the posted total sitting at the median of the modelled total. Coarse grid
    over (mean total, home share), then a fine grid around the best cell.
    """
    t0 = total if total else (8.5 if r else 6.0 if hockey else 2.6)
    kmax = 20 if r else 12

    def err(mu, s):
        lh, la = mu * s, mu * (1 - s)
        g = grid(lh, la, kmax, r)
        e = (_pwin(g, s if hockey else None) - p_home) ** 2
        if p_draw is not None:
            e += (sum(p for (h, a), p in g.items() if h == a) - p_draw) ** 2
        if total:
            # a level regulation score in hockey gains one goal in OT or the
            # shootout -- prob() counts it, so the fit must count it too, or
            # every over leg comes out several points too likely
            over = sum(p for (h, a), p in g.items()
                       if h + a > total or (hockey and h == a and h + a + 1 > total))
            e += 0.5 * (over - p_over) ** 2
        return e

    span = 1.6 if r else 1.0 if hockey else 0.6
    best = min(((err(mu, s), mu, s)
                for mu in [t0 - span + k * span / 4 for k in range(9)] if mu > 0.3
                for s in [k / 50 for k in range(3, 48)]))
    _, m0, s0 = best
    best = min(((err(mu, s), mu, s)
                for mu in [m0 - span / 8 + k * span / 32 for k in range(9)] if mu > 0.3
                for s in [s0 - 0.02 + k * 0.004 for k in range(11)] if 0.02 < s < 0.98))
    _, mu, s = best
    return mu * s, mu * (1 - s)


# ------------------------------------------------------------ game models
class Game:
    """Score distribution for one game, plus a way to price any leg."""

    @staticmethod
    def SD_SHIFT(sport, p_over):
        return SD_TOTAL[sport] * nquant(min(max(p_over, 0.05), 0.95))

    def __init__(self, sport, home, away, p_home, total=None, spread=None,
                 p_draw=None, soccer=False, p_over=0.5):
        self.sport, self.home, self.away = sport, home, away
        self.soccer = soccer
        self.kind = "poisson" if (soccer or sport in POISSON or sport in NEGBIN) else "normal"
        if self.kind == "poisson":
            r = MLB_R if sport in NEGBIN else None
            lh, la = fit_poisson(p_home, total, p_draw if soccer else None,
                                 hockey=not soccer, p_over=p_over, r=r)
            self.g = grid(lh, la, 25 if r else 15, r)
            self.ot = None if soccer else lh / (lh + la)
            self.mu_total = lh + la
        else:
            sdm = SD_MARGIN[sport]
            # mean home margin: from the spread when posted, else from the
            # moneyline through the same normal
            if spread is not None:
                self.mu_m = spread
            else:
                self.mu_m = sdm * nquant(min(max(p_home, 0.01), 0.99))
            self.sd_m = sdm
            # a juiced total means the book's median is off the line
            self.mu_t = (total + self.SD_SHIFT(sport, p_over)) if total else None
            self.sd_t = SD_TOTAL[sport]
            self.mu_total = total

    def prob_specs(self, specs):
        """Probability that every spec holds. One spec on a normal model has a
        closed form; anything else integrates the score distribution."""
        if self.kind == "normal" and len(specs) == 1 and self.mu_t is not None:
            sp = specs[0]
            t, home = sp["t"], sp.get("team") == self.home
            m, sm, T, st = self.mu_m, self.sd_m, self.mu_t, self.sd_t
            up = lambda mu, sd, L: 1 - ncdf((L - mu) / sd)       # P(X > L)
            if t == "over":
                return up(T, st, sp["line"])
            if t == "under":
                return 1 - up(T, st, sp["line"])
            if t == "win":
                return up(m, sm, 0) if home else 1 - up(m, sm, 0)
            if t == "spread":
                L = sp["line"]
                return up(m, sm, -L) if home else 1 - up(m, sm, L)
            if t == "nomargin":
                L = sp["line"]
                return 1 - up(m, sm, L) if home else up(m, sm, -L)
            if t in ("teamover", "teamunder"):
                mu = (T + m) / 2 if home else (T - m) / 2
                sd = math.sqrt(st * st + sm * sm) / 2
                p = up(mu, sd, sp["line"])
                return p if t == "teamover" else 1 - p
        if self.kind == "normal" and self.mu_t is not None:
            return self._joint_normal(specs)
        return self.prob([predicate(sp, self.home, self.away) for sp in specs])

    def _joint_normal(self, specs):
        """Joint probability on the margin/total normals. Given the margin m,
        every leg is a cutoff on the total t (or on m alone), so integrate m
        finely and take t's part exactly."""
        home = self.home
        def bounds(sp, m):
            """-> (ok_on_margin, t_low, t_high) for this spec at margin m."""
            t, L = sp["t"], sp.get("line")
            hm = sp.get("team") == home
            inf = float("inf")
            if t == "over":
                return True, L, inf
            if t == "under":
                return True, -inf, L
            if t == "win":
                return (m > 0 if hm else m < 0), -inf, inf
            if t == "spread":
                return (m > -L if hm else m < L), -inf, inf
            if t == "nomargin":
                return (m < L if hm else m > -L), -inf, inf
            if t == "teamover":      # (t + m)/2 > L  or  (t - m)/2 > L
                return True, (2 * L - m if hm else 2 * L + m), inf
            if t == "teamunder":
                return True, -inf, (2 * L - m if hm else 2 * L + m)
            raise ValueError(t)
        steps, span = 3000, 6.0
        tot = wsum = 0.0
        for i in range(steps):
            z = -span + 2 * span * (i + 0.5) / steps
            w = math.exp(-z * z / 2)
            wsum += w
            m = self.mu_m + z * self.sd_m
            lo, hi, ok = -float("inf"), float("inf"), True
            for sp in specs:
                o, a_, b_ = bounds(sp, m)
                ok = ok and o
                lo, hi = max(lo, a_), min(hi, b_)
            if not ok or lo >= hi:
                continue
            pt = (ncdf((hi - self.mu_t) / self.sd_t) if hi != float("inf") else 1.0) - \
                 (ncdf((lo - self.mu_t) / self.sd_t) if lo != -float("inf") else 0.0)
            tot += w * pt
        return tot / wsum

    # each leg is a predicate on the final (home, away) score
    def prob(self, preds):
        """Joint probability that every predicate holds."""
        if self.kind == "poisson":
            tot = 0.0
            for (h, a), p in self.g.items():
                if h == a and self.ot is not None:
                    # hockey: the OT/shootout winner gets one extra goal
                    for hh, aa, w in ((h + 1, a, self.ot), (h, a + 1, 1 - self.ot)):
                        if all(f(hh, aa) for f in preds):
                            tot += p * w
                    continue
                if all(f(h, a) for f in preds):
                    tot += p
            return tot
        # normals: margin and total treated as independent; integrate on a
        # grid fine enough that line placement on .5 is resolved
        if self.mu_t is None:
            return None
        tot = 0.0
        steps = 200         # even, so the centre falls between two points
        # midpoints, so no grid point ever sits exactly on a .0 or .5 line
        zs = [-4 + 8 * (i + 0.5) / steps for i in range(steps)]
        ws = [math.exp(-z * z / 2) for z in zs]
        for zm, wm in zip(zs, ws):
            m = self.mu_m + zm * self.sd_m
            for zt, wt in zip(zs, ws):
                t = self.mu_t + zt * self.sd_t
                h, a = (t + m) / 2, (t - m) / 2
                if all(f(h, a) for f in preds):
                    tot += wm * wt
        norm = sum(ws) ** 2
        return tot / norm


def haircut(p, league=None):
    k = MISS_BY_SPORT.get(sport_of(league), MISS_INFLATE)
    return max(0.0, 1 - (1 - p) * k)


def sport_of(league):
    """Group a league key into the sport its backtest factor belongs to."""
    if league in SD_MARGIN or league in POISSON or league in NEGBIN:
        return league
    return "soccer"


# Per-sport miss factors, filled from tools/backtest.py results. Until a sport
# has one, MISS_INFLATE applies.
MISS_BY_SPORT = {}


def _load_backtest():
    """Per-sport miss factors fitted by tools/backtest.py (soccer leagues are
    pooled, weighted by how many legs each contributed)."""
    try:
        with open(os.path.join(HERE, "data", "backtest_stacks.json")) as fh:
            bt = json.load(fh)
    except (OSError, ValueError):
        return
    pool = defaultdict(lambda: [0.0, 0])
    for k, v in (bt.get("sports") or {}).items():
        n = ((v.get("stack_legs") or {}).get("fit")) or 0
        f = v.get("fitted_miss_factor")
        if f and n:
            x = pool[sport_of(k)]
            x[0] += f * n
            x[1] += n
    for sp, (w, n) in pool.items():
        MISS_BY_SPORT[sp] = round(w / n, 2)


_load_backtest()

# ----------------------------------------------------------- self-tuning
# The backtest factor is a starting point, not the last word. Every graded
# stack leg in stacks.json is an out-of-sample test the model did not see, so
# each rebuild re-fits each sport's miss factor on backtest + live results:
#
#     k = (prior misses + live misses) / (prior expected + live expected)
#
# where "expected" is the misses the RAW model predicted, sum(1 - p_model).
# The backtest counts as PRIOR_EXPECTED expected misses -- enough that a bad
# weekend cannot swing it, little enough that a month of live results can.
# A sport that misses more than promised gets a bigger haircut, so fewer of
# its legs clear LEG_MIN and the builder leans on sports that are delivering.
# Live misses never make a sport look better than the data says.
PRIOR_EXPECTED = 40.0
TUNE_MIN_EXPECTED = 5.0      # live evidence needed before it counts at all
TUNE_BOUNDS = (0.7, 3.0)
TUNING = {}                  # sport -> what was fitted, for the page


def _self_tune():
    try:
        with open(LEDGER) as fh:
            book = json.load(fh)
    except (OSError, ValueError, NameError):
        return
    live = defaultdict(lambda: [0, 0.0, 0])   # misses, expected misses, legs
    for L in (book.get("legs") or {}).values():
        if L.get("status") not in ("won", "lost") or not L.get("p_model"):
            continue
        x = live[sport_of(L.get("league"))]
        x[0] += L["status"] == "lost"
        x[1] += 1 - L["p_model"]
        x[2] += 1
    for sp, (miss, exp, n) in live.items():
        prior = MISS_BY_SPORT.get(sp, MISS_INFLATE)
        row = dict(legs=n, missed=miss, raw_expected=round(exp, 1),
                   backtest=prior, used=prior)
        if exp >= TUNE_MIN_EXPECTED:
            k = (prior * PRIOR_EXPECTED + miss) / (PRIOR_EXPECTED + exp)
            k = round(min(max(k, TUNE_BOUNDS[0]), TUNE_BOUNDS[1]), 2)
            MISS_BY_SPORT[sp] = k
            row["used"] = k
        TUNING[sp] = row


_self_tune()


def backtest_summary():
    """Per-sport backtest results for the page: leg calibration on the
    holdout and how tickets did against what they promised."""
    try:
        with open(os.path.join(HERE, "data", "backtest_stacks.json")) as fh:
            bt = json.load(fh)
    except (OSError, ValueError):
        return None
    rows = []
    for k, v in (bt.get("sports") or {}).items():
        cal = (v.get("stack_legs") or {}).get("haircut") or []
        n = sum(c["n"] for c in cal)
        if not n:
            continue
        said = sum(c["said"] * c["n"] for c in cal) / n
        hit = sum(c["hit"] * c["n"] for c in cal) / n
        tk = v.get("tickets") or []
        won = sum(t["won"] for t in tk)
        exp = sum(t["expected"] for t in tk)
        rows.append(dict(sport=k, games=v.get("games"), legs=n, said=round(said, 1),
                         hit=round(hit, 1), tickets=sum(t["played"] for t in tk),
                         won=won, expected=round(exp, 1)))
    return dict(run=bt.get("run"), rows=rows, tuning=TUNING)


def half(x):
    """Nearest .5 line."""
    return math.floor(x) + 0.5


# ------------------------------------------------------------------- legs
def leg_specs(game, sport, fav_home):
    """Every candidate leg for a game as (group, label, spec). `group` keeps
    at most one total leg and one side leg per game on a ticket."""
    H, A = game.home, game.away
    fav, dog = (H, A) if fav_home else (A, H)
    out = []
    if game.kind == "poisson":
        unit = "runs" if sport in NEGBIN else "goals"
        if sport in NEGBIN:
            overs, unders, margins = (4.5, 5.5, 6.5), (10.5, 11.5, 12.5), (1.5, 2.5, 3.5, 4.5)
        else:
            overs = (0.5, 1.5, 2.5) if game.soccer else (2.5, 3.5, 4.5)
            unders = (3.5, 4.5, 5.5) if game.soccer else (7.5, 8.5, 9.5)
            margins = (2.5, 3.5) if game.soccer else (2.5,)
        for L in overs:
            out.append(("total", f"Over {L} {unit}", dict(t="over", line=L)))
        for L in unders:
            out.append(("total", f"Under {L} {unit}", dict(t="under", line=L)))
        for team in (fav, dog):
            for L in margins:
                out.append(("side", f"No · {team} wins by over {L} {unit}",
                            dict(t="nomargin", team=team, line=L)))
        out.append(("side", f"{fav} to win", dict(t="win", team=fav)))
        if game.soccer:
            out.append(("btts", "Both teams to score", dict(t="btts")))
        return out
    alt = ALT[sport]
    T = game.mu_t
    spread = abs(game.mu_m)
    if T:
        for k in alt["over"]:
            L = half(T - k)
            if L > 0:
                out.append(("total", f"Over {L} points", dict(t="over", line=L)))
        for k in alt["under"]:
            L = half(T + k)
            out.append(("total", f"Under {L} points", dict(t="under", line=L)))
    for k in alt["fav"]:
        L = half(spread + k)
        out.append(("side", f"No · {fav} wins by over {L} points",
                    dict(t="nomargin", team=fav, line=L)))
    for k in alt["dog"]:
        L = half(k)
        out.append(("side", f"No · {dog} wins by over {L} points",
                    dict(t="nomargin", team=dog, line=L)))
    out.append(("side", f"{fav} to win", dict(t="win", team=fav)))
    return out


def predicate(spec, home, away):
    """spec -> f(home_score, away_score) -> bool."""
    t = spec["t"]
    if t == "over":
        return lambda h, a: h + a > spec["line"]
    if t == "under":
        return lambda h, a: h + a < spec["line"]
    if t == "btts":
        return lambda h, a: h >= 1 and a >= 1
    if t == "btts_no":
        return lambda h, a: h == 0 or a == 0
    if t == "draw":
        return lambda h, a: h == a
    is_home = spec["team"] == home
    if t == "spread":
        L = spec["line"]          # +3.5 = may lose by up to 3; -3.5 = must win by 4+
        return (lambda h, a: h - a + L > 0) if is_home else (lambda h, a: a - h + L > 0)
    if t == "teamover":
        L = spec["line"]
        return (lambda h, a: h > L) if is_home else (lambda h, a: a > L)
    if t == "teamunder":
        L = spec["line"]
        return (lambda h, a: h < L) if is_home else (lambda h, a: a < L)
    if t == "dc":                 # double chance: this team or the draw
        return (lambda h, a: h >= a) if is_home else (lambda h, a: a >= h)
    if t == "win":
        return (lambda h, a: h > a) if is_home else (lambda h, a: a > h)
    if t == "nomargin":
        L = spec["line"]
        return (lambda h, a: h - a < L) if is_home else (lambda h, a: a - h < L)
    raise ValueError(t)


# ----------------------------------------------------------------- inputs
def _ml_prob(price):
    if str(price).strip().upper() == "EVEN":
        price = "+100"
    try:
        v = int(str(price).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if -100 < v < 100:
        return None
    return 100 / (v + 100) if v > 0 else -v / (-v + 100)


def game_from_row(row, league, soccer):
    """Build a Game from a board row's market block, or None if unpriced."""
    m = row.get("mkt") or {}
    home, away = m.get("home"), m.get("away")
    if not home or not away:
        return None
    legs = {L["side"]: L for L in row.get("legs") or []}
    ph, pa = (_ml_prob((legs.get("home") or {}).get("price")),
              _ml_prob((legs.get("away") or {}).get("price")))
    pdr = _ml_prob((legs.get("draw") or {}).get("price"))
    if (ph is None or pa is None) and league in SD_MARGIN \
            and m.get("spread") is not None and m.get("fav") in ("home", "away"):
        # some college lines post a spread and no moneyline; the spread then
        # sets the win probability through the same normal
        mag = abs(float(m["spread"]))
        pf = ncdf(mag / SD_MARGIN[league])
        ph, pa = (pf, 1 - pf) if m["fav"] == "home" else (1 - pf, pf)
    if ph is None or pa is None:
        return None
    if soccer:
        if pdr is None:
            return None
        s = ph + pa + pdr
        ph, pa, pdr = ph / s, pa / s, pdr / s
    else:
        s = ph + pa
        ph, pa = ph / s, pa / s
    total = m.get("total")
    po, pu = _ml_prob(m.get("over")), _ml_prob(m.get("under"))
    p_over = po / (po + pu) if po and pu else 0.5
    spread = None
    if m.get("spread") is not None and m.get("fav") in ("home", "away") \
            and league in SD_MARGIN:
        mag = abs(float(m["spread"]))
        spread = mag if m["fav"] == "home" else -mag
    if league in SD_MARGIN and not total:
        return None                       # alt lines need a posted total
    if league not in SD_MARGIN and league not in POISSON and league not in NEGBIN \
            and not soccer:
        return None                       # MLB, tennis, golf, UFC: not modelled
    return Game(league, home, away, ph, total=total, spread=spread,
                p_draw=pdr, soccer=soccer, p_over=p_over)


# ---------------------------------------------------------------- markets
def american(p):
    if p <= 0 or p >= 1:
        return None
    return f"-{round(100 * p / (1 - p))}" if p >= 0.5 else f"+{round(100 * (1 - p) / p)}"


def market_menu(g, league, mkt):
    """Every market this model can price for one game: (group, label, spec)."""
    H, A = g.home, g.away
    out = [("Winner", f"{H} to win", dict(t="win", team=H)),
           ("Winner", f"{A} to win", dict(t="win", team=A))]
    if g.kind == "poisson":
        unit = "runs" if league in NEGBIN else "goals"
        if g.soccer:
            out += [("Winner", "Draw", dict(t="draw")),
                    ("Double chance", f"{H} or draw", dict(t="dc", team=H)),
                    ("Double chance", f"{A} or draw", dict(t="dc", team=A)),
                    ("Both teams to score", "Yes", dict(t="btts")),
                    ("Both teams to score", "No", dict(t="btts_no"))]
            lines, team_lines, spreads = (0.5, 1.5, 2.5, 3.5, 4.5), (0.5, 1.5, 2.5), (1.5, 2.5)
        elif league in NEGBIN:
            lines, team_lines, spreads = (5.5, 6.5, 7.5, 8.5, 9.5, 10.5), (2.5, 3.5, 4.5, 5.5), (1.5, 2.5, 3.5)
        else:
            lines, team_lines, spreads = (3.5, 4.5, 5.5, 6.5, 7.5), (1.5, 2.5, 3.5), (1.5, 2.5)
        for L in lines:
            out += [("Total", f"Over {L} {unit}", dict(t="over", line=L)),
                    ("Total", f"Under {L} {unit}", dict(t="under", line=L))]
        for team in (H, A):
            for L in team_lines:
                out.append(("Team total", f"{team} over {L} {unit}",
                            dict(t="teamover", team=team, line=L)))
            for L in spreads:
                out += [("Spread", f"{team} -{L}", dict(t="spread", team=team, line=-L)),
                        ("Spread", f"{team} +{L}", dict(t="spread", team=team, line=L))]
        return out
    T, spread = g.mu_t, abs(g.mu_m)
    posted = mkt.get("spread")
    base = abs(float(posted)) if posted is not None else round(spread * 2) / 2
    fav, dog = (H, A) if g.mu_m >= 0 else (A, H)
    for k in (-7, -3, 0, 3, 7):
        L = base + k
        if L <= 0:
            continue
        out += [("Spread", f"{fav} -{L:g}", dict(t="spread", team=fav, line=-L)),
                ("Spread", f"{dog} +{L:g}", dict(t="spread", team=dog, line=L))]
    tot = mkt.get("total") or T
    for k in (-14, -10, -7, -3, 0, 3, 7, 10, 14):
        L = tot + k
        out += [("Total", f"Over {L:g}", dict(t="over", line=L)),
                ("Total", f"Under {L:g}", dict(t="under", line=L))]
    for team, share in ((H, (T + g.mu_m) / 2), (A, (T - g.mu_m) / 2)):
        for k in (-7, -3, 0, 3, 7):
            L = half(share + k)
            out.append(("Team total", f"{team} over {L:g}",
                        dict(t="teamover", team=team, line=L)))
    return out


def markets(slots, soccer_keys, labels=None):
    """{slot: [game with its priced market list]} for the Markets tab."""
    res = {}
    for slot in ("today", "tomorrow"):
        games = []
        for league, rows in (slots.get(slot) or {}).items():
            for row in rows:
                try:
                    g = game_from_row(row, league, league in soccer_keys)
                    if not g:
                        continue
                    ms = []
                    for group, label, spec in market_menu(g, league, row.get("mkt") or {}):
                        p = g.prob_specs([spec])
                        if p is None or not 0.01 <= p <= 0.99:
                            continue
                        ms.append(dict(g=group, l=label, p=round(p, 4), f=american(p)))
                except Exception as e:
                    print(f"markets: {league} {row.get('label')}: {e}", file=sys.stderr)
                    continue
                games.append(dict(id=row["id"], lg=(labels or {}).get(league, league),
                                  match=f"{g.away} at {g.home}", tip=row.get("tip"),
                                  m=ms))
        games.sort(key=lambda x: (x["lg"], x["tip"] or ""))
        res[slot] = games
    return res


# ---------------------------------------------------------------- tickets
def candidates(board_slot, soccer_keys, labels=None, extra=None, keep=None,
               band=None):
    """All legs worth stacking, grouped by game, best first.

    `extra(league, row, game)` may add (group, label, spec) legs -- the lines
    an exchange actually lists; `keep(league, row, spec)` may veto a leg, so a
    ticket can be restricted to what one venue can fill."""
    games = []
    for league, rows in (board_slot or {}).items():
        for row in rows:
            try:
                g = game_from_row(row, league, league in soccer_keys)
            except Exception as e:                       # one bad feed row
                print(f"stacks: {league} {row.get('label')}: {e}", file=sys.stderr)
                continue
            if not g:
                continue
            fav_home = g.prob_specs([dict(t="win", team=g.home)]) >= \
                g.prob_specs([dict(t="win", team=g.away)])
            legs = []
            specs = list(leg_specs(g, league, fav_home))
            if extra:
                specs += list(extra(league, row, g) or [])
            seen = set()
            for group, label, spec in specs:
                key = json.dumps(spec, sort_keys=True)
                if key in seen:
                    continue
                seen.add(key)
                if keep and not keep(league, row, spec):
                    continue
                p = g.prob_specs([spec])
                if p is None:
                    continue
                q = haircut(p, league)
                lo, hi = band or (LEG_MIN, LEG_MAX)
                if lo <= q <= hi:
                    legs.append(dict(group=group, label=label, spec=spec,
                                     p_model=round(p, 4), p=round(q, 4)))
            if not legs:
                continue
            legs.sort(key=lambda L: abs(L["p"] - TARGET))
            games.append(dict(gid=row["id"], league=league, lg=(labels or {}).get(league, league),
                              home=g.home, away=g.away, tip=row.get("tip"),
                              match=f"{g.away} at {g.home}", model=g, legs=legs))
    return games


def pick_for_game(game, n_legs):
    """1 or 2 legs from one game, from different groups, priced jointly."""
    chosen, groups = [], set()
    for L in game["legs"]:
        if L["group"] in groups:
            continue
        chosen.append(L)
        groups.add(L["group"])
        if len(chosen) == n_legs:
            break
    g = game["model"]
    raw = g.prob_specs([L["spec"] for L in chosen])
    # the haircut applies per leg; carry it over to the joint figure
    joint = raw
    for L in chosen:
        joint *= L["p"] / L["p_model"] if L["p_model"] else 1
    return chosen, joint


def build_tickets(games, tiers=TIERS, variants=VARIANTS):
    """{size: [ticket, ...]}. One leg per game first; a second leg from the
    same game (priced jointly) only when there are fewer games than legs."""
    out = {}
    for n in tiers:
        made, used = [], {}
        for v in range(variants):
            # games not yet used in this size first, so the variants are
            # genuinely different tickets rather than one ticket three times
            order = sorted(games, key=lambda G: (used.get(G["gid"], 0),
                                                 abs(G["legs"][0]["p"] - TARGET)))
            per = {G["gid"]: 1 for G in order[:n]}
            extra = n - len(per)
            for G in order[:n]:
                if extra <= 0:
                    break
                if len({L["group"] for L in G["legs"]}) >= 2:
                    per[G["gid"]] = 2
                    extra -= 1
            if extra > 0:
                break                          # not enough legs on the slate
            legs, joint = [], 1.0
            for G in order[:n]:
                chosen, pj = pick_for_game(G, per[G["gid"]])
                joint *= pj
                legs.extend(dict(L, gid=G["gid"], league=G["league"], lg=G["lg"],
                                 match=G["match"], tip=G["tip"], home=G["home"],
                                 away=G["away"]) for L in chosen)
            for gid in per:
                used[gid] = used.get(gid, 0) + 1
            sig = tuple(sorted((L["gid"], L["label"]) for L in legs))
            if any(t["sig"] == sig for t in made):
                continue
            made.append(dict(sig=sig, n=len(legs), prob=round(joint, 4),
                             fair=round(1 / joint, 2) if joint > 0 else None,
                             legs=legs))
        for t in made:
            t.pop("sig")
        out[n] = made
    return out


def build(slots, soccer_keys, labels=None, extra=None, keep=None):
    global TARGET, LEG_MAX
    res = {}
    for slot in ("today", "tomorrow"):
        games = candidates(slots.get(slot), soccer_keys, labels, extra, keep)
        tickets = build_tickets(games, tiers=tuple(n for n in TIERS if n not in TIER_AIM))
        base = (TARGET, LEG_MAX)
        for (aim, top) in sorted(set(TIER_AIM.values())):
            sizes = tuple(n for n, a in TIER_AIM.items() if a == (aim, top))
            TARGET, LEG_MAX = aim, top
            try:
                g2 = candidates(slots.get(slot), soccer_keys, labels, extra, keep)
                tickets.update(build_tickets(g2, tiers=sizes))
            finally:
                TARGET, LEG_MAX = base
        tickets = {n: tickets.get(n, []) for n in TIERS}
        res[slot] = dict(games=len(games), tickets=tickets)
    return res


# ---------------------------------------------------------------- ledger
def load():
    try:
        with open(LEDGER) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"legs": {}, "tickets": {}}


def save(d):
    with open(LEDGER, "w") as fh:
        json.dump(d, fh, indent=1, sort_keys=True)


def record(stacks, dates):
    """Log every leg and ticket of today's stacks. Idempotent per day."""
    book = load()
    now = dt.datetime.now(ZoneInfo("America/New_York")).isoformat()[:16]
    for slot in ("today",):
        day = dates.get(slot)
        if not day:
            continue
        for n, tickets in (stacks.get(slot) or {}).get("tickets", {}).items():
            for i, t in enumerate(tickets):
                tkey = f"{day}:{n}:{i}"
                if tkey in book["tickets"]:
                    continue                    # first version of the day stands
                keys = []
                for L in t["legs"]:
                    lkey = f'{L["gid"]}|{L["label"]}'
                    keys.append(lkey)
                    book["legs"].setdefault(lkey, dict(
                        league=L["league"], match=L["match"], label=L["label"],
                        spec=L["spec"], home=L["home"], away=L["away"],
                        p=L["p"], p_model=L["p_model"], status="open",
                        logged=now, date=f"{day[:4]}-{day[4:6]}-{day[6:]}"))
                book["tickets"][tkey] = dict(n=int(n), prob=t["prob"], fair=t["fair"],
                                             legs=keys, status="open", logged=now)
    save(book)


def grade(final):
    """`final(league, comp_id, entry)` is ledger._final. Settles legs, then
    tickets whose legs are all settled."""
    book = load()
    for key, L in book["legs"].items():
        if L["status"] != "open":
            continue
        gid = key.split("|", 1)[0]
        lg, comp = gid.split(":", 1)
        res = final(lg, comp, L)
        if res and res.get("missing"):
            # the game left the feed: void it once it is a week stale, the
            # same rule the picks ledger uses, or the ticket never settles
            import ledger as _ledger
            if _ledger._stale(L):
                L["status"] = "void"
            continue
        if not res or res.get("live"):
            continue
        if res.get("void"):
            L["status"] = "void"
            continue
        sc = res.get("scores") or {}
        h, a = sc.get(L["home"]), sc.get(L["away"])
        if not isinstance(h, int) or not isinstance(a, int):
            continue
        ok = predicate(L["spec"], L["home"], L["away"])(h, a)
        L["status"] = "won" if ok else "lost"
        L["score"] = f"{L['away']} {a} - {L['home']} {h}"
    for t in book["tickets"].values():
        if t["status"] != "open":
            continue
        st = [book["legs"].get(k, {}).get("status", "open") for k in t["legs"]]
        if "lost" in st:
            t["status"] = "lost"
        elif "open" not in st:
            # A void leg changes what the ticket was: its stated probability
            # no longer applies, so it is kept out of the won-vs-promised
            # record rather than counted as a win at the original odds.
            t["status"] = "void" if "void" in st else "won"
    save(book)


def report():
    book = load()
    legs = [L for L in book["legs"].values() if L["status"] in ("won", "lost")]
    bands = {}
    for L in legs:
        b = min(int(L["p"] * 100) // 5 * 5, 95)
        x = bands.setdefault(b, [0, 0, 0.0])
        x[0] += 1
        x[1] += L["status"] == "won"
        x[2] += L["p"]
    tk = [t for t in book["tickets"].values() if t["status"] in ("won", "lost")]
    by_n = {}
    for t in tk:
        x = by_n.setdefault(t["n"], [0, 0, 0.0])
        x[0] += 1
        x[1] += t["status"] == "won"
        x[2] += t["prob"]
    return dict(
        legs=len(legs), legs_won=sum(1 for L in legs if L["status"] == "won"),
        calibration=[dict(band=b, n=v[0], said=round(100 * v[2] / v[0], 1),
                          actual=round(100 * v[1] / v[0], 1))
                     for b, v in sorted(bands.items())],
        tickets=[dict(n=n, played=v[0], won=v[1],
                      expected=round(v[2], 1))
                 for n, v in sorted(by_n.items())])


# -------------------------------------------------------------------- CLI
def show(res):
    for slot in ("today", "tomorrow"):
        r = res.get(slot) or {}
        print(f"\n{slot.upper()} -- {r.get('games', 0)} games with priced legs")
        for n, tickets in (r.get("tickets") or {}).items():
            for i, t in enumerate(tickets):
                print(f"\n  {n}-LEG #{i+1}   hits {100*t['prob']:.1f}%   "
                      f"fair payout {t['fair']:.2f}x  ($10 -> ${10*t['fair']:.2f})")
                for L in t["legs"]:
                    print(f"     {100*L['p']:5.1f}%  {L['label']:<44} {L['match']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="show", choices=["show", "report"])
    a = ap.parse_args()
    if a.cmd == "report":
        print(json.dumps(report(), indent=1))
        return
    try:
        with open(STATE) as fh:
            board = json.load(fh)
    except (OSError, ValueError):
        raise SystemExit("no board yet -- run python3 rebuild_board.py first")
    show(board.get("stacks") or {})
    print("\nOnly buy a ticket where Kalshi's payout beats the fair payout.")


if __name__ == "__main__":
    main()
