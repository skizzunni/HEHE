"""De-vig a two-way moneyline into fair win probabilities.

The posted price includes the book's hold. Stripping it proportionally gives
the market's actual estimate -- the single sharpest public forecast there is.

Run: python3 devig.py
"""

from parlay_math import american_to_decimal, decimal_to_american


def devig(odds_a, odds_b):
    """Proportional (multiplicative) de-vig of a two-way market."""
    pa, pb = 1 / american_to_decimal(odds_a), 1 / american_to_decimal(odds_b)
    total = pa + pb
    return pa / total, pb / total, total - 1


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
