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
            + (f" -- replayed, cashed {R['cashed']} of the last {R['days']} days" if R.get("days") else "")
            + (f" (only {T['n']} games priced so far; it fills to {ten_leg.N} at the 8 AM card)" if T["n"] < ten_leg.N else "")
            # 2026-11-20: the card was read at 8:06, before the board rebuilt on the 8 AM pool, so
            # it showed a preview (Iowa State) while the real ticket had Bowling Green
            + (" -- PREVIEW: the board has not rebuilt on the 8 AM card yet; these legs can still change"
               if X.get("preview") and day == "today" else ""))
    from ladder_ticket import needs                        # the ladder ticket's plain-words wording
    out = [head]
    Z = [z for z in X.get("sizes") or [] if z.get("days")]
    if len(Z) > 1:                                         # the trade, as on the page's 10-leg box
        out.append("  Other sizes, replayed: " + "; ".join(
            f"{z['n']} legs cashed {z['cashed']}/{z['days']}" + (f" at {z['pays']:.2f}x" if z.get("pays") else "") for z in Z)
            + " -- fewer legs win more often, pay less.")
    A = X.get("alt2x") or {}
    if A.get("n") and A.get("pays"):                       # the same lines stacked to the ladder's 2x, as on the page
        out.append(f"  The same lines to {A['pays']:.2f}x: {A['n']} legs, {pc(A.get('chance'))} stated all win"
                   + (f"; replayed, cashed {A['cashed']} of the last {A['days']} days" if A.get("days") else "") + ".")
        T2 = ten_leg.to_target(((D.get("every_game") or {}).get(day)) or [], A["pays"])
        mine = {(g.get("gid"), g.get("label")) for g in T["legs"]}
        extra = [g for g in (T2 or {}).get("legs") or [] if (g.get("gid"), g.get("label")) not in mine]
        if T2 and extra:                                   # so the 2x ticket can be placed: what it adds
            out.append("    It adds: " + "; ".join(f"{g['label']} {g.get('price') or ''} {pc(g['p'])} ({g.get('match') or ''})"
                                                    for g in extra))
        theirs = {(g.get("gid"), g.get("label")) for g in (T2 or {}).get("legs") or []}
        drop = [g for g in T["legs"] if (g.get("gid"), g.get("label")) not in theirs]
        if T2 and drop:                                    # the 10-leg fills American games first; the 2x does not
            out.append("    It leaves out: " + "; ".join(f"{g['label']} ({g.get('match') or ''})" for g in drop))
    for i, g in enumerate(sorted(T["legs"], key=_tip_key), 1):          # in start order, so it reads as the night runs
        out.append(f"  {i}. {g['label']} {g.get('price') or ''} -- {pc(g['p'])} ({str(g.get('league') or '').upper()}, "
                   f"{g.get('match') or ''}{', ' + g['tip'] if g.get('tip') else ''})")
        n = needs(g["label"], g.get("league"))
        if n and n != g["label"]:
            out.append(f"     Needs: {n}")
    return out


def _tip_key(g):
    """Sort key for a leg by its ET start ('7:30 PM'); legs without one last."""
    import datetime as dt
    try:
        return (0, dt.datetime.strptime(str(g.get("tip") or ""), "%I:%M %p").time())
    except ValueError:
        return (1, dt.time(0))


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


PER_GAME = 3          # at most this many players from one game, so the list covers the slate


def spread_games(P, top, per_game=PER_GAME):
    """The first `top` of P (likeliest first) with at most per_game from any
    one match: a 15-name list from 3 games tells less than one from 8."""
    out, seen = [], {}
    for p in P:
        m = p.get("match")
        if seen.get(m, 0) >= per_game:
            continue
        seen[m] = seen.get(m, 0) + 1
        out.append(p)
        if len(out) >= top:
            break
    return out


def _minutes_note(P, minutes_fn):
    """{label: caution} for NBA props on players under nba_minutes.LOW_MPG
    over their last 5 games (strategy lab 2026-11-23; information only)."""
    import nba_minutes
    by_game = {}
    for p in P:
        by_game.setdefault(p.get("gid"), []).append(p["name"])
    notes = {}
    for gid, names in by_game.items():
        if not gid:
            continue
        try:
            mp = minutes_fn(gid, names)
        except Exception:
            continue
        for p in P:
            m = mp.get(p["name"]) if p.get("gid") == gid else None
            if m is not None and m < nba_minutes.LOW_MPG:
                notes[p["label"]] = f" -- {m:g} min a game over his last 5: {nba_minutes.NOTE}"
    return notes


def prop_lines(D, day="today", top=15, head=None, minutes_fn=None):
    """NBA and NHL player props, one per player: his best-paying line still
    FLOOR+ likely on its own, at most PER_GAME players from one game. NBA
    props on low-minute players carry a caution (minutes_fn; None skips it)."""
    games = ((D.get("props") or {}).get(day) or {}).get("games") or []
    out = [head or f"NBA and NHL player props, one per player (his best-paying line at {round(100 * FLOOR)}%+):"]
    for lg, name in (("nba", "NBA"), ("nhl", "NHL")):
        P = best_per_player([dict(p, match=g.get("match")) for g in games if str(g.get("id", "")).startswith(lg + ":")
                             for p in g.get("props") or [] if p.get("p") and p.get("plays", True)])
        P = spread_games(P, top)
        notes = _minutes_note(P, minutes_fn) if (lg == "nba" and minutes_fn and P) else {}
        if P:
            out.append(f"  {name}:")
            out += [f"    {p['label']} {p.get('price') or ''} -- {pc(p['p'])} ({p.get('match') or ''}){notes.get(p['label'], '')}"
                    for p in P]
    return out if len(out) > 1 else []


def scorer_lines(D, day="today", per_game=None, top=15, minutes_fn=None):
    """NFL touchdown scorers for every player when NFL plays, then the NBA
    and NHL player props (user, 2026-11-17: "for nba, team points, player
    props") -- on a one-game Thursday the basketball props are most of the
    card, so they are no longer dropped when NFL plays."""
    td = [g for g in ((D.get("td") or {}).get(day) or []) if g.get("lg") == "NFL"]
    if not td:
        P = prop_lines(D, day, top, minutes_fn=minutes_fn, head=f"No NFL today -- player props instead, one per player "
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
    P = prop_lines(D, day, top, minutes_fn=minutes_fn)
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


def board_record(day, book=None):
    """(won, lost) for the board picks graded on `day` (record-excluded and
    unpriced picks left out, as the board's own record does)."""
    if book is None:
        import ledger
        book = ledger.load()
    from record_eligibility import record_priced          # the board record's own filter
    R = [e for e in book.values() if isinstance(e, dict) and e.get("date") == day
         and e.get("status") in ("won", "lost") and not e.get("record_excluded") and record_priced(e)]
    return sum(e["status"] == "won" for e in R), sum(e["status"] == "lost" for e in R)


def yesterday_lines(today_iso=None, tickets_fn=None, book=None):
    """'Yesterday (Nov 20): ladder lost, 10-leg cashed, 2x every-game lost'
    -- how the three ways to play the card did, so the morning message
    starts from the last result (daily_review.tickets_text)."""
    import datetime as dt
    if today_iso is None:
        from zoneinfo import ZoneInfo
        today_iso = dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    y = (dt.date.fromisoformat(today_iso) - dt.timedelta(days=1)).isoformat()
    if tickets_fn is None:
        from daily_review import tickets_text as tickets_fn
    t = tickets_fn(y)
    w, l = board_record(y, book)
    bits = ([f"board {w}-{l}"] if w + l else []) + ([t[len("; tickets: "):]] if t else [])
    return [f"Yesterday ({y}): " + "; ".join(bits) + "."] if bits else []


def card(D, day="today", minutes_fn=None):
    parts = [yesterday_lines() if day == "today" else [], ten_leg_lines(D, day), scorer_lines(D, day, minutes_fn=minutes_fn),
             team_points_lines(D, day), winner_lines(D, day)]
    return "\n\n".join("\n".join(p) for p in parts if p)


if __name__ == "__main__":
    import line_moves
    import nba_minutes
    print(card(line_moves.board(), sys.argv[1] if len(sys.argv) > 1 else "today", minutes_fn=nba_minutes.mpg_last5))
