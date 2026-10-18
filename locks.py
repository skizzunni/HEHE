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
import props_ledger
import stacks

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "locks.json")
# Safe Locks: the same card, rules and grading, built from heavy favourites
# (-2000 .. -500) beside the regular card, which keeps its -400 .. -120 rule.
# On 16,000 settled Kalshi legs the 90-100c band won 92.0% against 93.1c paid
# (spread and fee included): the best-priced band there is, so each leg's
# stated chance holds and eleven of them all hit far more often than eleven
# legs at -400 (about 8%).
SAFE_LEDGER = os.path.join(HERE, "safe_locks.json")
SAFE_DEC = (1.05, 1.20)                 # -2000 .. -500
SAFE_BAND = (0.75, 0.995)               # model pre-filter only
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


SOCCER_KINDS = {"dc"}


def fd_specs(FD, refs):
    """For stacks.candidates: every line FanDuel posts for the game -- main
    lines from the league feed plus alternate spreads, totals and team totals
    from the game's own page. `refs` collects (gid, spec) -> (ref, price, where); `where` is set
    only for alternate lines, which FanDuel's add-to-slip link gets wrong."""
    def fn(league, row, g):
        gm = fanduel.find(FD, league, g.away, g.home, (row.get("mkt") or {}).get("start"))
        if not gm:
            return []
        out = []

        def add(group, label, spec, ref, price=None, where=None):
            out.append((group, label, spec))
            price = price or (gm.get("px") or {}).get(ref)
            refs[(row["id"], json.dumps(spec, sort_keys=True))] = (ref, price, where)

        def team_of(name):
            # soccer: FanDuel's own spelling of the matched fixture's teams
            if gm.get("soccer"):
                return g.home if name == gm["home"] else g.away if name == gm["away"] else None
            if fanduel.same_team(name, g.home) or fanduel.same_team(g.home, name):
                return g.home
            if fanduel.same_team(name, g.away) or fanduel.same_team(g.away, name):
                return g.away
            return None

        unit = _unit(g, league)
        for team in (g.home, g.away):
            ref = (gm["ml"].get(gm["home"] if team == g.home else gm["away"]) if gm.get("soccer")
                   else fanduel._runner(gm["ml"], team))
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
            # soccer: only what tools/soccer_lab.py has checked against the
            # market on unseen matches -- the result and double chance (heavy
            # favourites beat their price in both halves). Totals, team totals
            # and handicaps wait for their own test.
            if gm.get("soccer") and kind not in SOCCER_KINDS:
                continue
            if kind == "total":
                add("Total", f"{side.title()} {L:g} {unit}", dict(t=side, line=L), ref, price, where)
            elif kind == "spread":
                tm = team_of(team)
                if tm:
                    add("Spread", f"{tm} {L:+g}", dict(t="spread", team=tm, line=L), ref, price, where)
            elif kind == "dc":
                tm = team_of(team)
                if tm:
                    add("Double chance", f"{tm} or draw", dict(t="dc", team=tm), ref, price, where)
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


def build(slot_rows, soccer_keys, labels, FD, n=N_LOCKS, day=None, prop_games=None,
          dec=None, band=None):
    dmin, dmax = dec or (DEC_MIN, DEC_MAX)
    now = dt.datetime.now(dt.timezone.utc)
    rows = {lg: [r for r in rs if _eligible(r, day, now)]
            for lg, rs in (slot_rows or {}).items() if fanduel.covered(lg)}
    refs = {}
    games = stacks.candidates(rows, soccer_keys, labels, extra=fd_specs(FD, refs),
                              band=band or (LOCK_MIN, LOCK_MAX))
    # where games drop out, per league: on the board -> eligible by time ->
    # found in FanDuel's feed -> a FanDuel line in the probability band
    import sys
    diag = {}
    for lg, rs in (slot_rows or {}).items():
        if not fanduel.covered(lg):
            continue
        el = rows.get(lg) or []
        found = 0
        for r in el:
            m = r.get("mkt") or {}
            if fanduel.find(FD, lg, m.get("away"), m.get("home"), m.get("start")):
                found += 1
        diag[lg] = [len(rs), len(el), found, len(FD.get(lg) or [])]
    print(f"locks [{day}] board/eligible/onFanDuel/FDfeed: {diag}", file=sys.stderr)
    if any(v[1] and not v[2] for v in diag.values()):
        for lg, rs in rows.items():
            if not (diag.get(lg) and diag[lg][1] > diag[lg][2]):
                continue                        # every eligible game matched
            for r in rs[:2]:
                m = r.get("mkt") or {}
                print(f"   unmatched? {lg}: board {m.get('away')!r} @ {m.get('home')!r}; "
                      f"FanDuel has {[(g['away'], g['home']) for g in (FD.get(lg) or [])][:3]}",
                      file=sys.stderr)
    pool = []
    for g in games:
        for L in g["legs"]:
            ref, price, where = refs.get((g["gid"], json.dumps(L["spec"], sort_keys=True)),
                                         (None, None, None))
            d = _dec(price)
            if not ref or not d or not dmin <= d <= dmax:
                continue
            pm = _market_p(price)
            if pm and L["spec"].get("t") in ("over", "under"):
                # kickoff wind on football totals (weather.py, tested both halves)
                import weather
                row_ = next((r for rs in rows.values() for r in rs if r["id"] == g["gid"]), {})
                pm = min(0.99, max(0.01, pm + weather.adjust(g["league"], row_.get("mkt") or {},
                                                             L["spec"]["t"], pm)))
            if pm:
                c = dict(L, fd=ref, price=price, where=where, p=pm)
                pool.append(dict(gid=g["gid"], league=g["league"], lg=g["lg"], match=g["match"],
                                 home=g["home"], away=g["away"], tip=g.get("tip"),
                                 label=c["label"], spec=c["spec"], p=c["p"],
                                 p_model=c["p_model"], fd=c["fd"], price=c["price"],
                                 where=c["where"]))
    # FanDuel player props compete with the game lines: per game, the lock is
    # the likeliest of all of them. A prop's chance is FanDuel's own price,
    # de-vigged across both sides where it lists both (fd_props.py).
    # props may come from any league FanDuel prices (UFC fights included),
    # not only the ones whose game lines it lists on a page
    ok = {r["id"]: r for lg, rs in (slot_rows or {}).items() for r in rs
          if _eligible(r, day, now)}
    for pg in prop_games or []:
        row = ok.get(pg.get("id"))
        if not row:
            continue                            # not eligible by start time
        for P in pg.get("props") or []:
            d = _dec(P.get("price"))
            if not P.get("fd") or not d or not dmin <= d <= dmax:
                continue
            # only markets the box score can settle: anything else would sit
            # open on the card forever and its margin is never tuned
            if not props_ledger.gradable(pg["id"].split(":", 1)[0], P["market"]):
                continue
            # an over/under prop's p is already de-vigged across both sides
            # every prop's p already carries its market's tuned margin
            # (props_ledger.hold per league and market) -- ladders included;
            # they used to be re-priced with a fixed 4.5%
            pm = _market_p(P["price"], P["p"])
            if not pm:
                continue
            # a ladder rung priced off the player's own main line (fd_props
            # consistency): where that says more than the price, use it
            # the ladder model's p_fair no longer overrides the price: when it
            # raised a chance, props won 6 of 8 (75%) against 83% shown, and
            # it made a -395 leg (Kayla Thornton 5+ points, scored 0) the top
            # lock at 89%. The market's number leads, as everywhere else.
            P = dict(P, p=pm)
            m = row.get("mkt") or {}
            pool.append(dict(kind="prop", gid=pg["id"], league=pg["id"].split(":", 1)[0],
                                    lg=pg.get("lg"), match=pg.get("match"), tip=pg.get("tip"),
                                    home=m.get("home"), away=m.get("away"),
                                    label=P["label"], p=P["p"], price=P["price"], fd=P["fd"],
                                    where=P.get("where"), name=P["name"], market=P["market"],
                                    line=P["line"], aid=P.get("aid"), edge=P.get("edge"),
                                    p_fair=P.get("p_fair")))
    locks, picks = choose(pool, n), _best_per_game(pool)
    locks.sort(key=lambda x: -x["p"])
    prob = 1.0
    for L in locks:
        prob *= L["p"]
    return dict(locks=locks, available=len(picks), prob=round(prob, 4),
                fair=round(1 / prob, 2) if prob else None, sizes=sizes(locks))


PER_GAME = 3          # legs from one game, only when games run short of n


def _slot(L):
    """What a leg is about, so one game never carries two legs on the same
    question: one total, one side (spread or moneyline), one leg per player."""
    t = (L.get("spec") or {}).get("t")
    if L.get("kind") == "prop":
        return ("player", L.get("name"))
    if t in ("over", "under"):
        return ("total",)
    return ("side",)


def _best_per_game(pool):
    best = {}
    for L in pool:
        if L["gid"] not in best or L["p"] > best[L["gid"]]["p"]:
            best[L["gid"]] = L
    return sorted(best.values(), key=lambda x: -x["p"])


MAX_SAME = 4      # legs of one kind (league + over/under/side/prop) on a card


def _kind(L):
    t = (L.get("spec") or {}).get("t") or ""
    k = ("prop" if L.get("kind") == "prop" else "under" if "under" in t
         else "over" if "over" in t else "side")
    return (L.get("league"), k)


def choose(pool, n):
    """The likeliest leg from each game first, but no more than MAX_SAME legs
    of one kind: same-day college unders missed together 2.6 times more than
    independent legs would (16,000-leg backtest, a high-scoring day sinks them
    all at once), so a card of nine of them is riskier than its legs say.
    Only when the card is still short does a game give a second or third leg
    (a light Friday), never a contradiction of a leg already taken."""
    out, used_g, kinds = [], set(), {}
    for cap in (MAX_SAME, n):                  # diversified first, then fill
        for L in sorted(pool, key=lambda x: -x["p"]):
            if len(out) >= n:
                break
            if L["gid"] in used_g or kinds.get(_kind(L), 0) >= cap:
                continue
            out.append(L)
            used_g.add(L["gid"])
            kinds[_kind(L)] = kinds.get(_kind(L), 0) + 1
    if len(out) >= n:
        return out
    used = {(L["gid"], _slot(L)) for L in out}
    count = {}
    for L in out:
        count[L["gid"]] = count.get(L["gid"], 0) + 1
    for L in sorted(pool, key=lambda x: -x["p"]):
        if len(out) >= n:
            break
        k = (L["gid"], _slot(L))
        if k in used or count.get(L["gid"], 0) >= PER_GAME:
            continue
        used.add(k)
        count[L["gid"]] = count.get(L["gid"], 0) + 1
        out.append(L)
    return out


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
def load(path=None):
    try:
        with open(path or LEDGER) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"days": {}, "legs": {}}


def save(book, path=None):
    with open(path or LEDGER, "w") as fh:
        json.dump(book, fh, indent=1, sort_keys=True)


def record(res, day, path=None, tag="locks"):
    """The day's first full card of locks stands; later rebuilds only add
    legs for games that had no lock yet (a late line), up to N_LOCKS."""
    book = load(path)
    day = str(day)
    if len(day) == 8:
        day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    keys = book["days"].setdefault(day, [])
    first = not keys
    for L in res["locks"]:
        if len(keys) >= N_LOCKS:
            break
        k = f'{L["gid"]}|{L["label"]}'
        if k in keys:
            continue
        # a moved line must not add a second leg on the same question
        same = [book["legs"][x] for x in keys if x.split("|", 1)[0] == L["gid"]]
        if (any(_slot(x) == _slot(L) for x in same) or len(same) >= PER_GAME):
            continue
        # extra legs from one game belong to the 8 AM card only; later
        # rebuilds may add a late game, never a second leg to a set card
        if same and not first:
            continue
        keys.append(k)
        book["legs"].setdefault(k, dict(league=L["league"], match=L["match"], label=L["label"],
                                        spec=L.get("spec"), home=L.get("home"), away=L.get("away"),
                                        p=L["p"], status="open", date=day, gid=L["gid"],
                                        lg=L.get("lg"), tip=L.get("tip"), fd=L.get("fd"),
                                        price=L.get("price"), where=L.get("where"),
                                        kind=L.get("kind", "game"), name=L.get("name"),
                                        market=L.get("market"), line=L.get("line"),
                                        aid=L.get("aid"), edge=L.get("edge"),
                                        p_fair=L.get("p_fair")))
    save(book, path)
    # prop locks are settled from box scores by the props ledger
    props = [book["legs"][k] for k in keys if book["legs"][k].get("kind") == "prop"]
    if props:
        import props_ledger
        props_ledger.record({"tickets": {tag: [{"legs": props}]}}, day)


def card_time(now=None):
    """True once today's card should be set (8:00 AM Eastern)."""
    now = now or dt.datetime.now(ET)
    return now.hour >= CARD_HOUR


def frozen(day, path=None):
    """The recorded card for `day`, in build()'s shape, with results."""
    day = str(day)
    if len(day) == 8:
        day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    book = load(path)
    legs = [dict(book["legs"][k]) for k in book["days"].get(day, []) if k in book["legs"]]
    prob = 1.0
    for L in legs:
        prob *= L["p"]
    return dict(locks=legs, available=len(legs), prob=round(prob, 4),
                fair=round(1 / prob, 2) if legs else None, set=True, day=day,
                sizes=sizes(legs))


def grade(final, path=None):
    """Settle open locks with the same final-score feed as the picks."""
    book = load(path)
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
    save(book, path)


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


def report(path=None):
    book = load(path)
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
