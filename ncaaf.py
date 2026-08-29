"""NCAAF slate analysis: de-vigged moneylines cross-checked against the spread.

Two independent markets price the same game. The spread implies a win
probability via the distribution of final margins; the moneyline implies one
directly. When they disagree, one of them is stale -- that is where a real
edge lives, as opposed to just backing chalk.

CFB margin-of-victory SD is ~16.5 points (wider than the NFL's ~13.5).
"""

import math
from parlay_math import american_to_decimal, decimal_to_american

CFB_SIGMA = 16.5


def devig(odds_a, odds_b):
    pa, pb = 1 / american_to_decimal(odds_a), 1 / american_to_decimal(odds_b)
    t = pa + pb
    return pa / t, pb / t, t - 1


def spread_win_prob(favorite_points):
    """P(favorite wins outright) given the closing spread."""
    return 0.5 * (1 + math.erf(favorite_points / (CFB_SIGMA * math.sqrt(2))))


def risk_per_dollar(odds):
    """Dollars risked to win one dollar."""
    return 1 / (american_to_decimal(odds) - 1)


# (time, away, away_spread, away_ml, home, home_ml, total, handle_k)
GAMES = [
    ("7:00p", "Stetson", +49.0, None, "South Dakota St", None, 58.5, None),
    ("7:00p", "East Texas A&M", +22.5, +1400, "Mercer", -2800, 57.5, 5.7),
    ("7:00p", "Ab. Christian", -7.0, -285, "Lamar", +230, 49.5, 4.8),
    ("7:00p", "S.F. Austin", -11.0, -450, "McNeese St", +340, 50.0, 8.9),
    ("7:00p", "NC Central", -10.5, -450, "Texas Southern", +340, 51.5, 7.9),
    ("7:00p", "Monmouth", +9.0, +260, "Tenn. Tech", -330, 59.5, 6.6),
    ("7:00p", "Hawaii", +4.5, +170, "Stanford", -205, 48.5, 39.0),
    ("7:00p", "New Mexico St", +31.5, +2800, "Florida St", -9000, 54.0, 32.0),
    ("7:00p", "Samford", +7.0, +220, "North Alabama", -270, 55.0, 8.2),
    ("7:00p", "E Kentucky", +3.0, +120, "Western Carolina", -145, 55.0, None),
    ("7:30p", "Alabama A&M", +1.5, +105, "Howard", -125, 46.5, None),
    ("8:30p", "Jackson St", -11.5, -575, "Tennessee St", +420, 49.0, 7.8),
    ("9:00p", "Southern Utah", +16.5, +550, "Montana", -800, 61.5, 8.7),
    ("9:00p", "Prairie View", +18.5, +900, "Tarleton St", -1500, 54.5, 5.7),
    ("10:00p", "Memphis", +4.0, +155, "UNLV", -190, 56.0, 34.0),
    ("10:00p", "Montana St", -32.0, -10000, "Utah Tech", +3000, 57.5, 4.2),
]


def main():
    rows = []
    print("=" * 96)
    print("NCAAF -- de-vigged moneyline vs spread-implied win probability")
    print("=" * 96)

    for t, away, asp, aml, home, hml, total, handle in GAMES:
        if aml is None or hml is None:
            print(f"\n{away} @ {home} ({t})  spread {asp:+.1f}, o/u {total}")
            print("  moneyline not offered -- book won't price a 49-point game")
            continue

        pa, ph, hold = devig(aml, hml)
        # Favorite is whoever is laying points.
        if asp < 0:
            fav, fav_p, fav_ml, pts = away, pa, aml, -asp
        else:
            fav, fav_p, fav_ml, pts = home, ph, hml, asp
        sp_p = spread_win_prob(pts)
        gap = fav_p - sp_p
        rows.append((fav, fav_p, sp_p, gap, fav_ml, t, handle, away, home, pts))

        print(f"\n{away} @ {home}   ({t})   o/u {total}"
              + (f"   [{handle:.0f}k bets]" if handle else "   [thin]"))
        print(f"  {away:<20}{aml:>+7}  ->{pa*100:6.1f}%")
        print(f"  {home:<20}{hml:>+7}  ->{ph*100:6.1f}%     hold {hold*100:.1f}%")
        print(f"  spread says {fav} -{pts:.1f} wins {sp_p*100:.1f}%  |  "
              f"moneyline says {fav_p*100:.1f}%  |  gap {gap*100:+.1f} pts")
        print(f"  risking ${risk_per_dollar(fav_ml):.2f} to win $1 on the favorite")

    print("\n" + "=" * 96)
    print("BIGGEST SPREAD / MONEYLINE DISAGREEMENTS  (+ = ML more confident than spread)")
    print("=" * 96)
    for fav, fp, sp, gap, ml, t, h, a, hm, pts in sorted(rows, key=lambda r: -abs(r[3])):
        tag = "ML rich" if gap > 0 else "ML cheap -- dog has value" if gap < -0.03 else ""
        print(f"  {a} @ {hm:<20} {fav:<18} ML {fp*100:5.1f}%  "
              f"spread {sp*100:5.1f}%  {gap*100:+6.1f}  {tag}")

    print("\n" + "=" * 96)
    print("PAYOUT REALITY ON THE HEAVY CHALK")
    print("=" * 96)
    for fav, fp, sp, gap, ml, t, h, a, hm, pts in sorted(rows, key=lambda r: -r[1])[:5]:
        r = risk_per_dollar(ml)
        # Loss rate needed to break even at this price.
        print(f"  {fav:<20}{ml:>+7}  fair {fp*100:.1f}%   risk ${r:.2f} per $1   "
              f"one loss wipes out {r:.1f} wins")

    print("\n" + "=" * 96)
    print("TOSSUPS -- no edge available, skip")
    print("=" * 96)
    for fav, fp, sp, gap, ml, t, h, a, hm, pts in sorted(rows, key=lambda r: r[1])[:3]:
        print(f"  {a} @ {hm:<22} {fav} only {fp*100:.1f}%")




def calibrate():
    """Fit the margin SD to this slate instead of assuming a league-wide 16.5.

    A uniform one-directional gap across 11 of 15 games is a model artifact,
    not 11 separate mispricings. Fitting sigma removes the systematic component
    so the residuals mean something.

    Variance scales with scoring, so sigma is modelled as k*sqrt(total/55)
    rather than a single constant.
    """
    obs = []
    for t, away, asp, aml, home, hml, total, handle in GAMES:
        if aml is None:
            continue
        pa, ph, _ = devig(aml, hml)
        if asp < 0:
            obs.append((-asp, pa, total, away, home, aml))
        else:
            obs.append((asp, ph, total, home, away, hml))

    def sse(k):
        s = 0.0
        for pts, ml_p, total, *_ in obs:
            sig = k * math.sqrt(total / 55.0)
            s += (ml_p - spread_win_prob_sig(pts, sig)) ** 2
        return s

    best_k, best = None, float("inf")
    x = 8.0
    while x <= 22.0:
        v = sse(x)
        if v < best:
            best, best_k = v, x
        x += 0.05

    print("\n" + "=" * 96)
    print(f"CALIBRATED: sigma = {best_k:.2f} * sqrt(total/55)   "
          f"(was a flat 16.5 -- too wide, which faked an edge on every favorite)")
    print("=" * 96)
    print(f"{'GAME':<38}{'PICK':<18}{'ML%':>7}{'SPREAD%':>9}{'RESID':>8}")
    rows = []
    for pts, ml_p, total, fav, dog, ml in obs:
        sig = best_k * math.sqrt(total / 55.0)
        sp = spread_win_prob_sig(pts, sig)
        rows.append((fav, dog, ml_p, sp, ml_p - sp, ml, pts))
    for fav, dog, ml_p, sp, resid, ml, pts in sorted(rows, key=lambda r: r[4]):
        note = ""
        if resid < -0.02:
            note = f"  <- {dog} live"
        elif resid > 0.02:
            note = "  <- fav overpriced"
        print(f"{fav+' -'+format(pts,'.1f')+' vs '+dog:<38}{fav:<18}"
              f"{ml_p*100:6.1f}%{sp*100:8.1f}%{resid*100:+7.1f}{note}")
    return best_k


def spread_win_prob_sig(points, sigma):
    return 0.5 * (1 + math.erf(points / (sigma * math.sqrt(2))))


if __name__ == "__main__":
    main()
    calibrate()
