#!/usr/bin/env python3
"""Re-check a saved ticket against the latest official NBA injury report.

The ticket is built at 8 AM from the morning report, but statuses move all
day: a prop player ruled out at 5 PM stays on a saved ticket unless someone
looks again. This reads the saved legs (build_ticket.py --save) and the
latest report, and prints every leg that now needs attention:

  * a prop on a player now Out / Doubtful / Questionable (build_ticket drops
    those at build time; here they are flagged, the ticket is the user's)
  * an NBA moneyline whose team now has a top-minutes player Out / Doubtful /
    Questionable (a caution: priced in on the record, README 2026-11-24)

    python3 tools/recheck_ticket.py work/slate_nov24/ticket.json [today]
    python3 tools/recheck_ticket.py work/slate_nov24/ticket.json today --final   # by game, KEEP / CAUTION / DROP
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BAD = ("Out", "Doubtful", "Questionable")


def _same(a, b):
    """Same player across sources: same last name, and one first name starts
    with the other ('Mitch Marner' / 'Mitchell Marner', 2026-11-24 -- an exact
    match flagged Marner as missing from Vegas's lines)."""
    a, b = (a or "").lower().replace(".", "").split(), (b or "").lower().replace(".", "").split()
    if len(a) < 2 or len(b) < 2 or a[-1] != b[-1]:
        return a == b
    return a[0].startswith(b[0]) or b[0].startswith(a[0])


def recheck_nhl(legs, lineups):
    """[(label, note)] for NHL prop legs whose player is not in either team's
    projected lines (DailyFaceoff), is on the injured list, or is a game-time
    decision. lineups: [{name: note}] for the game's two teams."""
    out = []
    for L in legs:
        if L.get("lg") != "nhl" or L.get("kind") != "prop":
            continue
        pages = lineups(L.get("id")) or []
        if not any(pages):
            continue                       # page unreachable: say nothing rather than guess
        note = next((v for pg in pages for k, v in pg.items() if k != "__source__" and _same(k, L.get("player"))), None)
        src = next((pg.get("__source__") for pg in pages if pg.get("__source__")), None)
        if note is None:
            out.append((L.get("label"), f"{L.get('player')} is not in either team's projected lines"
                        + (f" ({src})" if src else "") + " -- check he is dressing"))
        elif note:
            out.append((L.get("label"), f"{L.get('player')}: {note}"))
    return out


def price_check(legs, current):
    """[(label, note)] for prop legs whose line is no longer posted, or whose
    price has moved, at FanDuel. current: {(player, market, line_text): price}.
    2026-11-24: told the user four legs had gone from FanDuel when they were
    still posted (the re-run had only chosen other players) -- look, don't guess."""
    out = []
    for L in legs:
        if L.get("kind") != "prop":
            continue
        key = (L.get("player"), L.get("market"), L.get("line_text"))
        if key not in current:
            out.append((L.get("label"), "this line is no longer posted at FanDuel"))
            continue
        now, was = current[key], L.get("price")
        try:
            moved = float(str(now).replace("+", "")) != float(str(was).replace("+", ""))
        except (TypeError, ValueError):
            moved = False
        if moved:
            out.append((L.get("label"), f"FanDuel now {now} (was {was})"))
    return out


def ml_check(legs, rows):
    """[(label, note)] for moneyline legs whose DraftKings price (ESPN) has
    moved since the ticket, with the no-vig chance now. rows: slate_sheet rows."""
    out = []
    by = {str(r.get("id")): r for r in rows or []}
    for L in legs:
        if L.get("kind") != "ml":
            continue
        r = by.get(str(L.get("id")))
        if not r or r.get("home_ml") is None or r.get("away_ml") is None:
            continue
        home = L.get("team") == r.get("home")
        now = r["home_ml"] if home else r["away_ml"]
        try:
            moved = float(now) != float(str(L.get("price")).replace("+", ""))
        except (TypeError, ValueError):
            continue
        if moved:
            mh = r.get("market_home")
            p = "" if mh is None else f", {round(100 * (mh if home else 1 - mh))}% no-vig"
            out.append((L.get("label"), f"DraftKings now {int(now):+d} (was {L.get('price')}){p}"))
    return out


def recheck(legs, status_fn, team_out_fn=None):
    """[(leg label, note)] for legs that need a look. status_fn(display name)
    -> report status or None; team_out_fn(team abbr) -> [(name, min, status)]."""
    out = []
    for L in legs:
        if L.get("lg") != "nba":
            continue
        if L.get("kind") == "prop":
            st = status_fn(L.get("player") or "")
            if st in BAD:
                out.append((L.get("label"), f"{L.get('player')} is now {st} on the official report"))
        elif L.get("kind") == "ml" and team_out_fn:
            try:
                miss = team_out_fn(L.get("team"))
            except Exception:
                miss = []
            if miss:
                out.append((L.get("label"), "caution: " + ", ".join(f"{n} ({s})" for n, _, s in miss)))
    return out


def unsubmitted(rep, mmdd, legs, rows):
    """Teams in the ticket's NBA games that the report lists as NOT YET
    SUBMITTED for the day: their players' statuses are not in yet, so 'no
    leg affected' would be false comfort (2026-11-24)."""
    ids = {str(L.get("id")) for L in legs if L.get("lg") == "nba"}
    names = {n for r in rows or [] if str(r.get("id")) in ids for n in (r.get("home_name"), r.get("away_name")) if n}
    return sorted({t for d, _, t in rep.get("not_submitted") or [] if d == mmdd and (not names or t in names)})


def text(flags, asof=None, pending=()):
    head = f"Ticket re-check against the official NBA injury report{f' of {asof}' if asof else ''}:"
    wait = [f"  {t}: report NOT YET SUBMITTED -- its players' statuses are not in; check again" for t in pending]
    if not flags and not wait:
        return head + " no leg affected."
    if not flags:
        return "\n".join([head] + wait + ["  no leg affected among the teams that have reported."])
    return "\n".join([head] + wait + [f"  {lab} -- {note}" for lab, note in flags])


def main(path, day, final=False):
    import datetime as dt
    import key_absences as K
    import nba_injury_report as R
    _, txt = R.latest()
    rep = R.parse(txt or "") if txt else {"rows": [], "asof": None}
    mmdd = dt.date.fromisoformat(day).strftime("%m/%d/%Y")
    status = {r["player"]: r["status"] for r in rep["rows"] if r["date"] == mmdd}   # report names are unique enough
    team_out = lambda abbr: K.key_missing(K.recent_minutes(abbr, day), status)
    legs = json.load(open(path))
    flags = recheck(legs, lambda n: K.status_of(n, status), team_out)
    import nhl_goalies as NG
    import urllib.request
    cache = {}

    def lineups(gid):
        if gid not in cache:
            try:
                s = json.load(urllib.request.urlopen(
                    f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/summary?event={gid}", timeout=30))
                comps = s["header"]["competitions"][0]["competitors"]
                cache[gid] = [NG.fetch_lineup(c["team"]["displayName"]) for c in comps]
            except Exception:
                cache[gid] = []
        return cache[gid]
    try:
        import build_ticket as B
        import slate_sheet
        rows = slate_sheet.main(day)
        pg = B._fd_props(rows)
        current = {(p["name"], p.get("market"), str(p.get("line"))): p.get("price") for g in pg for p in g["props"]}
        prices = (price_check(legs, current) if current else []) + ml_check(legs, rows)
    except Exception:
        prices, rows = [], []
    allf = flags + recheck_nhl(legs, lineups) + prices
    pending = unsubmitted(rep, mmdd, legs, rows)
    if final:
        games = {str(r.get("id")): r.get("game") for r in rows or []}
        out = final_text(legs, allf, games, rep.get("asof"))
        return "\n".join([f"NOTE: {t} has NOT YET SUBMITTED its injury report -- recheck before tip." for t in pending] + [out])
    return text(allf, rep.get("asof"), pending)


DROP_WORDS = ("is now Out", "is now Doubtful", "is now Questionable", "on the injured list", "no longer posted")


def verdict(notes):
    """('DROP' | 'CAUTION' | 'KEEP', reasons) for one leg's re-check notes. A
    drop follows the ticket's own build rules (a prop player Out / Doubtful /
    Questionable is left off; a line no longer posted cannot be bet); anything
    else that changed is a caution and the leg stays -- the user decides."""
    if any(w in n for n in notes for w in DROP_WORDS):
        return "DROP", notes
    if any(not n.startswith(("FanDuel now", "DraftKings now")) for n in notes):
        return "CAUTION", notes
    return "KEEP", notes


def final_text(legs, flags, games=None, asof=None):
    """The final ticket by game: each leg KEEP / CAUTION / DROP with its notes,
    then the kept count. games: {event id: 'AWAY @ HOME'}."""
    notes = {}
    for lab, note in flags:
        notes.setdefault(lab, []).append(note)
    by = {}
    for L in legs:
        by.setdefault(str(L.get("id")), []).append(L)
    out = [f"Final ticket, re-checked{f' (injury report {asof})' if asof else ''}:"]
    kept = 0
    for gid, ls in by.items():
        out.append(f"  {(games or {}).get(gid) or gid}")
        for L in ls:
            v, why = verdict(notes.get(L.get("label"), []))
            kept += v != "DROP"
            out.append(f"    {v:7} {L.get('label')}" + (f" -- {'; '.join(why)}" if why else ""))
    out.append(f"{kept} of {len(legs)} legs stay.")
    return "\n".join(out)


if __name__ == "__main__":
    import build_ticket as B
    args = [a for a in sys.argv[1:] if a != "--final"]
    print(main(args[0], B.resolve_day(args[1] if len(args) > 1 else None), final="--final" in sys.argv))
