"""ROI with an interval that matches it, counted by games.

A backtest's rows are not independent: one game gives dozens of alternate
lines on the same final score, so 16,000 rows were really 204 games on 32
dates. The interval here resamples whole games (every row of a game drawn
together) and recomputes the same stake-weighted ROI as the point estimate.
Before 2026-10-18 the interval was built on the unweighted per-bet mean and
treated every row as its own trial -- a different number, and far too narrow.
"""
import random


def roi_ci(rows, cost, won=lambda r: r["won"], group=lambda r: r.get("game") or r.get("date"),
           draws=1000, seed=7):
    """dict(n, games, roi, ci95) -- roi = (returned - staked) / staked, in %."""
    if not rows:
        return dict(n=0, games=0, roi=None, ci95=None)
    by = {}
    for r in rows:
        by.setdefault(group(r), []).append(r)
    sums = [(sum(cost(r) for r in v), sum(won(r) for r in v)) for v in by.values()]

    def roi(ss):
        st = sum(s for s, _ in ss)
        return 100 * (sum(w for _, w in ss) - st) / st if st else None

    point = roi(sums)
    rng = random.Random(seed)
    k = len(sums)
    boot = sorted(x for x in (roi([sums[rng.randrange(k)] for _ in range(k)]) for _ in range(draws))
                  if x is not None)
    ci = [round(boot[int(0.025 * len(boot))], 1), round(boot[int(0.975 * len(boot)) - 1], 1)] if boot else None
    return dict(n=len(rows), games=k, roi=round(point, 2) if point is not None else None, ci95=ci)
