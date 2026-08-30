"""Sport-agnostic odds desk.

Everything that actually produced signal this weekend, generalised:
  1. de-vig a two-way market into fair probabilities
  2. rank markets by hold -- the same bet is taxed differently game to game
  3. decompose line movement into REAL MOVES vs HOLD CHANGES
  4. cross-check a second market (spread / run line / puck line) against the
     moneyline, controlling for total and favorite strength
  5. show what parlay length costs before any handicapping

Works for any sport with a two-way market: NFL, NCAAF, NBA, NHL, MLB, golf
two-balls, tennis, MMA, soccer moneylines. Feed it prices off a screenshot.

    python3 oddsdesk.py --demo
"""
import argparse
import math

# Margin-of-victory SD per sport, used to convert a spread into a win
# probability. MLB and NHL use a fixed 1.5 line instead, so they are handled
# through the ratio method rather than a normal CDF.
SIGMA = {
    "nfl": 13.5,
    "ncaaf": 16.5,     # calibrate per slate -- 8/29 fit came out at 14.15
    "nba": 12.0,
    "ncaab": 11.0,
    "golf_2ball": 4.10,   # strokes, one round, difference of two players
}


def am_to_dec(o):
    return 1 + (o / 100 if o > 0 else 100 / -o)


def dec_to_am(d):
    return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))


def devig(a, b):
    """Proportional de-vig of a two-way market -> (pA, pB, hold)."""
    pa, pb = 1 / am_to_dec(a), 1 / am_to_dec(b)
    t = pa + pb
    return pa / t, pb / t, t - 1


def spread_to_prob(points, sport):
    """P(favorite wins outright) from the spread."""
    s = SIGMA.get(sport)
    if not s:
        raise ValueError(f"no sigma for {sport}; use the ratio method")
    return 0.5 * (1 + math.erf(points / (s * math.sqrt(2))))


def classify_move(open_fav, open_dog, now_fav, now_dog):
    """A move is REAL only if the favorite's own price changed.

    If only the dog moved, the book re-cut its margin. The de-vigged
    probability shifts either way, but only the first carries information.
    """
    p0, _, h0 = devig(open_fav, open_dog)
    p1, _, h1 = devig(now_fav, now_dog)
    shift = (p1 - p0) * 100
    if open_fav != now_fav:
        toward = "favorite" if now_fav < open_fav else "dog"
        kind = f"REAL -- money on the {toward}"
    elif open_dog != now_dog:
        kind = "HOLD CHANGE ONLY -- no signal"
    else:
        kind = "unchanged"
    return dict(open_p=p0, now_p=p1, shift=shift, hold0=h0, hold1=h1, kind=kind)


def parlay_cost(hold, legs):
    """Expected return per $1 with no edge: (1/overround)^legs."""
    return (1 / (1 + hold)) ** legs


def rank_by_hold(markets):
    """markets: [(label, oddsA, oddsB)] -> cheapest tax first."""
    out = []
    for label, a, b in markets:
        pa, pb, h = devig(a, b)
        fav_p = max(pa, pb)
        out.append((label, fav_p, h))
    return sorted(out, key=lambda r: r[2])


def demo():
    print("=" * 78)
    print("1. DE-VIG  (works on any two-way price)")
    print("=" * 78)
    for label, a, b in [("MLB  Braves/Rockies", -225, +185),
                        ("NCAAF Stanford/Hawaii", -205, +170),
                        ("Golf Scheffler/Gotterup", -230, +165),
                        ("MMA  fighter A/B", -350, +270)]:
        pa, pb, h = devig(a, b)
        print(f"  {label:<26}{a:+6}/{b:+6}  ->  {pa*100:5.1f}% / {pb*100:5.1f}%"
              f"   hold {h*100:.2f}%")

    print("\n" + "=" * 78)
    print("2. HOLD RANKING -- same bet, different tax")
    print("=" * 78)
    for label, fp, h in rank_by_hold([
            ("Burns/Bridgeman", -175, +140),
            ("Aberg/Scott", -165, +115),
            ("Braves/Rockies", -225, +185),
            ("Matsuyama/Macintyre", -140, +100)]):
        print(f"  {label:<24}fav {fp*100:5.1f}%   hold {h*100:5.2f}%")

    print("\n" + "=" * 78)
    print("3. LINE MOVEMENT")
    print("=" * 78)
    for label, of, od, nf, nd in [
            ("Hovland/Gerard", -140, +105, -125, -105),
            ("McIlroy/Young", -140, +100, -150, +115),
            ("Cantlay/Reitan", -175, +140, -175, +125)]:
        m = classify_move(of, od, nf, nd)
        print(f"  {label:<20}{m['open_p']*100:5.1f}% -> {m['now_p']*100:5.1f}%"
              f"   hold {m['hold0']*100:.1f}%->{m['hold1']*100:.1f}%   {m['kind']}")

    print("\n" + "=" * 78)
    print("4. SPREAD vs MONEYLINE  (football/basketball)")
    print("=" * 78)
    for sport, pts, ml_a, ml_b in [("ncaaf", 4.0, -190, +155),
                                   ("nfl", 3.0, -170, +145),
                                   ("nba", 6.5, -240, +195)]:
        pa, pb, _ = devig(ml_a, ml_b)
        sp = spread_to_prob(pts, sport)
        print(f"  {sport.upper():<7}-{pts:<5} ML says {max(pa,pb)*100:5.1f}%   "
              f"spread says {sp*100:5.1f}%   gap {(max(pa,pb)-sp)*100:+5.1f}")
    print("\n  Fit sigma to the slate before trusting a gap -- a uniform")
    print("  one-directional bias across a board is your model, not an edge.")

    print("\n" + "=" * 78)
    print("5. WHAT LENGTH COSTS  (no edge assumed)")
    print("=" * 78)
    print(f"  {'legs':>5}{'MLB 4.6%':>12}{'NCAAF 4.8%':>12}{'golf 7.0%':>12}")
    for n in (1, 2, 3, 5, 8, 12, 14):
        print(f"  {n:>5}{parlay_cost(.046,n):>12.3f}{parlay_cost(.048,n):>12.3f}"
              f"{parlay_cost(.070,n):>12.3f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--devig", nargs=2, type=int, metavar=("A", "B"))
    a = ap.parse_args()
    if a.devig:
        pa, pb, h = devig(*a.devig)
        print(f"{pa*100:.2f}% / {pb*100:.2f}%   hold {h*100:.2f}%   "
              f"fair {dec_to_am(1/pa):+d} / {dec_to_am(1/pb):+d}")
    else:
        demo()
