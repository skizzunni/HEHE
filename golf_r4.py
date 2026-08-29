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
