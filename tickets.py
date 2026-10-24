"""Whole-ticket optimizer: the likeliest ticket that pays what you asked.

For a payout target -- total return 2x, 3x, 5x on the stake, profit boost
applied if you have one -- find the combination of legs with the highest
estimated chance that every leg wins, subject to

    * every leg at or above a declared leg standard (its estimated chance),
    * at most one leg per game (legs from one game are not independent),
    * at most MAX_LEGS legs, and at most KIND_CAP legs of one league + kind
      (same-day college unders missed together 2.6x more than independent
      legs would -- see locks.MAX_SAME),
    * the combined decimal price reaching the target.

Nothing is filled to a quota: a 2x target is usually met by two or three
legs, and taking more only lowers the chance. If no combination reaches the
target at the standard, the answer is "unavailable" -- never a quietly
weaker leg.

Every game keeps all its lines that are not dominated (another line of the
same game both likelier AND paying more), so a game's likeliest line does
not crowd out a slightly longer one that finishes the payout far more
cheaply than adding a whole extra leg.

Search: exact branch-and-bound. The chance can only fall as legs are added,
so a partial ticket already less likely than the best complete one is cut;
a partial ticket that cannot reach the target even with the longest prices
left is cut too. A node budget guards the worst case; if it is ever hit the
result says exact=False (tests compare it with brute-force enumeration).

Chances multiply as if games were independent. tools/whole_ticket.py checks
that against settled history (cash rate vs the product of chances).
"""
import math

MAX_LEGS = 6
POOL_DEC = (1.02, 6.0)        # FanDuel prices considered: -5000 .. +500
POOL_BAND = (0.55, 0.995)     # estimated chances considered
BOOST_CHOICES = (0.0, 0.25, 0.50, 1.00)
KIND_CAP = 3
NODE_BUDGET = 400_000
EPS = 1e-12


def needed_price(target, boost=0.0):
    """Decimal price the legs must multiply to for a total return of
    `target` with a profit boost `boost` (0.25 = +25% on winnings)."""
    return 1 + (target - 1) / (1 + boost)


def total_return(dec, boost=0.0):
    return 1 + (dec - 1) * (1 + boost)


def kind(L):
    t = (L.get("spec") or {}).get("t") or ""
    k = ("prop" if L.get("kind") == "prop" else "under" if "under" in t
         else "over" if "over" in t else "side")
    return (L.get("league"), k)


def pareto(legs):
    """Per game, the lines not dominated by another line of the same game."""
    by = {}
    for L in legs:
        by.setdefault(L["gid"], []).append(L)
    out = {}
    for g, ls in by.items():
        keep = []
        for L in ls:
            dom = any(o is not L and o["p"] >= L["p"] and o["dec"] >= L["dec"]
                      and (o["p"] > L["p"] or o["dec"] > L["dec"]) for o in ls)
            if not dom:
                keep.append(L)
        # equal (p, dec) duplicates: keep one
        seen, uniq = set(), []
        for L in sorted(keep, key=lambda x: (-x["p"], -x["dec"], str(x.get("label")))):
            k = (round(L["p"], 9), round(L["dec"], 9))
            if k not in seen:
                seen.add(k)
                uniq.append(L)
        out[g] = uniq
    return out


def optimize(legs, target, min_p, max_legs=MAX_LEGS, boost=0.0, kind_cap=KIND_CAP,
             budget=NODE_BUDGET):
    """The likeliest qualifying ticket reaching `target` total return.

    Returns dict(legs, prob, dec, total, exact, nodes) or dict(legs=None, ...)
    when none exists. `legs` need gid, p (estimated chance), dec (decimal
    price) and optionally league/kind/spec for the kind cap."""
    need = needed_price(target, boost)
    pool = [L for L in legs if L.get("p") is not None and L.get("dec")
            and L["p"] >= min_p - EPS and L["dec"] > 1.0]
    games = pareto(pool)
    # games ordered by their best "price per unit of chance", so good tickets
    # are found early and the bound bites
    order = sorted(games, key=lambda g: -max(math.log(L["dec"]) / max(-math.log(L["p"]), 1e-9)
                                             for L in games[g]))
    opts = [sorted(games[g], key=lambda L: -L["p"]) for g in order]
    logneed = math.log(need)
    # longest price still available from game i onward, per number of slots
    maxlog = [max(math.log(L["dec"]) for L in o) for o in opts]
    best = dict(legs=None, logp=-math.inf, logd=-math.inf)
    nodes = 0
    exhausted = False

    # suff[i][k]: the k longest prices among games i.. (log), summed
    suff = []
    for i in range(len(opts) + 1):
        c, acc = [0.0], 0.0
        for v in sorted(maxlog[i:], reverse=True):
            acc += v
            c.append(acc)
        suff.append(c)

    # sufp[i][k]: the k best chances among games i.. (log), summed
    maxlp = [max(math.log(L["p"]) for L in o) for o in opts]
    sufp = []
    for i in range(len(opts) + 1):
        c, acc = [0.0], 0.0
        for v in sorted(maxlp[i:], reverse=True):
            acc += v
            c.append(acc)
        sufp.append(c)

    # U[i][k][b]: the best log-chance games i.. can add with at most k legs
    # whose log-prices, each rounded UP to RES, sum to at least b buckets.
    # Rounding up makes it a valid upper bound for every ticket that truly
    # reaches the price, and tight to within one bucket.
    NB = max(1, math.ceil(logneed / RES - 1e-9))
    NEG = -math.inf
    n = len(opts)
    U = [None] * (n + 1)
    U[n] = [[0.0] + [NEG] * NB for _ in range(max_legs + 1)]
    for i in range(n - 1, -1, -1):
        nxt = U[i + 1]
        cur = [row[:] for row in nxt]                    # game i sits out
        steps = [(math.log(L["p"]), math.ceil(math.log(L["dec"]) / RES - 1e-9)) for L in opts[i]]
        for k in range(1, max_legs + 1):
            row, prev = cur[k], nxt[k - 1]
            for b in range(NB + 1):
                for lp, db in steps:
                    v = prev[max(0, b - db)]
                    if v != NEG and v + lp > row[b]:
                        row[b] = v + lp
        U[i] = cur

    def bound(i, slots, short):
        """Upper bound on the log-chance still to come. None if unreachable."""
        b = max(0, math.ceil(short / RES - 1e-9))
        v = U[i][max(0, min(slots, max_legs))][min(b, NB)]
        return None if v == NEG else v

    def reach(i, slots):
        """Largest log-price obtainable from games i.. with `slots` legs."""
        c = suff[i]
        return c[min(max(slots, 0), len(c) - 1)]

    def walk(i, chosen, logp, logd, kinds):
        nonlocal nodes, exhausted
        if exhausted:
            return
        nodes += 1
        if nodes > budget:
            exhausted = True
            return
        if logd >= logneed - EPS:
            if (logp > best["logp"] + EPS
                    or (abs(logp - best["logp"]) <= EPS and logd > best["logd"])):
                best.update(legs=list(chosen), logp=logp, logd=logd)
            return                       # another leg only lowers the chance
        if i >= len(opts) or len(chosen) >= max_legs:
            return
        if logp < best["logp"] - EPS:
            return
        b = bound(i, max_legs - len(chosen), logneed - logd)
        if b is None or logp + b < best["logp"] - EPS:
            return
        for L in opts[i]:
            lp = logp + math.log(L["p"])
            if lp < best["logp"] - EPS:
                break                    # options run likeliest first
            k = kind(L)
            if kinds.get(k, 0) >= kind_cap:
                continue
            kinds[k] = kinds.get(k, 0) + 1
            chosen.append(L)
            walk(i + 1, chosen, lp, logd + math.log(L["dec"]), kinds)
            chosen.pop()
            kinds[k] -= 1
        walk(i + 1, chosen, logp, logd, kinds)       # this game sits out

    seed = _dp_seed(opts, logneed, max_legs, kind_cap)
    if seed:
        best.update(legs=seed, logp=sum(math.log(L["p"]) for L in seed),
                    logd=sum(math.log(L["dec"]) for L in seed))
    walk(0, [], 0.0, 0.0, {})
    if best["legs"] is None:
        return dict(legs=None, exact=not exhausted, nodes=nodes, need=need)
    d = math.exp(best["logd"])
    return dict(legs=best["legs"], prob=math.exp(best["logp"]), dec=d,
                total=total_return(d, boost), exact=not exhausted, nodes=nodes, need=need)


RES = 0.002          # log-price bucket of the seeding program


def _dp_seed(opts, logneed, max_legs, kind_cap):
    """A good ticket to start the exact search from: dynamic programming over
    games, legs used and log-price rounded DOWN to RES (so every ticket it
    returns truly reaches the target), ignoring the kind cap. Only a starting
    bound -- the branch-and-bound still proves the optimum."""
    B = max(1, math.ceil(logneed / RES))
    NEG = -math.inf
    # dp[j][b] = (logp, back) after the games so far; b capped at B
    dp = [[NEG] * (B + 1) for _ in range(max_legs + 1)]
    dp[0][0] = 0.0
    back = []
    for o in opts:
        nd = [row[:] for row in dp]
        bk = {}
        steps = [(math.log(L["p"]), min(B, int(math.log(L["dec"]) / RES)), L) for L in o]
        for j in range(max_legs):
            row = dp[j]
            for b in range(B + 1):
                v = row[b]
                if v == NEG:
                    continue
                for lp, db, L in steps:
                    nb = min(B, b + db)
                    if v + lp > nd[j + 1][nb]:
                        nd[j + 1][nb] = v + lp
                        bk[(j + 1, nb)] = (j, b, L)
        back.append(bk)
        dp = nd
    j = max(range(max_legs + 1), key=lambda k: dp[k][B])
    if dp[j][B] == NEG:
        return None
    pick, b = [], B
    for bk in reversed(back):
        if (j, b) in bk:
            pj, pb, L = bk[(j, b)]
            # the entry is this game's only if it produced the value at (j, b)
            pick.append(L)
            j, b = pj, pb
    if j != 0:
        return None
    ks = {}
    for L in pick:
        ks[kind(L)] = ks.get(kind(L), 0) + 1
    if ks and max(ks.values()) > kind_cap:
        return None
    if sum(math.log(L["dec"]) for L in pick) < logneed - EPS:
        return None
    return pick


def ceiling(legs, min_p, max_legs=MAX_LEGS, boost=0.0, kind_cap=KIND_CAP):
    """The largest total return any qualifying ticket can reach (one leg per
    game, the longest qualifying line of each), for "unavailable" answers."""
    games = pareto([L for L in legs if L.get("p") is not None and L.get("dec")
                    and L["p"] >= min_p - EPS])
    longest = sorted((max(ls, key=lambda L: L["dec"]) for ls in games.values()),
                     key=lambda L: -L["dec"])
    pick, kinds = [], {}
    for L in longest:
        if len(pick) >= max_legs:
            break
        k = kind(L)
        if kinds.get(k, 0) >= kind_cap:
            continue
        kinds[k] = kinds.get(k, 0) + 1
        pick.append(L)
    d = math.prod(L["dec"] for L in pick) if pick else 1.0
    return dict(legs=pick, dec=d, total=total_return(d, boost))


# 10x and a 65% standard since 2026-10-22: at 75%+ a 10x ticket needs 8-9 legs
# (over MAX_LEGS); the best 10x tickets in both backtests cashed about 1 in 11.
TARGETS = (2.0, 3.0, 5.0, 10.0)
STANDARDS = (0.90, 0.85, 0.80, 0.75, 0.65)


def frontier(legs, targets=TARGETS, standards=STANDARDS,
             max_legs=MAX_LEGS, boost=0.0):
    """For every (target, standard): the optimal ticket, or why there is none
    and the most it could pay at that standard."""
    out = []
    for T in targets:
        for s in standards:
            r = optimize(legs, T, s, max_legs=max_legs, boost=boost)
            row = dict(target=T, standard=s, boost=boost, exact=r["exact"])
            if r["legs"]:
                row.update(legs=r["legs"], prob=r["prob"], dec=r["dec"], total=r["total"],
                           n=len(r["legs"]), ev=r["prob"] * r["total"] - 1)
            else:
                c = ceiling(legs, s, max_legs=max_legs, boost=boost)
                row.update(legs=None, ceiling=round(c["total"], 3), ceiling_n=len(c["legs"]))
            out.append(row)
    return out


# ------------------------------------------------------------- evidence
BANDS = ((0.70, 0.75), (0.75, 0.80), (0.80, 0.85), (0.85, 0.90), (0.90, 0.95), (0.95, 1.0))
METHOD_FROM = "2026-10-18"     # chances are the de-vigged price, unadjusted, from this date


def wilson(k, n, z=1.96):
    if not n:
        return None
    ph = k / n
    den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def _cluster_ci(rs, draws=1000, seed=3):
    """95% range of the hit rate, resampling whole games: one game's many
    alternate lines settle on one score and are not separate trials."""
    import random
    by = {}
    for r in rs:
        by.setdefault(r[3], []).append(r[1])
    g = list(by.values())
    rng = random.Random(seed)
    vals = []
    for _ in range(draws):
        smp = [rng.choice(g) for _ in g]
        n = sum(len(x) for x in smp)
        vals.append(100 * sum(sum(x) for x in smp) / n)
    vals.sort()
    return [round(vals[int(0.025 * draws)], 1), round(vals[int(0.975 * draws) - 1], 1)]


def _band_rows(rows):
    """rows: (p, won, date, game). Per band: legs, games, won, hit, said, 95%
    range (by game), dates and a verdict -- supported / thin / contradicted --
    never an adjustment. 'thin' under 30 games."""
    out = []
    for lo, hi in BANDS:
        rs = [r for r in rows if lo <= r[0] < hi]
        n = len(rs)
        if not n:
            out.append(dict(band=f"{int(100 * lo)}-{int(100 * hi)}%", n=0, games=0))
            continue
        k = sum(r[1] for r in rs)
        games = len({r[3] for r in rs})
        said = 100 * sum(r[0] for r in rs) / n
        ci = _cluster_ci(rs) if games < n and games >= 30 else wilson(k, n)
        verdict = ("thin" if games < 30 else "contradicted" if ci[1] < said else "supported")
        out.append(dict(band=f"{int(100 * lo)}-{int(100 * hi)}%", n=n, games=games, won=k,
                        hit=round(100 * k / n, 1), said=round(said, 1), ci95=ci,
                        first=min(r[2] for r in rs), last=max(r[2] for r in rs), verdict=verdict))
    return out


def evidence(root=None):
    """How the estimated chances behind each leg standard have done on
    comparable settled legs, by source. Sample size, dates and a 95% range
    are always shown; nothing here changes a rating."""
    import json
    import os
    root = root or os.path.dirname(os.path.abspath(__file__))

    def load(name, default):
        try:
            with open(os.path.join(root, name)) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return default
    fd_new, fd_old, props = [], [], []
    for book in (load("locks.json", {}), load("safe_locks.json", {})):
        for L in (book.get("legs") or {}).values():
            if L.get("status") in ("won", "lost") and L.get("p") and L.get("date"):
                (fd_new if L["date"] >= METHOD_FROM else fd_old).append(
                    (L["p"], L["status"] == "won", L["date"], L.get("gid")))
    for d, v in (load("lottery.json", {}).get("days") or {}).items():
        for t in v.get("tickets") or []:
            for L in t["legs"]:
                if L.get("kind") == "game" and L.get("status") in ("won", "lost") and L.get("p"):
                    (fd_new if d >= METHOD_FROM else fd_old).append((L["p"], L["status"] == "won", d,
                                                                     L.get("gid")))
    for e in load("props.json", {}).values():
        if isinstance(e, dict) and e.get("status") in ("won", "lost") and e.get("p") and e.get("date"):
            props.append((e["p"], e["status"] == "won", e["date"], e.get("gid")))
    kal = []
    for r in load(os.path.join("data", "backtest_kalshi_legs.json"), []):
        mid = r["cost"] - (r.get("width") or 0) / 2
        kal.append((mid, bool(r["won"]), r["date"], r["game"]))
    return dict(method_from=METHOD_FROM, sources=[
        dict(name="FanDuel game lines, current method", rows=_band_rows(fd_new)),
        dict(name="FanDuel game lines, before " + METHOD_FROM + " (old band factor)", rows=_band_rows(fd_old)),
        dict(name="FanDuel player props (de-vigged)", rows=_band_rows(props)),
        dict(name="Kalshi mid-prices, game-line contracts (earlier, other book)", rows=_band_rows(kal))])


# ------------------------------------------------------- exact wager check
QUOTE_MAX_AGE_MIN = 15          # freshness.MAX_AGE_MIN: one rule for every price
SETTLEMENT = ("FanDuel NY rules as graded here: full game including overtime; "
              "an integer line landing exactly pushes and drops off the slip; "
              "a game not played, or a player who does not play, voids the leg")


def verify(L, now=None):
    """(ok, reasons): can this exact wager be placed as described right now?"""
    import datetime as dt
    now = now or dt.datetime.now(dt.timezone.utc)
    why = []
    if not L.get("fd"):
        why.append("no FanDuel selection id")
    if not (L.get("where") or L.get("market") or (L.get("spec") or {}).get("t")):
        why.append("market not identified")
    if L.get("price") in (None, "") or not L.get("dec"):
        why.append("no price")

    def ts(x):
        try:
            t = dt.datetime.fromisoformat(str(x).replace("Z", "+00:00"))
            return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)
        except (TypeError, ValueError):
            return None
    q = ts(L.get("quoted"))
    if q is None:
        why.append("quote time unknown")
    elif (now - q).total_seconds() > QUOTE_MAX_AGE_MIN * 60:
        why.append(f"quote older than {QUOTE_MAX_AGE_MIN} min")
    st = ts(L.get("start"))
    if st is None:
        why.append("start time unknown")
    elif st <= now:
        why.append("game has started")
    if L.get("kind") == "prop" and not L.get("plays"):
        why.append("player not confirmed to play" + (f" ({L.get('play')})" if L.get("play") else ""))
    return (not why), why


def candidates(pool, now=None):
    """Pool legs with their decimal price, split into usable and excluded
    (with the reasons), so nothing is dropped silently."""
    import locks
    ok, out = [], []
    for L in pool or []:
        L = dict(L, dec=locks._dec(L.get("price")))
        good, why = verify(L, now)
        (ok if good else out).append(L if good else dict(L, excluded=why))
    return ok, out


# Player props cost more than game lines at the same chance: 482 graded
# FanDuel props at 80-90% returned -7.1% per $1 (2026-10-15..21) against
# -1.9% for 727 game-line favourites in that band (README, 2026-10-22). The
# recommended tickets are built from game lines only.
GAME_LINES_ONLY = True


def game_lines(pool):
    return [L for L in pool or [] if L.get("kind") != "prop"] if GAME_LINES_ONLY else list(pool or [])


def build_frontier(pool, targets=TARGETS, standards=STANDARDS,
                   max_legs=MAX_LEGS, boost=0.0, now=None):
    """The frontier from a live candidate pool, every number labelled."""
    ok, excluded = candidates(game_lines(pool), now)
    rows = frontier(ok, targets, standards, max_legs=max_legs, boost=boost)
    for r in rows:
        r["payout_basis"] = "estimated: product of FanDuel's listed prices (FanDuel prices the slip)"
        if r.get("legs"):
            r["legs"] = [{k: L.get(k) for k in ("gid", "label", "p", "price", "dec", "where", "match",
                                                "tip", "league", "kind", "devig", "quoted", "start",
                                                "fd", "play", "spec", "home", "away", "name",
                                                "market", "line")} for L in r["legs"]]
    from collections import Counter
    return dict(rows=rows, candidates=len(ok), games=len({L["gid"] for L in ok}),
                excluded=len(excluded),
                excluded_why=dict(Counter(w for L in excluded for w in L["excluded"]).most_common(6)),
                settlement=SETTLEMENT, max_legs=max_legs, kind_cap=KIND_CAP, boost=boost)


# ------------------------------------------------------------- record
def _ledger():
    import os
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontier.json")


def load(path=None):
    import json
    try:
        with open(path or _ledger()) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"days": {}}


def save(book, path=None):
    import json
    with open(path or _ledger(), "w") as fh:
        json.dump(book, fh, indent=1, sort_keys=True)


def _sig(front):
    # plain lists: the stored copy comes back from JSON as lists
    return [[r["target"], r["standard"], [L["label"] for L in r.get("legs") or []]] for r in front["rows"]]


def record(front, pool, day, set_card=False, path=None, now=None):
    """Archive before play. Every change of the live frontier is appended
    (time, policy, tickets); at card time the day's tickets are frozen with
    the full candidate pool they were chosen from, and graded later."""
    import datetime as dt
    import policy
    book = load(path)
    for d_ in book["days"].values():
        # a card frozen outside the morning window (before this rule existed)
        # is not a card: drop it. An in-window card whose targets were all
        # unavailable stays -- that is a real answer.
        if d_.get("set_at") and not in_card_window(_at(d_["set_at"])):
            for k in ("tickets", "set_at", "policy", "pool"):
                d_.pop(k, None)
    d = book["days"].setdefault(day, dict(versions=[]))
    stamp = (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds")
    sig = _sig(front)
    if not d["versions"] or d["versions"][-1]["sig"] != sig:
        d["versions"].append(dict(t=stamp, policy=policy.version(), sig=sig))
        d["versions"] = d["versions"][-60:]
    # a card is set only in the morning window, from a pool with usable legs:
    # the first build after 8 AM ET. (First live run, 2026-10-19, came at 10 PM
    # after every game had started and froze "unavailable" from an empty pool.)
    usable = sum(1 for L in pool or [] if verify(dict(L, dec=__import__("locks")._dec(L.get("price"))), now)[0])
    if set_card and "tickets" not in d and usable and in_card_window(now):
        d["set_at"], d["policy"] = stamp, policy.version()
        d["pool"] = pool
        d["tickets"] = [dict(target=r["target"], standard=r["standard"], prob=r.get("prob"),
                             dec=r.get("dec"), total=r.get("total"), status="open" if r.get("legs") else "none",
                             legs=[dict(L, status="open") for L in r.get("legs") or []],
                             ceiling=r.get("ceiling"))
                        for r in front["rows"]]
        props = [L for t in d["tickets"] for L in t["legs"] if L.get("kind") == "prop"]
        if props:
            import props_ledger
            props_ledger.record({"tickets": {"frontier": [{"legs": props}]}}, day)
    for old in sorted(book["days"])[:-30]:
        book["days"][old].pop("pool", None)              # keep 30 days of pools
    save(book, path)


CARD_WINDOW_MIN = 60          # minutes after 8 AM ET in which a card may be set


def in_card_window(now=None):
    import datetime as dt
    from zoneinfo import ZoneInfo
    t = (now or dt.datetime.now(dt.timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    start = t.replace(hour=8, minute=0, second=0, microsecond=0)
    return start <= t < start + dt.timedelta(minutes=CARD_WINDOW_MIN)


def grade(final, path=None):
    """Settle frozen tickets: game legs on final scores (pushes leave the
    slip), props from the props ledger."""
    import locks
    import props_ledger
    import stacks
    book = load(path)
    pl = props_ledger.load()
    for d in book["days"].values():
        for t in d.get("tickets") or []:
            for L in t["legs"]:
                if L["status"] != "open":
                    continue
                if L.get("kind") == "prop":
                    e = pl.get(props_ledger.prop_key(L))
                    if e and e["status"] != "open":
                        L["status"] = "void" if e["status"] == "ungradable" else e["status"]
                else:
                    locks.settle(L, final)
                    stacks.repush(L)
            st = [L["status"] for L in t["legs"]]
            if t["status"] == "none":
                continue
            t["status"] = ("lost" if "lost" in st else "open" if "open" in st
                           else "won" if "won" in st else "void")
    save(book, path)


def report(path=None):
    """Forward record of frozen tickets by target and standard: made, cashed,
    claimed chance (the product at the time), and how many were unavailable."""
    book = load(path)
    agg = {}
    for day, d in sorted(book["days"].items()):
        for t in d.get("tickets") or []:
            k = f'{t["target"]:g}x at {round(100 * t["standard"])}%'
            a = agg.setdefault(k, dict(target=t["target"], standard=t["standard"], made=0, cashed=0,
                                       settled=0, claimed=0.0, unavailable=0, days=[]))
            if t["status"] == "none":
                a["unavailable"] += 1
                continue
            a["made"] += 1
            if t["status"] in ("won", "lost"):
                a["settled"] += 1
                a["cashed"] += t["status"] == "won"
                a["claimed"] += t.get("prob") or 0
            a["days"].append(day)
    for a in agg.values():
        a["claimed"] = round(100 * a["claimed"] / a["settled"], 1) if a["settled"] else None
        a["first"] = a["days"][0] if a["days"] else None
        a["days"] = len(a["days"])
    return sorted(agg.values(), key=lambda a: (a["target"], -a["standard"]))


def challenge_track(path=None, start=100.0, target=10000.0):
    """The bankroll challenge played on the frozen 8 AM tickets: for each
    payout size, every day's likeliest ticket of that size (any standard),
    all in, winnings rolled into the next day; a loss restarts at `start`
    and counts as a bust; reaching `target` counts as a success and also
    restarts. Days without a settled ticket of that size are skipped."""
    book = load(path)
    out = {}
    for m in TARGETS:
        bank, busts, wins_in_row, reached, best, log = start, 0, 0, 0, start, []
        for day, d in sorted(book["days"].items()):
            ts = [t for t in d.get("tickets") or [] if t.get("target") == m and t.get("legs")]
            if not ts:
                continue
            t = max(ts, key=lambda t: t.get("prob") or 0)
            if t["status"] not in ("won", "lost", "void"):
                log.append(dict(day=day, status="open", bank=round(bank, 2), prob=t.get("prob")))
                continue
            if t["status"] == "won":
                bank *= t.get("total") or m
                wins_in_row += 1
                best = max(best, bank)
                if bank >= target:
                    reached += 1
                    log.append(dict(day=day, status="reached", bank=round(bank, 2), prob=t.get("prob")))
                    bank, wins_in_row = start, 0
                    continue
            elif t["status"] == "lost":
                busts += 1
                bank, wins_in_row = start, 0
            log.append(dict(day=day, status=t["status"], bank=round(bank, 2), prob=t.get("prob")))
        out[f"{m:g}"] = dict(bank=round(bank, 2), busts=busts, streak=wins_in_row, reached=reached,
                            best=round(best, 2), days=log)
    return dict(start=start, target=target, sizes=out)


def replay(day, path=None):
    """True when the optimizer, re-run on the day's archived pool, gives the
    tickets frozen at card time; None without an archive."""
    d = load(path)["days"].get(day) or {}
    if not d.get("pool") or "tickets" not in d:
        return None
    import locks
    legs = [dict(L, dec=locks._dec(L.get("price"))) for L in d["pool"]]
    ok = [L for L in legs if verify(L, now=_at(d["set_at"]))[0]]
    for t in d["tickets"]:
        r = optimize(ok, t["target"], t["standard"])
        want = [L["label"] for L in t["legs"]]
        if [L["label"] for L in r["legs"] or []] != want:
            return False
    return True


def _at(iso):
    import datetime as dt
    return dt.datetime.fromisoformat(iso)
