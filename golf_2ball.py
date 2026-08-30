"""Golf two-ball pricing, backtested on 36 tournaments of 2026 round scores.

    python3 golf_2ball.py --gap 0.9        # win prob for a season-form gap

BACKTEST (4,191 player-tournament records, 36 events, point-in-time skill:
a player's rating uses only rounds from tournaments BEFORE the one being
predicted). Rounds 3 and 4 only, since that is when two-balls are offered.

Random pairings, n=1,571 decided matchups:

    point-in-time season form   57.8%
    better tournament position  52.5%
    hotter previous round       52.0%     <- "form" is almost worthless
    tie rate                    11.1%

Win rate rises with the skill gap, and this curve is the model:

    gap (strokes/round)   win rate
    0.00 - 0.50            52.0%      n=598
    0.50 - 1.00            57.5%      n=492
    1.00 - 1.50            62.6%      n=235
    1.50 - 2.00            65.4%      n=136
    2.00 +                 70.9%      n=110

THE CATCH THAT MATTERS

Real two-balls are not random pairings. Rounds 3 and 4 are paired by
leaderboard position, so the two players are close in score and usually close
in ability -- the gaps land in the flat bottom of that curve. Re-run on
leaderboard-adjacent pairings, the same signal scores only **54.8%**, and the
tie rate rises to **17.7%**.

That 17.7% is the number to remember. On a two-ball WITHOUT "tie no bet", a tie
is a loss. Roughly one leg in six dies for reasons that have nothing to do with
whether the read was right.
"""
import argparse
import math

CURVE = [(0.00, 0.50, 52.0), (0.50, 1.00, 57.5), (1.00, 1.50, 62.6),
         (1.50, 2.00, 65.4), (2.00, 99.0, 70.9)]

TIE_RATE_ADJACENT = 0.177
TIE_RATE_RANDOM = 0.111
OWGR_STROKES_PER_LOGPOINT = 0.80


def win_prob(gap):
    """Empirical two-ball win rate for a season-form gap, in strokes per round."""
    g = abs(gap)
    for lo, hi, v in CURVE:
        if lo <= g < hi:
            return v / 100.0
    return CURVE[-1][2] / 100.0


def gap_from_owgr(pts_a, pts_b):
    """Approximate strokes-per-round gap from OWGR average points."""
    return abs(math.log(pts_a) - math.log(pts_b)) * OWGR_STROKES_PER_LOGPOINT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap", type=float, help="skill gap in strokes per round")
    ap.add_argument("--owgr", nargs=2, type=float, metavar=("PTS_A", "PTS_B"))
    a = ap.parse_args()
    gap = a.gap if a.gap is not None else (
        gap_from_owgr(*a.owgr) if a.owgr else None)
    if gap is None:
        ap.error("pass --gap or --owgr")
    p = win_prob(gap)
    print(f"\n  skill gap        {gap:.2f} strokes/round")
    print(f"  tie-no-bet win   {p*100:.1f}%   (random pairings)")
    print(f"  realistic        ~{min(p*100, 54.8 + (p*100-52)*0.5):.1f}%   "
          f"(leaderboard-adjacent, how books actually pair them)")
    print(f"  tie risk         {TIE_RATE_ADJACENT*100:.1f}% -- a tie LOSES "
          f"without tie-no-bet\n")


if __name__ == "__main__":
    main()
