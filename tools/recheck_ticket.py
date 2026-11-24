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


def text(flags, asof=None):
    head = f"Ticket re-check against the official NBA injury report{f' of {asof}' if asof else ''}:"
    if not flags:
        return head + " no leg affected."
    return "\n".join([head] + [f"  {lab} -- {note}" for lab, note in flags])


def main(path, day):
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
        pg = B._fd_props(slate_sheet.main(day))
        current = {(p["name"], p.get("market"), str(p.get("line"))): p.get("price") for g in pg for p in g["props"]}
        prices = price_check(legs, current) if current else []
    except Exception:
        prices = []
    return text(flags + recheck_nhl(legs, lineups) + prices, rep.get("asof"))


if __name__ == "__main__":
    import build_ticket as B
    print(main(sys.argv[1], B.resolve_day(sys.argv[2] if len(sys.argv) > 2 else None)))
