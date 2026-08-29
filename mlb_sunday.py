"""Sunday 8/30 MLB slate: de-vigged moneylines, cross-checked against run lines.

Every game prices the same question twice -- who wins (ML) and who wins by 2+
(run line). The ratio between them is stable across baseball. Games where it
isn't are where the board is saying something inconsistent.
"""

from parlay_math import american_to_decimal, decimal_to_american
from statistics import median


def devig(a, b):
    pa, pb = 1 / american_to_decimal(a), 1 / american_to_decimal(b)
    t = pa + pb
    return pa / t, pb / t, t - 1


# away, away_sp, away_ml, away_rl, home, home_sp, home_ml, home_rl, total, time
GAMES = [
    ("SD Padres", "Robbie Ray", +140, -145, "TB Rays", "Drew Rasmussen", -170, +120, 7.5, "1:40p"),
    ("LA Dodgers", "Tyler Glasnow", -165, +110, "DET Tigers", "Framber Valdez", +135, -135, 7.5, "1:40p"),
    ("KC Royals", "Seth Lugo", +155, -140, "CLE Guardians", "Parker Messick", -190, +115, 7.5, "1:40p"),
    ("TEX Rangers", "Kumar Rocker", +140, -160, "MIL Brewers", "Dustin May", -170, +130, 8.5, "2:10p"),
    ("PIT Pirates", "Braxton Ashcraft", -120, +140, "STL Cardinals", "Matthew Liberatore", +100, -170, 8.0, "2:15p"),
    ("HOU Astros", "Ethan Pecko", +100, -190, "NY Mets", "Zac Thornton", -120, +155, 9.0, "3:10p"),
    ("BAL Orioles", "Chris Bassitt", -155, +100, "Athletics", "Jeffrey Springs", +130, -120, 10.5, "4:05p"),
    ("PHI Phillies", "Zack Wheeler", -195, -115, "LA Angels", "Yusei Kikuchi", +160, -105, 8.0, "4:07p"),
    ("CIN Reds", "Chase Burns", +120, -180, "CHI Cubs", "Shota Imanaga", -145, +145, 9.0, "7:20p"),
]


def main():
    rows = []
    print("=" * 90)
    print("SUNDAY 8/30 -- FAIR WIN PROBABILITIES")
    print("=" * 90)

    for a, asp, aml, arl, h, hsp, hml, hrl, tot, t in GAMES:
        pa, ph, hold = devig(aml, hml)
        # Run line: favorite lays -1.5.
        if pa > ph:
            fav, dog, fav_p = a, h, pa
            fav_cov, _, rl_hold = devig(arl, hrl)
        else:
            fav, dog, fav_p = h, a, ph
            _, fav_cov, rl_hold = devig(arl, hrl)
        ratio = fav_cov / fav_p
        rows.append((fav, dog, fav_p, fav_cov, ratio, t, tot, a, h))

        print(f"\n{a} @ {h}   ({t})   o/u {tot}")
        print(f"  {asp} vs {hsp}")
        print(f"  {a:<16}{aml:>+6} ->{pa*100:6.1f}%     "
              f"{h:<16}{hml:>+6} ->{ph*100:6.1f}%   hold {hold*100:.1f}%")
        print(f"  run line: {fav} wins by 2+ = {fav_cov*100:.1f}%   "
              f"| ratio to ML {ratio:.3f}")

    med = median(r[4] for r in rows)
    print("\n" + "=" * 90)
    print(f"RUN-LINE CONSISTENCY  (slate median ratio {med:.3f})")
    print("=" * 90)
    for fav, dog, fp, fc, ratio, t, tot, a, h in sorted(rows, key=lambda r: -r[4]):
        d = ratio - med
        if d > 0.05:
            note = f"<- board expects a BLOWOUT; {fav} ML relatively cheap"
        elif d < -0.05:
            note = f"<- board expects a GRINDER; {dog} live, {fav} ML rich"
        else:
            note = ""
        print(f"  {a} @ {h:<18}{fav:<16}{ratio:6.3f}  {d:+.3f}  {note}")

    print("\n" + "=" * 90)
    print("RANKED BY WIN PROBABILITY")
    print("=" * 90)
    for fav, dog, fp, fc, ratio, t, tot, a, h in sorted(rows, key=lambda r: -r[2]):
        bar = "#" * int(fp * 40)
        print(f"  {fav:<17}{fp*100:5.1f}%  {bar}")

    print("\n" + "=" * 90)
    print("WHAT A 'LOCK' ACTUALLY COSTS YOU")
    print("=" * 90)
    top = sorted(rows, key=lambda r: -r[2])
    best = top[0]
    print(f"  Board's strongest side: {best[0]} at {best[2]*100:.1f}%")
    print(f"  That loses {100-best[2]*100:.1f}% of the time -- about 1 start in 3.")
    for n in (2, 3, 4, 5):
        p = 1.0
        for r in top[:n]:
            p *= r[2]
        print(f"  Top {n} 'locks' all hitting: {p*100:5.1f}%")


if __name__ == "__main__":
    main()


def control_for_total():
    """Does the ML/run-line ratio just track the game total and the favorite's
    strength? If so the 'outliers' are artifacts. Fit both, inspect residuals.
    """
    data = []
    for a, asp, aml, arl, h, hsp, hml, hrl, tot, t in GAMES:
        pa, ph, _ = devig(aml, hml)
        if pa > ph:
            fav, fp = a, pa
            fc, _, _ = devig(arl, hrl)
        else:
            fav, fp = h, ph
            _, fc, _ = devig(arl, hrl)
        data.append((fav, fp, fc / fp, tot, a, h))

    n = len(data)
    def corr(xs, ys):
        mx, my = sum(xs)/n, sum(ys)/n
        cov = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
        vx = sum((x-mx)**2 for x in xs) ** 0.5
        vy = sum((y-my)**2 for y in ys) ** 0.5
        return cov / (vx*vy)

    ratios = [d[2] for d in data]
    totals = [d[3] for d in data]
    favps = [d[1] for d in data]
    r_tot = corr(totals, ratios)
    r_fav = corr(favps, ratios)

    print("\n" + "=" * 90)
    print("CONTROLLING THE RUN-LINE SIGNAL")
    print("=" * 90)
    print(f"  corr(ratio, game total)      = {r_tot:+.3f}")
    print(f"  corr(ratio, favorite win %)  = {r_fav:+.3f}")

    # Two-variable least squares on total and favorite strength.
    mx1, mx2, my = sum(totals)/n, sum(favps)/n, sum(ratios)/n
    x1 = [v-mx1 for v in totals]; x2 = [v-mx2 for v in favps]; y = [v-my for v in ratios]
    s11 = sum(v*v for v in x1); s22 = sum(v*v for v in x2)
    s12 = sum(a*b for a, b in zip(x1, x2))
    s1y = sum(a*b for a, b in zip(x1, y)); s2y = sum(a*b for a, b in zip(x2, y))
    det = s11*s22 - s12*s12
    b1 = (s22*s1y - s12*s2y) / det
    b2 = (s11*s2y - s12*s1y) / det

    print(f"\n  fitted: ratio = {my:.3f} + {b1:+.4f}*(total-{mx1:.2f}) "
          f"{b2:+.3f}*(favP-{mx2:.3f})")
    print(f"\n  {'GAME':<34}{'FAV':<16}{'ACTUAL':>8}{'FITTED':>8}{'RESID':>8}")
    out = []
    for fav, fp, ratio, tot, a, h in data:
        fit = my + b1*(tot-mx1) + b2*(fp-mx2)
        out.append((a, h, fav, ratio, fit, ratio-fit))
    for a, h, fav, ratio, fit, res in sorted(out, key=lambda r: -r[5]):
        flag = "  <- genuine outlier" if abs(res) > 0.04 else ""
        print(f"  {a+' @ '+h:<34}{fav:<16}{ratio:8.3f}{fit:8.3f}{res:+8.3f}{flag}")
    return out


if __name__ == "__main__":
    control_for_total()
