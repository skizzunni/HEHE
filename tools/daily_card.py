"""Today's card in one message, from the published board:

    python3 tools/daily_card.py [today|tomorrow]

  1. the daily 10-leg (ten_leg.py), each leg with its own chance
  2. scorers: NFL touchdown scorers for every listed player -- anytime, 2+
     and first touchdown (td_scorers); on days with no NFL, NBA and NHL
     player props instead, likeliest first (user, 2026-11-17)
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
            + (f" -- replayed, cashed {R['cashed']} of {R['days']} days" if R.get("days") else ""))
    return [head] + [f"  {i}. {g['label']} {g.get('price') or ''} -- {pc(g['p'])} ({str(g.get('league') or '').upper()}, "
                     f"{g.get('match') or ''}{', ' + g['tip'] if g.get('tip') else ''})"
                     for i, g in enumerate(T["legs"], 1)]


def scorer_lines(D, day="today", per_game=None, top=15):
    """NFL touchdown scorers for every player when NFL plays; else the
    likeliest NBA and NHL player props."""
    td = [g for g in ((D.get("td") or {}).get(day) or []) if g.get("lg") == "NFL"]
    if td:
        out = ["NFL touchdown scorers (anytime / 2+ / first TD):"]
        for g in td:
            out.append(f"  {g['match']}{' ' + g['tip'] if g.get('tip') else ''}:")
            for x in (g.get("everyone") or g.get("players") or [])[:per_game]:
                out.append(f"    {x['name']}: {pc(x.get('p'))} / {pc(x.get('p2'))} / {pc(x.get('pfirst'))} ({x.get('price') or ''})")
        return out
    games = ((D.get("props") or {}).get(day) or {}).get("games") or []
    out = ["No NFL today -- likeliest player props instead:"]
    for lg, name in (("nba", "NBA"), ("nhl", "NHL")):
        allp = sorted((dict(p, match=g.get("match")) for g in games if str(g.get("id", "")).startswith(lg + ":")
                       for p in g.get("props") or [] if p.get("p") and p.get("plays", True)),
                      key=lambda p: (-p["p"], -(p.get("imp") or 0)))
        P, seen = [], set()
        for p in allp:                      # one prop per player: more players, not one player's ladder
            if p.get("name") in seen:
                continue
            seen.add(p.get("name"))
            P.append(p)
            if len(P) >= top:
                break
        if P:
            out.append(f"  {name}:")
            out += [f"    {p['label']} {p.get('price') or ''} -- {pc(p['p'])} ({p.get('match') or ''})" for p in P]
    return out if len(out) > 1 else ["No NFL today, and no NBA or NHL player props posted yet."]


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


def winner_lines(D, day="today"):
    out = []
    S = (D.get("slots") or {}).get(day) or {}
    for lg in sorted(S, key=lambda k: LEAGUE_ORDER.index(k) if k in LEAGUE_ORDER else 99):
        rows = [r for r in (S[lg] or {}).get("rows") or [] if r.get("mp")]
        if rows:
            out.append(f"  {lg.upper()} ({len(rows)}): " + "; ".join(
                f"{r['mp']} {r.get('mc')}%" for r in sorted(rows, key=lambda r: -(r.get("mc") or 0))))
    return (["Winners, every game (the board's pick and its chance):"] + out) if out else []


def card(D, day="today"):
    parts = [ten_leg_lines(D, day), scorer_lines(D, day), team_points_lines(D, day), winner_lines(D, day)]
    return "\n\n".join("\n".join(p) for p in parts if p)


if __name__ == "__main__":
    import line_moves
    print(card(line_moves.board(), sys.argv[1] if len(sys.argv) > 1 else "today"))
