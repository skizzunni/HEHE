"""The lottery: $1 tickets built to pay about $10,000.

A long shot on purpose. Each ticket stacks plus-money legs until the book's
own prices multiply to TARGET (10,000x the stake), so a $1 ticket returns
about $10,000 if every leg lands. The tab shows the honest chance next to
each one -- usually around 1 in 15,000 to 1 in 40,000.

HOW LEGS ARE CHOSEN

  * Game legs: every line FanDuel (New York) posts for a game that has not
    started -- moneylines, spreads, totals, alternate lines and team totals
    (locks.fd_specs) -- priced by the same backtested, self-tuning model as
    the stacks, and paid at FanDuel's own price.
  * Player props: DraftKings' priced props from ESPN, with the margin the
    graded props have earned (props_ledger.tune).
  * A leg's value is chance x decimal price: what $1 on it returns on
    average. The tickets take the legs that keep the most value per unit
    of payout first (_rank), so they are the
    least bad way to buy a 10,000x shot, not a good bet. A sportsbook
    parlay compounds the book's margin on every leg.
  * One leg per game, so legs are independent; one book per ticket, because
    a parlay is placed at one book.

Each day's tickets are set at 8:00 AM Eastern like the locks, recorded in
lottery.json and graded, so the tab shows whether the chances it quoted
were honest.
"""
import datetime as dt
import json
import math
import os

import fanduel
import kalshi
import locks
import participation
import props_ledger
import stacks

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "lottery.json")
TARGET = 10000.0            # payout multiple a ticket is built to reach
MAX_LEGS = 14
N_TICKETS = 3               # per book, built from disjoint games
GAME_BAND = (0.15, 0.80)    # model chance of a game leg
DEC_BAND = (1.65, 6.0)      # $10k tier: -154 .. +500, no moonshots
LEG_DEC = (1.25, 6.0)       # every leg considered: -400 .. +500


def decimal(price):
    try:
        v = float(str(price).replace("+", "").strip())
    except (TypeError, ValueError):
        return None
    if -100 < v < 100:
        return None
    return 1 + (v / 100 if v > 0 else 100 / -v)


# What the past says (tools/lottery_backtest.py, 16,000 priced Kalshi legs):
#
#   * Where the model disagreed with the market, the MARKET was right: legs
#     the model rated as value lost 8% (edge >= 0) and 20% (edge >= 3 points)
#     on games it had not seen. So a leg's chance is the market's, never the
#     model's; the model only decides which lines are worth looking at.
#   * By price band, 10-20c legs lost 13% and 90c+ legs lost 1% -- but that
#     is Kalshi's fee-inclusive return, and a correction built from it did
#     not beat the plain price on unseen games (see market_chance). BAND_VALUE
#     is kept for the report only; no chance uses it.
#   * Ladders (one game's lines priced out of order): 0 in 2,950 pairs.
BACKTEST = os.path.join(HERE, "data", "backtest_lottery.json")
FD_HOLD = 1.045             # FanDuel's typical margin on a single alternate line
SHRINK_N = 800              # legs at which a band's own return gets half weight


def _band_values():
    try:
        bp = json.load(open(BACKTEST))["by_price"]
    except (OSError, ValueError, KeyError):
        return {}
    rows = [(int(k.split("-")[0]) // 10, v) for k, v in bp.items() if v.get("n")]
    n_all = sum(v["n"] for _, v in rows)
    mean = sum(v["roi"] * v["n"] for _, v in rows) / n_all if n_all else 0.0
    # Each band's return includes Kalshi's spread and fee, which every band
    # pays; only the SHAPE across bands (the bias) carries over to a fair
    # price, so each band is taken relative to the average.
    return {b: (1 + ((v["n"] * v["roi"] + SHRINK_N * mean) / (v["n"] + SHRINK_N)) / 100)
            / (1 + mean / 100) for b, v in rows}


BAND_VALUE = _band_values()


def market_chance(price_p):
    """The chance a leg is given: its de-vigged market price, unchanged.

    Until 2026-10-18 this multiplied by a per-10c-band factor (BAND_VALUE).
    That jumped at every band edge (39.9999% -> 41.02% but 40.00% -> 39.72%)
    and pushed both sides of a 50/50 to 50.46%. Tested by date halves on
    Kalshi's own mid-prices (ask less half the spread) for 17,766 settled legs
    (226 games, 38 dates; no game in both halves), scored by log loss on the
    half not used to fit:
      * the band factors lost to the plain price on the older half (0.5466 vs
        0.5440) and won by a hair on the newer (0.5241 vs 0.5246);
      * a smooth, complement-preserving logit stretch q = s(b*logit p) fitted
        on one half lost on the other in both directions (b 0.96 vs 1.06; the
        game-bootstrap 90% CI of its gain, -0.0015..+0.0004, includes zero).
    (The first version of this test, 2026-10-18, scored the archive's "p" --
    the Stacks score model's chance, not a market price -- by mistake; found in
    PR #2's independent review. The conclusion did not change.)
    Neither held on unseen games, so the market price stands. It is monotone
    and keeps complementary outcomes summing to 1. The cap at 0.99 is kept."""
    return min(max(float(price_p), 0.0), 0.99)


def _game_legs(rows, soccer_keys, labels, FD, KB=None):
    """Every FanDuel line, with the market's chance for it. A leg's edge is
    that chance x FanDuel's price - 1: positive only where Kalshi's traders
    price the same line shorter than FanDuel pays."""
    by_id = {r["id"]: r for rs in (rows or {}).values() for r in rs}
    refs = {}
    games = stacks.candidates(rows, soccer_keys, labels, extra=locks.fd_specs(FD, refs),
                              band=GAME_BAND)
    out = []
    for g in games:
        for L in g["legs"]:
            ref, price, where = refs.get((g["gid"], json.dumps(L["spec"], sort_keys=True)),
                                         (None, None, None))
            d = decimal(price)
            if not ref or not d or not LEG_DEC[0] <= d <= LEG_DEC[1]:
                continue
            k = None
            if KB:
                try:
                    k = kalshi.leg(KB, g["league"], (by_id.get(g["gid"]) or {}).get("mkt") or {},
                                   L["spec"])
                except Exception:
                    k = None
            pk = (k or {}).get("mid")
            # Kalshi's traders where they price the line; otherwise FanDuel's
            # price de-vigged against its own opposite side (locks.two_sided)
            p_fd, how = locks.two_sided(refs, g["gid"], L["spec"], g["home"], g["away"], price,
                                        g["league"] in fanduel.SOCCER)
            p_mkt = pk if pk and 0.01 < pk < 0.99 else p_fd
            p = market_chance(p_mkt)
            if L["spec"].get("t") in ("over", "under"):
                import weather
                p += weather.adjust(g["league"], (by_id.get(g["gid"]) or {}).get("mkt") or {},
                                    L["spec"]["t"], p)
            p = round(min(0.99, max(0.01, p)), 4)
            out.append(dict(kind="game", gid=g["gid"], league=g["league"], lg=g["lg"],
                            match=g["match"], home=g["home"], away=g["away"], tip=g.get("tip"),
                            label=L["label"], spec=L["spec"], p=p, p_model=L["p"], p_kalshi=pk,
                            p_market=round(p_mkt, 4), devig="kalshi" if p_mkt == pk else how,
                            price=price, dec=round(d, 3), fd=ref, where=where,
                            value=round(p * d, 4)))
    return out


def _prop_legs(prop_games, ok_gids):
    out = []
    for g in prop_games or []:
        if g["id"] not in ok_gids:
            continue
        lg = g["id"].split(":", 1)[0]
        for P in g.get("props") or []:
            d = decimal(P.get("price"))
            if not d or not LEG_DEC[0] <= d <= LEG_DEC[1] or not (P.get("aid") or P.get("name")):
                continue
            if not props_ledger.gradable(lg, P["market"]):
                continue
            # a backup keeper's saves look like the best value on the board and
            # can only void: confirmed participants only (participation.py)
            if not participation.eligible(P):
                continue
            pf = P["p"]                    # the price, not the ladder model (see locks.py)
            out.append(dict(P, p=pf, kind="prop", gid=g["id"], league=lg, lg=g["lg"],
                            match=g["match"], tip=g.get("tip"), dec=round(d, 3),
                            value=round(pf * d, 4)))
    return out


def _rank(L):
    """A ticket's chance is the product of its legs' values divided by its
    payout, so for a fixed payout the best leg is the one that gives up the
    least value per unit of payout it adds: log(value) / log(price)."""
    return math.log(L["value"]) / math.log(L["dec"])


def _rank_chance(L):
    """For a fixed chance, the best leg adds the most payout per unit of
    chance it costs: log(value) / -log(p)."""
    return math.log(L["value"]) / -math.log(L["p"])


# Two tiers. The payout and the chance cannot both be set: a $1 ticket that
# hits 1 time in 100 is worth at most about $100 before the book's margin,
# so "1 in 100" pays tens of dollars and "$10,000" is a 1-in-20,000 shot.
# FanDuel and DraftKings hand out parlay PROFIT boosts most days (+25% to
# +100% on the winnings). A boost is the one real edge a $1 parlay can get:
# with +100% the legs only need to reach ~5,000x for the ticket to pay
# $10,000, which takes fewer legs and roughly doubles the chance. So the $10k
# tier is also built for each common boost; the tab shows the one you have.
BOOSTS = (0.25, 0.50, 1.00)
OPTIMIZER_VERSION = "pareto-polish-v1"


def boosted(pay, boost):
    """What a ticket returns with a profit boost on its winnings."""
    return 1 + (pay - 1) * (1 + boost)


TIERS = (
    # name, decimal price range, rank, stop rule
    dict(tier="100", dec=(1.25, 3.0), rank=_rank_chance, chance=0.01),
    dict(tier="10k", dec=DEC_BAND, rank=_rank, pay=TARGET),
) + tuple(dict(tier=f"10k+{int(b * 100)}", boost=b, dec=DEC_BAND, rank=_rank,
               pay=1 + (TARGET - 1) / (1 + b), n=1) for b in BOOSTS)


def polish_ticket(pick, candidates, target, boost=0, used=()):
    """Improve cash chance without reducing modeled expected cash return.

    Consider removal and every one-leg replacement, including other lines
    of a selected game. Preserve payout target, one/event and prior-ticket
    exclusions. This is a bounded local improvement, not a global optimum
    or evidence that the supplied probabilities are calibrated.
    """
    pick = list(pick)
    blocked = set(used)
    candidates = [L for L in candidates if 0 < L.get("p", 0) <= 1
                  and L.get("dec", 0) > 1 and L.get("gid") not in blocked]
    for _ in range(2 * len(pick)):
        p = math.prod(L["p"] for L in pick)
        d = math.prod(L["dec"] for L in pick)
        value = p * boosted(d, boost)
        best = None
        for i, old in enumerate(pick):
            rest = pick[:i] + pick[i + 1:]
            on = {L["gid"] for L in rest} | blocked
            for new in [None] + [L for L in candidates if L["gid"] not in on]:
                if new is old or (new is None and not rest):
                    continue
                pn = p / old["p"] * (new["p"] if new else 1)
                dn = d / old["dec"] * (new["dec"] if new else 1)
                vn = pn * boosted(dn, boost)
                peps = 1e-12 * max(p, pn, 1e-300)
                veps = 1e-12 * max(value, vn, 1e-300)
                if dn + 1e-12 * target < target or pn < p - peps or vn < value - veps:
                    continue
                if pn <= p + peps and vn <= value + veps:
                    continue
                key = (pn, vn, -dn)
                if best is None or key > best[0]:
                    best = key, rest + ([new] if new else [])
        if best is None:
            break
        pick = best[1]
    return pick


def _tickets(legs, book, tier=TIERS[1], legacy=False):
    """Up to N_TICKETS tickets of the most efficient legs for the tier: built
    up to the payout TARGET, or down to the chance (1 in 100)."""
    lo, hi = tier["dec"]
    rank = tier["rank"]
    best = {}
    inband = [L for L in legs if lo <= L["dec"] <= hi]
    for L in sorted(inband, key=lambda L: -rank(L)):
        best.setdefault(L["gid"], L)            # one leg per game: its best
    pool = sorted(best.values(), key=lambda L: -rank(L))
    used, made = set(), []
    for _ in range(tier.get("n", N_TICKETS)):
        pick, pay, prob = [], 1.0, 1.0
        for L in pool:
            if L["gid"] in used:
                continue
            if tier.get("chance") and prob * L["p"] < tier["chance"] * 0.9:
                continue                        # would overshoot the chance
            if tier.get("pay") and pay * L["dec"] >= tier["pay"]:
                # this leg finishes the ticket: finish it with the likeliest
                # leg that still reaches the payout, not the next in line,
                # so the ticket does not overshoot $10,000 at the cost of odds.
                # Any line of any unused game may finish it: until 2026-10-19
                # only each game's top-ranked line was looked at, so a ticket
                # needing x1.70 more took a 2.35 leg at 41% (13,846 paid) when
                # 1.70-1.85 lines at ~55% were on the board.
                in_pick = {x["gid"] for x in pick}
                fin = [x for x in inband if x["gid"] not in used and x["gid"] not in in_pick
                       and pay * x["dec"] >= tier["pay"]]
                L = max(fin, key=lambda x: (x["p"], -x["dec"]))
            pick.append(L)
            pay *= L["dec"]
            prob *= L["p"]
            if len(pick) >= MAX_LEGS:
                break
            if tier.get("pay") and pay >= tier["pay"]:
                break
            if tier.get("chance") and prob <= tier["chance"] * 1.1:
                break
        if tier.get("pay") and pay < tier["pay"]:
            break
        if tier.get("chance") and not tier["chance"] * 0.9 <= prob <= tier["chance"] * 1.25:
            break
        if tier.get("pay") and not legacy:
            pick = polish_ticket(pick, inband, tier["pay"], tier.get("boost", 0), used)
            pay = math.prod(L["dec"] for L in pick)
            prob = math.prod(L["p"] for L in pick)
        used.update(L["gid"] for L in pick)
        b = tier.get("boost", 0)
        made.append(dict(book=book, tier=tier["tier"], boost=b, legs=pick,
                         pays=round(boosted(pay, b)), base=round(pay),
                         prob=prob, odds=round(1 / prob) if prob else None))
    return made


def build(slot_rows, soccer_keys, labels, FD, prop_games=None, day=None, KB=None):
    now = dt.datetime.now(dt.timezone.utc)
    rows = {lg: [r for r in rs if locks._eligible(r, day, now)]
            for lg, rs in (slot_rows or {}).items()}
    ok = {r["id"] for rs in rows.values() for r in rs}
    fd_rows = {lg: rs for lg, rs in rows.items() if lg in locks.fanduel.PAGES}
    games = _game_legs(fd_rows, soccer_keys, labels, FD, KB)
    # a prop priced more than freshness.MAX_AGE_MIN ago, or with no quote
    # time, is never a leg (game lines arrive already filtered: fresh_slots)
    import freshness
    props = [P for P in _prop_legs(prop_games, ok) if freshness.is_fresh(P.get("quoted"), now)]
    tickets = []
    for tier in TIERS:
        # a parlay is placed at one book: FanDuel props ride with FanDuel lines
        tickets += (_tickets(games + [P for P in props if P.get("fd")], "FanDuel", tier)
                    + _tickets([P for P in props if not P.get("fd")], "DraftKings", tier))
    edge = sorted((L for L in games if L["value"] > 1), key=lambda L: -L["value"])
    keep = ("gid", "label", "p", "dec", "value", "kind", "fd", "price", "devig", "name", "market",
            "line", "league", "plays")
    return dict(tickets=tickets,
                # every candidate leg the builder saw, archived with the day's
                # card so its tickets can be rebuilt exactly (replay)
                candidates=[{k: L.get(k) for k in keep} for L in games + props],
                pool=dict(games=len({L["gid"] for L in games}), props=len(props),
                          checked=sum(L["p_kalshi"] is not None for L in games),
                          edges=len(edge),
                          confirmed=sum(L["p_kalshi"] is not None for L in edge)),
                edges=[dict(label=L["label"], match=L["match"], lg=L["lg"], price=L["price"],
                            p=L["p"], p_model=L["p_model"], p_kalshi=L["p_kalshi"],
                            edge=round(100 * (L["value"] - 1), 1), where=L.get("where"),
                            fd=L["fd"]) for L in edge[:15]])


# ------------------------------------------------------------------ record
def load():
    try:
        with open(LEDGER) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"days": {}}


def save(book):
    with open(LEDGER, "w") as fh:
        json.dump(book, fh, indent=1, sort_keys=True)


def _iso(day):
    day = str(day)
    return f"{day[:4]}-{day[4:6]}-{day[6:]}" if len(day) == 8 else day


def record(res, day):
    """The day's first card of tickets stands. Prop legs also go into the
    props ledger, which settles them from box scores."""
    day = _iso(day)
    book = load()
    have = {(t["book"], t.get("tier", "10k"))
            for t in (book["days"].get(day) or {}).get("tickets", [])}
    tickets = []
    for t in res.get("tickets") or []:
        if (t["book"], t.get("tier", "10k")) in have:
            continue                            # that tier's card already stands
        legs = [dict(L, status="open", date=day) for L in t["legs"]]
        tickets.append(dict(t, legs=legs))
    if not tickets:
        return
    first = day not in book["days"]
    book["days"].setdefault(day, dict(tickets=[]))["tickets"] += tickets
    if first and res.get("candidates") is not None:
        import policy
        pools = book.setdefault("pools", {})
        pools[day] = dict(t=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                          optimizer=OPTIMIZER_VERSION,
                          policy=policy.version(), legs=res["candidates"],
                          tickets=[[L["label"] for L in t["legs"]] for t in tickets],
                          keys=[[t["book"], t.get("tier")] for t in tickets])
        for old_day in sorted(pools)[:-14]:
            del pools[old_day]
    save(book)
    props = [L for t in tickets for L in t["legs"] if L["kind"] == "prop"]
    if props:
        props_ledger.record({"tickets": {"lottery": [{"legs": props}]}}, day)


def grade(final):
    book = load()
    pl = props_ledger.load()
    for d in book["days"].values():
        for t in d["tickets"]:
            for L in t["legs"]:
                if L["kind"] == "game":
                    stacks.repush(L)
                # a prop leg voided from a record the fixed grader has since settled re-syncs
                if L["status"] != "open" and not (L["kind"] != "game" and L["status"] == "void"):
                    continue
                if L["kind"] == "game":
                    locks.settle(L, final)
                else:
                    e = pl.get(props_ledger.prop_key(L))
                    if e and e["status"] not in ("open",):
                        L["status"] = "void" if e["status"] == "ungradable" else e["status"]
                        if e.get("value") is not None:
                            L["score"] = f'{e["value"]:g}'
            st = [L["status"] for L in t["legs"]]
            t["status"] = ("lost" if "lost" in st else "open" if "open" in st
                           else "won" if "won" in st else "void")
            # a void leg leaves the slip: the bet that stands is the rest of
            # it, at their payout and chance -- kept beside the original
            live = [L for L in t["legs"] if L["status"] != "void"]
            if len(live) < len(t["legs"]):
                pay = prob = 1.0
                for L in live:
                    pay *= L.get("dec") or 1.0
                    prob *= L.get("p") or 1.0
                t["settled"] = dict(legs=len(live), pays=round(pay, 1), prob=prob,
                                    voided=[L["label"] for L in t["legs"] if L["status"] == "void"])
    save(book)


def replay(day):
    """True when the builder, re-run on the archived candidates, gives the
    recorded tickets; None without an archive."""
    snap = (load().get("pools") or {}).get(_iso(day))
    if not snap:
        return None
    legs = snap["legs"]
    legacy = snap.get("optimizer") != OPTIMIZER_VERSION
    got = []
    for tier in TIERS:
        got += (_tickets([L for L in legs if L.get("kind") == "game" or L.get("fd")], "FanDuel", tier, legacy)
                + _tickets([L for L in legs if L.get("kind") == "prop" and not L.get("fd")], "DraftKings", tier, legacy))
    want = {(b, tr): lab for (b, tr), lab in zip(map(tuple, snap["keys"]), snap["tickets"])}
    have = {}
    for t in got:
        have.setdefault((t["book"], t.get("tier")), []).append([L["label"] for L in t["legs"]])
    return all(lab in have.get(k, []) for k, lab in want.items())


def frozen(day):
    d = load()["days"].get(_iso(day))
    if not d:
        return None
    return dict(tickets=d["tickets"], set=True, day=_iso(day))


def report():
    """Every recorded ticket and leg, so the quoted chances can be checked."""
    book = load()
    legs = [L for d in book["days"].values() for t in d["tickets"] for L in t["legs"]
            if L["status"] in ("won", "lost")]
    tickets = [t for d in book["days"].values() for t in d["tickets"]]
    done = [t for t in tickets if t.get("status") in ("won", "lost")]
    # one bet per leg: the same leg sits on several tickets, and counting it
    # once per ticket (until 2026-10-24) made 98 bets read as 204 and the
    # return +30.2% instead of +17.9%
    ed = list({(d, L.get("gid"), L.get("label")): L for d, v in book["days"].items()
               for t in v["tickets"] for L in t["legs"]
               if L["status"] in ("won", "lost") and L.get("value", 0) > 1}.values())
    ret = sum((L["dec"] - 1) if L["status"] == "won" else -1 for L in ed)
    return dict(edge_legs=len(ed), edge_won=sum(L["status"] == "won" for L in ed),
                edge_said=round(100 * sum(L["p"] for L in ed) / len(ed), 1) if ed else None,
                edge_roi=round(100 * ret / len(ed), 1) if ed else None,
                legs=len(legs), won=sum(L["status"] == "won" for L in legs),
                said=round(100 * sum(L["p"] for L in legs) / len(legs), 1) if legs else None,
                tickets=len(done), hits=sum(t["status"] == "won" for t in done),
                days=[dict(day=k, n=len(v["tickets"]),
                           won=sum(t.get("status") == "won" for t in v["tickets"]),
                           best=max([sum(L["status"] == "won" for L in t["legs"])
                                     for t in v["tickets"]] or [0]),
                           open=sum(t.get("status", "open") == "open" for t in v["tickets"]))
                      for k, v in sorted(book["days"].items(), reverse=True)[:14]])
