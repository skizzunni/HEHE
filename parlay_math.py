"""Parlay economics: why a good picker still loses on long parlays.

Pure math, no network. Run: python3 parlay_math.py
"""

from dataclasses import dataclass, field


def american_to_decimal(odds: int) -> float:
    return 1 + (odds / 100 if odds > 0 else 100 / -odds)


def decimal_to_american(dec: float) -> int:
    return round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))


def implied_prob(dec: float) -> float:
    return 1 / dec


def geometric_leg_prob(parlay_dec: float, legs: int) -> float:
    """Average per-leg implied probability baked into a parlay price."""
    return implied_prob(parlay_dec) ** (1 / legs)


def parlay_ev(legs: int, true_leg_prob: float, hold_per_leg: float, stake: float = 1.0):
    """Expected return on a parlay where the book takes `hold_per_leg` on each leg.

    The book prices each leg at true_prob inflated by the hold, so the payout
    multiplier is (true_leg_prob * (1 + hold)) ** -legs. Every added leg
    compounds the hold — that is the whole story.
    """
    priced_prob = min(true_leg_prob * (1 + hold_per_leg), 0.999)
    payout_dec = (1 / priced_prob) ** legs
    win_prob = true_leg_prob ** legs
    expected = win_prob * payout_dec * stake
    return {
        "legs": legs,
        "win_prob": win_prob,
        "payout_dec": payout_dec,
        "american": decimal_to_american(payout_dec),
        "expected_return": expected,
        "edge": expected - stake,
    }


def breakeven_hit_rate(parlay_dec: float, legs: int) -> float:
    """Per-leg accuracy needed for this parlay price to be break-even."""
    return (1 / parlay_dec) ** (1 / legs)


@dataclass
class Slip:
    name: str
    legs: int
    american: int
    stake: float
    won: int = 0
    lost: int = 0
    ungraded: int = 0
    note: str = ""
    resolved: bool = True

    @property
    def graded(self) -> int:
        return self.won + self.lost


SLIPS = [
    Slip("Table tennis / MMA", 12, 21074, 5.00, won=9, lost=3,
         note="LOST -- 75% leg accuracy was not enough"),
    Slip("Golf R3 2-balls", 14, 152121, 5.00, won=1, lost=4, ungraded=9,
         note="LOST -- dead after 4 legs, 9 never mattered"),
    Slip("MLB 10-leg", 10, 20316, 5.00, won=2, ungraded=8,
         note="PENDING -- needs 8 straight", resolved=False),
    Slip("MLB 12-leg", 12, 62536, 5.00, won=2, ungraded=10,
         note="PENDING -- needs 10 straight", resolved=False),
]


def report():
    print("=" * 74)
    print("SLIP AUTOPSY")
    print("=" * 74)
    for s in SLIPS:
        dec = american_to_decimal(s.american)
        be = breakeven_hit_rate(dec, s.legs)
        avg_leg = geometric_leg_prob(dec, s.legs)
        print(f"\n{s.name}: {s.legs} legs @ +{s.american}  (${s.stake:.2f})")
        print(f"  {s.note}")
        print(f"  Implied parlay win prob      : {implied_prob(dec)*100:8.4f}%")
        print(f"  Avg per-leg implied price    : {avg_leg*100:8.2f}%  "
              f"({decimal_to_american(1/avg_leg):+d} per leg)")
        print(f"  Per-leg accuracy to break even: {be*100:7.2f}%")
        if s.graded:
            hit = s.won / s.graded
            print(f"  Actual graded accuracy       : {hit*100:8.2f}%  "
                  f"({s.won}/{s.graded})")
            print(f"  P(all {s.legs} legs) at that rate : "
                  f"{hit**s.legs*100:8.4f}%")
        if s.ungraded and not s.resolved:
            print(f"  Still needs {s.ungraded} straight; at 58%/leg that is "
                  f"{0.58**s.ungraded*100:.2f}%")

    print("\n" + "=" * 74)
    print("WHY LENGTH IS THE BUG (4.5% hold per leg, genuinely skilled 55% picker)")
    print("=" * 74)
    print(f"{'legs':>5} {'win prob':>10} {'price':>10} {'exp. return':>12} {'edge/$1':>9}")
    for n in (1, 2, 3, 4, 6, 8, 10, 12, 14):
        r = parlay_ev(n, 0.55, 0.045)
        print(f"{n:>5} {r['win_prob']*100:9.3f}% {r['american']:>+10d} "
              f"{r['expected_return']:11.3f}  {r['edge']:+8.3f}")
    print("\nA 55% picker is +EV on a single bet and -EV by 12 legs:")
    print("the hold compounds as (1 - h)^n while your edge only multiplies.")

    print("\n" + "=" * 74)
    print("SAME $10 DEPLOYED THREE WAYS (55% true, -110 singles)")
    print("=" * 74)
    single = 10 * (0.55 * american_to_decimal(-110))
    print(f"  10 x $1 singles @ -110      -> expected ${single:6.2f}  "
          f"({single-10:+.2f})")
    for legs, stake in ((3, 10), (12, 10)):
        r = parlay_ev(legs, 0.55, 0.045, stake)
        print(f"  ${stake} on a {legs:>2}-leg parlay     -> expected "
              f"${r['expected_return']:6.2f}  ({r['edge']:+.2f})")


if __name__ == "__main__":
    report()
