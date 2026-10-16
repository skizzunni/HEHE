"""The day's locks: the 11 likeliest bets FanDuel (New York) actually lists,
one per game, ready to add to a FanDuel slip.

"Lock" is the page's word for "the most likely result on the board", not a
promise. Each leg's probability is the same haircut, backtested and
self-tuned model the stacks use (stacks.py), and every lock is graded in
locks.json so the tab shows how locks really do.

WHAT QUALIFIES

  * A line FanDuel posts for the game right now -- moneyline, the posted
    spread or the posted total (fanduel.py reads FanDuel's own feed, so a
    leg here is a leg the FanDuel app will take). Alternate lines are not in
    that feed, so they are not offered.
  * A game that has not started.
  * Probability between LOCK_MIN and LOCK_MAX. Above ~96% a leg is usually a
    -2000 favourite that adds almost nothing to the payout while still able
    to sink the ticket.
  * One leg per game, so the legs are independent of each other.

THE ARITHMETIC THE TAB STATES PLAINLY

Eleven legs at 92% each all hit 40% of the time. A parlay of locks is not a
lock; it is a long shot with a big payout. The tab shows the true combined
chance next to every ticket.
"""
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

import fanduel
import stacks

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "locks.json")
N_LOCKS = 11
LOCK_MIN, LOCK_MAX = 0.55, 0.92        # model pre-filter only; the price decides
# Normal odds only (2026-10-16). Legs at -6000 made 11 locks pay 1.35x --
# a whole day's risk for almost nothing. A lock must be priced between -400
# and -120, and its chance is the MARKET's (FanDuel's price less its margin,
# corrected for the price-band bias the 16,000-leg backtest measured), the
# same honest rule as the lottery -- never the model's, which lost to the
# market on unseen games.
DEC_MIN, DEC_MAX = 1.25, 1.834         # -400 .. -120


def _dec(price):
    try:
        v = float(str(price).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if -100 < v < 100:
        return None
    return 1 + (v / 100 if v > 0 else 100 / -v)


def _market_p(price, two_sided_p=None):
    """The leg's chance from the market: an exactly de-vigged two-sided
    price where there is one, else FanDuel's price less its margin; then the
    backtest's price-band correction."""
    import lottery
    d = _dec(price)
    if not d:
        return None
    p = two_sided_p if two_sided_p else (1 / d) / lottery.FD_HOLD
    return round(lottery.market_chance(p), 4)
# The day's card is set at 8:00 AM Eastern and then stands: the tab shows the
# same legs all day, each with its result, instead of drifting with the odds.
# Before 8 the tab shows a preview of what the card would be right now.
CARD_HOUR = 8
ET = ZoneInfo("America/New_York")


def _unit(g, league):
    if g.kind == "poisson":
        return "runs" if league == "mlb" else "goals"
    return "points"


def fd_specs(FD, refs):
    """For stacks.candidates: every line FanDuel posts for the game -- main
    lines from the league feed plus alternate spreads, totals and team totals
    from the game's own page. `refs` collects (gid, spec) -> (ref, price, where); `where` is set
    only for alternate lines, which FanDuel's add-to-slip link gets wrong."""
    def fn(league, row, g):
        gm = fanduel.find(FD, league, g.away, g.home)
        if not gm:
            return []
        out = []

        def add(group, label, spec, ref, price=None, where=None):
            out.append((group, label, spec))
            price = price or (gm.get("px") or {}).get(ref)
            refs[(row["id"], json.dumps(spec, sort_keys=True))] = (ref, price, where)

        def team_of(name):
            if fanduel.same_team(name, g.home) or fanduel.same_team(g.home, name):
                return g.home
            if fanduel.same_team(name, g.away) or fanduel.same_team(g.away, name):
                return g.away
            return None

        unit = _unit(g, league)
        for team in (g.home, g.away):
            ref = fanduel._runner(gm["ml"], team)
            if ref:
                add("Winner", f"{team} to win", dict(t="win", team=team), ref)
            v = fanduel._runner(gm["spread"], team)
            if v and v[0] is not None:
                L = float(v[0])
                add("Spread", f"{team} {L:+g}", dict(t="spread", team=team, line=L), v[1])
        for side in ("over", "under"):
            v = gm["total"].get(side)
            if v and v[0] is not None:
                L = float(v[0])
                add("Total", f"{side.title()} {L:g} {unit}", dict(t=side, line=L), v[1])
        for kind, team, side, L, ref, price, where in fanduel.load_alts(gm):
            if kind == "total":
                add("Total", f"{side.title()} {L:g} {unit}", dict(t=side, line=L), ref, price, where)
            elif kind == "spread":
                tm = team_of(team)
                if tm:
                    add("Spread", f"{tm} {L:+g}", dict(t="spread", team=tm, line=L), ref, price, where)
            elif kind == "teamtotal":
                tm = team_of(team)
                if tm:
                    add("Team total", f"{tm} {side} {L:g} {unit}",
                        dict(t="team" + side, team=tm, line=L), ref, price, where)
        return out
    return fn


START_BUFFER = dt.timedelta(minutes=10)   # board status can lag a live game


def _eligible(row, day, now):
    """Only games that start on `day` (Eastern), at or after 8:00 AM, and at
    least START_BUFFER from now. A game with no start time is left out: it
    cannot be shown not to be live or finished. The board itself already
    drops games ESPN marks in progress or final (dashboard.collect)."""
    st = (row.get("mkt") or {}).get("start")
    if not st:
        return False
    try:
        t = dt.datetime.fromisoformat(str(st).replace("Z", "+00:00"))
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    t = t.astimezone(ET)
    if day:
        d = str(day).replace("-", "")
        if t.strftime("%Y%m%d") != d:
            return False
        floor = dt.datetime.strptime(d, "%Y%m%d").replace(hour=CARD_HOUR, tzinfo=ET)
        if t < floor:
            return False
    if row.get("state") in ("in", "post") or row.get("completed"):
        return False
    return t >= now + START_BUFFER


def build(slot_rows, soccer_keys, labels, FD, n=N_LOCKS, day=None, prop_games=None):
    now = dt.datetime.now(dt.timezone.utc)
    rows = {lg: [r for r in rs if _eligible(r, day, now)]
            for lg, rs in (slot_rows or {}).items() if lg in fanduel.PAGES}
    refs = {}
    games = stacks.candidates(rows, soccer_keys, labels, extra=fd_specs(FD, refs),
                              band=(LOCK_MIN, LOCK_MAX))
    # where games drop out, per league: on the board -> eligible by time ->
    # found in FanDuel's feed -> a FanDuel line in the probability band
    import sys
    diag = {}
    for lg, rs in (slot_rows or {}).items():
        if lg not in fanduel.PAGES:
            continue
        el = rows.get(lg) or []
        found = 0
        for r in el:
            m = r.get("mkt") or {}
            if fanduel.find(FD, lg, m.get("away"), m.get("home")):
                found += 1
        diag[lg] = [len(rs), len(el), found, len(FD.get(lg) or [])]
    print(f"locks [{day}] board/eligible/onFanDuel/FDfeed: {diag}", file=sys.stderr)
    if any(v[1] and not v[2] for v in diag.values()):
        for lg, rs in rows.items():
            for r in rs[:2]:
                m = r.get("mkt") or {}
                print(f"   unmatched? {lg}: board {m.get('away')!r} @ {m.get('home')!r}; "
                      f"FanDuel has {[(g['away'], g['home']) for g in (FD.get(lg) or [])][:3]}",
                      file=sys.stderr)
    picks = []
    for g in games:
        best = None
        for L in g["legs"]:
            ref, price, where = refs.get((g["gid"], json.dumps(L["spec"], sort_keys=True)),
                                         (None, None, None))
            d = _dec(price)
            if not ref or not d or not DEC_MIN <= d <= DEC_MAX:
                continue
            pm = _market_p(price)
            if pm and (best is None or pm > best["p"]):
                best = dict(L, fd=ref, price=price, where=where, p=pm)
        if best:
            picks.append(dict(gid=g["gid"], league=g["league"], lg=g["lg"], match=g["match"],
                              home=g["home"], away=g["away"], tip=g.get("tip"),
                              label=best["label"], spec=best["spec"], p=best["p"],
                              p_model=best["p_model"], fd=best["fd"], price=best["price"],
                              where=best["where"]))
    # FanDuel player props compete with the game lines: per game, the lock is
    # the likeliest of all of them. A prop's chance is FanDuel's own price,
    # de-vigged across both sides where it lists both (fd_props.py).
    ok = {r["id"]: r for rs in rows.values() for r in rs}
    by_gid = {x["gid"]: x for x in picks}
    for pg in prop_games or []:
        row = ok.get(pg.get("id"))
        if not row:
            continue                            # not eligible by start time
        for P in pg.get("props") or []:
            d = _dec(P.get("price"))
            if not P.get("fd") or not d or not DEC_MIN <= d <= DEC_MAX:
                continue
            # an over/under prop's p is already de-vigged across both sides
            pm = _market_p(P["price"], P["p"] if not str(P.get("line", "")).endswith("+") else None)
            if not pm:
                continue
            P = dict(P, p=pm)
            cur = by_gid.get(pg["id"])
            if cur and cur["p"] >= P["p"]:
                continue
            m = row.get("mkt") or {}
            by_gid[pg["id"]] = dict(kind="prop", gid=pg["id"], league=pg["id"].split(":", 1)[0],
                                    lg=pg.get("lg"), match=pg.get("match"), tip=pg.get("tip"),
                                    home=m.get("home"), away=m.get("away"),
                                    label=P["label"], p=P["p"], price=P["price"], fd=P["fd"],
                                    where=P.get("where"), name=P["name"], market=P["market"],
                                    line=P["line"], aid=P.get("aid"))
    picks = list(by_gid.values())
    picks.sort(key=lambda x: -x["p"])
    locks = picks[:n]
    prob = 1.0
    for L in locks:
        prob *= L["p"]
    return dict(locks=locks, available=len(picks), prob=round(prob, 4),
                fair=round(1 / prob, 2) if prob else None, sizes=sizes(locks))


def sizes(legs):
    """What the top 2, 3, 4, 5 ... legs pay at FanDuel's prices and how often
    they all hit, so the card can be played at the size you want."""
    out, pay, prob = [], 1.0, 1.0
    for i, L in enumerate(legs, 1):
        d = _dec(L.get("price"))
        if not d:
            break
        pay *= d
        prob *= L["p"]
        if i >= 2:
            out.append(dict(n=i, pays=round(pay, 2), prob=round(prob, 4),
                            american=f"+{round((pay - 1) * 100)}"))
    return out


# ------------------------------------------------------------------ record
def load():
    try:
        with open(LEDGER) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"days": {}, "legs": {}}


def save(book):
    with open(LEDGER, "w") as fh:
        json.dump(book, fh, indent=1, sort_keys=True)


def record(res, day):
    """The day's first full card of locks stands; later rebuilds only add
    legs for games that had no lock yet (a late line), up to N_LOCKS."""
    book = load()
    day = str(day)
    if len(day) == 8:
        day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    keys = book["days"].setdefault(day, [])
    for L in res["locks"]:
        if len(keys) >= N_LOCKS:
            break
        k = f'{L["gid"]}|{L["label"]}'
        if any(x.split("|", 1)[0] == L["gid"] for x in keys):
            continue
        keys.append(k)
        book["legs"].setdefault(k, dict(league=L["league"], match=L["match"], label=L["label"],
                                        spec=L.get("spec"), home=L.get("home"), away=L.get("away"),
                                        p=L["p"], status="open", date=day, gid=L["gid"],
                                        lg=L.get("lg"), tip=L.get("tip"), fd=L.get("fd"),
                                        price=L.get("price"), where=L.get("where"),
                                        kind=L.get("kind", "game"), name=L.get("name"),
                                        market=L.get("market"), line=L.get("line"),
                                        aid=L.get("aid")))
    save(book)
    # prop locks are settled from box scores by the props ledger
    props = [book["legs"][k] for k in keys if book["legs"][k].get("kind") == "prop"]
    if props:
        import props_ledger
        props_ledger.record({"tickets": {"locks": [{"legs": props}]}}, day)


def card_time(now=None):
    """True once today's card should be set (8:00 AM Eastern)."""
    now = now or dt.datetime.now(ET)
    return now.hour >= CARD_HOUR


def frozen(day):
    """The recorded card for `day`, in build()'s shape, with results."""
    day = str(day)
    if len(day) == 8:
        day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    book = load()
    legs = [dict(book["legs"][k]) for k in book["days"].get(day, []) if k in book["legs"]]
    prob = 1.0
    for L in legs:
        prob *= L["p"]
    return dict(locks=legs, available=len(legs), prob=round(prob, 4),
                fair=round(1 / prob, 2) if legs else None, set=True, day=day,
                sizes=sizes(legs))


def grade(final):
    """Settle open locks with the same final-score feed as the picks."""
    book = load()
    import props_ledger
    pl = props_ledger.load()
    for L in book["legs"].values():
        if L.get("kind") == "prop":
            if L.get("status") == "open":
                e = pl.get(props_ledger.prop_key(L))
                if e and e["status"] != "open":
                    L["status"] = "void" if e["status"] == "ungradable" else e["status"]
                    if e.get("value") is not None:
                        L["score"] = f'{e["value"]:g}'
            continue
        settle(L, final)
    save(book)


def settle(L, final):
    """Grade one open game leg (needs gid, home, away, spec) in place."""
    if L.get("status") != "open":
        return
    lg, comp = L["gid"].split(":", 1)
    res = final(lg, comp, L)
    if res and res.get("missing"):
        import ledger as _ledger
        if _ledger._stale(L):
            L["status"] = "void"
        return
    if not res or res.get("live"):
        return
    if res.get("void"):
        L["status"] = "void"
        return
    sc = res.get("scores") or {}
    h, a = sc.get(L["home"]), sc.get(L["away"])
    if not isinstance(h, int) or not isinstance(a, int):
        return
    L["status"] = "won" if stacks.predicate(L["spec"], L["home"], L["away"])(h, a) else "lost"
    L["score"] = f"{L['away']} {a} - {L['home']} {h}"


def report():
    book = load()
    legs = [L for L in book["legs"].values() if L["status"] in ("won", "lost")]
    days = []
    for day, keys in sorted(book["days"].items(), reverse=True)[:14]:
        st = [book["legs"].get(k, {}).get("status", "open") for k in keys]
        days.append(dict(day=day, n=len(keys), won=st.count("won"), lost=st.count("lost"),
                         void=st.count("void"), open=st.count("open"),
                         all_hit=bool(keys) and "lost" not in st and "open" not in st
                         and st.count("won") > 0))
    return dict(legs=len(legs), won=sum(1 for L in legs if L["status"] == "won"),
                said=round(100 * sum(L["p"] for L in legs) / len(legs), 1) if legs else None,
                days=days)
