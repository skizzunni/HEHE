"""Remove the book's margin from a market: the one place it is done.

A posted price includes the book's hold. Removing it gives the market's own
estimate. Three ways of removing it, for any number of outcomes:

    proportional   divide every implied chance by their sum. Spreads the
                   margin evenly, so a favourite keeps too little of it back
                   and the longshot too much (the favourite-longshot bias).
    power          raise every implied chance to the k that makes them sum
                   to 1. Puts more of the margin on the longshot, as books do.
    shin           Shin's insider-trading model: the margin a book needs
                   against a share z of informed money. Also loads the
                   longshot.

METHOD is the one used everywhere (dashboard, locks, stacks, props, tennis
Kalshi pairs and the old one-off scripts). It was chosen on the OLDER half of
tools/edge_lab.py's closing-price study (3,485 games, seven leagues, run
2026-10-19) -- nothing from the ledger's evaluation window was looked at:

    log-loss, older half    proportional 0.60082   power 0.60044   shin 0.60046
    log-loss, newer half    proportional 0.57521   power 0.57296   shin 0.57368

REVERTED 2026-10-20. On the ledger's untouched evaluation window (graded
picks 2026-10-15..19, N = 426, DraftKings' final prices) power did not
improve: log-loss 0.5935 vs 0.5925, difference +0.0010 (95% -0.0023 to
+0.0052), Brier tied at 0.2005. By the plan's rule a change that cannot show
an improvement on untouched data is reverted, so METHOD is back to what the
board used before: proportional, with power for the leagues in POWER_LEAGUES
(college football and basketball, where edge_lab found power better on
unseen games). Power and Shin stay here for the next test.

Run: python3 devig.py   (the demo below)
"""

import math

from parlay_math import american_to_decimal, decimal_to_american

METHOD = "proportional"
POWER_LEAGUES = {"ncaaf", "ncaab"}


def method_for(league):
    """The method the board uses for a league's moneyline."""
    return "power" if league in POWER_LEAGUES else METHOD


def proportional(raw):
    t = sum(raw)
    return [r / t for r in raw]


def power(raw):
    """k with sum(r ** k) = 1; k > 1 when the book is overround."""
    lo, hi = 0.05, 20.0
    for _ in range(100):
        k = (lo + hi) / 2
        if sum(r ** k for r in raw) > 1:
            lo = k
        else:
            hi = k
    out = [r ** ((lo + hi) / 2) for r in raw]
    s = sum(out)
    return [o / s for o in out]


def shin(raw):
    """Shin (1993), solved for z by bisection; z = 0 when there is no margin."""
    S = sum(raw)
    if S <= 1:
        return proportional(raw)

    def q(z):
        return [(math.sqrt(z * z + 4 * (1 - z) * r * r / S) - z) / (2 * (1 - z)) for r in raw]
    lo, hi = 0.0, 0.999
    for _ in range(100):
        z = (lo + hi) / 2
        if sum(q(z)) > 1:
            lo = z
        else:
            hi = z
    out = q((lo + hi) / 2)
    s = sum(out)
    return [o / s for o in out]


METHODS = dict(proportional=proportional, power=power, shin=shin)


def fair_implied(*raw, method=None):
    """Fair chances from implied chances (1 / decimal price, or exchange
    prices), or None when any is missing or out of range."""
    if len(raw) < 2 or any(r is None or not 0 < r < 1 for r in raw):
        return None
    return METHODS[method or METHOD](list(raw))


def fair_decimal(*decs, method=None):
    if any(d is None or d <= 1 for d in decs):
        return None
    return fair_implied(*[1 / d for d in decs], method=method)


def fair(*american, method=None):
    """Fair chances from American odds."""
    try:
        decs = [american_to_decimal(int(a)) for a in american]
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return fair_decimal(*decs, method=method)


def devig(odds_a, odds_b, method=None):
    """Two-way market -> (fair a, fair b, hold)."""
    ia, ib = 1 / american_to_decimal(odds_a), 1 / american_to_decimal(odds_b)
    pa, pb = fair_implied(ia, ib, method=method)
    return pa, pb, ia + ib - 1


GAMES = [
    # (start, away, away_ml, away_sp, home, home_ml, home_sp)
    ("7:15p", "BOS Red Sox", +120, "Alec Gamboa",
     "NY Yankees", -145, "Max Fried"),
    ("7:15p", "TEX Rangers", +140, "Cal Quantrill",
     "MIL Brewers", -170, "Shane Drohan"),
    ("10:05p", "ARI Diamondbacks", -130, "TBD",
     "SF Giants", +110, "TBD"),
    ("10:05p", "BAL Orioles", -145, "Shane Baz",
     "Athletics", +120, "Jack Perkins"),
    ("10:07p", "PHI Phillies", -245, "Cristopher Sanchez",
     "LA Angels", +200, "Ryan Johnson"),
]


def main():
    print(f"\n{'MATCHUP':<34}{'FAIR WIN %':>22}{'HOLD':>8}")
    print("=" * 66)
    picks = []
    for start, away, aml, asp, home, hml, hsp in GAMES:
        pa, ph, hold = devig(aml, hml)
        fav, prob = (away, pa) if pa > ph else (home, ph)
        picks.append((fav, prob, start))
        print(f"\n{away} @ {home}   ({start})")
        print(f"  {asp} vs {hsp}")
        print(f"  {away:<22}{aml:>+6}  ->{pa*100:6.1f}%  (fair {decimal_to_american(1/pa):+d})")
        print(f"  {home:<22}{hml:>+6}  ->{ph*100:6.1f}%  (fair {decimal_to_american(1/ph):+d})")
        print(f"  book hold: {hold*100:.2f}%")

    print("\n" + "=" * 66)
    print("PICKS, most to least confident")
    print("=" * 66)
    for fav, prob, start in sorted(picks, key=lambda x: -x[1]):
        print(f"  {fav:<22}{prob*100:5.1f}%   {start}")

    print("\n" + "=" * 66)
    print("IF YOU PARLAY THEM")
    print("=" * 66)
    joint = 1.0
    for _, prob, _ in picks:
        joint *= prob
    print(f"  All 5 together: {joint*100:.2f}%  (about 1 in {1/joint:.0f})")
    for n in (2, 3):
        top = sorted(picks, key=lambda x: -x[1])[:n]
        p = 1.0
        for _, prob, _ in top:
            p *= prob
        print(f"  Top {n} only:     {p*100:.2f}%  (about 1 in {1/p:.1f})")


if __name__ == "__main__":
    main()
