"""TOUR Championship R4 two-balls: de-vigged, with leaderboard order inferred
from tee times (final round, leaders go last).
"""
from parlay_math import american_to_decimal

# tee, playerA, oddsA, playerB, oddsB
M = [
    ("11:02a", "Patrick Cantlay", -175, "Kristoffer Reitan", +140),
    ("11:14a", "Hideki Matsuyama", -140, "Robert Macintyre", +100),
    ("11:26a", "Gary Woodland", -150, "Akshay Bhatia", +115),
    ("11:38a", "Xander Schauffele", -250, "Ryan Fox", +185),
    ("11:56a", "Collin Morikawa", -150, "Tom Kim", +115),
    ("12:08p", "Tommy Fleetwood", -185, "Alex Fitzpatrick", +140),
    ("12:20p", "Matt Fitzpatrick", -115, "Wyndham Clark", -115),
    ("12:32p", "Si Woo Kim", -150, "Justin Rose", +110),
    ("12:44p", "Sam Burns", -175, "Jacob Bridgeman", +140),
    ("1:02p", "Russell Henley", -150, "Min Woo Lee", +115),
    ("1:14p", "Rory McIlroy", -140, "Cameron Young", +100),
    ("1:26p", "Scottie Scheffler", -230, "Chris Gotterup", +165),
    ("1:38p", "Ludvig Aberg", -165, "Adam Scott", +115),
    ("1:50p", "Viktor Hovland", -140, "Ryan Gerard", +105),
]


def devig(a, b):
    pa, pb = 1/american_to_decimal(a), 1/american_to_decimal(b)
    t = pa + pb
    return pa/t, pb/t, t-1


rows = []
print("=" * 84)
print("R4 TWO-BALLS -- FAIR PROBABILITIES  (tee order = leaderboard, leaders last)")
print("=" * 84)
print(f"{'TEE':<8}{'FAVORITE':<20}{'FAIR%':>7}   {'DOG':<20}{'FAIR%':>7}{'HOLD':>7}")
for tee, a, oa, b, ob in M:
    pa, pb, hold = devig(oa, ob)
    fav, fp, dog, dp = (a, pa, b, pb) if pa >= pb else (b, pb, a, pa)
    rows.append((tee, fav, fp, dog, dp, hold, oa if fav == a else ob))
    print(f"{tee:<8}{fav:<20}{fp*100:6.1f}%   {dog:<20}{dp*100:6.1f}%{hold*100:6.1f}%")

holds = [r[5] for r in rows]
print(f"\naverage hold {sum(holds)/len(holds)*100:.2f}%   "
      f"tightest {min(holds)*100:.2f}%   widest {max(holds)*100:.2f}%")

print("\n" + "=" * 84)
print("RANKED BY WIN PROBABILITY")
print("=" * 84)
ranked = sorted(rows, key=lambda r: -r[2])
for tee, fav, fp, dog, dp, hold, ml in ranked:
    print(f"  {fav:<20}{ml:>+6}  {fp*100:5.1f}%  vs {dog:<20}{tee:>8}  "
          f"{'#'*int(fp*35)}")

print("\n" + "=" * 84)
print("STACKING THEM")
print("=" * 84)
p = 1.0
for i, r in enumerate(ranked, 1):
    p *= r[2]
    if i in (1, 2, 3, 4, 6, 10, 14):
        odds = (1/p - 1) * 100
        print(f"  Top {i:>2} legs: {p*100:8.4f}%   (about 1 in {1/p:,.0f})")

print("\n" + "=" * 84)
print("WHAT THE HOLD ALONE COSTS, NO SKILL ASSUMED")
print("=" * 84)
o = 1 + sum(holds)/len(holds)
for n in (1, 2, 3, 5, 8, 14):
    print(f"  {n:>2} legs -> keep ${(1/o)**n:.3f} per $1  ({((1/o)**n - 1)*100:+.1f}%)")


def implied_talent_gap():
    """Convert each fair probability into the strokes-gained-per-round edge the
    market is claiming.

    Single-round scoring for a tour pro has SD ~2.9 strokes. The DIFFERENCE of
    two players' rounds therefore has SD ~2.9*sqrt(2) = 4.1. So:

        P(A beats B) = Phi(gap / 4.1)

    This is the key to reading two-balls. Round 4 pairings are set by 54-hole
    score, so both players in every matchup have shot IDENTICAL golf this week.
    In-tournament form is neutralised by the pairing mechanism itself. What is
    left is pure baseline talent -- and the question becomes whether the gap the
    market is charging you for is a gap those two players actually have.
    """
    import math

    def probit(p):
        # Acklam's inverse normal CDF approximation.
        a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
             1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
        b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
             6.680131188771972e+01, -1.328068155288572e+01]
        c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
             -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
        d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
             3.754408661907416e+00]
        pl = 0.02425
        if p < pl:
            q = math.sqrt(-2*math.log(p))
            return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                   ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        if p > 1-pl:
            q = math.sqrt(-2*math.log(1-p))
            return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                    ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
        q = p - 0.5; r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)

    SIGMA = 4.10
    print("\n" + "=" * 88)
    print("WHAT TALENT GAP IS THE MARKET CHARGING FOR?")
    print("=" * 88)
    print("  Both players in each pairing shot the SAME 54-hole score.")
    print("  So the price is a pure claim about baseline ability.\n")
    print(f"  {'FAVORITE':<20}{'DOG':<20}{'FAIR%':>7}{'IMPLIED SG/RD':>15}")
    out = []
    for tee, a, oa, b, ob in M:
        pa, pb, _ = devig(oa, ob)
        fav, fp, dog = (a, pa, b) if pa >= pb else (b, pb, a)
        gap = probit(fp) * SIGMA
        out.append((fav, dog, fp, gap, tee))
        print(f"  {fav:<20}{dog:<20}{fp*100:6.1f}%{gap:+14.2f}")

    print("\n  Reference points for a full-season strokes-gained gap:")
    print("    0.3-0.5  two comparable tour pros")
    print("    0.8-1.2  a top-20 player over a journeyman")
    print("    1.5-2.0  world #1 over a fringe player  <- rare")
    print("    2.0+     essentially does not exist between two players")
    print("             who both qualified for the TOUR Championship")
    return out


if __name__ == "__main__":
    implied_talent_gap()
