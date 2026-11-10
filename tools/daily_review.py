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
import sys
sys.path.insert(0, ROOT)
from record_eligibility import record_priced
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
    for e in sorted((e for e in graded if record_priced(e)), key=lambda e: day_of(e) or ""):
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
    for e in sorted((e for e in graded if record_priced(e)), key=lambda e: day_of(e) or ""):     # halves by date
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
    # Only exact-market priced picks can be calls, including captured DC quotes.
    from tennis_eligibility import captured_quote
    rows = [e for e in C.graded(graded) if lo <= C.day_of(e) <= hi
            and (e.get("league") not in ("atp", "wta") or captured_quote(e))]
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
            if k / n >= CALL_TARGET and lb >= (CALL_TARGET if lg in ("atp", "wta") else floor):
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
    rows = [e for e in C.graded(graded) if lo and lo <= C.day_of(e) <= hi]
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


STUCK_DAYS = 6          # props, locks and lottery void an unplayed game after 5 days


# Game picks wait longer: the ledger voids an unplayed or rescheduled game
# only after its VOID_AFTER_DAYS (7), so flagging picks at 6 raised false
# alarms (2026-10-26: a Saudi game moved to December, voided the next day).
def _pick_stuck_days():
    try:
        import ledger as _l
        return _l.VOID_AFTER_DAYS + 2
    except Exception:
        return 9


PICK_STUCK_DAYS = _pick_stuck_days()


def pool_ctx(w, F):
    """For a Locks / Safe Locks caution, the same bet type across every saved
    line over the last pool days, so a short card split can be read against
    the pool it was drawn from. '' when not a card caution or no pool."""
    f = F.get((w.get("league"), w.get("t"))) if w.get("where") in ("Locks", "Safe Locks") else None
    if not f or not f.get("n"):
        return ""
    pct = 100 * f["won"] / f["n"]
    return (f" (all saved lines since {f['since']}: {f['won']}/{f['n']}, {round(pct)}% vs {round(f['said'])}%"
            + (" -- pool on par" if pct >= f["said"] - 2 else " -- pool short too") + ")")


def caution_line():
    """The cautions in force (locks.watch_kinds per card, locks.watch_pool),
    one line, or None."""
    try:
        import locks
        W = [dict(w, where="Locks") for w in locks.watch_kinds(locks.load())]
        W += [dict(w, where="Safe Locks") for w in locks.watch_kinds(locks.load(locks.SAFE_LEDGER))]
        W += [dict(w, where="all saved lines") for w in locks.watch_pool()]
    except Exception:
        return None
    try:                                  # calls by league and chance band (ledger.call_cautions)
        import ledger
        C = ledger.call_cautions(ledger.load())
    except Exception:
        C = []
    try:                                  # bet types ahead of their chance (locks.bright_pool)
        B = locks.bright_pool()
    except Exception:
        B = []
    try:                                  # last 7 pool days of every saved line (locks.pool_form)
        F = {(f["league"], f["t"]): f for f in locks.pool_form()}
    except Exception:
        F = {}
    parts = [f"{w['league'].upper()} {w['t']} on {w['where']} {w['won']}/{w['n']} vs {w['said']}%" + pool_ctx(w, F) for w in W]
    parts += [f"{c['league'].upper()} calls at {c['band']}-{c['band'] + 10}% {c['won']}/{c['n']} vs {c['said']}%" for c in C]
    out = ("Cautions in force: " + "; ".join(parts) + ".") if parts else None
    if B:
        ahead = "Running ahead: " + "; ".join(f"{b['league'].upper()} {b['t']} on all saved lines {b['won']}/{b['n']} vs {b['said']}%"
                                              for b in B) + "."
        out = f"{out} {ahead}" if out else ahead
    return out


def prereg_line():
    """Where the pre-registered spread-band test stands (locks.prereg_status)."""
    try:
        import locks
        s = locks.prereg_status()
    except Exception:
        return None
    rec = f"{s['won']}/{s['n']}" + (f" ({round(100 * s['won'] / s['n'])}% vs {round(s['said'])}% stated)" if s["n"] else "")
    what = {"waiting": f"waiting for {s['need']} legs", "short": "SHORT again -- propose excluding the band",
            "fine": "fine -- drop the caution"}[s["verdict"]]
    return f"Pre-registered test, {s['name']}: {rec}; {what}."


def dc_side_line(ledger=None, min_n=30):
    """Soccer "or draw" picks split by the side taken (home or away), each
    with its date halves: won% against stated%. Priced, graded rows only.
    A watch line, not a rule: on 2026-11-09 both sides ran at or above their
    stated chance in both halves (home 77% vs 74% on 402, away 74% vs 72%
    on 199), so nothing is cut."""
    if ledger is None:
        ledger = load("ledger.json", {})
    rows = sorted((v for v in ledger.values() if isinstance(v, dict) and v.get("dc")
                   and v.get("status") in ("won", "lost") and not v.get("record_excluded")
                   and v.get("myside") in ("home", "away") and v.get("conf") is not None),
                  key=lambda v: v.get("date") or "")
    if len(rows) < min_n:
        return None
    mid = rows[len(rows) // 2].get("date") or ""

    def rec(s):
        return f"{round(100 * sum(v['status'] == 'won' for v in s) / len(s))}%" if s else "-"
    parts = []
    for side in ("home", "away"):
        s = [v for v in rows if v["myside"] == side]
        if not s:
            continue
        said = round(sum(v["conf"] for v in s) / len(s))
        a = [v for v in s if (v.get("date") or "") < mid]
        b = [v for v in s if (v.get("date") or "") >= mid]
        flag = " SHORT" if sum(v["status"] == "won" for v in s) / len(s) * 100 < said - 3 else ""
        parts.append(f"{side} {rec(s)} vs {said}% stated on {len(s)} (halves {rec(a)}, {rec(b)}){flag}")
    out = "Soccer or-draw picks by side: " + "; ".join(parts) + "."
    short = []                      # chance bands 2+ points short of stated in both date halves
    for lo, hi in ((60, 65), (65, 70), (70, 75), (75, 80), (80, 101)):
        hv = [[v for v in rows if lo <= v["conf"] < hi and ((v.get("date") or "") < mid) == first] for first in (True, False)]
        if all(len(h) >= 10 for h in hv) and all(
                100 * sum(v["status"] == "won" for v in h) / len(h) < sum(v["conf"] for v in h) / len(h) - 2 for h in hv):
            short.append(f"{lo}-{min(hi, 100)}% ({rec(hv[0])}, then {rec(hv[1])})")
    if short:
        out += " Short in both halves: " + ", ".join(short) + "."
    soc = {v.get("league") for v in rows}
    sw = [v for v in ledger.values() if isinstance(v, dict) and not v.get("dc") and v.get("league") in soc
          and v.get("status") in ("won", "lost") and not v.get("record_excluded") and v.get("conf") is not None]
    if sw:
        lost = [v for v in sw if v["status"] == "lost"]
        drawn = sum(1 for v in lost if len(set((v.get("scores") or {}).values())) == 1 and v.get("scores"))
        said = round(sum(v["conf"] for v in sw) / len(sw))
        out += (f" Straight wins: {rec(sw)} vs {said}% stated on {len(sw)}"
                + (f"; {drawn} of {len(lost)} losses were draws" if lost else "") + ".")
    return out


def ufc_line(today=None, back=8):
    """The most recent UFC card in the last `back` days, its picks graded
    (ufc_model.card_record), one line or None."""
    try:
        import ufc_model
    except Exception:
        return None
    today = today or dt.date.today()
    for i in range(1, back + 1):
        day = (today - dt.timedelta(days=i)).strftime("%Y%m%d")
        try:
            r = ufc_model.card_record(day)
        except Exception:
            r = None
        if r:
            c = r["close"]
            return (f"UFC {day[:4]}-{day[4:6]}-{day[6:]}: picks (the price favourite) {r['won']}-{r['lost']}"
                    + (f"; close fights (under 60%) {c[0]} of {c[1]}" if c[1] else "")
                    + (f"; lost: {', '.join(r['losses'])}" if r["losses"] else "") + ".")
    return None


def card_check(now=None, book=None, report_fn=None):
    """After 8:15 AM Eastern, today's Locks card must be saved -- the ladder
    ticket is set from it. A MISSING line when it is not, else None."""
    now = now or dt.datetime.now(ET)
    if (now.hour, now.minute) < (8, 15):
        return None
    if book is None:
        import locks
        book = locks.load()
    day = now.date().isoformat()
    if day in (book.get("days") or {}):
        # the card is saved: there must also be a ladder ticket for it (open
        # today, or already settled today)
        try:
            import ladder
            r = report_fn(book) if report_fn else ladder.report(book)
        except Exception:
            return None
        if r.get("today") or (r.get("last") or {}).get("day") == day:
            return None
        return (f"MISSING today's ladder ticket ({day}): the 8 AM card is saved but no ticket was built from it"
                " (no combination paying 2x-5x?); check ladder.choose.")
    return (f"MISSING today's 8 AM Locks card ({day}) at {now.strftime('%-I:%M %p')} ET -- the ladder ticket"
            " cannot be set until it is saved; check the board build.")


def _ufc_bands():
    """ufc_bands.json (tools/ufc_bands.py), or {}."""
    try:
        with open(os.path.join(ROOT, "ufc_bands.json")) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def ufc_next_line(today=None, ahead=7, picks_fn=None, rates=None):
    """The next UFC card in the coming `ahead` days with prices posted: each
    fight's price favourite and chance, close fights (under 60%) flagged."""
    if picks_fn is None:
        try:
            import picks as P
            picks_fn = P.ufc_picks
        except Exception:
            return None
    today = today or dt.date.today()
    for i in range(0, ahead + 1):
        day = (today + dt.timedelta(days=i)).strftime("%Y%m%d")
        try:
            r = picks_fn(day)
        except Exception:
            r = None
        if r:
            fights = sorted(r.items(), key=lambda kv: -(kv[1].get("conf") or 0))
            close = sum((v.get("conf") or 0) < 0.60 for _, v in fights)
            B = _ufc_bands()
            band = lambda c: "50-60" if c < 60 else "60-70" if c < 70 else "70-80" if c < 80 else "80-100"
            used = sorted({band(100 * (v.get("conf") or 0)) for _, v in fights} & set(B), key=lambda k: -int(k.split("-")[0]))
            rec = ("; favourites since 2021 by band: " + ", ".join(
                f"{k}% won {round(100 * B[k]['won'] / B[k]['n'])}% ({B[k]['roi']:+g}% a bet)" for k in used)) if used else ""
            if rates is None:
                try:
                    import ufc_model
                    rates = ufc_model.distance_rates(load("ufc_history.json", {}))
                except Exception:
                    rates = {}
            lean = {}
            if rates:
                import ufc_model
                for k, _ in fights:
                    if isinstance(k, (tuple, list)) and len(k) == 2:
                        lean[tuple(k)] = ufc_model.distance_lean(k[0], k[1], rates)
            dl = [f"{k[0]} v {k[1]}" for k, x in lean.items() if x == "distance"]
            fl = [f"{k[0]} v {k[1]}" for k, x in lean.items() if x == "finish"]
            how = ((" Likely to go the distance (both usually do; such fights went 63-78%): " + ", ".join(dl) + ".") if dl else "") \
                + ((" Likely to end early (both usually finish or get finished; such fights went the distance 31-32%): "
                    + ", ".join(fl) + ".") if fl else "")
            return (f"Next UFC card {day[:4]}-{day[4:6]}-{day[6:]} ({len(fights)} fights priced, {close} close): "
                    + "; ".join(f"{v['pick']} {round(100 * (v.get('conf') or 0))}%" + (" (close)" if (v.get("conf") or 0) < 0.60 else "")
                                for _, v in fights) + rec + "." + how)
    return None


def prop_fair_line():
    """Props won against the book's fair chance and our capped one, by band."""
    try:
        import props_ledger
        B = props_ledger.fair_bands()
    except Exception:
        return None
    if not B:
        return None
    pc = lambda x: f"{round(100 * x[0] / x[1])}%" if x[1] else "-"
    return "Props by the book's fair chance (won, by half; fair / our stated): " + "; ".join(
        f"{b['band']} {pc(b['halves'][0])}, {pc(b['halves'][1])} ({round(b['halves'][1][2] or 0)}% / {round(b['halves'][1][3] or 0)}%)"
        for b in B) + "."


def form_line(min_n=100, gap=5):
    """Bet types running cold over the last 7 pool days (locks.pool_form):
    5+ points under their stated chance on 100+ legs, one line or None.
    Information for the hourly report, never a pick rule."""
    try:
        import locks
        F = locks.pool_form()
    except Exception:
        return None
    cold = [f for f in F if f["n"] >= min_n and 100 * f["won"] / f["n"] <= f["said"] - gap]
    if not cold:
        return None
    cold.sort(key=lambda f: 100 * f["won"] / f["n"] - f["said"])
    try:
        C = locks.cold_check()
    except Exception:
        C = {}
    c, r = C.get("cold") or [0, 0, None], C.get("rest") or [0, 0, None]
    tail = (f" Walk-forward: legs of a type running cold won {100 * c[0] / c[1]:.1f}% the next day vs {100 * r[0] / r[1]:.1f}%"
            f" for the rest ({c[1]} and {r[1]} legs), so a cold week is noise, not a signal." if c[1] and r[1] else "")
    return "Running cold (last 7 days, all saved lines at 70-95%): " + "; ".join(
        f"{f['league'].upper()} {f['t']} {f['won']}/{f['n']} ({round(100 * f['won'] / f['n'])}% vs {round(f['said'])}%)" for f in cold) + "." + tail


_PERIODS = {"nba": (4, 12), "wnba": (4, 10), "ncaab": (2, 20), "nfl": (4, 15), "ncaaf": (4, 15), "nhl": (3, 20)}


def _elapsed(live, n, mins):
    """Minutes played from a live clock like "9:23 - 2nd", or None."""
    import re
    c = re.search(r"(\d+):(\d+)\s*-\s*(\d)", live)
    s = re.match(r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d)", live)
    e = re.search(r"End of (\d)", live, re.I)
    if c:
        return (int(c.group(3)) - 1) * mins + (mins - (int(c.group(1)) + int(c.group(2)) / 60))
    if s:
        return (int(s.group(2)) - 1) * mins + (mins - float(s.group(1)) / 60)
    if e:
        return int(e.group(1)) * mins
    if re.search(r"half", live, re.I):
        return n * mins / 2
    return None


def prop_pace(L):
    """A live "N+" prop's pace: "on pace for 14 (8 so far), behind the pace
    it needs" -- None before 25% of the game or when it cannot be read."""
    import re
    F = _PERIODS.get(L.get("league") or "")
    need = re.match(r"^\s*(\d+(?:\.\d+)?)\+\s*$", str(L.get("line") or ""))
    if not (F and need and L.get("live") and L.get("so_far") is not None):
        return None
    v, target = float(L["so_far"]), float(need.group(1))
    if v >= target:
        return None
    el = _elapsed(str(L["live"]), *F)
    if not el or el < 0.25 * F[0] * F[1]:
        return None
    pace = v / el * F[0] * F[1]
    return f"on pace for {round(pace)}, " + ("on track" if pace >= target else "behind the pace it needs")


def pace_text(L):
    """The board's paceNote in words for a live game or team total: "on pace
    for 240, on track" / "already over" / "too early to project"; None when
    it cannot be read (props, unknown clock or league)."""
    import re
    lab, live, sc = str(L.get("label") or ""), str(L.get("live") or ""), str(L.get("live_score") or "")
    F = _PERIODS.get(L.get("league") or "")
    if not (F and live and sc):
        return None
    m, team = re.match(r"^(Over|Under)\s+([\d.]+)", lab, re.I), None
    if m:
        side, line = m.group(1).lower(), float(m.group(2))
        pts = [int(x) for x in re.findall(r"-?\d+(?=\s*(?:-|$))", sc)]
        if len(pts) < 2:
            return None
        total = pts[-2] + pts[-1]
    else:
        t = re.match(r"^(.+?)\s+(over|under)\s+([\d.]+)", lab, re.I)
        if not t:
            return None
        team, side, line = t.group(1), t.group(2).lower(), float(t.group(3))
        part = next((x for x in re.split(r"\s+-\s+", sc) if x.startswith(team)), None)
        v = re.search(r"(-?\d+)\s*$", part or "")
        if not v:
            return None
        total = int(v.group(1))
    if total > line:
        return f"already over ({total}, line {line:g})" if side == "over" else f"gone over ({total}, line {line:g})"
    n, mins = F
    c = re.search(r"(\d+):(\d+)\s*-\s*(\d)", live)
    s = re.match(r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d)", live)
    e = re.search(r"End of (\d)", live, re.I)
    if c:
        el = (int(c.group(3)) - 1) * mins + (mins - (int(c.group(1)) + int(c.group(2)) / 60))
    elif s:
        el = (int(s.group(2)) - 1) * mins + (mins - float(s.group(1)) / 60)
    elif e:
        el = int(e.group(1)) * mins
    elif re.search(r"half", live, re.I):
        el = n * mins / 2
    else:
        return None
    if el <= 0:
        return None
    if el < 0.25 * n * mins:
        return f"{total} so far, line {line:g}, too early to project"
    pace = total / el * n * mins
    good = pace > line if side == "over" else pace < line
    # what is left to happen: points an over still needs, or room an under has
    left = (f", needs {int(line) + 1 - total} more" if side == "over"
            else f", room for {math.ceil(line) - 1 - total} more")
    return f"on pace for {round(pace)} ({total} so far, line {line:g}{left}), " + ("on track" if good else "behind the pace it needs")


def leg_text(L, mark=None):
    """One ladder leg for the review: what, which game, and where it stands --
    "Over 214.5 points (WAS at ATL, 7:00 PM; live Q2 5:12, ATL 55 - WAS 50)"."""
    mark = mark or {"won": "won", "lost": "LOST", "void": "void", "push": "void"}
    st = L.get("status")
    where = [str(L["match"])] if L.get("match") else []
    if st in (None, "open"):
        if L.get("live"):
            bit = f"live {L['live']}" + (f", {L['live_score']}" if L.get("live_score") else "")
            p = pace_text(L)
            if p:
                bit += f", {p}"
            if L.get("so_far") is not None:
                v = L["so_far"]
                bit += f", {int(v) if float(v).is_integer() else v} so far"
                import re
                need = re.match(r"^\s*(\d+(?:\.\d+)?)\+\s*$", str(L.get("line") or ""))
                if need:                    # "2+": reached, or how many more
                    left = float(need.group(1)) - float(v)
                    bit += ", line reached" if left <= 0 else f", needs {int(left) if left.is_integer() else left} more"
                pp = prop_pace(L)
                if pp:
                    bit += f", {pp}"
            where.append(bit)
        else:
            where.append((f"{L['tip']}, " if L.get("tip") else "") + "open")
    else:
        where.append(mark.get(st, st))
    pr = L.get("prop_rec")
    if pr and pr.get("n") and st in (None, "open"):      # a prop leg's own history at a similar chance
        where.append(f"props like it {pr['won']}/{pr['n']}")
    return f"{L['label']} ({'; '.join(where)})"


def now_text(legs):
    """Where the open ticket stands once a leg has settled: "4 of 5 won; the
    ticket now rests on 1 leg, 76% on its stated chance" (stated chances
    taken as independent; a live game's state is not priced in)."""
    done = [L for L in legs if L.get("status") in ("won", "lost", "void", "push")]
    if not done:
        return ""
    won = sum(L.get("status") == "won" for L in done)
    if any(L.get("status") == "lost" for L in done):
        return f"; {won} of {len(legs)} won, a leg lost -- the ticket is lost"
    left = [L for L in legs if L.get("status") in (None, "open")]
    if not left:
        return f"; {won} of {len(legs)} won"
    p = 1.0
    for L in left:
        p *= L.get("p") or 0
    return (f"; {won} of {len(legs)} won, the ticket now rests on {len(left)} leg{'s' if len(left) > 1 else ''},"
            f" {100 * p:.0f}% on {'their' if len(left) > 1 else 'its'} stated chance before play")


def rule_text(day=None):
    """How the next ladder ticket is built, from ladder.py's constants."""
    import ladder
    day = day or dt.date.today().isoformat()
    if day >= ladder.FLEX_FROM:
        return (f"the top Locks paying {ladder.PAY_MIN:g}x-{ladder.PAY_MAX:g}x, leg count {ladder.FLEX_MIN}-{ladder.FLEX_MAX}"
                f" by the best chance of reaching ${ladder.TARGET:,.0f}")
    return f"the top {ladder.FIXED_LEGS} Locks"


def runs_line(book=None):
    """Every ladder run so far in one line: start, days, peak, and the leg
    that ended it."""
    try:
        import ladder
        H = ladder.report(book).get("history") or []
    except Exception:
        return None
    if not H:
        return None
    return "Ladder runs: " + "; ".join(
        f"{i + 1}) {h['start']}, {h['days']} day{'s' if h['days'] != 1 else ''}, peak ${h['peak']:.2f}"
        + (f", lost on {', '.join(h.get('lost_on') or [])}" if h.get("status") == "lost" else f", {h.get('status')}")
        for i, h in enumerate(H)) + "."


def ladder_line(book=None):
    """One line on the $1 -> $10k ladder (ladder.py), or None before it starts."""
    try:
        import ladder
        r = ladder.report(book)
    except Exception:
        return None
    if not r.get("runs"):
        return None
    t = r.get("today")
    if r.get("ended"):
        e = r["ended"]
        return (f"Ladder: run {r['runs']} ended (peak ${e['peak']:.2f}, lost on {', '.join(e['lost_on']) or 'a leg'});"
                f" the next ticket starts again at $1 with the 8 AM card ({rule_text()}); best ever ${r['best']:.2f}.")
    mark = {"won": "won", "lost": "LOST", "void": "void", "push": "void"}
    legs = ("; legs: " + ", ".join(leg_text(L, mark) for L in t["legs"])) if t else ""
    legs += now_text(t["legs"]) if t else ""
    return (f"Ladder: run {r['runs']}, bank ${r['bank']:.2f}, {r['streak']} win(s) in a row, best ${r['best']:.2f}"
            + (f"; today stakes ${t['stake']:.2f} at {t['pays']:.2f}x ({100 * t['prob']:.0f}% est.)" if t else "")
            + (f", the best-chance 2x-5x combination ({len(t['legs'])} legs) against {100 * t['vs_top4']['prob']:.0f}%"
               f" at {t['vs_top4']['pays']:.2f}x for the plain top 4" if t and t.get("vs_top4") else "")
            + f"; {r['wins_needed']} wins to ${r['target']:,.0f}" + legs + ".")


BIG_MB = 60     # GitHub refuses any file over 100 MB, and every build then fails


def big_files(root=None, limit_mb=BIG_MB):
    """[(name, MB)] for the bot's data files grown past limit_mb: a warning
    well before the push limit (ledger.json reached 100.09 MB on 2026-10-30
    and stopped the board)."""
    root = root or os.path.join(HERE, "..")
    out = []
    for name in sorted(os.listdir(root)):
        if name.endswith(".json"):
            mb = os.path.getsize(os.path.join(root, name)) / 1e6
            if mb > limit_mb:
                out.append((name, round(mb, 1)))
    return out


def stuck(ledger, props, locks, lottery, today):
    """Records still open a week after their game: by then every grader has
    settled or voided them, so anything left means grading broke somewhere
    (2026-10-18: a UFC prop waited on a result line ESPN never posted)."""
    def old(d, n=None):
        try:
            return (today - dt.date.fromisoformat(str(d)[:10])).days >= (n or STUCK_DAYS)
        except ValueError:
            return False
    out = [("picks", k) for k, e in ledger.items()
           if e.get("status") == "open" and old(e.get("played") or e.get("date") or "", PICK_STUCK_DAYS)]
    # a prop reopened for one more try counts from its retry (date_retry)
    out += [("props", k) for k, e in props.items() if e.get("status") == "open"
            and old(e.get("date_retry") or e.get("date") or "")]
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
        # both date halves, so a short slump reads apart from a split that is
        # short throughout
        ds = sorted({r.get("date") for r in rs if r.get("date")})
        halves = None
        if len(ds) >= 2:
            mid = ds[len(ds) // 2]
            halves = []
            for h in (False, True):
                X = [r for r in rs if r.get("date") and (r["date"] >= mid) == h]
                if X:
                    halves.append([sum(won_of(r) for r in X), len(X), round(100 * sum(p_of(r) for r in X) / len(X), 1)])
        out.append(dict(name=name, n=n, hit=round(100 * hit, 1), said=round(100 * said, 1),
                        flag=bool(flag), halves=halves))

    tennis = [e for e in graded if e.get("league") in ("atp", "wta")]
    for src, f in (("Kalshi-priced", lambda e: "Kalshi" in (e.get("why") or "")),
                   ("no market", lambda e: "no market" in (e.get("why") or ""))):
        line(f"tennis {src}", [e for e in tennis if f(e)], lambda e: (e.get("conf") or 0) / 100,
             lambda e: e["status"] == "won")
    # only markets still offered: a market already taken off (soccer shots)
    # is a closed case, and a permanent alarm for it would hide new ones
    import props_ledger as _pl
    # props stated before the ceiling (props_ledger.CAP_SINCE) are a closed
    # case too: the alarm tests the rule now in force, not the one replaced
    pg = [e for e in props.values() if isinstance(e, dict) and e.get("status") in ("won", "lost")
          and _pl.offered(e.get("league"), e.get("market") or "")
          and (e.get("date") or "") >= _pl.CAP_SINCE]
    for key in sorted({(e["league"], e["market"]) for e in pg}):
        line(f"props {key[0]} {key[1]}", [e for e in pg if (e["league"], e["market"]) == key],
             lambda e: e.get("p"), lambda e: e["status"] == "won")
    lg = [v for v in (locks.get("legs") or {}).values() if v.get("status") in ("won", "lost")
          and not (v.get("kind") == "prop" and (v.get("date") or "") < _pl.CAP_SINCE)]
    kinds = {}
    for v in lg:
        t = (v.get("spec") or {}).get("t") or ""
        k = "prop" if v.get("kind") == "prop" else "under" if "under" in t else "over" if "over" in t else "side"
        kinds.setdefault(f'locks {v.get("league")} {k}', []).append(v)
    for k, vs in sorted(kinds.items()):
        line(k, vs, lambda v: v.get("p"), lambda v: v["status"] == "won")
    # every other product with a stated (or sportsbook-fair) chance, so no
    # card can drift unseen: Safe Locks by league and kind, the daily calls,
    # Prop Locks, value bets and the Kalshi maker bids that would have filled
    def _load(name):
        try:
            with open(os.path.join(HERE, "..", name)) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}
    safe = {}
    for v in (_load("safe_locks.json").get("legs") or {}).values():
        if v.get("status") not in ("won", "lost"):
            continue
        if v.get("kind") == "prop" and (v.get("date") or "") < _pl.CAP_SINCE:
            continue
        t = (v.get("spec") or {}).get("t") or ""
        k = "prop" if v.get("kind") == "prop" else "under" if "under" in t else "over" if "over" in t else "side"
        safe.setdefault(f'safe locks {v.get("league")} {k}', []).append(v)
    for k, vs in sorted(safe.items()):
        line(k, vs, lambda v: v.get("p"), lambda v: v["status"] == "won")
    line("daily calls", [e for e in graded if e.get("call") and not e.get("call_pulled")],
         lambda e: (e.get("call_conf") or e.get("conf") or 0) / 100, lambda e: e["status"] == "won")
    line("prop locks", [e for e in props.values() if isinstance(e, dict) and e.get("prop_lock")
                        and e.get("status") in ("won", "lost")],
         lambda e: e.get("p"), lambda e: e["status"] == "won")
    line("value bets", [f for f in (_load("value.json").get("finds") or {}).values()
                        if f.get("kind") == "value" and f.get("status") in ("won", "lost")],
         lambda f: f.get("fair"), lambda f: f["status"] == "won")
    line("kalshi maker bids (filled)", [b for b in (_load("maker.json").get("bids") or {}).values()
                                         if b.get("status") == "graded" and b.get("fill") in ("strict", "queue")],
         lambda b: b.get("fair"), lambda b: bool(b.get("won")))
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
    graded = [e for e in ledger.values() if e.get("status") in ("won", "lost") and record_priced(e)]
    todays = [e for e in graded if day_of(e) == day]
    leagues = defaultdict(list)
    for e in todays:
        leagues[e["league"]].append(e)
    import sys
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from ledger import loss_tags, day_rarity
    lost_e = sorted((e for e in todays if e["status"] == "lost"), key=lambda e: e.get("settled") or "")
    losses = [dict(league=e["league"], pick=e["pick"] + (" or draw" if e.get("dc") else ""), said=e.get("conf"), price=e.get("price"),
                   match=e.get("matchup"), score=e.get("scores") or {},
                   against_market=e.get("market_agrees") is False, why=e.get("diagnosis") or "",
                   tags=loss_tags(e), like=like_record(ledger, e))
              for e in lost_e]
    # the whole board as one ticket: clean, or broken by its first loss
    n_open = sum(1 for e in ledger.values() if record_priced(e) and e.get("status") == "open"
                 and (e.get("date") or "") == day)
    sweep = dict(won=sum(e["status"] == "won" for e in todays), lost=len(lost_e), open=n_open,
                 broke_on=(f'{lost_e[0]["league"]} {lost_e[0]["pick"]}{" or draw" if lost_e[0].get("dc") else ""} at {lost_e[0].get("conf")}%'
                           if lost_e else None))
    sweep.update(day_rarity(todays))     # losses expected so far, how unusual
    sweep["coin_flips"] = sum((e.get("conf") or 0) < 60 for e in lost_e)   # losses called under 60%
    # the last 14 days, to tell a bad night from a leak
    since = (dt.date.fromisoformat(day) - dt.timedelta(days=14)).isoformat()
    recent = [e for e in graded if since <= day_of(e) <= day and not exhibition(e) and record_priced(e)]
    by_lg = defaultdict(list)
    for e in recent:
        by_lg[e["league"]].append(e)
    leaks = []
    for lg, rs in by_lg.items():
        s = summarize(rs)
        # a leak: 20+ calls hitting 8+ points under what they claimed
        if s["n"] >= 20 and s["hit"] < s["said"] - 8:
            leaks.append(dict(league=lg, **s))
    # why the last 14 days' losses happened, counted (ledger.loss_tags)
    reasons = defaultdict(int)
    for e in recent:
        if e["status"] == "lost":
            for t in loss_tags(e):
                reasons[t.split(" (")[0]] += 1
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
    from ledger import _strong
    strong = [e for e in todays if _strong(e)]
    return dict(day=day, picks=summarize(todays), strong=summarize(strong), clv=clv([e for e in todays if e.get("first_price")]),
                picks_by_league={k: summarize(v) for k, v in leagues.items()},
                losses=losses, sweep=sweep, loss_reasons_14d=dict(sorted(reasons.items(), key=lambda x: -x[1])),
                leaks_14d=leaks, vs_market_14d=vs_mkt,
                locks=lk_view, safe_locks=sk_view, lottery=lt_view, props=pr_view)


def like_record(book, e, band=5):
    """ledger.like_record: graded picks like a lost one (same league, same
    bet, within `band` points), or None under 10."""
    import ledger
    return ledger.like_record(book, e, band)


def loss_line(L):
    """One lost pick and why, for the review and the hourly report."""
    sc = L.get("score") or {}
    score = " - ".join(f"{k} {v}" for k, v in sc.items()) if sc else ""
    return (f"- LOST {L['league']} {L['pick']} at {L['said']}%" + (f" ({L['price']})" if L.get("price") else "")
            + (f", {score}" if score else "") + (" (against the market)" if L.get("against_market") else "")
            + f": {L.get('why') or ''}" + (lambda t: f" [{', '.join(t)}]" if t else "")(
                [t for t in L.get("tags") or [] if t not in (L.get("why") or "")])
            + (lambda k: f"; picks like it: {k['won']} of {k['n']} ({round(100 * k['won'] / k['n'])}% vs {k['said']}% stated)"
               if k else "")(L.get("like")))


def yesterday_line(y):
    """Yesterday's board in one line, with the losses its chances expected."""
    ys = y.get("sweep") or {}
    return (f"Yesterday ({y['day']}): board {ys.get('won', 0)}-{ys.get('lost', 0)}"
            + (f", sweep broken by {ys['broke_on']}" if ys.get("broke_on") else ", clean sweep" if ys.get("won") else "")
            + (f"; {ys['expected_losses']:g} losses expected, {ys.get('lost', 0)} came in"
               f" ({pct_text(ys['as_bad_pct'])} chance of that many or more)"
               if ys.get("expected_losses") is not None and ys.get("lost") else "")
            + (f" -- an unusually good day: only {pct_text(ys['as_good_pct'])} of days go this well"
               if ys.get("as_good_pct") is not None and ys["as_good_pct"] < 10 and (ys.get("won") or 0) + (ys.get("lost") or 0) >= 10
               else "") + ".")


def pool_props(league, props=None):
    """Every saved prop line in a league, graded: (won, n, stated%) or None.
    The context for a short Locks prop split: Locks take a handful of these,
    so a pool on par says the split is a small-sample slump, a pool short
    says the props themselves are off."""
    if props is None:
        props = load("props.json", {})
    R = [v for v in props.values() if isinstance(v, dict) and v.get("league") == league
         and v.get("status") in ("won", "lost") and v.get("p") is not None]
    if not R:
        return None
    return (sum(v["status"] == "won" for v in R), len(R), round(100 * sum(v["p"] for v in R) / len(R)))


def trailing_line(a, props=None):
    """A trailing split, with its two date halves when known, and for a
    Locks prop split the record of every saved prop line in that league."""
    s = f"TRAILING {a['name']}: {a['hit']}% hit vs {a['said']}% stated on {a['n']}"
    H = a.get("halves") or []
    if len(H) == 2 and all(h[1] for h in H):
        both = all(100 * h[0] / h[1] < h[2] for h in H)
        s += (f" (by half {H[0][0]}/{H[0][1]} then {H[1][0]}/{H[1][1]}; "
              + ("short in both halves" if both else "short in one half only -- a slump, not yet a pattern") + ")")
    bits = str(a.get("name") or "").split()
    if len(bits) == 3 and bits[0] == "locks" and bits[2] == "prop":
        P = pool_props(bits[1], props)
        if P and P[1] >= 100:
            w, n, said = P
            par = 100 * w / n >= said - 2
            s += (f"; all {n} saved {bits[1].upper()} prop lines {w}/{n} ({round(100 * w / n)}% vs {said}% stated) -- "
                  + ("the pool is on par, so this looks like a small-sample slump on the few Locks take"
                     if par else "the pool is short too"))
    return s


def pct_text(x):
    """A small percentage in words: 'under 0.1%' rather than a rounded 0%."""
    return "under 0.1%" if x is not None and x < 0.1 else f"{x:g}%"


def sweep_line(sw):
    """Today's board as one ticket: record, clean or the pick that broke it,
    and once broken how unusual that many losses is from the chances."""
    if not (sw.get("won") or sw.get("lost") or sw.get("open")):
        return None
    return (f"Board sweep: {sw['won']}-{sw['lost']}, {sw['open']} open -- "
            + (f"broken (first loss: {sw['broke_on']})" if sw.get("lost") else "still clean")
            + (f"; {sw['expected_losses']:g} losses expected from the settled picks' chances,"
               f" so {sw['lost']} or more by now had a {pct_text(sw['as_bad_pct'])} chance"
               if sw.get("lost") and sw.get("expected_losses") is not None else "")
            + (f" -- an unusually good day: only {pct_text(sw['as_good_pct'])} of days go this well this far in"
               if sw.get("as_good_pct") is not None and sw["as_good_pct"] < 10 and sw.get("lost") is not None
               and (sw.get("won") or 0) + sw["lost"] >= 10 else "")
            + (f"; {sw['coin_flips']} of the {sw['lost']} were near coin flips (called under 60%),"
               f" {sw['lost'] - sw['coin_flips']} were real misses"
               if sw.get("lost") and sw.get("coin_flips") is not None else "")
            + ("; losses by league: " + ", ".join(f"{k} {v} ({(sw.get('expected_by_league') or {}).get(k, 0):g} expected)"
                                                  for k, v in sw["lost_by_league"].items())
               if sw.get("lost") and sw.get("lost_by_league") else "") + ".")


def words(r, fit):
    p = r["picks"]
    out = [f"# Review {r['day']}", ""]
    if p.get("n"):
        out.append(f"Picks {p['won']}-{p['lost']} ({p['hit']}% vs {p['said']}% claimed"
                   + (f", ROI {p['roi']:+}%" if p.get("roi") is not None else "") + ").")
    else:
        out.append("No picks settled yet.")
    if r.get("ladder"):
        out.append(r["ladder"])
    if r.get("runs"):
        out.append(r["runs"])
    if r.get("cautions"):
        out.append(r["cautions"])
    if r.get("cold"):
        out.append(r["cold"])
    if r.get("prereg"):
        out.append(r["prereg"])
    if r.get("prop_fair"):
        out.append(r["prop_fair"])
    if r.get("dc_side"):
        out.append(r["dc_side"])
    if r.get("ufc"):
        out.append(r["ufc"])
    if r.get("ufc_next"):
        out.append(r["ufc_next"])
    if r.get("card_missing"):
        out.append(r["card_missing"])
    for name, mb in r.get("big_files") or []:
        out.append(f"BIG FILE {name} is {mb} MB -- GitHub refuses files over 100 MB and the board stops; trim it")
    st = r.get("stuck") or []
    if st:
        out.append(f"STUCK {len(st)} record(s) open a week after their game -- grading is broken: "
                   + "; ".join(f"{a} {b}" for a, b in st[:5]))
    for a in [a for a in (r.get("audit") or []) if a["flag"]]:
        out.append(trailing_line(a))
    sc = r.get("strong") or {}
    if sc.get("n"):
        out.append(f"Strong calls {sc['won']}-{sc['lost']} ({sc['hit']}% vs {sc['said']}% claimed).")
    c = r.get("clv") or {}
    if c.get("n"):
        out.append(f"Closing line value: {c['avg']:+} points on {c['n']} picks; beat the close on {c['beat']}%.")
    sl = sweep_line(r.get("sweep") or {})
    if sl:
        out.append(sl)
    for L in r["losses"]:
        out.append(loss_line(L))
    rs = r.get("loss_reasons_14d") or {}
    if rs:
        out.append("Why picks lost (14 days): " + ", ".join(f"{k} {v}" for k, v in rs.items()) + ".")
    y = r.get("yesterday") or {}
    if y.get("day"):
        out.append(yesterday_line(y))
        for L in y.get("losses") or []:
            out.append(loss_line(L))
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
              and not exhibition(e) and record_priced(e)]
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
    log[today.isoformat()]["big_files"] = big_files()
    log[today.isoformat()]["ladder"] = ladder_line()
    log[today.isoformat()]["runs"] = runs_line()
    log[today.isoformat()]["cautions"] = caution_line()
    log[today.isoformat()]["cold"] = form_line()
    log[today.isoformat()]["prereg"] = prereg_line()
    log[today.isoformat()]["prop_fair"] = prop_fair_line()
    log[today.isoformat()]["dc_side"] = dc_side_line(ledger)
    log[today.isoformat()]["card_missing"] = card_check()
    log[today.isoformat()]["ufc"] = ufc_line(today)
    log[today.isoformat()]["ufc_next"] = ufc_next_line(today)
    yk = (today - dt.timedelta(days=1)).isoformat()
    log[today.isoformat()]["yesterday"] = dict(day=yk, sweep=log[yk].get("sweep"), losses=log[yk].get("losses"))
    with open(log_path, "w") as fh:
        json.dump(log, fh, indent=1, sort_keys=True)
    latest = max(k for k, v in log.items() if v["picks"].get("n") or k == today.isoformat())
    with open(os.path.join(OUT, "latest.md"), "w") as fh:
        fh.write(words(log[latest], detail))
    print(words(log[latest], detail))


if __name__ == "__main__":
    main()
