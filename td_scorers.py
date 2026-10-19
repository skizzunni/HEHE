"""Who scores a touchdown, for every NFL (and college) game on the board.

The most accurate public read on a player's touchdown chance is FanDuel's
anytime-TD market: it already prices red-zone role, injuries, matchup and
game script. Its weakness is the margin, which on one-sided TD markets is
large and uneven. So the chances are made to add up to the game itself:

  * each listed player's price -> an expected touchdown count
        lam_i = -ln(1 - implied_i)
  * the game's expected offensive touchdowns from its posted total
        TD_PER_POINT * total  (minus the small share defences and returners score)
  * every lam_i scaled so they sum to that, and back to a chance
        p_i = 1 - exp(-lam_i * k)

That removes the margin in one consistent step and ties every player's number
to how much scoring the game is expected to have. Picks are recorded in the
props ledger and graded from the box score like every other prop.
"""
import json
import math
import os

import fanduel
import fd_props

LEAGUES = {"nfl": 0.105, "ncaaf": 0.11}   # touchdowns per point of posted total
NON_OFFENSE = 0.04                         # defensive / return touchdowns
SHOW = 6                                   # players listed per game
MARKET = "Anytime Touchdown Scorer"


def for_game(row, league, FD):
    m = row.get("mkt") or {}
    g = fanduel.find(FD, league, m.get("away"), m.get("home"))
    if not g:
        return None
    props = [p for p in fd_props.for_game(g, league)
             if p.get("market") == MARKET and str(p.get("line")) == "1+" and p.get("imp")]
    if len(props) < 4:
        return None
    lam = [-math.log(max(1e-6, 1 - min(p["imp"], 0.95))) for p in props]
    try:
        total = float(m.get("total"))
    except (TypeError, ValueError):
        total = None
    # never scale a chance up: a short player list would otherwise inflate
    # everyone to cover touchdowns scored by players FanDuel does not list
    k = 1 / fd_props.props_ledger.hold(league, MARKET)
    basis = "FanDuel margin removed"
    if total:
        target = LEAGUES[league] * total * (1 - NON_OFFENSE)
        if target / sum(lam) < k:
            k = target / sum(lam)
            basis = f"scaled to {target:.1f} expected touchdowns (total {total:g})"
    out = []
    for p, l in zip(props, lam):
        q = 1 - math.exp(-l * k)
        out.append(dict(p, p=round(q, 4), gid=row["id"], label=f'{p["name"]}: anytime TD'))
    out.sort(key=lambda x: -x["p"])
    return dict(id=row["id"], lg=league.upper() if league == "nfl" else "NCAA FB",
                match=row.get("label", ""), tip=row.get("tip"), total=total, basis=basis,
                players=out[:SHOW], everyone=out)


def for_slot(board_slot):
    try:
        FD = fanduel.load()
    except Exception:
        return []
    games = []
    for league in LEAGUES:
        for row in (board_slot or {}).get(league) or []:
            try:
                g = for_game(row, league, FD)
            except Exception:
                g = None
            if g:
                games.append(g)
    # NFL first, then by start time
    games.sort(key=lambda g: (g["lg"] != "NFL", g.get("tip") or ""))
    return games


HISTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "td_history.json")


def _load():
    try:
        with open(HISTORY) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def log(games, day):
    """Every listed player's chance, every game, at the latest price before
    kickoff -- ESPN wipes prop prices once a game is over, so this is the only
    way to build a touchdown history to test methods and player form on."""
    book = _load()
    day = str(day)
    if len(day) == 8:
        day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    for g in games:
        for p in g.get("everyone") or []:
            k = f'{g["id"]}|{p["name"]}'
            e = book.get(k)
            if e and e.get("status") != "open":
                continue
            book[k] = dict(gid=g["id"], name=p["name"], date=day, imp=p["imp"], p=p["p"],
                           price=p["price"], total=g.get("total"), status="open")
    with open(HISTORY, "w") as fh:
        json.dump(book, fh, indent=0, sort_keys=True)


def grade():
    """Settle logged touchdown chances from ESPN box scores."""
    import props_ledger as PL
    book = _load()
    # once: entries graded before 2026-10-19 by exact name only (a spelling
    # difference read as a DNP) or with no rushing/receiving line (ungradable)
    for e in book.values():
        if e["status"] in ("void", "ungradable") and not e.get("rechecked"):
            e["rechecked"] = e["status"]
            e["status"] = "open"
    open_by = {}
    for k, e in book.items():
        if e["status"] == "open":
            open_by.setdefault(e["gid"], []).append(e)
    for gid, es in list(open_by.items())[:40]:
        league, eid = gid.split(":", 1)
        sm = PL.summary(league, eid)
        if not sm or not sm.get("completed"):
            continue
        st = PL.box_stats(sm)
        fn = PL.MARKETS[league][MARKET]
        for e in es:
            # the props ledger's resolver: id / name / alias / surname + first
            # name; only a surname nowhere in the box is a did-not-play
            s_, how = PL.resolve(st, dict(name=e["name"]))
            if how == "absent":
                e["status"] = "void"
                continue
            if s_ is None:
                e["status"] = "ungradable"          # ambiguous name: set aside, not a DNP
                e["void_why"] = "identity_unresolved"
                continue
            v = fn(s_)
            e["status"] = "ungradable" if v is None else ("won" if v >= 1 else "lost")
    with open(HISTORY, "w") as fh:
        json.dump(book, fh, indent=0, sort_keys=True)


def record(games, day):
    """The top two per game go in the props ledger, graded from box scores."""
    import props_ledger
    legs = [p for g in games for p in g["players"][:2]]
    if legs:
        props_ledger.record({"tickets": {"td": [{"legs": legs}]}}, day)
