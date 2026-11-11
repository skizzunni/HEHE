"""Ladder challenge: $1 to $10,000 on the day's likeliest Locks (3 to 8 legs).

Each day's ticket is the 5 highest-chance legs of that day's Locks card (set
at 8 AM Eastern and recorded in locks.json, one leg per game), as one parlay.
A win rolls the whole bank into the next day's ticket; a single loss ends the
run, and the next day starts a new run from $1. A leg that voids or pushes
drops out of the parlay (pays 1x), as sportsbooks settle it.

Nothing is stored here: the ladder is replayed from the locks ledger on every
build, from START, so it can never drift from the graded record.

Odds, honestly: on 16 graded cards before the start, all 5 top legs won on 5
days (31%, against 32% stated) and the parlay paid about 3.05x. Reaching
$10,000 from $1 takes 9 wins in a row at that price -- about 1 in 40,000.

How many legs (from 2026-11-05; 5 before): each day the ticket is the top K
Locks for the K in 3..8 that gives the best estimated chance of reaching the
target from the day's bank -- the ticket's chance (its legs' p multiplied)
raised to the wins still needed at its payout. Tested on cards 10-17 to 11-03
against a fixed 5: reach chance 3.1e-05 vs 1.3e-06, then 1.3e-03 vs 2.6e-04
by date half (it chose 3 legs on 18 of 20 days).

Why Locks, not Safe Locks (2026-11-04, cards 10-17 to 11-03): the top 5 Safe
Locks all won on 5/8 then 6/9 days but pay ~1.29x, so $10,000 takes 37 wins
in a row (chance 2.8e-08 / 3.1e-07 by half) against the Locks' 9 (2/9 then
4/10 days at ~3x: 1.3e-06 / 2.6e-04). Locks win in both halves.
"""
import math

import locks

START = "2026-11-03"
BANK0 = 1.0
TARGET = 10000.0
LEGS = 5                    # cards before LEGS_FROM
LEGS_FROM = "2026-11-05"
MIN_LEGS, MAX_LEGS = 3, 8
# the user's call (2026-11-06, "5 might be our lucky number"): from this card
# on, every ticket is the top 5 again. The 3-8 chooser ran on 11-05 only and
# stays in the record; options() still shows what each count would have been.
FIXED_FROM, FIXED_LEGS = "2026-11-06", 5
# the user's call (2026-11-07, "whatever gets me to 2x-5x my money per day"):
# from this card on, the ticket is the top K Locks (1..8) whose payout is
# 2x-5x, choosing K by the best estimated chance of reaching target. A study
# of ~20 cards (top 2: 15/20 at 1.55x, top 4: 10/20 at 2.41x, top 5: 7/19 at
# 3.00x) is too small to fix K, so the chooser decides each day. If no count
# lands in 2x-5x, the count whose payout is nearest the band is taken.
FLEX_FROM, FLEX_MIN, FLEX_MAX = "2026-11-07", 1, 8
PAY_MIN, PAY_MAX = 2.0, 5.0
# the user's call (2026-11-08, "i need winning ladder runs"): from this card
# on, the ticket is the combination of Locks legs (one per game, up to
# BEST_MAX, from the BEST_POOL likeliest) paying 2x-5x with the highest
# chance of ALL winning -- not the top K. Walk-forward on every saved card it
# cashed 11 of 21 (6/11 then 5/10, ~2.0-2.5x) against 10/22 for the top 4,
# 7/21 for the top 5, and the 6-leg tickets the reach chooser was picking.
BEST_FROM, BEST_MAX, BEST_POOL = "2026-11-09", 6, 12
# Leg kinds kept off the ladder, only on the user's word: (league, bet type)
# or (league, "prop") for every prop in a league, matched against
# locks.kind_key. Empty unless the user asks (2026-11-09: NFL props on the
# Locks card were 5 of 10 vs ~80% stated, short in both halves on 10 legs --
# offered, not applied).
SKIP_KINDS = ()


def games_ticket(book, day, n):
    """The day's n likeliest Locks game lines (no player props), or []."""
    keys = book["days"].get(day) or []
    if isinstance(keys, dict):
        keys = keys.get("legs") or []
    legs = sorted((dict(book["legs"][k], key=k) for k in keys if k in book["legs"] and book["legs"][k].get("kind") != "prop"),
                  key=lambda L: -L["p"])
    return legs[:n] if len(legs) >= n else []


def ticket(book, day, n=LEGS):
    """The day's n likeliest Locks legs, or [] when the card is short."""
    keys = book["days"].get(day) or []
    if isinstance(keys, dict):
        keys = keys.get("legs") or []
    legs = sorted((dict(book["legs"][k], key=k) for k in keys if k in book["legs"]), key=lambda L: -L["p"])
    return legs[:n] if len(legs) >= n else []


def options(book, day, bank=BANK0, target=TARGET):
    """Every leg count the chooser weighed (from LEGS_FROM): [{legs, prob,
    pays, need, reach}] -- the ticket's chance, its payout, the wins still
    needed at that payout, and the chance of reaching target that way."""
    out = []
    if day < LEGS_FROM:
        return out
    lo, hi = (FLEX_MIN, FLEX_MAX) if day >= FLEX_FROM else (MIN_LEGS, MAX_LEGS)
    for k in range(lo, hi + 1):
        legs = ticket(book, day, k)
        if not legs:
            continue
        p = math.prod(L["p"] for L in legs)
        pays = math.prod(locks._dec(L["price"]) for L in legs)
        if pays <= 1:
            continue
        need = max(1, math.ceil(math.log(max(target / bank, 1.0001)) / math.log(pays)))
        out.append(dict(legs=k, prob=round(p, 4), pays=round(pays, 3), need=need, reach=p ** need,
                        in_band=PAY_MIN <= pays <= PAY_MAX))
    return out


def best_combo(legs, lo=PAY_MIN, hi=PAY_MAX, maxk=BEST_MAX, pool=BEST_POOL):
    """Of the `pool` likeliest legs, the combination (one leg per game, up to
    `maxk`) whose parlay pays lo..hi with the highest joint stated chance;
    ties go to fewer legs. [] when none pays in the band."""
    import itertools
    cand = sorted(legs, key=lambda L: -L["p"])[:pool]
    best = None
    for k in range(1, maxk + 1):
        for c in itertools.combinations(cand, k):
            if len({L.get("gid") or L.get("key") for L in c}) < k:
                continue
            try:
                pays = math.prod(locks._dec(L["price"]) for L in c)
            except (KeyError, TypeError, ValueError):
                continue
            if not (lo <= pays <= hi):
                continue
            p = math.prod(L["p"] for L in c)
            if best is None or p > best[0] + 1e-12:
                best = (p, list(c))
    return best[1] if best else []


def skipped(L, skip=None):
    """Is this leg's kind kept off the ladder (SKIP_KINDS)?"""
    skip = SKIP_KINDS if skip is None else skip
    if not skip:
        return False
    lg, t = locks.kind_key(L)
    return (lg, t) in skip or (L.get("kind") == "prop" and (lg, "prop") in skip)


def _best(book, day):
    keys = book["days"].get(day) or []
    if isinstance(keys, dict):
        keys = keys.get("legs") or []
    legs = [dict(book["legs"][k], key=k) for k in keys if k in book["legs"] and not skipped(book["legs"][k])]
    got = best_combo(legs)
    return sorted(got, key=lambda L: -L["p"]) if got else []


def _flex(book, day, bank, target):
    """From FLEX_FROM: the top K Locks paying 2x-5x with the best chance of
    reaching target; with none in the band, the count paying nearest it."""
    opts = options(book, day, bank, target)
    if not opts:
        return []
    band = [o for o in opts if o["in_band"]]
    if band:
        k = max(band, key=lambda o: (o["reach"], -o["legs"]))["legs"]
    else:
        k = min(opts, key=lambda o: (PAY_MIN - o["pays"] if o["pays"] < PAY_MIN else o["pays"] - PAY_MAX, o["legs"]))["legs"]
    return ticket(book, day, k)


def choose(book, day, bank=BANK0, target=TARGET):
    """The day's ticket: 5 legs before LEGS_FROM; from then, the top K Locks
    (MIN_LEGS..MAX_LEGS) with the best estimated chance of reaching target
    from bank. Decided from the frozen 8 AM card, so a replay never moves."""
    if day < LEGS_FROM:
        return ticket(book, day)
    if day >= BEST_FROM:
        return _best(book, day) or _flex(book, day, bank, target)
    if day >= FLEX_FROM:
        return _flex(book, day, bank, target)
    if day >= FIXED_FROM:
        return ticket(book, day, FIXED_LEGS)
    best = None
    for k in range(MIN_LEGS, MAX_LEGS + 1):
        legs = ticket(book, day, k)
        if not legs:
            continue
        p = math.prod(L["p"] for L in legs)
        pays = math.prod(locks._dec(L["price"]) for L in legs)
        if pays <= 1:
            continue
        need = max(1, math.ceil(math.log(max(target / bank, 1.0001)) / math.log(pays)))
        score = p ** need
        if best is None or score > best[0] + 1e-15:
            best = (score, legs)
    return best[1] if best else []


def count_record(book=None, start=START, hi=FLEX_MAX, games_only=False):
    """Every graded Locks card since start, as if the ladder had always used
    the top K legs (K = 1..hi): [{legs, won, n, pays}] -- days that K would
    have cashed, cards with K graded legs, and its average payout. Lets the
    2x-5x chooser be checked against fixed counts as days come in."""
    book = book or locks.load()
    out = []
    for k in range(1, hi + 1):
        won = n = 0
        pay = 0.0
        for day in sorted(d for d in book.get("days", {}) if d >= start):
            legs = ticket(book, day, k) if not games_only else games_ticket(book, day, k)
            if not legs or any(L.get("status") not in ("won", "lost") for L in legs):
                continue
            try:
                pay += math.prod(locks._dec(L["price"]) for L in legs)
            except Exception:
                continue
            n += 1
            won += all(L["status"] == "won" for L in legs)
        if n:
            out.append(dict(legs=k, won=won, n=n, pays=round(pay / n, 2)))
    return out


def _game_miss(L):
    """A lost game or team total with its final number and the miss:
    "Over 208.5 points (207, missed by 1.5)". The label alone otherwise."""
    import re
    lab, sc = str(L.get("label") or ""), str(L.get("score") or "")
    fmt = lambda x: int(x) if float(x).is_integer() else x
    m = re.match(r"^(Over|Under)\s+([\d.]+)", lab, re.I)
    if m:
        pts = [int(x) for x in re.findall(r"-?\d+(?=\s*(?:-|$))", sc)]
        if len(pts) < 2:
            return lab
        got, line = pts[-2] + pts[-1], float(m.group(2))
    else:
        t = re.match(r"^(.+?)\s+(over|under)\s+([\d.]+)", lab, re.I)
        if not t:
            return lab
        part = next((x for x in re.split(r"\s+-\s+", sc) if x.startswith(t.group(1))), None)
        v = re.search(r"(-?\d+)\s*$", part or "")
        if not v:
            return lab
        got, line, m = int(v.group(1)), float(t.group(3)), t
        m = re.match(r"(over|under)", t.group(2), re.I)
    miss = (line - got) if m.group(1).lower() == "over" else (got - line)
    return f"{lab} ({got}, missed by {fmt(miss)})" if miss > 0 else lab


def miss_label(L, pbook=None):
    """A lost leg's label, with a prop's final number and the miss when the
    props ledger has it: "Kyle Pitts: 25+ Receiving Yards (23, missed by 2)"."""
    if L.get("status") == "lost" and L.get("kind") != "prop":
        return _game_miss(L)
    if L.get("kind") != "prop" or L.get("status") != "lost" or not L.get("market"):
        return L["label"]
    try:
        import props_ledger
        pbook = pbook if pbook is not None else props_ledger.load()
        e = pbook.get(props_ledger.prop_key(L)) or {}
        v = e.get("value")
        need = float(str(L.get("line") or "").rstrip("+"))
    except Exception:
        return L["label"]
    if not isinstance(v, (int, float)):
        return L["label"]
    miss = need - v
    fmt = lambda x: int(x) if float(x).is_integer() else x
    return f"{L['label']} ({fmt(v)}, missed by {fmt(miss)})" if miss > 0 else L["label"]


def settle(legs):
    """('won', payout) / ('lost', 0) / ('open', None) for one parlay."""
    st = [L.get("status") for L in legs]
    if "lost" in st:
        return "lost", 0.0
    if any(s not in ("won", "void", "push") for s in st):
        return "open", None
    return "won", math.prod(locks._dec(L["price"]) if L.get("status") == "won" else 1.0 for L in legs)


def settle_pay(entry):
    """What a settled day entry paid per $1: 0 when lost; void legs at 1x."""
    if entry["result"] != "won":
        return 0.0
    return math.prod(locks._dec(L["price"]) if L["status"] == "won" else 1.0 for L in entry["legs"])


def replay(book=None, start=START, target=TARGET):
    """Every run from start: [{start, days: [...], status, bank}]; the last
    run is the live one. Stops at the first unsettled day."""
    book = book or locks.load()
    runs, cur = [], None
    for day in sorted(d for d in book["days"] if d >= start):
        if cur is None or cur["status"] in ("lost", "reached"):
            fresh = True
            bank0 = BANK0
        else:
            fresh = False
            bank0 = cur["bank"]
        legs = choose(book, day, bank0, target)
        if not legs:
            continue
        if fresh:
            cur = dict(start=day, days=[], status="live", bank=BANK0)
            runs.append(cur)
        res, pay = settle(legs)
        stake = cur["bank"]
        entry = dict(day=day, stake=round(stake, 2), result=res,
                     prob=round(math.prod(L["p"] for L in legs), 4),
                     pays=round(math.prod(locks._dec(L["price"]) for L in legs), 3),
                     legs=[dict(label=L["label"], price=L["price"], p=L["p"], match=L.get("match"),
                                tip=L.get("tip"), lg=L.get("lg") or L.get("league"), score=L.get("score"),
                                gid=L.get("gid"), t=(L.get("spec") or {}).get("t"), kind=L.get("kind"),
                                league=L.get("league"), name=L.get("name"), aid=L.get("aid"),
                                market=L.get("market"), line=L.get("line"),
                                status=L.get("status") or "open") for L in legs])
        cur["days"].append(entry)
        if res == "open":
            break
        if res == "lost":
            cur["status"], cur["bank"] = "lost", 0.0
        else:
            cur["bank"] = round(stake * pay, 2)
            if cur["bank"] >= target:
                cur["status"] = "reached"
    return runs


def live(legs):
    """Attach the game clock and score (the picks ledger's live fields, by
    game id) to each open leg, so the ticket can be followed in play."""
    try:
        import ledger
        book = ledger.load()
    except Exception:
        return
    for L in legs:
        e = book.get(L.get("gid")) or {}
        if L.get("status") in (None, "open") and e.get("live") and e.get("live_score"):
            L["live"] = e["live"]
            L["live_score"] = " - ".join(f"{t} {v}" for t, v in e["live_score"].items())
            if L.get("kind") == "prop" and L.get("market"):
                try:                        # the player's stat so far
                    import props_ledger
                    v = props_ledger.live_value(L)
                    if v is not None:
                        L["so_far"] = v
                except Exception:
                    pass


def legs_by_kind(legs):
    """Graded ladder legs split into game lines and player props:
    {"game"|"prop": dict(won, n, said)}. 2026-11-09: games 16 of 18, props
    7 of 10 (about 79% stated) -- too few props to act on."""
    out = {}
    for L in legs:
        if L.get("status") not in ("won", "lost") or L.get("p") is None:
            continue
        a = out.setdefault("prop" if L.get("kind") == "prop" else "game", [0, 0, 0.0])
        a[0] += L["status"] == "won"
        a[1] += 1
        a[2] += L["p"]
    return {k: dict(won=w, n=n, said=round(100 * p / n, 1)) for k, (w, n, p) in out.items()}


def report(book=None, start=START, target=TARGET):
    runs = replay(book, start, target)
    cur = runs[-1] if runs else None
    bank = cur["bank"] if cur and cur["status"] == "live" else BANK0
    today = cur["days"][-1] if cur and cur["days"] and cur["days"][-1]["result"] == "open" else None
    if today:
        live(today["legs"])
        try:                       # how Locks of each leg's kind have done
            kr = locks.kind_record(book or locks.load())
            import props_ledger
            for L in today["legs"]:
                r = kr.get(locks.kind_key(L))
                if r:
                    L["kind_rec"] = dict(won=r[0], n=r[1])
                if L.get("kind") == "prop" and L.get("market"):
                    pr = props_ledger.like_record(L.get("league"), L["market"], L["p"])
                    if pr:
                        L["prop_rec"] = pr
        except Exception:
            pass
        try:
            today["options"] = options(book or locks.load(), today["day"], today["stake"], target)
            if today["day"] >= BEST_FROM:      # the chosen combination against the plain top 4
                t4 = ticket(book or locks.load(), today["day"], 4)
                if t4:
                    today["vs_top4"] = dict(prob=round(math.prod(L["p"] for L in t4), 4),
                                            pays=round(math.prod(locks._dec(L["price"]) for L in t4), 3))
        except Exception:
            pass
    pays = (today or {}).get("pays") or 3.05
    need = max(0, math.ceil(math.log(target / bank) / math.log(pays))) if pays > 1 and bank < target else 0
    p = (today or {}).get("prob")
    done = [d for d in (cur or {}).get("days", []) if d["result"] != "open"]
    last = dict(done[-1], after=round(done[-1]["stake"] * settle_pay(done[-1]), 2)) if done else None
    return dict(start=start, target=target, bank=round(bank, 2), runs=len(runs),
                reached=sum(r["status"] == "reached" for r in runs),
                best=round(max([r["bank"] for r in runs if r["status"] != "lost"] +
                               [max([d["stake"] for d in r["days"]] or [BANK0]) for r in runs] + [BANK0]), 2),
                # a lost run's wins are history, not a streak: the next ticket starts again at $1
                streak=(sum(1 for d in cur["days"] if d["result"] == "won") if cur and cur["status"] != "lost" else 0),
                ended=(dict(start=cur["start"], peak=max([d["stake"] for d in cur["days"]] + [cur["bank"]]),
                            lost_on=[miss_label(L) for L in cur["days"][-1]["legs"] if L.get("status") == "lost"])
                       if cur and cur["status"] == "lost" else None),
                today=today, wins_needed=need, last=last,
                log=[dict(day=d["day"], stake=d["stake"], result=d["result"], pays=d["pays"], n=len(d["legs"]),
                          lost_on=[miss_label(L) for L in d["legs"] if L.get("status") == "lost"]) for d in done],
                chance_to_target=round(p ** need, 8) if p and need else None,
                # every ladder leg ever graded, against its stated chance
                legs_record=(lambda G: dict(won=sum(L["status"] == "won" for L in G), n=len(G),
                                            said=round(100 * sum(L["p"] for L in G) / len(G), 1)) if G else None)(
                    [L for r in runs for d in r["days"] for L in d["legs"] if L.get("status") in ("won", "lost")]),
                # the same, game lines and player props apart: which kind the ladder loses on
                legs_by_kind=legs_by_kind([L for r in runs for d in r["days"] for L in d["legs"]]),
                skip=[list(k) for k in SKIP_KINDS],    # leg kinds kept off the ladder (the board preview honours it)
        counts=count_record(book, ""),         # every saved Locks card, not just the ladder's
        counts_games=count_record(book, "", games_only=True),   # the same with game lines only
        tickets=dict(won=sum(1 for r in runs for d in r["days"] if d["result"] == "won"),
                             n=sum(1 for r in runs for d in r["days"] if d["result"] in ("won", "lost"))),
                # every settled day of every run: the bank after it (0 on a loss)
                path=[dict(day=d["day"], run=i + 1, bank=(0.0 if d["result"] == "lost"
                                                          else round(d["stake"] * settle_pay(d), 2)))
                      for i, r in enumerate(runs) for d in r["days"] if d["result"] != "open"],
                history=[dict(start=r["start"], status=r["status"], days=len(r["days"]),
                              peak=max([d["stake"] for d in r["days"]] + [r["bank"]]),
                              lost_on=[miss_label(L) for L in r["days"][-1]["legs"] if L.get("status") == "lost"]
                              if r["status"] == "lost" and r["days"] else [])
                         for r in runs][-10:])
