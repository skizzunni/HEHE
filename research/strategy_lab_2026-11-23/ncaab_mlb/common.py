"""Shared scoring for the NCAAB / MLB strategy lab.

A bet is (season, price_american, p_novig, result) with result 1 win, 0 loss,
None push (dropped). Per season: n, win%, mean no-vig implied, flat ROI at
the closing price, z = (wins - sum p) / sqrt(sum p(1-p)).
Verdict: adopted = ROI > 0 every season and z >= 2.8 in both halves;
on watch = ROI > 0 in all but at most one season (and >= 3 seasons with bets);
else rejected."""
import math


def imp(a):
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def novig(a, b):
    """No-vig probability of side a given the two sides' American prices."""
    pa, pb = imp(a), imp(b)
    return pa / (pa + pb)


def profit(a):
    return a / 100 if a > 0 else 100 / -a


def summ(bets):
    bets = [b for b in bets if b[3] is not None]
    n = len(bets)
    if not n:
        return dict(n=0)
    w = sum(b[3] for b in bets)
    ep = sum(b[2] for b in bets)
    var = sum(b[2] * (1 - b[2]) for b in bets)
    pl = sum(profit(b[1]) if b[3] else -1 for b in bets)
    return dict(n=n, win=w / n, imp=ep / n, roi=pl / n, z=(w - ep) / math.sqrt(var) if var > 0 else 0.0)


def evaluate(name, bets, seasons, halves):
    by = {s: summ([b for b in bets if b[0] == s]) for s in seasons}
    hz = [summ([b for b in bets if b[0] in h]) for h in halves]
    tot = summ(bets)
    rois = [by[s].get("roi") for s in seasons if by[s].get("n")]
    allpos = len(rois) == len(seasons) and all(r > 0 for r in rois)
    zs = [h.get("z", -9) if h.get("n") else -9 for h in hz]
    if allpos and all(z >= 2.8 for z in zs):
        v = "ADOPTED"
    elif len(rois) >= 3 and sum(r > 0 for r in rois) >= len(rois) - 1 and tot.get("roi", -1) > 0:
        v = "on watch"
    else:
        v = "rejected"
    return dict(name=name, total=tot, seasons={str(s): by[s] for s in seasons}, halves=hz, verdict=v)


def fmt(r, seasons):
    t = r["total"]
    if not t.get("n"):
        return f"{r['name']:<52} n=0"
    ss = " ".join(f"{(r['seasons'][str(s)].get('roi', float('nan'))*100):+6.1f}({r['seasons'][str(s)].get('n',0)})" for s in seasons)
    hz = "/".join(f"{h.get('z', float('nan')):+.2f}" for h in r["halves"])
    return (f"{r['name']:<52} n={t['n']:5d} win {t['win']*100:5.1f} vs {t['imp']*100:5.1f}  "
            f"ROI {t['roi']*100:+6.1f}  by season {ss}  z {hz}  {r['verdict']}")
