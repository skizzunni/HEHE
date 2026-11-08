"""UFC fighter ratings from ESPN fight history (ufc_history.json).

Each fighter carries an Elo-style rating that moves after every fight, more
for a finish than a split decision. Predictions are made walk-forward: a
fight's chance uses only fights before it, so the record it builds is the
record it would have had live. Also per-fighter finish rates, for method
props (inside the distance vs decision), which have no prices to test here.
"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "ufc_history.json")
START, K, DEBUT_SHRINK = 1500.0, 40.0, 0.5
WEIGHT = {"KO": 1.25, "TKO": 1.25, "Sub": 1.2, "U-Dec": 1.0, "Dec": 1.0, "M-Dec": 0.8, "S-Dec": 0.6}


def load(path=HIST):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def method(f):
    r = (f.get("result") or "").split()[0] if f.get("result") else ""
    for k in ("TKO", "KO", "Sub", "U-Dec", "S-Dec", "M-Dec", "Dec"):
        if r.startswith(k):
            return k
    return None


def expected(ra, rb):
    return 1 / (1 + 10 ** ((rb - ra) / 400))


def run(book=None, k=K):
    """Walk through every fight in date order. Returns (ratings, log) where
    log rows are (date, a, b, p_a_before, a_won, method, n_a, n_b)."""
    book = book if book is not None else load()
    R, N, log = {}, {}, []
    for cid, f in sorted(book.items(), key=lambda kv: (kv[1].get("date") or "", kv[0])):
        a, b = f["a"], f["b"]
        if a["won"] == b["won"]:              # draw / no contest: no rating change
            continue
        ia, ib = a["id"], b["id"]
        ra, rb = R.get(ia, START), R.get(ib, START)
        p = expected(ra, rb)
        log.append((f.get("date"), a["name"], b["name"], p, a["won"], method(f), N.get(ia, 0), N.get(ib, 0)))
        w = WEIGHT.get(method(f), 1.0)
        s = 1.0 if a["won"] else 0.0
        # a fighter's first fights move further, then settle
        ka = k * w * (1 + DEBUT_SHRINK / (1 + N.get(ia, 0)))
        kb = k * w * (1 + DEBUT_SHRINK / (1 + N.get(ib, 0)))
        R[ia] = ra + ka * (s - p)
        R[ib] = rb + kb * ((1 - s) - (1 - p))
        N[ia], N[ib] = N.get(ia, 0) + 1, N.get(ib, 0) + 1
    return R, log


def finish_rates(book=None):
    """{fighter id: (finishes, fights)} -- wins or losses inside the distance."""
    book = book if book is not None else load()
    out = {}
    for f in book.values():
        m = method(f)
        if not m:
            continue
        fin = m in ("KO", "TKO", "Sub")
        for x in (f["a"], f["b"]):
            a = out.setdefault(x["id"], [0, 0])
            a[0] += fin
            a[1] += 1
    return out


def score(log, since="2024-01-01", min_fights=1):
    """Walk-forward accuracy and log loss on fights from `since`, both fighters
    with at least `min_fights` earlier UFC fights."""
    X = [r for r in log if (r[0] or "") >= since and min(r[6], r[7]) >= min_fights]
    if not X:
        return None
    right = sum((r[3] >= 0.5) == r[4] for r in X)
    ll = -sum(math.log(max(1e-9, r[3] if r[4] else 1 - r[3])) for r in X) / len(X)
    return dict(n=len(X), right=right, acc=round(100 * right / len(X), 1), logloss=round(ll, 4))


def card_record(day, picks=None, winners=None):
    """The board's UFC picks for one card (picks.ufc_picks: the price
    favourite) graded against ESPN's results: dict(won, lost, losses=[...],
    close=[won, n]) where `close` is fights rated under 60%. `picks` and
    `winners` can be passed in (tests); otherwise they are fetched."""
    if picks is None:
        import picks as P
        picks = P.ufc_picks(day)
    if winners is None:
        import json as _j, urllib.request as _u
        d = _j.load(_u.urlopen(f"https://site.api.espn.com/apis/site/v2/sports/mma/ufc/scoreboard?dates={day}", timeout=60))
        winners = {}
        for ev in d.get("events") or []:
            for c in ev.get("competitions") or []:
                names = frozenset((x.get("athlete") or {}).get("displayName") for x in c.get("competitors") or [])
                w = [(x.get("athlete") or {}).get("displayName") for x in c.get("competitors") or [] if x.get("winner")]
                if w:
                    winners[names] = w[0]
    won = lost = cw = cn = 0
    losses = []
    for pair, v in (picks or {}).items():
        res = winners.get(frozenset(pair))
        if not res or not v.get("pick"):
            continue
        hit = res == v["pick"]
        won += hit
        lost += not hit
        if (v.get("conf") or 0) < 0.60:
            cn += 1
            cw += hit
        if not hit:
            losses.append(f"{v['pick']} ({round(100 * (v.get('conf') or 0))}%) lost to {res}")
    return dict(won=won, lost=lost, losses=losses, close=[cw, cn]) if won + lost else None
