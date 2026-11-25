#!/usr/bin/env python3
"""Re-check a saved ticket against the latest official NBA injury report.

The ticket is built at 8 AM from the morning report, but statuses move all
day: a prop player ruled out at 5 PM stays on a saved ticket unless someone
looks again. This reads the saved legs (build_ticket.py --save) and the
latest report, and prints every leg that now needs attention:

  * a prop on a player now Out / Doubtful / Questionable (build_ticket drops
    those at build time; here they are flagged, the ticket is the user's)
  * an NFL prop on a player now Out / Doubtful / Questionable on ESPN's NFL report
  * an NBA moneyline whose team now has a top-minutes player Out / Doubtful /
    Questionable (a caution: priced in on the record, README 2026-11-24)

    python3 tools/recheck_ticket.py work/slate_nov24/ticket.json [today]
    python3 tools/recheck_ticket.py work/slate_nov24/ticket.json today --final   # by game, KEEP / CAUTION / DROP
"""
import json
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BAD = ("Out", "Doubtful", "Questionable")


def _same(a, b):
    """Same player across sources: same last name, and one first name starts
    with the other ('Mitch Marner' / 'Mitchell Marner', 2026-11-24 -- an exact
    match flagged Marner as missing from Vegas's lines)."""
    import unicodedata

    def fold(x):   # accents dropped: DailyFaceoff 'Slafkovsky', the NHL 'Slafkovský'
        # and FanDuel's team tag: 'Sebastian Aho (CAR)' is Carolina's Aho (2026-11-25:
        # the tag read as his surname and he was flagged as missing from the lines)
        x = re.sub(r"\s*\([A-Za-z]{2,4}\)\s*$", "", x or "")
        return unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode().lower().replace(".", "").split()
    a, b = fold(a), fold(b)
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
            out.append((L.get("label"), "this line is no longer posted at FanDuel (pulled -- often a late scratch "
                                        "in the game being repriced; see game news)"))
            continue
        now, was = current[key], L.get("price")
        try:
            moved = float(str(now).replace("+", "")) != float(str(was).replace("+", ""))
        except (TypeError, ValueError):
            moved = False
        if moved:
            out.append((L.get("label"), f"FanDuel now {now} (was {was}){_direction(was, now)}"))
    return out


def _implied(price):
    try:
        a = float(str(price).replace("+", ""))
    except (TypeError, ValueError):
        return None
    return -a / (100 - a) if a < 0 else 100 / (100 + a)


def _direction(was, now):
    """', the market rates it less likely (92.9% -> 90.5%)' in plain words."""
    a, b = _implied(was), _implied(now)
    if a is None or b is None or a == b:
        return ""
    word = "more" if b > a else "less"
    return f", the market rates it {word} likely ({100 * a:.1f}% -> {100 * b:.1f}%)"


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
            out.append((L.get("label"), f"DraftKings now {int(now):+d} (was {L.get('price')}){p}{_direction(L.get('price'), now)}"))
    return out


def recheck(legs, status_fn, team_out_fn=None, nfl_status_fn=None):
    """[(leg label, note)] for legs that need a look. status_fn(display name)
    -> report status or None; team_out_fn(team abbr) -> [(name, min, status)];
    nfl_status_fn(display name) -> ESPN NFL report status or None (2026-11-25:
    NFL prop legs were never re-checked)."""
    out = []
    for L in legs:
        if L.get("lg") == "nfl" and L.get("kind") == "prop" and nfl_status_fn:
            st = nfl_status_fn(L.get("player") or "")
            if st in BAD:
                out.append((L.get("label"), f"{L.get('player')} is now {st} on ESPN's NFL injury report"))
            continue
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


def snapshot(legs, current, rows):
    """{leg label: current price} -- FanDuel for props, DraftKings for winners."""
    by = {str(r.get("id")): r for r in rows or []}
    snap = {}
    for L in legs:
        if L.get("kind") == "prop":
            snap[L.get("label")] = current.get((L.get("player"), L.get("market"), L.get("line_text")))
        elif L.get("kind") == "ml":
            r = by.get(str(L.get("id"))) or {}
            snap[L.get("label")] = r.get("home_ml") if L.get("team") == r.get("home") else r.get("away_ml")
    return snap


def ml_chance(legs, rows):
    """{leg label: DraftKings no-vig chance now} for moneyline legs."""
    by = {str(r.get("id")): r for r in rows or []}
    out = {}
    for L in legs:
        r = by.get(str(L.get("id"))) or {}
        if L.get("kind") == "ml" and r.get("market_home") is not None:
            out[L.get("label")] = r["market_home"] if L.get("team") == r.get("home") else 1 - r["market_home"]
    return out


def log_prices(path, legs, current, rows, now=None):
    """Append one line to price_log.jsonl beside the saved ticket: every leg's
    current price (FanDuel for props, DraftKings for winners) with the time.
    2026-11-24: prices moved a lot through the day (Hertl 1+ shots -1300 ->
    -950) and nothing kept the path, so "does a drifting price predict a
    loss?" could never be tested. This builds that history."""
    import datetime as dt
    snap = snapshot(legs, current, rows)
    rec = dict(t=(now or dt.datetime.now(dt.timezone.utc)).isoformat()[:19], prices=snap)
    out = os.path.join(os.path.dirname(os.path.abspath(path)), "price_log.jsonl")
    with open(out, "a") as f:
        f.write(json.dumps(rec) + "\n")
    return out


def game_news(legs, rows, team_out_fn, report_rows=None, mmdd=None):
    """['DET @ ORL: Detroit Pistons without Cade Cunningham (34.1 min, Out)', ...]
    -- top-minutes players out or doubtful/questionable on EITHER team of each
    NBA game on the ticket. 2026-11-24: Cade Cunningham went Out at 6:30 PM;
    the re-check only looked at ticket players, so all it said was that two
    Detroit prop lines had vanished (FanDuel repricing after the news)."""
    ids = {str(L.get("id")) for L in legs if L.get("lg") == "nba"}
    out = []
    for r in rows or []:
        if str(r.get("id")) not in ids or r.get("lg") != "nba":
            continue
        for abbr, name in ((r.get("away"), r.get("away_name")), (r.get("home"), r.get("home_name"))):
            try:
                miss = team_out_fn(abbr) or []
            except Exception:
                miss = []
            if miss:
                out.append(f"{r.get('game')}: {name or abbr} without " +
                           ", ".join(f"{n} ({m:g} min, {st})" for n, m, st in miss))
            # 2026-11-24: Orlando had Banchero, Isaac and three more out all
            # along -- long absences are not in "recent minutes", so the news
            # showed only Detroit's scratch and the Magic pick missed that both
            # sides were short. List every player Out on the report too.
            outs = sorted(x["player"].split(", ")[-1] + " " + x["player"].split(", ")[0]
                          for x in report_rows or [] if x.get("date") == mmdd and x.get("team") == name
                          and x.get("status") == "Out")
            if outs:
                out.append(f"{r.get('game')}: {name} has {len(outs)} Out on the report -- " + ", ".join(outs))
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
    with open(path) as f:
        legs = json.load(f)
    import build_ticket as BT
    nfl = BT.nfl_status() if any(L.get("lg") == "nfl" for L in legs) else {}
    flags = recheck(legs, lambda n: K.status_of(n, status), team_out, lambda n: K.status_of(n, nfl))
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
        snap = snapshot(legs, current, rows)
        try:
            log_prices(path, legs, current, rows)
        except OSError:
            pass
    except Exception:
        prices, rows, snap = [], [], None
    allf = flags + recheck_nhl(legs, lineups) + prices
    pending = unsubmitted(rep, mmdd, legs, rows)
    news = game_news(legs, rows, team_out, rep.get("rows"), mmdd)
    if final:
        games = {str(r.get("id")): r.get("game") for r in rows or []}
        try:
            import build_ticket as B
            rec = B.prop_record()
        except Exception:
            rec = {}
        out = final_text(legs, allf, games, rep.get("asof"), now_prices=snap, now_chance=ml_chance(legs, rows), record=rec)
        return "\n".join([f"NOTE: {t} has NOT YET SUBMITTED its injury report -- recheck before tip." for t in pending]
                         + [out] + (["Game news (either team, top minutes):"] + [f"  {n}" for n in news] if news else []))
    return text(allf, rep.get("asof"), pending) + ("\nGame news (either team, top minutes):\n" + "\n".join(f"  {n}" for n in news)
                                                    if news else "")


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


def final_text(legs, flags, games=None, asof=None, now_prices=None, now_chance=None, record=None):
    """The final ticket by game: each leg KEEP / CAUTION / DROP with its notes,
    then the kept count and -- when prices are known -- the kept legs' all-win
    chance and payout at the current prices (a price move can move a prop into
    another band of the record: Hertl -1300 -> -950, 2026-11-24).
    games: {event id: 'AWAY @ HOME'}."""
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
    if now_prices is not None:
        kept_legs = [L for L in legs if verdict(notes.get(L.get("label"), []))[0] != "DROP"]
        out.append(all_win_line(kept_legs, now_prices, now_chance or {}, record or {}))
        b = best_2x(leg_odds(kept_legs, now_prices, now_chance or {}, record or {}) or [])
        if b:
            out.append(f"Most likely 2x from these legs: {len(b['legs'])} legs, about {100 * b['chance']:.0f}% all win, "
                       f"pays {b['pays']:.2f}x -- " + "; ".join(_short(L, now_prices) for L in b["legs"]) + ".")
    return "\n".join(out)


def leg_odds(kept, now_prices, now_chance, record):
    """[(leg, decimal payout now, chance)] -- the chances all_win_line uses."""
    import build_ticket as B
    out = []
    for L in kept:
        price = now_prices.get(L.get("label")) or L.get("price")
        try:
            d = B._dec(price)
        except (TypeError, ValueError):
            return None
        if L.get("kind") == "prop":
            w, n = record.get((L.get("lg"), B._band(price)), (0, 0))
            c = min(B.PROP_CAP, w / n) if n >= B.RECORD_MIN else B.PROP_CAP
        else:
            c = now_chance.get(L.get("label"), 1 / d)
        out.append((L, d, c))
    return out


def best_2x(odds, target=2.0, cap=16):
    """The subset of legs paying at least `target` with the highest chance that
    all win (exhaustive up to `cap` legs). Several legs from one game may go
    together: same-game heavy props won together as often as independent ones
    (README 2026-11-24). None when even all of them do not reach it."""
    import math
    if not odds:
        return None
    if len(odds) > cap:
        return _best_cover(odds, target)
    best = None
    n = len(odds)
    for mask in range(1, 1 << n):
        pays, p = 1.0, 1.0
        for i in range(n):
            if mask >> i & 1:
                pays *= odds[i][1]
                p *= odds[i][2]
        if pays >= target and (best is None or p > best[0] or (p == best[0] and pays > best[1])):
            best = (p, pays, mask)
    if not best:
        return None
    p, pays, mask = best
    return dict(chance=p, pays=pays, legs=[odds[i][0] for i in range(n) if mask >> i & 1])


def _best_cover(odds, target):
    """best_2x for any number of legs, exactly: the cheapest cover of log
    `target` where a leg costs -log(chance) and brings log(payout).
    Branch and bound over groups of identical legs (same payout and chance --
    a fallback ticket has dozens of 87% legs at -1000, and treating them one
    by one makes the search explode), sorted by cost per unit of payout, cut
    by the fractional (greedy) bound. 2026-11-25: best_2x gave up past 16
    legs, so a 70-leg fallback ticket printed no "most likely 2x" at all."""
    import math
    W = math.log(target)
    groups = {}
    for i, (_, d, c) in enumerate(odds):
        if d > 1 and 0 < c <= 1:
            groups.setdefault((round(-math.log(c), 12), round(math.log(d), 12)), []).append(i)
    G = sorted(((c, w, ix) for (c, w), ix in groups.items()), key=lambda g: g[0] / g[1])
    if sum(w * len(ix) for _, w, ix in G) < W - 1e-12:
        return None
    best = [math.inf, None]

    def bound(k, need):
        lb = 0.0
        for c, w, ix in G[k:]:
            if w * len(ix) >= need:
                return lb + c * need / w
            lb += c * len(ix)
            need -= w * len(ix)
        return math.inf

    def go(k, cost, need, chosen):
        if need <= 1e-12:
            if cost < best[0] - 1e-12:
                best[0], best[1] = cost, list(chosen)
            return
        if k == len(G) or cost + bound(k, need) >= best[0] - 1e-12:
            return
        c, w, ix = G[k]
        top = min(len(ix), math.ceil(need / w - 1e-12))   # more than that overshoots for nothing
        for m in range(top, -1, -1):
            go(k + 1, cost + c * m, need - w * m, chosen + ix[:m])

    go(0, 0.0, W, [])
    if best[1] is None:
        return None
    idx = sorted(best[1])
    pays = math.prod(odds[i][1] for i in idx)
    return dict(chance=math.prod(odds[i][2] for i in idx), pays=pays, legs=[odds[i][0] for i in idx])


def _short(L, now_prices):
    """'Trae Young 15+ Pts + Ast at -1100 now' / 'BOS moneyline at -453 now'."""
    now = now_prices.get(L.get("label")) or L.get("price")
    now = f"{int(now):+d}" if isinstance(now, (int, float)) else now
    what = (f"{L.get('player')} {L.get('line_text')} {L.get('market')}" if L.get("kind") == "prop"
            else f"{L.get('team')} moneyline")
    return f"{what} at {now} now"


def all_win_line(kept, now_prices, now_chance, record):
    """'All 13 kept legs win: about 12% -- pays about 2.70x at current prices.'
    A prop's chance is the lower of the board cap and its band's record at the
    current price (build_ticket.apply_record's rule); a winner's is the
    no-vig chance now."""
    import build_ticket as B
    import math
    p, pays = 1.0, 1.0
    for L in kept:
        price = now_prices.get(L.get("label")) or L.get("price")
        try:
            pays *= B._dec(price)
        except (TypeError, ValueError):
            return "All-win chance at current prices: unavailable (a price is missing)."
        if L.get("kind") == "prop":
            w, n = record.get((L.get("lg"), B._band(price)), (0, 0))
            p *= min(B.PROP_CAP, w / n) if n >= B.RECORD_MIN else B.PROP_CAP
        else:
            p *= now_chance.get(L.get("label"), 1 / B._dec(price))
    return (f"All {len(kept)} kept legs win: about {100 * p:.0f}% -- pays about {pays:.2f}x at current prices. "
            "Each leg stands on its own; the size is your call.")


if __name__ == "__main__":
    import build_ticket as B
    args = [a for a in sys.argv[1:] if a != "--final"]
    print(main(args[0], B.resolve_day(args[1] if len(args) > 1 else None), final="--final" in sys.argv))
