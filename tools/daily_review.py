"""The daily review: what lost, why, and what to change for tomorrow.

    python3 tools/daily_review.py        # run by every board rebuild

Runs after each rebuild, so it updates as games finish. It reads everything
the site records -- picks (ledger.json), locks (locks.json), the lottery
(lottery.json), props (props.json) -- and writes:

  review/log.json            one entry per day, kept forever (the history the
                             page no longer shows)
  review/latest.md           the newest day in words
  review/anchor_weights.json the model's share of the say against the price,
                             per league, refitted on every graded pick

The refit is the self-improvement step. A pick blends the model with the
de-vigged price (dashboard.ANCHOR_W). Each day the weight that would have
predicted every graded pick best (log-loss) is found per league and used for
the next day's picks, within bounds and only with enough games behind it.
"""
import datetime as dt
import json
import math
import os
from collections import defaultdict
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "review")
ET = ZoneInfo("America/New_York")
MIN_FIT = 40                 # graded picks a league needs before its own weight
# 0 .. 0.40. Zero is in the grid: "market only" must be a real choice, not
# 5% (until 2026-10-18 the grid started at 0.05 and its first score was
# mislabelled market-only)
W_GRID = [i / 20 for i in range(0, 9)]
W_DEFAULT = 0.0          # no tested weight anywhere: the market alone (the baseline)


def load(name, default):
    try:
        with open(os.path.join(ROOT, name)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


# First regular-season day per league; graded picks before it were
# exhibitions (picked before dashboard skipped ESPN's preseason flag).
REGULAR_START = {"nba": "2026-10-16", "nhl": "2026-10-06", "nfl": "2026-09-09",
                 "ncaab": "2026-11-02"}


def exhibition(e):
    start = REGULAR_START.get(e.get("league"))
    played = e.get("played") or e.get("date") or ""
    return bool(start and played and played < start)


def implied(price):
    try:
        v = float(str(price).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if -100 < v < 100:
        return None
    return 100 / (v + 100) if v > 0 else -v / (-v + 100)


def dec(price):
    q = implied(price)
    return 1 / q if q else None


def day_of(e):
    return (e.get("played") or e.get("date") or (e.get("settled") or "")[:10]
            or (e.get("logged") or "")[:10])


def lg_(x):
    x = min(max(x, 1e-6), 1 - 1e-6)
    return math.log(x / (1 - x))


def picks_view(e):
    """(model p, market p) for the side picked, from the raw pair saved when
    the pick was made; None without one. Older entries only have the shown
    confidence (already a blend) and one side's price -- they measured a
    blend against a guess, so they are kept for description only, never
    fitted (until 2026-10-18 all 372 MLB and 79 NFL fitting rows were them)."""
    pa, qa = e.get("p_model_away"), e.get("p_market_away")
    if pa is not None and qa is not None and e.get("myside") in ("away", "home") and 0 < qa < 1:
        if e["myside"] == "away":
            return pa, qa
        return 1 - pa, 1 - qa
    return None


def refit(graded):
    by = defaultdict(list)
    for e in sorted(graded, key=lambda e: day_of(e) or ""):
        v = picks_view(e)
        if v:
            by[e["league"]].append((v[0], v[1], e["status"] == "won"))
    out, detail = {}, {}
    for lg, rs in by.items():
        if len(rs) < MIN_FIT:
            continue
        scores = []
        for w in W_GRID:
            ll = 0.0
            for pm, q, won in rs:
                p = 1 / (1 + math.exp(-((1 - w) * lg_(q) + w * lg_(pm))))
                ll -= math.log(p if won else 1 - p)
            scores.append((ll / len(rs), w))
        best = min(scores)
        # the model gets a say only if that holds on games it was not fitted
        # on: weight from the older half by date, scored on the newer half
        # against market-only. Otherwise market only (w = 0).
        m = len(rs) // 2
        def ll(rows, w):
            t = 0.0
            for pm, q, won in rows:
                p = 1 / (1 + math.exp(-((1 - w) * lg_(q) + w * lg_(pm))))
                t -= math.log(p if won else 1 - p)
            return t / len(rows)
        w_old = min(W_GRID, key=lambda w: ll(rs[:m], w))
        held = ll(rs[m:], w_old) < ll(rs[m:], 0.0)
        w = best[1] if held else 0.0
        out[lg] = w
        detail[lg] = dict(n=len(rs), weight=w, fitted=best[1], held_out=held, logloss=round(best[0], 4),
                          market_only=round(scores[0][0], 4),          # w = 0
                          model_40=round(scores[-1][0], 4))            # w = 0.40, the most allowed
    return out, detail


TWO_WAY = {"mlb", "nba", "nfl", "ncaaf", "nhl", "wnba", "ncaab"}
CUTS = [0.55 + 0.025 * i for i in range(11)]          # 0.55 .. 0.80
CALL_TARGET = 0.75
CALL_MIN_N = 25
# Tennis strong calls start at 65%: on 1,386 Sept-Oct matches the model never
# saw, its 60-70% band won 66.7%; ledger tennis picks at 65%+ won 81.8% (143).
CALL_FLOOR = {"atp": 0.65, "wta": 0.65}


def chance_and_result(e):
    """(chance of the side the board now calls, did it win) for a graded pick.

    The board follows the market's favourite in two-way sports, so an old
    pick against the favourite is re-scored as the favourite. Leagues with no
    price fall back to the pick's own stated chance."""
    won = e["status"] == "won"
    qa = e.get("p_market_away")
    if qa is not None and e.get("myside") in ("away", "home"):
        q = qa if e["myside"] == "away" else 1 - qa
        return (q, won) if q >= 0.5 else (1 - q, not won)
    q = implied(e.get("price"))
    if q is not None:
        q = min(q / 1.03, 0.99)
        if e["league"] in TWO_WAY and q < 0.5:
            return 1 - q, not won
        return q, won
    if e.get("conf"):
        return e["conf"] / 100, won
    return None


def published(e):
    """(chance shown, did it win) for a graded pick, exactly as published."""
    if not e.get("conf"):
        return None
    return e["conf"] / 100, e["status"] == "won"


def call_group(league):
    """The group a league's strong calls qualify in: every soccer league
    picks by the same market rule and has too few games alone, so soccer
    qualifies as one group -- by the same test as every other league
    (until 2026-10-19 soccer skipped the test and was given 75%)."""
    try:
        import ledger
        if league in ledger.SOCCER:
            return "soccer"
    except Exception:
        pass
    return league


def fit_calls(graded):
    """Per league, the lowest cutoff whose own record reaches CALL_TARGET on
    CALL_MIN_N+ games AND holds in both halves by date, on the chances as
    published. A league where none qualifies gets no strong calls and is
    listed as unqualified (until 2026-10-18 it fell back to the best cutoff
    on 15+ games, so "strong" appeared where nothing had qualified)."""
    by = defaultdict(list)
    for e in sorted(graded, key=lambda e: day_of(e) or ""):     # halves by date
        x = published(e)
        if x:
            by[call_group(e["league"])].append(x)
    cuts, detail = {}, {}
    for lg, rs in by.items():
        table = []
        for c in CUTS:
            sel = [w for q, w in rs if q >= c]
            if sel:
                table.append((c, len(sel), sum(sel) / len(sel)))
        # a cut-off counts only if it held in BOTH the older and the newer
        # half of the league's picks -- the lowest one that reached the target
        # once was often a lucky streak
        m = len(rs) // 2
        def holds(c):
            a = [w for q, w in rs[:m] if q >= c]
            b = [w for q, w in rs[m:] if q >= c]
            return (len(a) >= CALL_MIN_N // 2 and len(b) >= CALL_MIN_N // 2
                    and sum(a) / len(a) >= CALL_TARGET and sum(b) / len(b) >= CALL_TARGET)
        ok = [t for t in table if t[1] >= CALL_MIN_N and t[2] >= CALL_TARGET and holds(t[0])
              and t[0] >= CALL_FLOOR.get(lg, 0)]
        if not ok:
            detail[lg] = dict(cutoff=None, games=len(rs), note="insufficient evidence: no cutoff qualified",
                              all_hit=round(100 * sum(w for _, w in rs) / len(rs), 1))
            continue
        pick = ok[0]
        cuts[lg] = round(pick[0], 3)
        detail[lg] = dict(cutoff=round(pick[0], 3), calls=pick[1], hit=round(100 * pick[2], 1),
                          games=len(rs), all_hit=round(100 * sum(w for _, w in rs) / len(rs), 1))
    return cuts, detail


# ------------------------------------------- frozen strong-call cut-offs
# Since 2026-10-20 the cut-offs are not refitted daily. Each league's cut-off
# is frozen for FREEZE_DAYS; when the window ends it is refrozen from the
# FREEZE_DAYS before it. A league (soccer as one group) earns strong calls
# only if, in that prior window, its graded book-priced picks at or above the
# cut-off number at least STRONG_MIN_N, hit at least CALL_TARGET, have a Wilson
# 95% lower bound of at least CALL_TARGET - LB_MARGIN, and pass a one-sided
# exact binomial test against CALL_TARGET - LB_MARGIN after a Holm correction
# across every league tested (family-wise one-sided alpha HOLM_ALPHA). The
# lowest qualifying cut-off on the CUTS grid is the candidate; strong calls
# are the day's calls at or above it.
FREEZE_DAYS = 14
STRONG_MIN_N = 150
LB_MARGIN = 0.03
HOLM_ALPHA = 0.025


def wilson(w, n, z=1.96):
    if not n:
        return None
    p = w / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def binom_sf(k, n, p):
    """P(X >= k) for X ~ Binomial(n, p)."""
    if k <= 0:
        return 1.0
    lp, lq = math.log(p), math.log(1 - p)
    tot = 0.0
    for i in range(k, n + 1):
        tot += math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq)
    return min(tot, 1.0)


def fit_frozen(graded, start):
    """Cut-offs frozen from `start` (ISO date) for FREEZE_DAYS, fitted on the
    FREEZE_DAYS before it. -> (cutoffs, detail)."""
    import calibration as C
    d0 = dt.date.fromisoformat(start)
    lo, hi = (d0 - dt.timedelta(days=FREEZE_DAYS)).isoformat(), (d0 - dt.timedelta(days=1)).isoformat()
    # only picks that could be calls: "or draw" is never a call (calls.py)
    rows = [e for e in C.graded(graded) if lo <= C.day_of(e) <= hi and not e.get("dc")]
    by = defaultdict(list)
    for e in rows:
        by[call_group(e["league"])].append((e["conf"] / 100, e["status"] == "won"))
    floor = CALL_TARGET - LB_MARGIN
    detail, cand = {}, {}
    for lg, rs in sorted(by.items()):
        best = None
        for c in CUTS:
            if c < CALL_FLOOR.get(lg, 0):
                continue
            sel = [w for q, w in rs if q >= c]
            n, k = len(sel), sum(sel)
            if n < STRONG_MIN_N:
                break                                  # higher cut-offs only shrink N
            lb, ub = wilson(k, n)
            if k / n >= CALL_TARGET and lb >= floor:
                best = (c, n, k, lb, ub)
                break
        tested = sum(1 for q, w in rs) >= STRONG_MIN_N
        detail[lg] = dict(window=[lo, hi], games=len(rs), tested=tested, cutoff=None,
                          all_hit=round(100 * sum(w for _, w in rs) / len(rs), 1) if rs else None)
        if best:
            c, n, k, lb, ub = best
            cand[lg] = binom_sf(k, n, floor)
            detail[lg].update(candidate=round(c, 3), calls=n, hit=round(100 * k / n, 1),
                              wilson95=[round(100 * lb, 1), round(100 * ub, 1)], p=cand[lg])
        elif tested:
            detail[lg]["note"] = "no cut-off reached the target with its Wilson bound"
        else:
            detail[lg]["note"] = f"fewer than {STRONG_MIN_N} graded picks in the window"
    m = sum(1 for v in detail.values() if v["tested"])
    cuts = {}
    for i, (lg, pv) in enumerate(sorted(cand.items(), key=lambda x: x[1])):
        thr = HOLM_ALPHA / (m - i)
        detail[lg]["holm_threshold"] = thr
        if pv > thr:
            detail[lg]["note"] = "failed the Holm-corrected test"
            break                                      # Holm stops at the first failure
        cuts[lg] = detail[lg]["candidate"]
        detail[lg]["cutoff"] = cuts[lg]
    return cuts, detail


def frozen_report(graded, cfg):
    """How the frozen strong calls are doing in their window: N, dates, Wilson."""
    import calibration as C
    lo, hi = cfg.get("frozen_from"), cfg.get("frozen_to")
    cuts = cfg.get("cutoffs") or {}
    rows = [e for e in C.graded(graded) if lo and lo <= C.day_of(e) <= hi and not e.get("dc")]
    strong = [e for e in rows if cuts.get(call_group(e["league"])) is not None
              and e["conf"] / 100 >= cuts[call_group(e["league"])]]
    k = sum(e["status"] == "won" for e in strong)
    ak = sum(e["status"] == "won" for e in rows)
    w = wilson(k, len(strong))
    return dict(window=[lo, hi], n=len(strong), won=k, hit=round(100 * k / len(strong), 1) if strong else None,
                wilson95=[round(100 * w[0], 1), round(100 * w[1], 1)] if w else None,
                days=len({C.day_of(e) for e in strong}), all_n=len(rows),
                all_hit=round(100 * ak / len(rows), 1) if rows else None)


def frozen_cutoffs(graded, today, path):
    """The cut-off file for `today`: kept while its window runs, refrozen
    when it has ended (or was never frozen)."""
    try:
        with open(path) as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        cfg = {}
    t = today.isoformat()
    if not cfg.get("frozen_to") or t > cfg["frozen_to"]:
        cuts, detail = fit_frozen(graded, t)
        cfg = dict(frozen_from=t, frozen_to=(today + dt.timedelta(days=FREEZE_DAYS - 1)).isoformat(),
                   target=CALL_TARGET, min_n=STRONG_MIN_N, lb_margin=LB_MARGIN, holm_alpha=HOLM_ALPHA,
                   cutoffs=cuts, detail=detail,
                   unqualified=sorted(k for k, v in detail.items() if v.get("cutoff") is None))
    cfg["holdout"] = frozen_report(graded, cfg)
    cfg["updated"] = dt.datetime.now(ET).isoformat(timespec="minutes")
    return cfg


STUCK_DAYS = 6          # every grader voids an unplayed game after 5 days


def stuck(ledger, props, locks, lottery, today):
    """Records still open a week after their game: by then every grader has
    settled or voided them, so anything left means grading broke somewhere
    (2026-10-18: a UFC prop waited on a result line ESPN never posted)."""
    def old(d):
        try:
            return (today - dt.date.fromisoformat(str(d)[:10])).days >= STUCK_DAYS
        except ValueError:
            return False
    out = [("picks", k) for k, e in ledger.items()
           if e.get("status") == "open" and old(e.get("played") or e.get("date") or "")]
    out += [("props", k) for k, e in props.items() if e.get("status") == "open" and old(e.get("date") or "")]
    for name, book in (("locks", locks), ("safe locks", load("safe_locks.json", {"legs": {}}))):
        out += [(name, k) for k, e in (book.get("legs") or {}).items()
                if e.get("status") == "open" and old(e.get("date") or "")]
    for d, v in (lottery.get("days") or {}).items():
        out += [("lottery", f'{d} {L.get("label")}') for t in v.get("tickets") or []
                for L in t["legs"] if L.get("status") == "open" and old(d)]
    return out


def audit(graded, props, locks):
    """Running checks on every split that can drift: each line is hit vs
    stated, flagged when it trails by more than two standard errors."""
    out = []

    def line(name, rs, p_of, won_of):
        rs = [r for r in rs if p_of(r) is not None]
        if len(rs) < 10:
            return
        n = len(rs)
        hit = sum(won_of(r) for r in rs) / n
        said = sum(p_of(r) for r in rs) / n
        se = math.sqrt(max(said * (1 - said), 1e-6) / n)
        flag = " <- trailing" if hit < said - 2 * se else ""
        out.append(dict(name=name, n=n, hit=round(100 * hit, 1), said=round(100 * said, 1),
                        flag=bool(flag)))

    tennis = [e for e in graded if e.get("league") in ("atp", "wta")]
    for src, f in (("Kalshi-priced", lambda e: "Kalshi" in (e.get("why") or "")),
                   ("no market", lambda e: "no market" in (e.get("why") or ""))):
        line(f"tennis {src}", [e for e in tennis if f(e)], lambda e: (e.get("conf") or 0) / 100,
             lambda e: e["status"] == "won")
    # only markets still offered: a market already taken off (soccer shots)
    # is a closed case, and a permanent alarm for it would hide new ones
    import props_ledger as _pl
    pg = [e for e in props.values() if isinstance(e, dict) and e.get("status") in ("won", "lost")
          and _pl.offered(e.get("league"), e.get("market") or "")]
    for key in sorted({(e["league"], e["market"]) for e in pg}):
        line(f"props {key[0]} {key[1]}", [e for e in pg if (e["league"], e["market"]) == key],
             lambda e: e.get("p"), lambda e: e["status"] == "won")
    lg = [v for v in (locks.get("legs") or {}).values() if v.get("status") in ("won", "lost")]
    kinds = {}
    for v in lg:
        t = (v.get("spec") or {}).get("t") or ""
        k = "prop" if v.get("kind") == "prop" else "under" if "under" in t else "over" if "over" in t else "side"
        kinds.setdefault(f'locks {v.get("league")} {k}', []).append(v)
    for k, vs in sorted(kinds.items()):
        line(k, vs, lambda v: v.get("p"), lambda v: v["status"] == "won")
    return out


def _date_split(g):
    """Older / newer halves on a date boundary, so one day's games never sit
    on both sides."""
    h = len(g) // 2
    if not g:
        return [], []
    d = day_of(g[h]) or ""
    k = next((i for i, e in enumerate(g) if (day_of(e) or "") >= d), h)
    return g[:k], g[k:]


def holdout(graded):
    """The strong-call record the board shows, tested honestly: cut-offs
    fitted on the older half by date, scored on the newer half's picks AS
    PUBLISHED -- the side and chance actually shown, no re-scoring. Until
    2026-10-18 this re-scored old picks as the market favourite (flipping
    104 results in the newer half), which measured a different policy; that
    simulation is kept apart under `simulated`. Each row counts a pick;
    `days` says how many separate days they came from."""
    g = sorted(graded, key=lambda e: day_of(e) or "")
    old, new = _date_split(g)
    if len(old) < 100 or not new:
        return None
    cuts, _ = fit_calls(old)
    strong = alln = sw = aw = 0
    days = set()
    for e in new:
        x = published(e)
        if not x:
            continue
        alln += 1
        aw += x[1]
        c = cuts.get(call_group(e["league"]))
        if c is not None and x[0] >= c:
            strong += 1
            sw += x[1]
            days.add(day_of(e))
    if not strong:
        return None
    sim = [chance_and_result(e) for e in new]
    sim = [x for x in sim if x]
    return dict(n=strong, hit=round(100 * sw / strong, 1), all_n=alln, days=len(days),
                all_hit=round(100 * aw / alln, 1), since=day_of(new[0]), until=day_of(new[-1]),
                basis="as published",
                simulated=dict(what="old picks re-scored as the market favourite", n=len(sim),
                               hit=round(100 * sum(w for _, w in sim) / len(sim), 1) if sim else None))


def clv(rs):
    """Closing line value: how much better the first price was than the
    close, in percentage points of win chance (positive = we beat the close)."""
    xs = []
    for e in rs:
        a, b = implied(e.get("first_price")), implied(e.get("price"))
        if a and b:
            xs.append(100 * (b - a))
    return dict(n=len(xs), avg=round(sum(xs) / len(xs), 2) if xs else None,
                beat=round(100 * sum(x > 0 for x in xs) / len(xs), 1) if xs else None)


def summarize(rs):
    n = len(rs)
    if not n:
        return dict(n=0)
    w = sum(e["status"] == "won" for e in rs)
    pr = [e for e in rs if dec(e.get("price"))]
    roi = (sum((dec(e["price"]) - 1) if e["status"] == "won" else -1 for e in pr) / len(pr) * 100
           if pr else None)
    return dict(n=n, won=w, lost=n - w, hit=round(100 * w / n, 1),
                said=round(sum(e.get("conf") or 0 for e in rs) / n, 1),
                roi=round(roi, 1) if roi is not None else None)


def review_day(day, ledger, locks, lottery, props):
    graded = [e for e in ledger.values() if e.get("status") in ("won", "lost")]
    todays = [e for e in graded if day_of(e) == day]
    leagues = defaultdict(list)
    for e in todays:
        leagues[e["league"]].append(e)
    losses = [dict(league=e["league"], pick=e["pick"], said=e.get("conf"), price=e.get("price"),
                   against_market=e.get("market_agrees") is False, why=e.get("diagnosis") or "")
              for e in todays if e["status"] == "lost"]
    # the last 14 days, to tell a bad night from a leak
    since = (dt.date.fromisoformat(day) - dt.timedelta(days=14)).isoformat()
    recent = [e for e in graded if since <= day_of(e) <= day and not exhibition(e)]
    by_lg = defaultdict(list)
    for e in recent:
        by_lg[e["league"]].append(e)
    leaks = []
    for lg, rs in by_lg.items():
        s = summarize(rs)
        # a leak: 20+ calls hitting 8+ points under what they claimed
        if s["n"] >= 20 and s["hit"] < s["said"] - 8:
            leaks.append(dict(league=lg, **s))
    vs_mkt = dict(agree=summarize([e for e in recent if e.get("market_agrees") is True]),
                  against=summarize([e for e in recent if e.get("market_agrees") is False]))

    import sys
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

    def card(book):
        keys = (book.get("days") or {}).get(day, [])
        legs = [book["legs"][k] for k in keys if k in book.get("legs", {})]
        import locks as _lk
        return dict(plays={k: list(v) for k, v in _lk.plays(legs).items()},
                    n=len(legs), won=sum(L["status"] == "won" for L in legs),
                    lost=[f'{L["label"]} ({L["match"]}) {L.get("score", "")}'.strip()
                          for L in legs if L["status"] == "lost"],
                    open=sum(L["status"] == "open" for L in legs))
    lk_view = card(locks)
    sk_view = card(load("safe_locks.json", {"days": {}, "legs": {}}))
    lt = ((lottery.get("days") or {}).get(day) or {}).get("tickets", [])
    lt_view = [dict(tier=t.get("tier") or "10k", status=t.get("status", "open"),
                    legs=len(t["legs"]), won=sum(L["status"] == "won" for L in t["legs"]),
                    lost=sum(L["status"] == "lost" for L in t["legs"]),
                    killed_by=[L["label"] for L in t["legs"] if L["status"] == "lost"])
               for t in lt]
    pr = [e for e in props.values() if e.get("date") == day and e.get("status") in ("won", "lost")]
    # the ladder-consistency idea, all time: do rungs the main line says are
    # cheap win more often than their price says?
    fair = [e for e in props.values() if e.get("p_fair") and e.get("status") in ("won", "lost")]
    fair_view = dict(n=len(fair), won=sum(e["status"] == "won" for e in fair),
                     said_fair=round(100 * sum(e["p_fair"] for e in fair) / len(fair), 1) if fair else None,
                     said_price=round(100 * sum(e.get("imp") or 0 for e in fair) / len(fair), 1) if fair else None)
    pr_view = dict(fair=fair_view, n=len(pr), won=sum(e["status"] == "won" for e in pr),
                   said=round(100 * sum(e.get("p") or 0 for e in pr) / len(pr), 1) if pr else None)
    import sys
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import calls
    strong = [e for e in todays if calls.is_call(e.get("league"), e.get("conf"))]
    return dict(day=day, picks=summarize(todays), strong=summarize(strong), clv=clv([e for e in todays if e.get("first_price")]),
                picks_by_league={k: summarize(v) for k, v in leagues.items()},
                losses=losses, leaks_14d=leaks, vs_market_14d=vs_mkt,
                locks=lk_view, safe_locks=sk_view, lottery=lt_view, props=pr_view)


def words(r, fit):
    p = r["picks"]
    out = [f"# Review {r['day']}", ""]
    if p.get("n"):
        out.append(f"Picks {p['won']}-{p['lost']} ({p['hit']}% vs {p['said']}% claimed"
                   + (f", ROI {p['roi']:+}%" if p.get("roi") is not None else "") + ").")
    else:
        out.append("No picks settled yet.")
    st = r.get("stuck") or []
    if st:
        out.append(f"STUCK {len(st)} record(s) open a week after their game -- grading is broken: "
                   + "; ".join(f"{a} {b}" for a, b in st[:5]))
    for a in [a for a in (r.get("audit") or []) if a["flag"]]:
        out.append(f"TRAILING {a['name']}: {a['hit']}% hit vs {a['said']}% stated on {a['n']}")
    sc = r.get("strong") or {}
    if sc.get("n"):
        out.append(f"Strong calls {sc['won']}-{sc['lost']} ({sc['hit']}% vs {sc['said']}% claimed).")
    c = r.get("clv") or {}
    if c.get("n"):
        out.append(f"Closing line value: {c['avg']:+} points on {c['n']} picks; beat the close on {c['beat']}%.")
    for L in r["losses"]:
        out.append(f"- LOST {L['league']} {L['pick']} at {L['said']}%"
                   + (" (against the market)" if L["against_market"] else "") + f": {L['why']}")
    for k in r["leaks_14d"]:
        out.append(f"LEAK {k['league']}: {k['hit']}% hit vs {k['said']}% claimed on {k['n']} calls (14 days)")
    a, b = r["vs_market_14d"]["agree"], r["vs_market_14d"]["against"]
    if a.get("n") and b.get("n"):
        out.append(f"With the market {a['hit']}% ({a['n']}); against it {b['hit']}% ({b['n']}).")
    def named(v):
        tags = (("winners", "Winners parlay"), ("best", "Best play"))
        return "".join(f"; {t} top {v['plays'][k][0]} ({round(100 * v['plays'][k][1])}%) {v['plays'][k][2]}"
                       for k, t in tags if k in (v.get("plays") or {}))
    lk = r["locks"]
    if lk["n"]:
        out.append(f"Locks {lk['won']}/{lk['n']} won, {lk['open']} open" + named(lk)
                   + ("; lost: " + "; ".join(lk["lost"]) if lk["lost"] else "") + ".")
    sk = r.get("safe_locks") or {}
    if sk.get("n"):
        out.append(f"Safe Locks {sk['won']}/{sk['n']} won, {sk['open']} open" + named(sk)
                   + ("; lost: " + "; ".join(sk["lost"]) if sk["lost"] else "") + ".")
    for t in r["lottery"]:
        out.append(f"Lottery {t['tier']}: {t['status']} ({t['won']}/{t['legs']} legs won"
                   + (", killed by " + ", ".join(t["killed_by"]) if t["killed_by"] else "") + ")")
    fv = (r["props"] or {}).get("fair") or {}
    if fv.get("n"):
        out.append(f"Ladder-consistency props (all time): {fv['won']}/{fv['n']} won "
                   f"({100 * fv['won'] / fv['n']:.1f}%) vs {fv['said_fair']}% fair, {fv['said_price']}% price.")
    if r["props"]["n"]:
        out.append(f"Props {r['props']['won']}/{r['props']['n']} vs {r['props']['said']}% claimed.")
    out.append("")
    if r.get("calls"):
        out.append("Strong-call cut-offs (frozen; under them a call is a close call): "
                   + (", ".join(f"{k} {v['cutoff']:.1%} -> {v['hit']}% on {v['calls']} "
                                f"(Wilson {v['wilson95'][0]}-{v['wilson95'][1]}, {v['window'][0]}..{v['window'][1]})"
                                for k, v in sorted(r["calls"].items()) if v.get("cutoff") is not None)
                      or "none qualified"))
    out.append("Weights for tomorrow (model's share vs the price): "
               + ", ".join(f"{k} {v['weight']:.2f} (n={v['n']})" for k, v in sorted(fit.items())))
    return "\n".join(out) + "\n"


def main():
    ledger = load("ledger.json", {})
    locks = load("locks.json", {"days": {}, "legs": {}})
    lottery = load("lottery.json", {"days": {}})
    props = load("props.json", {})
    os.makedirs(OUT, exist_ok=True)
    log_path = os.path.join(OUT, "log.json")
    try:
        with open(log_path) as fh:
            log = json.load(fh)
    except (OSError, ValueError):
        log = {}
    today = dt.datetime.now(ET).date()
    # today (games still finishing) and yesterday (late games settle overnight)
    for d in (today - dt.timedelta(days=1), today):
        log[d.isoformat()] = review_day(d.isoformat(), ledger, locks, lottery, props)
    # Fits learn from real games only. Exhibition games were picked until
    # 2026-10-15 (all 55 graded NBA picks were preseason: 47.3% vs 68.5%
    # claimed), and letting them set the NBA weight and cut-off would carry
    # starters-resting noise into the regular season.
    graded = [e for e in ledger.values() if e.get("status") in ("won", "lost")
              and not exhibition(e)]
    weights, detail = refit(graded)
    # a league with no fit of its own (NBA in its first week, college
    # basketball before November) takes what the fitted leagues chose,
    # weighted by their games -- not a guess. On 2026-10-17 that was 0.09
    # against the hand-set 0.20.
    nw = [(v["weight"], v["n"]) for v in detail.values() if v.get("weight") is not None and v.get("n")]
    w_def = round(sum(w * n for w, n in nw) / sum(n for _, n in nw), 3) if nw else W_DEFAULT
    with open(os.path.join(OUT, "anchor_weights.json"), "w") as fh:
        json.dump(dict(updated=dt.datetime.now(ET).isoformat(timespec="minutes"),
                       default=w_def, weights=weights, detail=detail), fh, indent=1,
                  sort_keys=True)
    log[today.isoformat()]["weights"] = detail
    # strong-call cut-offs: frozen for FREEZE_DAYS, never refitted daily
    cpath = os.path.join(OUT, "call_min.json")
    cfg = frozen_cutoffs(graded, today, cpath)
    with open(cpath, "w") as fh:
        json.dump(cfg, fh, indent=1, sort_keys=True)
    log[today.isoformat()]["calls"] = cfg["detail"]
    log[today.isoformat()]["audit"] = audit(graded, props, locks)
    log[today.isoformat()]["stuck"] = stuck(ledger, props, locks, lottery, today)
    with open(log_path, "w") as fh:
        json.dump(log, fh, indent=1, sort_keys=True)
    latest = max(k for k, v in log.items() if v["picks"].get("n") or k == today.isoformat())
    with open(os.path.join(OUT, "latest.md"), "w") as fh:
        fh.write(words(log[latest], detail))
    print(words(log[latest], detail))


if __name__ == "__main__":
    main()
