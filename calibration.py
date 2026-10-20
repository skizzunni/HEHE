"""Walk-forward calibration of the published chance, and the calibration table.

For a pick on day D in league L (soccer leagues as one group, as for calls):

    training   L's graded, book-priced picks from days strictly before D --
               the most recent WINDOW of them
    fit        Platt scaling, logit(hit) = a + b * logit(p), shrunk toward
               "no change" (a = 0, b = 1) by LAMBDA
    publish    the fitted chance when training holds at least MIN_N picks,
               otherwise the raw no-vig chance; either way in whole percent

WINDOW, MIN_N and LAMBDA were set before any evaluation: MIN_N by the plan,
LAMBDA as rebuild_board.PLATT_LAMBDA, WINDOW at twice MIN_N.

p is the chance as published before calibration (the ledger's `p_raw`, or
`conf` for picks recorded before 2026-10-20). table() is the calibration
table on the Results tab: bins 50-60 ... 90+, realized hit rate and N, per
league and overall, with any bin trailing its stated chance by more than two
standard errors flagged.

    python3 calibration.py [--from 2026-10-15] [--to 2026-10-19]   # the study
"""
import datetime as dt
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
# Off: on the untouched window (graded picks 2026-10-15..19) the walk-forward
# fit made the published chances worse -- 358 fitted picks (college football,
# soccer): log-loss 0.5933 vs 0.5802 raw, difference +0.0131 (95% -0.0004 to
# +0.0260), Brier 0.1996 vs 0.1948 (README item 4). The raw no-vig chance is
# published until a fit wins on a later untouched window.
ENABLED = False
WINDOW = 400
MIN_N = 200
LAMBDA = 50.0
BINS = ((50, 60), (60, 70), (70, 80), (80, 90), (90, 101))


def group(league):
    try:
        import ledger
        return "soccer" if league in ledger.SOCCER else league
    except Exception:
        return league


def day_of(e):
    return e.get("date") or (e.get("logged") or "")[:10]


def book_priced(e):
    """Recorded with a sportsbook price (README item 2)."""
    from record_eligibility import record_priced
    return record_priced(e)


def raw_pct(e):
    v = e.get("p_raw", e.get("conf"))
    return float(v) if v else None


def graded(entries):
    return [e for e in entries if e.get("status") in ("won", "lost") and book_priced(e)
            and raw_pct(e) and day_of(e)]


def _logit(p):
    p = min(max(p, 0.01), 0.99)
    return math.log(p / (1 - p))


def _platt(data, lam=LAMBDA):
    a, b = 0.0, 1.0
    for _ in range(50):
        ga, gb = lam * a, lam * (b - 1)
        haa, hab, hbb = lam, 0.0, lam
        for x, y in data:
            p = 1 / (1 + math.exp(-(a + b * x)))
            r, w = p - y, p * (1 - p)
            ga += r
            gb += r * x
            haa += w
            hab += w * x
            hbb += w * x * x
        det = haa * hbb - hab * hab
        a -= (hbb * ga - hab * gb) / det
        b -= (haa * gb - hab * ga) / det
    return a, b


def fit(entries, league, before):
    """The fit for picks on day `before` (ISO date) in league's group, or
    None when fewer than MIN_N graded picks precede it."""
    g = group(league)
    rows = sorted((e for e in graded(entries) if group(e["league"]) == g and day_of(e) < before),
                  key=day_of)[-WINDOW:]
    if len(rows) < MIN_N:
        return dict(n=len(rows), group=g)
    a, b = _platt([(_logit(raw_pct(e) / 100), e["status"] == "won") for e in rows])
    return dict(a=a, b=b, n=len(rows), group=g, train=[day_of(rows[0]), day_of(rows[-1])])


def apply(f, p):
    """Calibrated chance for raw chance p (fraction), or p when unfitted."""
    if not f or "a" not in f or p is None:
        return p
    return min(max(1 / (1 + math.exp(-(f["a"] + f["b"] * _logit(p)))), 0.01), 0.99)


class Publisher:
    """Fits once per group for one publishing day; publish() gives the
    whole-percent chance and how it was made."""

    def __init__(self, entries=None, day=None):
        if entries is None:
            import ledger
            entries = list(ledger.load().values())
        self.entries = entries
        self.day = day or dt.datetime.now(dt.timezone(dt.timedelta(hours=-4))).date().isoformat()
        self.fits = {}

    def fit_for(self, league):
        g = group(league)
        if g not in self.fits:
            self.fits[g] = fit(self.entries, league, self.day)
        return self.fits[g]

    def publish(self, league, p):
        """(whole percent, note) for raw chance p (fraction)."""
        if p is None:
            return None, None
        if not ENABLED:
            return int(round(100 * p)), "raw no-vig (calibration failed its untouched test)"
        f = self.fit_for(league)
        q = apply(f, p)
        note = (f"calibrated on {f['n']} graded {f['group']} picks {f['train'][0]}..{f['train'][1]}"
                if "a" in f else f"raw no-vig ({f['n']} graded {f['group']} picks, needs {MIN_N})")
        return int(round(100 * q)), note


_PUB = {}


def publisher(day=None):
    """One Publisher per process and day (the ledger is read once)."""
    k = day or "today"
    if k not in _PUB:
        _PUB[k] = Publisher(day=day)
    return _PUB[k]


# ------------------------------------------------------------------ table
def _bins(rows):
    out = []
    for lo, hi in BINS:
        b = [e for e in rows if lo <= (e.get("conf") or 0) < hi]
        if not b:
            continue
        n = len(b)
        said = sum(e["conf"] for e in b) / n / 100
        hit = sum(e["status"] == "won" for e in b) / n
        se = math.sqrt(said * (1 - said) / n)
        out.append(dict(bin=f"{lo}-{hi}" if hi <= 100 else f"{lo}+", n=n,
                        stated=round(100 * said, 1), hit=round(100 * hit, 1),
                        se=round(100 * se, 1), flag=bool(hit < said - 2 * se)))
    return out


def table(entries, lo=None, hi=None):
    """Calibration of the chances as published, per league group and overall,
    with N and the window's dates."""
    rows = [e for e in graded(entries) if (not lo or day_of(e) >= lo) and (not hi or day_of(e) <= hi)]
    if not rows:
        return dict(n=0)
    by = {}
    for e in rows:
        by.setdefault(group(e["league"]), []).append(e)
    return dict(n=len(rows), dates=[min(map(day_of, rows)), max(map(day_of, rows))],
                overall=_bins(rows),
                leagues={g: dict(n=len(v), bins=_bins(v)) for g, v in sorted(by.items(), key=lambda x: -len(x[1]))})


# ------------------------------------------------------------------ study
def study(entries, lo, hi):
    """Walk-forward on [lo, hi]: each pick scored raw and calibrated, the fit
    for its day using only picks from earlier days."""
    rows = [e for e in graded(entries) if lo <= day_of(e) <= hi]
    cache, out = {}, []
    for e in rows:
        k = (group(e["league"]), day_of(e))
        if k not in cache:
            cache[k] = fit(entries, e["league"], day_of(e))
        p = raw_pct(e) / 100
        out.append(dict(league=k[0], day=k[1], won=int(e["status"] == "won"), raw=p,
                        cal=apply(cache[k], p), fitted="a" in cache[k]))

    def score(rs, key):
        if not rs:
            return None
        n = len(rs)
        return dict(n=n, brier=round(sum((r[key] - r["won"]) ** 2 for r in rs) / n, 4),
                    logloss=round(-sum(math.log(r[key] if r["won"] else 1 - r[key]) for r in rs) / n, 4),
                    stated=round(100 * sum(r[key] for r in rs) / n, 1),
                    hit=round(100 * sum(r["won"] for r in rs) / n, 1))
    fitted = [r for r in out if r["fitted"]]
    import random
    rng = random.Random(7)
    d = [(-math.log(r["cal"] if r["won"] else 1 - r["cal"])) - (-math.log(r["raw"] if r["won"] else 1 - r["raw"]))
         for r in fitted]
    bs = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(2000)) if d else []
    return dict(window=[lo, hi], all=dict(raw=score(out, "raw"), calibrated=score(out, "cal")),
                fitted=dict(raw=score(fitted, "raw"), calibrated=score(fitted, "cal"),
                            leagues=sorted({r["league"] for r in fitted})),
                logloss_diff_fitted=dict(mean=round(sum(d) / len(d), 5) if d else None,
                                         ci95=[round(bs[50], 5), round(bs[1949], 5)] if bs else None),
                fits={f"{g} {day}": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in f.items()}
                      for (g, day), f in sorted(cache.items()) if "a" in f})


def main():
    import argparse
    import ledger
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="lo", default="2026-10-15")
    ap.add_argument("--to", dest="hi", default="2026-10-19")
    a = ap.parse_args()
    ent = list(ledger.load().values())
    rep = dict(study=study(ent, a.lo, a.hi), table=table(ent, a.lo, a.hi))
    with open(os.path.join(HERE, "data", "calibration_study.json"), "w") as fh:
        json.dump(rep, fh, indent=1)
    print(json.dumps(rep["study"], indent=1))


if __name__ == "__main__":
    main()
