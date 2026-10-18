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

import kalshi
import locks
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
#   * The market itself is biased by price (favourite-longshot): 10-20c legs
#     lost 13%, 90c+ legs lost 1%. BAND_VALUE carries what each price band
#     actually returned, shrunk toward the average where the sample is thin,
#     and a leg's chance is its market price corrected by that.
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
    """A fair market chance corrected for the bias its price band showed."""
    f = BAND_VALUE.get(min(int(price_p * 10), 9), 1.0)
    return min(price_p * f, 0.99)


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
            # own price less its margin. Either way, corrected by price band.
            p_mkt = pk if pk and 0.01 < pk < 0.99 else (1 / d) / FD_HOLD
            p = market_chance(p_mkt)
            if L["spec"].get("t") in ("over", "under"):
                import weather
                p += weather.adjust(g["league"], (by_id.get(g["gid"]) or {}).get("mkt") or {},
                                    L["spec"]["t"], p)
            p = round(min(0.99, max(0.01, p)), 4)
            out.append(dict(kind="game", gid=g["gid"], league=g["league"], lg=g["lg"],
                            match=g["match"], home=g["home"], away=g["away"], tip=g.get("tip"),
                            label=L["label"], spec=L["spec"], p=p, p_model=L["p"], p_kalshi=pk,
                            p_market=round(p_mkt, 4),
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


def boosted(pay, boost):
    """What a ticket returns with a profit boost on its winnings."""
    return 1 + (pay - 1) * (1 + boost)


TIERS = (
    # name, decimal price range, rank, stop rule
    dict(tier="100", dec=(1.25, 3.0), rank=_rank_chance, chance=0.01),
    dict(tier="10k", dec=DEC_BAND, rank=_rank, pay=TARGET),
) + tuple(dict(tier=f"10k+{int(b * 100)}", boost=b, dec=DEC_BAND, rank=_rank,
               pay=1 + (TARGET - 1) / (1 + b), n=1) for b in BOOSTS)


def _tickets(legs, book, tier=TIERS[1]):
    """Up to N_TICKETS tickets of the most efficient legs for the tier: built
    up to the payout TARGET, or down to the chance (1 in 100)."""
    lo, hi = tier["dec"]
    rank = tier["rank"]
    best = {}
    for L in sorted((L for L in legs if lo <= L["dec"] <= hi), key=lambda L: -rank(L)):
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
                # so the ticket does not overshoot $10,000 at the cost of odds
                fin = [x for x in pool if x["gid"] not in used and x not in pick
                       and pay * x["dec"] >= tier["pay"]]
                L = max(fin, key=lambda x: x["p"])
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
    props = _prop_legs(prop_games, ok)
    tickets = []
    for tier in TIERS:
        # a parlay is placed at one book: FanDuel props ride with FanDuel lines
        tickets += (_tickets(games + [P for P in props if P.get("fd")], "FanDuel", tier)
                    + _tickets([P for P in props if not P.get("fd")], "DraftKings", tier))
    edge = sorted((L for L in games if L["value"] > 1), key=lambda L: -L["value"])
    return dict(tickets=tickets,
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
    book["days"].setdefault(day, dict(tickets=[]))["tickets"] += tickets
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
                if L["status"] != "open":
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
    save(book)


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
    ed = [L for L in legs if L.get("value", 0) > 1]
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
