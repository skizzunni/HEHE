"""Paired comparison of two choosers on the same decisions.

Both choosers see exactly the same candidates (same pregame prices and
inputs), pick the same number of selections under the same price window, and
are scored on the same later games. The comparison is in the selections where
they differ: how often the new one's pick won where the old one's lost, and
the reverse. A change is promoted only when, on games later than anything
used to design it, the new chooser wins more of those than it loses and a
day-level bootstrap's 95% interval for the difference stays above zero.

    python3 tools/paired.py        # writes data/paired_eval.json
"""
import json
import os
import random
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "data", "paired_eval.json")


def compare(days, old, new, k, draws=2000, seed=11):
    """days: {date: [candidate rows with 'won' and 'gid']}; old/new: functions
    (rows, k) -> chosen rows. Returns the paired summary and the discordant
    selections (new won where old lost, and the reverse)."""
    per_day, gained, lost_ = [], [], []
    n_old = n_new = w_old = w_new = 0
    for d in sorted(days):
        a, b = old(days[d], k), new(days[d], k)
        if len(a) != len(b):
            continue                       # same number of picks, or no comparison
        ka = {(x["gid"], x["label"]) for x in a}
        kb = {(x["gid"], x["label"]) for x in b}
        wa, wb = sum(x["won"] for x in a), sum(x["won"] for x in b)
        n_old += len(a); n_new += len(b); w_old += wa; w_new += wb
        only_new = [x for x in b if (x["gid"], x["label"]) not in ka]
        only_old = [x for x in a if (x["gid"], x["label"]) not in kb]
        gained += [dict(day=d, new=x["label"], game=x["gid"], won=x["won"]) for x in only_new if x["won"]]
        lost_ += [dict(day=d, old=x["label"], game=x["gid"], won=x["won"]) for x in only_old if x["won"]]
        per_day.append(wb - wa)
    rng = random.Random(seed)
    boot = sorted(sum(rng.choice(per_day) for _ in per_day) for _ in range(draws)) if per_day else []
    ci = [boot[int(0.025 * len(boot))], boot[int(0.975 * len(boot)) - 1]] if boot else None
    return dict(days=len(per_day), picks=n_new, old_won=w_old, new_won=w_new,
                diff=w_new - w_old, ci95_diff=ci,
                new_won_old_missed=len(gained), old_won_new_missed=len(lost_),
                examples_new=gained[:12], examples_old=lost_[:12],
                promote=bool(ci and ci[0] > 0))


def split_dates(days):
    ds = sorted(days)
    cut = ds[len(ds) // 2] if ds else ""
    return {d: v for d, v in days.items() if d < cut}, {d: v for d, v in days.items() if d >= cut}, cut
