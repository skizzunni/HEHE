"""Sunday 8/30 MLB: de-vigged moneylines cross-checked against run lines.

Every game is priced twice -- who wins (ML) and who wins by 2+ (run line).
The ratio between them is stable once you control for game total and how
strong the favorite is. Games that break the pattern are where the board
contradicts itself.

The run-line favorite (whoever lays -1.5) is the unambiguous anchor. On a
moneyline pick'em the ML "favorite" is undefined, so the run line decides
which side we measure -- otherwise you end up pairing one team's win
probability with the other team's cover price.
"""

from parlay_math import american_to_decimal
from statistics import median


def devig(a, b):
    pa, pb = 1 / american_to_decimal(a), 1 / american_to_decimal(b)
    t = pa + pb
    return pa / t, pb / t, t - 1


# away, away_sp, away_ml, home, home_sp, home_ml, rl_fav, fav_rl, dog_rl, total, time
GAMES = [
    ("SD Padres", "Robbie Ray", +140, "TB Rays", "Drew Rasmussen", -170, "h", +120, -145, 7.5, "1:40p"),
    ("LA Dodgers", "Tyler Glasnow", -165, "DET Tigers", "Framber Valdez", +135, "a", +110, -135, 7.5, "1:40p"),
    ("KC Royals", "Seth Lugo", +155, "CLE Guardians", "Parker Messick", -190, "h", +115, -140, 7.5, "1:40p"),
    ("TEX Rangers", "Kumar Rocker", +140, "MIL Brewers", "Dustin May", -170, "h", +130, -160, 8.5, "2:10p"),
    ("PIT Pirates", "Braxton Ashcraft", -120, "STL Cardinals", "Matthew Liberatore", +100, "a", +140, -170, 8.0, "2:15p"),
    ("HOU Astros", "Ethan Pecko", +100, "NY Mets", "Zac Thornton", -120, "h", +155, -190, 9.0, "3:10p"),
    ("BAL Orioles", "Chris Bassitt", -155, "Athletics", "Jeffrey Springs", +130, "a", +100, -120, 10.5, "4:05p"),
    ("PHI Phillies", "Zack Wheeler", -195, "LA Angels", "Yusei Kikuchi", +160, "a", -115, -105, 8.0, "4:07p"),
    ("CIN Reds", "Chase Burns", +120, "CHI Cubs", "Shota Imanaga", -145, "h", +145, -180, 9.0, "7:20p"),
    ("MIA Marlins", "Janson Junk", -110, "WSH Nationals", "Andrew Alvarez", -110, "a", +145, -180, 9.0, "12:15p"),
    ("COL Rockies", "Mason Adams", +185, "ATL Braves", "Tyler Mahle", -225, "h", -105, -115, 8.5, "1:35p"),
    ("BOS Red Sox", "Ranger Suarez", -115, "NY Yankees", "Will Warren", -105, "a", +145, -180, 8.0, "1:35p"),
]


def rows():
    out = []
    for a, asp, aml, h, hsp, hml, rlf, fav_rl, dog_rl, tot, t in GAMES:
        pa, ph, hold = devig(aml, hml)
        fav, dog, fav_p = (a, h, pa) if rlf == "a" else (h, a, ph)
        fav_cov, _, _ = devig(fav_rl, dog_rl)
        out.append(dict(away=a, home=h, fav=fav, dog=dog, fav_p=fav_p,
                        dog_p=1 - fav_p, cov=fav_cov, ratio=fav_cov / fav_p,
                        total=tot, time=t, hold=hold, asp=asp, hsp=hsp,
                        aml=aml, hml=hml))
    return out


def report():
    R = rows()
    print("=" * 92)
    print("SUNDAY 8/30 -- FAIR WIN PROBABILITIES (12 games)")
    print("=" * 92)
    for r in R:
        print(f"\n{r['away']} @ {r['home']}   ({r['time']})   o/u {r['total']}")
        print(f"  {r['asp']} vs {r['hsp']}")
        print(f"  {r['away']:<15}{r['aml']:>+6}      {r['home']:<15}{r['hml']:>+6}"
              f"   hold {r['hold']*100:.1f}%")
        print(f"  {r['fav']} wins {r['fav_p']*100:.1f}%  |  by 2+ {r['cov']*100:.1f}%"
              f"  |  ratio {r['ratio']:.3f}")

    n = len(R)
    def corr(xs, ys):
        mx, my = sum(xs)/n, sum(ys)/n
        cov = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
        return cov / ((sum((x-mx)**2 for x in xs)**.5) * (sum((y-my)**2 for y in ys)**.5))

    ratios = [r["ratio"] for r in R]
    totals = [r["total"] for r in R]
    favps = [r["fav_p"] for r in R]
    print("\n" + "=" * 92)
    print("RUN-LINE CONSISTENCY, controlled for total and favorite strength")
    print("=" * 92)
    print(f"  corr(ratio, total) = {corr(totals, ratios):+.3f}   "
          f"corr(ratio, fav win%) = {corr(favps, ratios):+.3f}")

    mx1, mx2, my = sum(totals)/n, sum(favps)/n, sum(ratios)/n
    x1 = [v-mx1 for v in totals]; x2 = [v-mx2 for v in favps]; y = [v-my for v in ratios]
    s11 = sum(v*v for v in x1); s22 = sum(v*v for v in x2)
    s12 = sum(p*q for p, q in zip(x1, x2))
    s1y = sum(p*q for p, q in zip(x1, y)); s2y = sum(p*q for p, q in zip(x2, y))
    det = s11*s22 - s12*s12
    b1 = (s22*s1y - s12*s2y)/det; b2 = (s11*s2y - s12*s1y)/det
    resid = sd = 0.0
    res = []
    for r in R:
        fit = my + b1*(r["total"]-mx1) + b2*(r["fav_p"]-mx2)
        res.append((r, r["ratio"]-fit, fit))
    sd = (sum(d*d for _, d, _ in res)/n) ** 0.5
    print(f"  residual SD = {sd:.3f}  (flagging beyond 1.5 SD)\n")
    print(f"  {'GAME':<34}{'SIDE':<16}{'ACT':>7}{'FIT':>7}{'RESID':>8}")
    for r, d, fit in sorted(res, key=lambda z: -z[1]):
        flag = ""
        if d > 1.5*sd:
            flag = f"  <- {r['fav']} ML cheap vs its run line"
        elif d < -1.5*sd:
            flag = f"  <- grinder; {r['dog']} live"
        print(f"  {r['away']+' @ '+r['home']:<34}{r['fav']:<16}"
              f"{r['ratio']:7.3f}{fit:7.3f}{d:+8.3f}{flag}")

    print("\n" + "=" * 92)
    print("ALL 12 PICKS, RANKED")
    print("=" * 92)
    ranked = sorted(R, key=lambda r: -r["fav_p"])
    for r in ranked:
        print(f"  {r['fav']:<16}{r['fav_p']*100:5.1f}%  {r['time']:>7}   "
              f"{'#'*int(r['fav_p']*40)}")

    print("\n" + "=" * 92)
    p = 1.0
    for i, r in enumerate(ranked, 1):
        p *= r["fav_p"]
        if i in (1, 2, 3, 5, 8, 12):
            print(f"  Top {i:>2} together: {p*100:7.3f}%")


if __name__ == "__main__":
    report()
