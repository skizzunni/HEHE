"""Today's card in one message, from the published board:

    python3 tools/daily_card.py [today|tomorrow]

  1. the daily 10-leg (ten_leg.py), each leg with its own chance
  2. scorers: NFL touchdown scorers for every listed player -- anytime, 2+
     and first touchdown (td_scorers); then NBA and NHL player props (on
     their own when no NFL plays): one line per player, the longest-priced line
     still 80%+ likely on its own (user, 2026-11-17: "think ab the props
     individually")
  3. NBA team points: each team's main team total and the side the price leans
  4. every game's winner pick, by league

Numbers come from the page as published; nothing here is made up or
locked -- chances are chances.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p_ in (HERE, ROOT):
    if p_ not in sys.path:
        sys.path.insert(0, p_)

LEAGUE_ORDER = ("nfl", "nba", "ncaaf", "ncaab", "nhl", "mlb", "wnba", "ufc", "soccer")


def pc(v):
    return "-" if v is None else ("<1%" if 100 * v < 1 else f"{100 * v:.0f}%")


def ten_leg_lines(D, day="today"):
    import ten_leg
    X = D.get("ten_leg") or {}
    T = X.get(day) if day == "today" else None
    if not T:
        T = ten_leg.build(((D.get("every_game") or {}).get(day)) or [])
    if not T:
        return ["Daily 10-leg: not set yet (the 8 AM card sets it)."]
    R = X.get("record") or {}
    head = (f"Daily {T['n']}-leg: all win {pc(T['chance'])}" + (f", pays {T['pays']:.2f}x" if T.get("pays") else "")
            + (f" -- replayed, cashed {R['cashed']} of {R['days']} days" if R.get("days") else "")
            + (f" (only {T['n']} games priced so far; it fills to {ten_leg.N} at the 8 AM card)" if T["n"] < ten_leg.N else ""))
    from ladder_ticket import needs                        # the ladder ticket's plain-words wording
    out = [head]
    Z = [z for z in X.get("sizes") or [] if z.get("days")]
    if len(Z) > 1:                                         # the trade, as on the page's 10-leg box
        out.append("  Other sizes, replayed: " + "; ".join(
            f"{z['n']} legs cashed {z['cashed']}/{z['days']}" + (f" at {z['pays']:.2f}x" if z.get("pays") else "") for z in Z)
            + " -- fewer legs win more often, pay less.")
    for i, g in enumerate(T["legs"], 1):
        out.append(f"  {i}. {g['label']} {g.get('price') or ''} -- {pc(g['p'])} ({str(g.get('league') or '').upper()}, "
                   f"{g.get('match') or ''}{', ' + g['tip'] if g.get('tip') else ''})")
        n = needs(g["label"], g.get("league"))
        if n and n != g["label"]:
            out.append(f"     Needs: {n}")
    return out


FLOOR = 0.80          # a player's line must be at least this likely on its own


def best_per_player(props, floor=FLOOR):
    """One line per player: of his lines at `floor`+ chance, the one the book
    prices longest (lowest implied) -- the most that still has a fair chance
    by itself, not his safest 5+ Points at -10000 that pays almost nothing.
    Players with nothing at the floor are left out. Likeliest first."""
    best = {}
    for p in props:
        if (p.get("p") or 0) < floor:
            continue
        k = p.get("name")
        cur = best.get(k)
        if cur is None or (p.get("imp") or 1) < (cur.get("imp") or 1):
            best[k] = p
    return sorted(best.values(), key=lambda p: (-p["p"], p.get("imp") or 1))


def prop_lines(D, day="today", top=15, head=None):
    """NBA and NHL player props, one per player: his best-paying line still
    FLOOR+ likely on its own."""
    games = ((D.get("props") or {}).get(day) or {}).get("games") or []
    out = [head or f"NBA and NHL player props, one per player (his best-paying line at {round(100 * FLOOR)}%+):"]
    for lg, name in (("nba", "NBA"), ("nhl", "NHL")):
        P = best_per_player([dict(p, match=g.get("match")) for g in games if str(g.get("id", "")).startswith(lg + ":")
                             for p in g.get("props") or [] if p.get("p") and p.get("plays", True)])[:top]
        if P:
            out.append(f"  {name}:")
            out += [f"    {p['label']} {p.get('price') or ''} -- {pc(p['p'])} ({p.get('match') or ''})" for p in P]
    return out if len(out) > 1 else []


def scorer_lines(D, day="today", per_game=None, top=15):
    """NFL touchdown scorers for every player when NFL plays, then the NBA
    and NHL player props (user, 2026-11-17: "for nba, team points, player
    props") -- on a one-game Thursday the basketball props are most of the
    card, so they are no longer dropped when NFL plays."""
    td = [g for g in ((D.get("td") or {}).get(day) or []) if g.get("lg") == "NFL"]
    if not td:
        P = prop_lines(D, day, top, head=f"No NFL today -- player props instead, one per player "
                                         f"(his best-paying line at {round(100 * FLOOR)}%+):")
        return P or ["No NFL today, and no NBA or NHL player props posted yet."]
    n = per_game or 6
    out = ["NFL touchdown scorers -- every player is on the page's Props tab; here each game's likeliest "
           "(first TD and 2+ are model estimates; even the top first-TD scorer is usually under 20%):"]
    for g in td:
        E = g.get("everyone") or g.get("players") or []
        out.append(f"  {g['match']}{' ' + g['tip'] if g.get('tip') else ''} ({len(E)} players listed):")
        out.append("    Anytime: " + "; ".join(f"{x['name']} {pc(x.get('p'))} ({x.get('price') or ''})" for x in E[:n]))
        for key, name in (("p2", "2+ TDs"), ("pfirst", "First TD")):
            best = sorted((x for x in E if x.get(key) is not None), key=lambda x: -x[key])[:3]
            if best:
                out.append(f"    {name}: " + "; ".join(f"{x['name']} {pc(x[key])}" for x in best))
    P = prop_lines(D, day, top)
    return out + ([""] + P if P else [])


def team_points_lines(D, day="today"):
    """Each NBA team's main team total: the line priced nearest even, and
    the side the price leans to."""
    out = []
    for r in ((D.get("markets") or {}).get(day) or []):
        if r.get("lg") != "NBA":
            continue
        tt = [m for m in r.get("m") or [] if m.get("g") == "Team total" and m.get("p") is not None]
        teams = {}
        for m in tt:
            l = m.get("l") or ""
            team = l.split(" over ")[0].split(" under ")[0].split(" Over ")[0].split(" Under ")[0]
            if abs(m["p"] - 0.5) < abs((teams.get(team) or {"p": 0}).get("p", 0) - 0.5) or team not in teams:
                if m["p"] >= 0.5:
                    teams[team] = m
        if teams:
            out.append(f"  {r.get('match')}: " + "; ".join(f"{m['l']} {pc(m['p'])}" for m in teams.values()))
    return (["NBA team points (main team total, the side the price leans):"] + out) if out else []


TOSS = 55          # a winner pick under this chance is called a toss-up on the card


def _w(team, c):
    return f"{team} {c}%" + (" (toss-up)" if c is not None and c < TOSS else "")


def winner_lines(D, day="today"):
    """Every game's winner pick by league, likeliest first; picks under
    TOSS% say toss-up, so a 50% pick is not read like an 85% one."""
    out = []
    S = (D.get("slots") or {}).get(day) or {}
    for lg in sorted(S, key=lambda k: LEAGUE_ORDER.index(k) if k in LEAGUE_ORDER else 99):
        rows = sorted((r for r in (S[lg] or {}).get("rows") or [] if r.get("mp")), key=lambda r: -(r.get("mc") or 0))
        win = [r for r in rows if not str(r["mp"]).endswith(" or draw")]
        dc = [r for r in rows if str(r["mp"]).endswith(" or draw")]       # soccer double chance: a draw wins too
        if win:
            out.append(f"  {lg.upper()} ({len(win)}): " + "; ".join(_w(r["mp"], r.get("mc")) for r in win))
        if dc:
            out.append(f"  {lg.upper()} win or draw ({len(dc)}): " + "; ".join(
                _w(r["mp"][:-len(" or draw")], r.get("mc")) for r in dc))
    return (["Winners, every game (the board's pick and its chance):"] + out) if out else []


def card(D, day="today"):
    parts = [ten_leg_lines(D, day), scorer_lines(D, day), team_points_lines(D, day), winner_lines(D, day)]
    return "\n\n".join("\n".join(p) for p in parts if p)


if __name__ == "__main__":
    import line_moves
    print(card(line_moves.board(), sys.argv[1] if len(sys.argv) > 1 else "today"))
