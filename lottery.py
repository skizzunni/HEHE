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

import locks
import props_ledger
import stacks

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "lottery.json")
TARGET = 10000.0            # payout multiple a ticket is built to reach
MAX_LEGS = 14
N_TICKETS = 3               # per book, built from disjoint games
GAME_BAND = (0.15, 0.62)    # model chance of a game leg
DEC_BAND = (1.65, 6.0)      # -154 .. +500: real plus-money legs, no moonshots


def decimal(price):
    try:
        v = float(str(price).replace("+", "").strip())
    except (TypeError, ValueError):
        return None
    if -100 < v < 100:
        return None
    return 1 + (v / 100 if v > 0 else 100 / -v)


def _game_legs(rows, soccer_keys, labels, FD):
    refs = {}
    games = stacks.candidates(rows, soccer_keys, labels, extra=locks.fd_specs(FD, refs),
                              band=GAME_BAND)
    out = []
    for g in games:
        for L in g["legs"]:
            ref, price, where = refs.get((g["gid"], json.dumps(L["spec"], sort_keys=True)),
                                         (None, None, None))
            d = decimal(price)
            if not ref or not d or not DEC_BAND[0] <= d <= DEC_BAND[1]:
                continue
            out.append(dict(kind="game", gid=g["gid"], league=g["league"], lg=g["lg"],
                            match=g["match"], home=g["home"], away=g["away"], tip=g.get("tip"),
                            label=L["label"], spec=L["spec"], p=L["p"], price=price,
                            dec=round(d, 3), fd=ref, where=where,
                            value=round(L["p"] * d, 4)))
    return out


def _prop_legs(prop_games, ok_gids):
    out = []
    for g in prop_games or []:
        if g["id"] not in ok_gids:
            continue
        lg = g["id"].split(":", 1)[0]
        for P in g.get("props") or []:
            d = decimal(P.get("price"))
            if not d or not DEC_BAND[0] <= d <= DEC_BAND[1] or not P.get("aid"):
                continue
            if not props_ledger.gradable(lg, P["market"]):
                continue
            out.append(dict(P, kind="prop", gid=g["id"], league=lg, lg=g["lg"],
                            match=g["match"], tip=g.get("tip"), dec=round(d, 3),
                            value=round(P["p"] * d, 4)))
    return out


def _rank(L):
    """A ticket's chance is the product of its legs' values divided by its
    payout, so for a fixed payout the best leg is the one that gives up the
    least value per unit of payout it adds: log(value) / log(price)."""
    return math.log(L["value"]) / math.log(L["dec"])


def _tickets(legs, book):
    """Up to N_TICKETS tickets of the most efficient legs, each reaching TARGET."""
    best = {}
    for L in sorted(legs, key=lambda L: -_rank(L)):
        best.setdefault(L["gid"], L)            # one leg per game: its best
    pool = sorted(best.values(), key=lambda L: -_rank(L))
    used, made = set(), []
    for _ in range(N_TICKETS):
        pick, pay = [], 1.0
        for L in pool:
            if L["gid"] in used:
                continue
            pick.append(L)
            pay *= L["dec"]
            if pay >= TARGET or len(pick) >= MAX_LEGS:
                break
        if pay < TARGET:
            break
        used.update(L["gid"] for L in pick)
        prob = 1.0
        for L in pick:
            prob *= L["p"]
        made.append(dict(book=book, legs=pick, pays=round(pay), prob=prob,
                         odds=round(1 / prob) if prob else None))
    return made


def build(slot_rows, soccer_keys, labels, FD, prop_games=None, day=None):
    now = dt.datetime.now(dt.timezone.utc)
    rows = {lg: [r for r in rs if locks._eligible(r, day, now)]
            for lg, rs in (slot_rows or {}).items()}
    ok = {r["id"] for rs in rows.values() for r in rs}
    fd_rows = {lg: rs for lg, rs in rows.items() if lg in locks.fanduel.PAGES}
    games = _game_legs(fd_rows, soccer_keys, labels, FD)
    props = _prop_legs(prop_games, ok)
    return dict(tickets=_tickets(games, "FanDuel") + _tickets(props, "DraftKings"),
                pool=dict(games=len({L["gid"] for L in games}), props=len(props)))


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
    if book["days"].get(day) or not res.get("tickets"):
        return
    tickets = []
    for t in res["tickets"]:
        legs = [dict(L, status="open", date=day) for L in t["legs"]]
        tickets.append(dict(t, legs=legs))
    book["days"][day] = dict(tickets=tickets)
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
                    e = pl.get(f'{L["gid"]}|{L["aid"]}|{L["market"]}|{L["line"]}')
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
    return dict(legs=len(legs), won=sum(L["status"] == "won" for L in legs),
                said=round(100 * sum(L["p"] for L in legs) / len(legs), 1) if legs else None,
                tickets=len(done), hits=sum(t["status"] == "won" for t in done),
                days=[dict(day=k, n=len(v["tickets"]),
                           won=sum(t.get("status") == "won" for t in v["tickets"]),
                           best=max([sum(L["status"] == "won" for L in t["legs"])
                                     for t in v["tickets"]] or [0]),
                           open=sum(t.get("status", "open") == "open" for t in v["tickets"]))
                      for k, v in sorted(book["days"].items(), reverse=True)[:14]])
