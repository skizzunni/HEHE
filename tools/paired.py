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


# ---------------------------------------------------------------- studies
def _ledger_days():
    """Graded two-way picks as decisions: the published pick (old) against the
    same game's same-time market favourite (new), from the same price."""
    import daily_review as R
    L = json.load(open(os.path.join(ROOT, "ledger.json")))
    two = {"mlb", "nba", "nfl", "ncaaf", "nhl", "wnba", "ncaab", "atp", "wta", "ufc"}
    days = defaultdict(list)
    for k, e in L.items():
        if e.get("status") not in ("won", "lost") or R.exhibition(e) or e["league"] not in two:
            continue
        qa = e.get("p_market_away")
        if qa is not None and e.get("myside") in ("away", "home"):
            q = qa if e["myside"] == "away" else 1 - qa
        else:
            q = R.implied(e.get("price"))
            if q is None:
                continue
            q = min(q / 1.03, 0.99)
        won = e["status"] == "won"
        days[R.day_of(e)].append(dict(gid=k, league=e["league"], label=e["pick"], q=q,
                                      won_old=won, won_new=won if q >= 0.5 else not won))
    return days


def study_market_only():
    days = _ledger_days()
    _, newer, cut = split_dates(days)
    by = {}
    for scope in ["all"] + sorted({r["league"] for v in newer.values() for r in v}):
        rows = {d: [r for r in v if scope == "all" or r["league"] == scope] for d, v in newer.items()}
        # one decision per game: both choosers pick a side of every game
        old = lambda rs, k: [dict(x, label=x["label"], won=x["won_old"]) for x in rs]
        # the same team where the market agreed; otherwise its opponent
        new = lambda rs, k: [dict(x, label=x["label"] if x["q"] >= 0.5 else "opponent of " + x["label"],
                                  won=x["won_new"]) for x in rs]
        r = compare({d: v for d, v in rows.items() if v}, old, new, 0)
        by[scope] = {k: r[k] for k in ("days", "picks", "old_won", "new_won", "diff", "ci95_diff",
                                       "new_won_old_missed", "old_won_new_missed", "promote")}
        if scope == "all":
            by[scope]["examples_new"] = r["examples_new"][:8]
            by[scope]["examples_old"] = r["examples_old"][:8]
    return dict(name="Model weight off (market-only) vs the published picks",
                baseline="the pick as published (hand-set model weights in NFL/WNBA/MLB/tennis)",
                proposal="the same-time market favourite (tested weight 0)",
                same="one pick per game, same game, same price", untouched_from=cut, result=by)


def study_locks_uncertainty():
    rows = json.load(open(os.path.join(ROOT, "data", "backtest_kalshi_legs.json")))
    out = {}
    for nm, (lo, hi) in (("Locks (-400..-120)", (0.545, 0.80)), ("Safe (-2000..-500)", (0.833, 0.952))):
        days = defaultdict(list)
        for r in rows:
            if lo <= r["cost"] <= hi:
                # Kalshi's own mid-price: the ask less half the spread. (r["p"] is
                # the Stacks score model's chance from the sportsbook close, not a
                # market price -- used here by mistake until 2026-10-20.)
                w = r.get("width") or 0
                days[r["date"]].append(dict(gid=r["game"], label=r["ticker"] + r["side"],
                                            p=r["cost"] - w / 2, width=w, won=r["won"]))

        def pick(key):
            def f(rs, k):
                best = {}
                for x in sorted(rs, key=key):
                    best.setdefault(x["gid"], x)
                c = sorted(best.values(), key=key)
                return c[:k] if len(c) >= k else []
            return f
        _, newer, cut = split_dates(days)
        r = compare(newer, pick(lambda x: -x["p"]), pick(lambda x: -(x["p"] - x["width"] / 2)), 11)
        out[nm] = {k: r[k] for k in ("days", "picks", "old_won", "new_won", "diff", "ci95_diff",
                                     "new_won_old_missed", "old_won_new_missed", "promote")}
        out[nm]["untouched_from"] = cut
    return dict(name="Locks ranked by chance minus its uncertainty",
                baseline="ranked by chance", proposal="ranked by chance - half the bid/ask width",
                same="11 legs a day, one per game, same price window, same quotes", result=out)


def study_lab():
    import policy
    lab = json.load(open(os.path.join(ROOT, "data", "edge_lab.json")))
    out = {}
    for lg, v in (lab.get("leagues") or {}).items():
        for f, r in v.items():
            if isinstance(r, dict) and "picks_changed" in r:
                out[f"{lg} {f}"] = dict(changed=r["picks_changed"], net=r["extra_wins"],
                                        promote=policy.promoted(r))
    return dict(name="Pregame inputs beyond the closing price (edge lab)",
                baseline="closing favourite", proposal="close + one input (home, drift, rest, form...)",
                same="every game, untouched half by date", rule="net >= 2 x sqrt(changed)",
                result=out, promoted=sorted(k for k, x in out.items() if x["promote"]))


def main():
    rep = dict(run=__import__("datetime").date.today().isoformat(),
               rule="promote only if the day-bootstrap 95% interval of (new wins - old wins) on "
                    "untouched later days is above zero (lab inputs: net >= 2 SE)",
               studies=[study_market_only(), study_locks_uncertainty(), study_lab()])
    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1)
    for s in rep["studies"]:
        r = s["result"]
        print(s["name"])
        for k, v in list(r.items())[:12]:
            print("  ", k, {x: v.get(x) for x in ("picks", "old_won", "new_won", "diff", "ci95_diff",
                                                  "new_won_old_missed", "old_won_new_missed",
                                                  "changed", "net", "promote") if x in v})
    return rep


if __name__ == "__main__":
    main()
