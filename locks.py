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
import participation
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


def opposite(spec, home, away):
    """The spec that loses exactly when `spec` wins (ignoring pushes), so the
    pair's two FanDuel prices can be de-vigged against each other. None when
    the market has no single opposite listed (a 3-way result has two)."""
    t, L = spec.get("t"), spec.get("line")
    other = away if spec.get("team") == home else home
    if t == "over":
        return dict(t="under", line=L)
    if t == "under":
        return dict(t="over", line=L)
    if t == "teamover":
        return dict(t="teamunder", team=spec["team"], line=L)
    if t == "teamunder":
        return dict(t="teamover", team=spec["team"], line=L)
    if t == "spread" and L is not None:
        return dict(t="spread", team=other, line=-L if L else 0.0)
    if t == "dc":                                # this team or draw <-> the other team wins
        return dict(t="win", team=other)
    return None


def two_sided(refs, gid, spec, home, away, price, soccer=False):
    """(chance, how): FanDuel's price de-vigged against the opposite side's
    own price where FanDuel lists it ('two-sided'), else the price less an
    assumed 4.5% margin ('assumed margin'), which is an estimate only.
    Until 2026-10-18 every game line used the assumed margin, so legs from
    markets with different margins were compared on an uneven footing."""
    import lottery
    d = _dec(price)
    if not d:
        return None, None
    o = opposite(spec, home, away)
    if spec.get("t") == "win":
        # a 2-way moneyline's opposite is the other side; soccer's is "or draw"
        o = dict(t="dc" if soccer else "win", team=away if spec.get("team") == home else home)
    if o:
        _, op, _ = refs.get((gid, json.dumps(o, sort_keys=True)), (None, None, None))
        do = _dec(op)
        if do:
            a, b = 1 / d, 1 / do
            if 1.0 <= a + b <= 1.25:                 # a sane two-way book
                import devig
                return devig.fair_implied(a, b)[0], "two-sided"
    return (1 / d) / lottery.FD_HOLD, "assumed margin"


# how a leg's chance moves as its line rises: an over gets harder, an under
# or a spread's cushion easier
_LADDER = {"over": -1, "teamover": -1, "under": 1, "teamunder": 1, "spread": 1}


def monotone(pool):
    """Nested alternate lines in order: within one game, market and team, a
    higher Over line never gets a higher chance than a lower one (and the
    reverse for unders and spread cushions). Each price is de-vigged on its
    own, so two out-of-order prices could rank the harder line likelier;
    violators are pooled to their average (pool-adjacent-violators)."""
    groups = {}
    for L in pool:
        sp = L.get("spec") or {}
        if L.get("kind") != "prop" and sp.get("t") in _LADDER and sp.get("line") is not None:
            groups.setdefault((L["gid"], sp["t"], sp.get("team")), []).append(L)
    for (_, t, _), legs in groups.items():
        legs.sort(key=lambda L: _LADDER[t] * L["spec"]["line"])     # chance should rise along this
        blocks = []                                   # [sum, count, legs]
        for L in legs:
            blocks.append([L["p"], 1, [L]])
            while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
                b = blocks.pop()
                blocks[-1][0] += b[0]
                blocks[-1][1] += b[1]
                blocks[-1][2] += b[2]
        for tot, n, ls in blocks:
            if n > 1:
                for L in ls:
                    L["p"] = round(tot / n, 4)
                    L["ladder_fixed"] = True
    return pool


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
# per game: FanDuel's event id and the game's scheduled start, for the exact
# wager check (tickets.verify) and the pre-selection archive
QUOTED = {}


def fd_specs(FD, refs):
    """For stacks.candidates: every line FanDuel posts for the game -- main
    lines from the league feed plus alternate spreads, totals and team totals
    from the game's own page. `refs` collects (gid, spec) -> (ref, price, where); `where` is set
    only for alternate lines, which FanDuel's add-to-slip link gets wrong."""
    def fn(league, row, g):
        gm = fanduel.find(FD, league, g.away, g.home, (row.get("mkt") or {}).get("start"))
        if not gm:
            return []
        QUOTED[row["id"]] = dict(event=gm.get("id"), start=(row.get("mkt") or {}).get("start"))
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
            p2, how = two_sided(refs, g["gid"], L["spec"], g["home"], g["away"], price,
                                g["league"] in fanduel.SOCCER)
            pm = _market_p(price, p2)
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
                                 where=c["where"], devig=how,
                                 event=(QUOTED.get(g["gid"]) or {}).get("event"),
                                 start=(QUOTED.get(g["gid"]) or {}).get("start"),
                                 quoted=fanduel.quote_time(dict(id=(QUOTED.get(g["gid"]) or {}).get("event")))))
    # a FanDuel quote older than freshness.MAX_AGE_MIN, or with no time, is
    # never in a pool (props are held to the same rule below)
    import freshness
    pool = [L for L in pool if freshness.is_fresh(L.get("quoted"), now)]
    monotone(pool)
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
            if not participation.eligible(P):
                continue                        # not confirmed to play (participation.py)
            if not freshness.is_fresh(P.get("quoted"), now):
                continue                        # stale or untimed quote (freshness.py)
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
                                    p_fair=P.get("p_fair"), play=P.get("play"), plays=P.get("plays"),
                                    start=m.get("start"), devig="prop market",
                                    quoted=P.get("quoted")))
    locks, picks = choose(pool, n), _best_per_game(pool)
    locks.sort(key=_order)
    mark_ties(locks, pool)
    prob = 1.0
    for L in locks:
        prob *= L["p"]
    return dict(locks=locks, available=len(picks), prob=round(prob, 4),
                fair=round(1 / prob, 2) if prob else None, sizes=sizes(locks),
                extras=extras(pool, locks), n=n,
                # what the chooser saw, saved with the card so it can be replayed
                pool=[{k: L.get(k) for k in POOL_KEYS} for L in pool])


POOL_KEYS = ("gid", "label", "p", "kind", "league", "spec", "name", "price", "devig",
             "where", "fd", "match", "tip", "play", "plays", "market", "line", "quoted", "start", "event",
             "home", "away", "aid", "lg")
POOLS_KEPT = 14       # days of decision-time pools kept in a ledger
PER_GAME = 1          # legs from one game on a ticket (was 3 on light days: see choose)
EXTRA_PER_GAME = 2    # same-game ideas shown beside the card, never on it


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


# How far apart two legs' chances must be before their order means anything:
# one American-odds step near -400 moves a chance ~0.4 points, and a price
# de-vigged on an assumed margin is less certain still. Documented, used to
# flag ties -- NOT to rank: ranking by mid-price minus half the spread
# (tools/paired.py, the Kalshi legs' untouched days) won +3 on the regular
# window (8 vs 5 where they differed; range 0..+6) and -1 on Safe -- short of
# promotion. (First run, 2026-10-19, ranked the score model by mistake.)
UNCERT = {"two-sided": 0.004}
UNCERT_DEFAULT = 0.010
CHOOSER = "2026-10-19"      # tie-break by a fixed order (archived with each card)


def uncert(L):
    return UNCERT.get(L.get("devig"), UNCERT_DEFAULT)


def _order(L, legacy=False):
    """Likeliest first. Ties break by a fixed order -- the better-measured
    price, then game and label -- not by the order a feed listed them
    (legacy: the feed order, for cards set before 2026-10-19)."""
    if legacy:
        return (-L["p"],)
    return (-L["p"], uncert(L), str(L.get("gid")), str(L.get("label")))


def mark_ties(card, pool):
    """Flag legs at the bottom of the card whose chance is within its
    uncertainty of the best leg left out: their place is a tie, not a
    preference (2026-10-18: Colts +1.5 at 75.73% took the last NFL slot over
    Under 46.5 at 75.65%, and lost)."""
    on = {id(L) for L in card}
    used = {L["gid"] for L in card}
    rest = [L for L in pool if id(L) not in on and L["gid"] not in used]
    if not rest or not card:
        return card
    nxt = max(rest, key=lambda L: L["p"])
    for L in card:
        if L["p"] - nxt["p"] < max(uncert(L), uncert(nxt)):
            L["tie_at_cut"] = round(nxt["p"], 4)
    return card


def choose(pool, n, legacy=False):
    """The likeliest leg from each game first, but no more than MAX_SAME legs
    of one kind: same-day college unders missed together 2.6 times more than
    independent legs would (16,000-leg backtest, a high-scoring day sinks them
    all at once), so a card of nine of them is riskier than its legs say.

    Never more than one leg from a game. Until 2026-10-18 a light day filled
    the card with a second and third leg from the same game and multiplied
    their chances as if unrelated (a game's under, a player's threes and
    another player's points); same-game legs move together, so neither the
    all-hit chance nor the payout -- FanDuel prices a Same Game Parlay itself
    -- was real. A light day now shows fewer legs; standards do not drop."""
    out, used_g, kinds = [], set(), {}
    for cap in (MAX_SAME, n):                  # diversified first, then fill
        for L in sorted(pool, key=lambda x: _order(x, legacy)):
            if len(out) >= n:
                break
            if L["gid"] in used_g or kinds.get(_kind(L), 0) >= cap:
                continue
            out.append(L)
            used_g.add(L["gid"])
            kinds[_kind(L)] = kinds.get(_kind(L), 0) + 1
    return out


def extras(pool, card):
    """Other strong legs from games already on the card, for a same-game
    parlay the bettor prices at FanDuel. Not part of the card: never in its
    chance, payout, Winners parlay or Best play, and no all-hit number is
    claimed for them (there is no validated joint chance for same-game legs)."""
    on = {L["gid"] for L in card}
    used = {(L["gid"], _slot(L)) for L in card}
    count, out = {}, []
    for L in sorted(pool, key=lambda x: -x["p"]):
        k = (L["gid"], _slot(L))
        if L["gid"] not in on or k in used or count.get(L["gid"], 0) >= EXTRA_PER_GAME:
            continue
        used.add(k)
        count[L["gid"]] = count.get(L["gid"], 0) + 1
        out.append(dict(L, extra=True))
    return out


def carry_extras(live, card):
    """Same-game ideas for a set card, from this build's live pool (the
    card's legs plus the ideas beside them), against the legs it stands on."""
    pool = [dict(L, extra=False) for L in (live.get("locks") or []) + (live.get("extras") or [])]
    card["extras"] = extras(pool, card.get("locks") or [])
    return card


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
        # one leg per game: a moved line or a second idea from the same game
        # never joins the card (same-game legs are not independent)
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
                                        aid=L.get("aid"), edge=L.get("edge"),
                                        p_fair=L.get("p_fair")))
    if first and keys and res.get("pool") is not None:
        # the decision-time snapshot: the pool the card was chosen from and
        # the card as first set, so replay() can re-run the same chooser
        pools = book.setdefault("pools", {})
        pools[day] = dict(n=res.get("n") or N_LOCKS, legs=res["pool"], card=list(keys), chooser=CHOOSER,
                          t=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
        for old_day in sorted(pools)[:-POOLS_KEPT]:
            del pools[old_day]
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


def replay(day, path=None):
    """(ok, replayed keys, recorded keys) for a day with a saved pool: the
    live chooser, re-run on exactly what it saw, must give the card it set."""
    book = load(path)
    snap = (book.get("pools") or {}).get(day)
    if not snap:
        return None
    legacy = snap.get("chooser") != CHOOSER
    got = [f'{L["gid"]}|{L["label"]}' for L in sorted(choose(snap["legs"], snap["n"], legacy),
                                                      key=lambda x: _order(x, legacy))]
    return got == snap["card"], got, snap["card"]


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
        stacks.repush(L)
        if L.get("kind") == "prop":
            # open, or voided from a prop record the fixed grader has since settled
            if L.get("status") == "open" or (L.get("status") == "void" and not L.get("push")):
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
    r = stacks.settle_score(L["spec"], L["home"], L["away"], h, a)
    L["status"] = "void" if r == "push" else r       # a push leaves the slip, as at FanDuel
    if r == "push":
        L["push"] = True
    L["score"] = f"{L['away']} {a} - {L['home']} {h}"


# the card's two named plays (board.html): the biggest top-N slice that all
# hits at least this often
PLAYS = (("winners", 0.8), ("best", 0.5))


def plays(legs):
    """{name: (n, chance, result)} for the Winners parlay and Best play of a
    recorded card -- the same slice the page showed, from the same sizes().
    result is 'won', 'lost' or 'open'; a void leg drops off the slip, as at
    FanDuel. Without this the record could only say whether all 11 hit, so
    the parlay the page tells you to play was never checked."""
    sz = sizes(legs)
    out = {}
    for name, floor in PLAYS:
        z = [x for x in sz if x["prob"] >= floor]
        if not z:
            continue
        n, prob = z[-1]["n"], z[-1]["prob"]
        st = [L.get("status", "open") for L in legs[:n]]
        res = "lost" if "lost" in st else "open" if "open" in st else "won" if "won" in st else "void"
        out[name] = (n, prob, res)
    return out


def report(path=None):
    book = load(path)
    legs = [L for L in book["legs"].values() if L["status"] in ("won", "lost")]
    days, tally = [], {name: [0, 0, 0.0] for name, _ in PLAYS}
    for day, keys in sorted(book["days"].items(), reverse=True):
        card = [book["legs"].get(k, {}) for k in keys]
        st = [L.get("status", "open") for L in card]
        pl = plays(card)
        for name, (n, prob, res) in pl.items():
            if res in ("won", "lost"):
                t = tally[name]
                t[0] += 1
                t[1] += res == "won"
                t[2] += prob
        if len(days) < 14:
            days.append(dict(day=day, n=len(keys), won=st.count("won"), lost=st.count("lost"),
                             void=st.count("void"), open=st.count("open"),
                             all_hit=bool(keys) and "lost" not in st and "open" not in st
                             and st.count("won") > 0,
                             plays={k: dict(n=v[0], prob=v[1], result=v[2]) for k, v in pl.items()}))
    return dict(legs=len(legs), won=sum(1 for L in legs if L["status"] == "won"),
                said=round(100 * sum(L["p"] for L in legs) / len(legs), 1) if legs else None,
                days=days,
                plays={k: dict(days=t[0], hit=t[1], said=round(100 * t[2] / t[0], 1) if t[0] else None)
                       for k, t in tally.items()})
