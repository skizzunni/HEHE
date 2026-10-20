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


def frontier(legs, targets=(2.0, 3.0, 5.0), standards=(0.90, 0.85, 0.80, 0.75),
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
