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
import math

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
    k = 1 / fd_props.props_ledger.hold(league)
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
                players=out[:SHOW])


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


def record(games, day):
    """The top two per game go in the props ledger, graded from box scores."""
    import props_ledger
    legs = [p for g in games for p in g["players"][:2]]
    if legs:
        props_ledger.record({"tickets": {"td": [{"legs": legs}]}}, day)
