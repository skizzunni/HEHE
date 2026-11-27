#!/usr/bin/env python3
"""The user's daily ticket, laid out by game, every leg judged on its own.

User, 2026-11-23, after a 21-leg ticket lost on the Thunder, Raptors and
Cavaliers moneylines, LaMelo Ball 4+ assists and the Bengals: "dont think of
it as a parlay think of it as individually ... same kind of legs but lets get
it right". A leg goes on only if it passes every check below; every leg left
off is listed with the reason.

Winners (NBA, NFL, NHL moneylines from the board):
  * the board's chance is MIN_WIN (75%) or more          -- Thunder were 63%
  * key players Out / Doubtful / Questionable (tools/key_absences.py) are SHOWN as a
    caution, not cut: tested 2026-11-24 on 174 board NBA picks, the side missing
    a key player won 76% then 73% vs 66%, 69% stated -- the price counts it
  * our price-blind number does not favour the other side -- Cavaliers: blind had them by 4 vs -8.5
Props (the card's ~87% lines, one per player, at most PER_GAME per game):
  * the player is not Out / Doubtful / Questionable on the official report
  * flagged, not cut: a game with an 80%+ favourite (blowout minutes; LaMelo)

    python3 tools/build_ticket.py                    # today
    python3 tools/build_ticket.py 2026-11-24 --save work/slate_nov24/ticket.json
"""
import datetime as dt
import json
import math
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ET = ZoneInfo("America/New_York")
MIN_WIN = 75
WIN_LEAGUES = ("nba", "nfl", "nhl")
PROP_FLOOR = 0.85
PROP_CAP = 0.8727      # FanDuel props read at most this (props_ledger.cap) -- the ticket's stated prop chance
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PER_GAME = 3
BLOWOUT = 80
STAT = {"Points": "PTS", "Rebounds": "REB", "Assists": "AST", "Threes Made": "3PM", "Pts + Ast": "PTS+AST",
        "Pts + Reb": "PTS+REB", "Reb + Ast": "REB+AST", "Pts + Reb + Ast": "PTS+REB+AST", "Steals": "STL", "Blocks": "BLK"}


BANDS = ((-500, -300), (-1000, -500), (-1500, -1000), (-2500, -1500), (-10 ** 6, -2500))
RECORD_MIN = 100


def prop_record(props=None):
    """{(league, band): (won, n)} for graded board props (props.json) by
    American-price band. 2026-11-24: FanDuel's straight props all read 87%
    (the cap), while the record at those prices is about 85% -- the ticket's
    all-win chance should use what props like it have actually done."""
    if props is None:
        try:
            props = json.load(open(os.path.join(ROOT, "props.json")))
        except (OSError, ValueError):
            return {}
    out = {}
    for e in props.values():
        if not isinstance(e, dict) or e.get("status") not in ("won", "lost"):
            continue
        b = _band(e.get("price"))
        if b is None:
            continue
        w, n = out.get((e.get("league"), b), (0, 0))
        out[(e.get("league"), b)] = (w + (e["status"] == "won"), n + 1)
    return out


def _band(price):
    try:
        a = float(str(price).replace("+", ""))
    except (TypeError, ValueError):
        return None
    return next((b for b in BANDS if b[0] < a <= b[1]), None)


def apply_record(t, record):
    """Each prop leg's chance becomes the lower of its stated chance and the
    record for its league and price band (RECORD_MIN+ graded), labelled."""
    for L in (x for g in t["games"].values() for x in g):
        if L["kind"] != "prop":
            continue
        w, n = record.get((L.get("lg"), _band(L.get("price"))), (0, 0))
        if n >= RECORD_MIN:
            rate = w / n
            L["label"] += f" [props like it {100 * rate:.0f}% on {n:,}]"
            L["chance"] = min(L["chance"], rate)
    return t


def _dec(price):
    a = float(str(price).replace("+", ""))
    return 1 + (a / 100 if a > 0 else 100 / -a)


def judge_winner(row, key_out, blind_pick_p):
    """(ok, reason) for one board winner. key_out: [(name, min, status)] for
    the picked team; blind_pick_p: our price-blind chance for the picked side
    (None when there is no number)."""
    c = row.get("mc") or 0
    if c < MIN_WIN:
        return False, f"board chance {c}% is under {MIN_WIN}%"
    if blind_pick_p is not None and blind_pick_p < 0.5:
        return False, f"our own number favours the other side ({round(100 * blind_pick_p)}% for this pick)"
    # Key players out is a caution, not a cut: on 174 graded board NBA picks the
    # side missing a top-6 player won 76% then 73% vs 66%, 69% stated (README
    # 2026-11-24) -- the price already counts the absence.
    miss = [f"{n} ({s})" for n, m, s in key_out if s in ("Out", "Doubtful", "Questionable")]
    return True, ("caution: " + ", ".join(miss) + " -- priced in on the record so far") if miss else ""


def judge_prop(p, status):
    """(ok, reason, caution) for one card prop; status from the official report."""
    if status in ("Out", "Doubtful", "Questionable"):
        return False, f"{status} on the official injury report", ""
    return True, "", ""


LOCK_NOTE = " [Prop Lock: confirmed playing; Prop Locks hit 93% then 94% vs ~87% stated]"


def build(rows_by_lg, props_games, key_out_fn, blind_fn, status_fn, fav_fn, prop_locks=(), b2b_fn=None, minutes_fn=None,
          logs_fn=None):
    """Pure core: returns {"games": {match: [legs]}, "left_off": [(label, reason)]}.
    key_out_fn(row) -> [(name, min, status)]; blind_fn(row) -> p or None;
    status_fn(player) -> report status or None; fav_fn(gid) -> favourite chance %."""
    import daily_card
    games, left = {}, []
    for lg in WIN_LEAGUES:
        for r in sorted(rows_by_lg.get(lg) or [], key=lambda r: -(r.get("mc") or 0)):
            if not r.get("mp") or not r.get("p"):
                continue
            ok, why = judge_winner(r, key_out_fn(r), blind_fn(r))
            label = f"{r['mp']} moneyline {r['p']} ({r.get('mc')}%)" + (f" -- {why}" if ok and why else "")
            if ok and b2b_fn and b2b_fn(r):
                label += " -- caution: second night of a back-to-back (priced in on the record)"
            if ok:
                games.setdefault(r.get("match") or r["id"], []).append(dict(
                    label=label, id=str(r["id"]).split(":")[-1], lg=lg, kind="ml", team=r.get("abbr") or r["mp"],
                    price=r["p"], chance=r["mc"] / 100, gid=r["id"]))
            elif (r.get("mc") or 0) >= MIN_WIN - 15:
                left.append((label, why))
    for g in props_games:
        pool = [dict(p, match=g.get("match")) for p in g.get("props") or [] if p.get("plays", True)]
        cand = (safest_per_player(pool, str(g.get("id")).split(":")[0]) if SAFEST_MODE["on"]
                else daily_card.best_per_player(pool, floor=PROP_FLOOR))
        # the day's Prop Locks first (player confirmed to play): 93.0% then 93.9%
        # vs ~87% stated by date half (z +1.89, +3.05; README 2026-11-24) -- an
        # ordering and a label, not a cut
        locks = {k for k in prop_locks}
        cand = sorted(cand, key=lambda p: (p["name"] not in locks,))
        n = 0
        for p in cand:
            if n >= PER_GAME:
                break
            ok, why, _ = judge_prop(p, status_fn(p["name"]))
            label = f"{p['label']} {p.get('price') or ''} ({round(100 * p['p'])}%)"
            if not ok:
                left.append((label, why))
                continue
            caution = (LOCK_NOTE if p["name"] in locks else "") + (
                " -- caution: big favourite in this game (blowout minutes)" if (fav_fn(g["id"]) or 0) >= BLOWOUT else "")
            games.setdefault(g.get("match") or g["id"], []).append(dict(
                label=label + caution, id=str(g["id"]).split(":")[-1], lg=str(g["id"]).split(":")[0], kind="prop",
                player=p["name"], stat=STAT.get(p.get("market"), p.get("market")), market=p.get("market"),
                line_text=str(p.get("line", "")),
                line=float(str(p.get("line", "0")).rstrip("+") or 0), price=p.get("price"), chance=p["p"], gid=g["id"]))
            n += 1
        _minutes_caution(games.get(g.get("match") or g["id"]) or [], g["id"], minutes_fn)
        _l10_caution(games.get(g.get("match") or g["id"]) or [], g["id"], logs_fn)
    return dict(games=games, left_off=left)


def _l10_caution(legs, gid, logs_fn):
    """Adds a caution to NBA prop legs whose player reached the line in under
    70% of his last 10 games (2026-11-24: 2,749 graded heavy NBA props, leak-free
    -- under 70% hit 81.5% then 82.4% vs 85% stated, z -1.16 / -0.83: short in
    both date halves but weak, so a caution, never a cut; README)."""
    import nba_minutes as M
    props = [L for L in legs if L["kind"] == "prop" and L.get("lg") == "nba"]
    if not props or not logs_fn:
        return
    try:
        logs = logs_fn(gid, sorted({L["player"] for L in props})) or {}
    except Exception:
        return
    for L in props:
        if L["player"] not in logs:
            # say so rather than skip in silence (2026-11-25: 'Jabari Smith'
            # never matched ESPN's 'Jabari Smith Jr.' and nobody could tell)
            L["label"] += " -- note: no ESPN game log found, last-10 check skipped"
            continue
        h = M.last10_hits(logs.get(L["player"]) or [], L.get("market"), L.get("line") or 0)
        if h and h[0] / h[1] < M.L10_LOW:
            L["label"] += f" -- caution: reached it in {h[0]} of his last {h[1]} ({M.L10_NOTE})"


def _minutes_caution(legs, gid, minutes_fn):
    """Adds the daily card's low-minutes caution to this game's NBA prop legs
    (tools/nba_minutes.py: under 20 min a game over his last 5 -> such props hit
    72% vs 84% stated; past the 2.8 bar in one date half only, so a caution,
    never a cut). 2026-11-24: the card showed it, the user's ticket did not."""
    import nba_minutes
    props = [L for L in legs if L["kind"] == "prop" and L.get("lg") == "nba"]
    if not props or not minutes_fn:
        return
    try:
        mp = minutes_fn(gid, sorted({L["player"] for L in props})) or {}
    except Exception:
        return
    for L in props:
        m = mp.get(L["player"])
        if m is not None and m < nba_minutes.LOW_MPG:
            L["label"] += f" -- caution: {m:g} min a game over his last 5 ({nba_minutes.NOTE})"


def resolve_day(arg, now=None):
    """ISO date from the command line: none / 'today' / 'tomorrow' / YYYY-MM-DD
    (ET). 2026-11-24: the morning routine runs `build_ticket.py today` and
    the literal 'today' crashed the fallback deep in the price-blind model."""
    base = (now or dt.datetime.now(ET)).astimezone(ET).date()
    if not arg or arg == "today":
        return base.isoformat()
    if arg == "tomorrow":
        return (base + dt.timedelta(days=1)).isoformat()
    return dt.date.fromisoformat(arg).isoformat()


def two_x_text(legs):
    """'Most likely 2x from these legs: ...' -- the subset of the ticket's legs
    paying 2x+ with the highest all-win chance (recheck_ticket.best_2x; legs
    from one game may go together). '' when nothing reaches 2x."""
    import recheck_ticket as R
    try:
        odds = [(L, _dec(L["price"]), L["chance"]) for L in legs]
    except (KeyError, TypeError, ValueError):
        return ""
    b = R.best_2x(odds)
    if not b or len(b["legs"]) == len(legs):
        return ""
    out = (f"Most likely 2x from these legs: {len(b['legs'])} legs, about {100 * b['chance']:.0f}% all win, "
           f"pays {b['pays']:.2f}x -- " + "; ".join(L["label"].split(" (")[0] for L in b["legs"]) + ".")
    if all(L.get("kind") == "ml" for L in b["legs"]):
        out += FAV_2X_NOTE
    return out


# 2026-11-27: the wide ticket's 2x was three -378 to -395 favourites (DET, BOS,
# POR) -- the user, Nov 25: "favorites be losing us hella slips bc u always just
# pick them". Board moneylines at a 75-80% market chance won 68 of 82 (34/41 in
# each date half), so each leg holds up; stacking them is what loses slips.
FAV_2X_NOTE = (" Note: every leg is a favourite's moneyline -- board moneylines at a 75-80% market chance"
               " won 68 of 82 (83%, 34/41 in each half), so one upset in any of them loses the whole 2x.")


SHORT_LEGS = 6
# replayed 2026-11-27 on 38 graded prop days (props at -1000 or shorter, the
# shortest price in each game, the 6 shortest): README
SHORT_RECORD = (" Replayed on 38 past days: all 6 won on 23 (10/19 then 13/19), paying 1.24x then 1.10x on"
                " average; six such legs taken at random won together 41% then 47% of the time. It still lost"
                " money: a $1 ticket every day returned -34% then -27% (3 legs -10% / -14%, 10 legs -64% / -38%)"
                " -- legs this short pay too little to cover one miss.")


def short_text(t, n=SHORT_LEGS):
    """'Short ticket: the 6 safest legs, one per game ...' when the ticket is
    much longer. 2026-11-27: the safest ticket for Nov 27 had 58 legs -- all
    win about 1 in 3,000 -- and Nov 24-26 every long ticket lost by one or two
    legs; the shortest version of it was nowhere on the page. Information
    only: the full ticket is unchanged."""
    best = []
    for legs in t["games"].values():
        try:
            g = sorted(legs, key=lambda L: (-L["chance"], _dec(L["price"])))
        except (KeyError, TypeError, ValueError):
            continue
        if g:
            best.append(g[0])
    if len(best) < n or sum(len(v) for v in t["games"].values()) < 2 * n:
        return ""
    pick = sorted(best, key=lambda L: (-L["chance"], _dec(L["price"])))[:n]
    allwin = math.prod(L["chance"] for L in pick)
    pays = math.prod(_dec(L["price"]) for L in pick)
    return (f"Short ticket: the {n} safest legs, one per game -- about {100 * allwin:.0f}% all win, pays about "
            f"{pays:.2f}x -- " + "; ".join(L["label"].split(" (")[0] for L in pick) + "." + SHORT_RECORD)


def ticket_legs(t):
    """The ticket's legs in tools/grade_picks.py's file format (what --save writes)."""
    return [{k: v for k, v in L.items() if k not in ("chance", "gid")} for g in t["games"].values() for L in g]


def chance_text(p):
    """'about 35%', or 'about 1 in 17,000' under 1% -- 2026-11-25: a 70-leg
    ticket read 'about 0%', which says impossible rather than how unlikely."""
    if p >= 0.01:
        return f"about {100 * p:.0f}%"
    if p <= 0:
        return "about 0%"
    n = 1 / p
    mag = 10 ** max(0, len(str(int(n))) - 2)
    return f"about 1 in {int(round(n / mag) * mag):,}"


def kickoff_et(start):
    """'2026-11-26T18:00Z' -> 'Thu 1:00 PM ET'; '' when unreadable."""
    try:
        t = dt.datetime.fromisoformat(str(start).replace("Z", "+00:00")).astimezone(ET)
    except ValueError:
        return ""
    return t.strftime("%a %I:%M %p ET").replace(" 0", " ")


def text(t):
    legs = [L for g in t["games"].values() for L in g]
    out = ([f"NOTE: {t['note']}"] if t.get("note") else []) + [f"Your ticket, by game -- {len(legs)} legs, each judged on its own:"]
    for match, L in t["games"].items():
        out.append(f"  {match}" + (f" -- {kickoff_et(t['starts'][match])}" if (t.get("starts") or {}).get(match) else ""))
        out += [f"    {x['label']}" for x in L]
    if legs:
        allwin = math.prod(x["chance"] for x in legs)
        try:
            pays = math.prod(_dec(x["price"]) for x in legs)
            out.append(f"All {len(legs)} win: {chance_text(allwin)} -- pays about {pays:.2f}x as one ticket. "
                       f"Each leg stands on its own; the size is your call.")
        except (TypeError, ValueError):
            out.append(f"All {len(legs)} win: {chance_text(allwin)}.")
    short = short_text(t)
    if short:
        out.append(short)
    if t.get("ladder"):
        out.append(t["ladder"])
    two = two_x_text(legs)
    if two:
        out.append(two)
    elif legs:
        # 2026-11-25: the safest ticket (9 legs near -1450) printed no 2x line at
        # all, so it read as if one had been forgotten -- say why there is none
        try:
            pays = math.prod(_dec(x["price"]) for x in legs)
        except (TypeError, ValueError):
            pays = None
        if pays is not None and pays < 2:
            out.append(f"No 2x from these legs: all {len(legs)} together pay {pays:.2f}x. "
                       "Reaching 2x means adding riskier legs (the wider ticket's 2x).")
    if t["left_off"]:
        out.append("Left off, and why:")
        out += [f"  {lab} -- {why}" for lab, why in t["left_off"]]
        if any("Questionable" in why for _, why in t["left_off"]):
            out.append("  " + QUESTIONABLE_NOTE)
    return "\n".join(out)


# README 2026-11-25: on the saved ESPN snapshots, NBA players day-to-day at
# 8 AM who then played won 75 of 85 props (88% vs 84% stated); 43 more were
# voided (did not play), a push on FanDuel. The drop stays; the user decides.
QUESTIONABLE_NOTE = ("(Questionable players are left off by rule. On the record, NBA players listed day-to-day "
                     "that morning who then played hit 75 of 85 props (88% vs 84% stated), and a no-show is voided, "
                     "not lost -- adding one back is your call.)")


NCAAB_FLOOR = 0.90
NCAAB_URL = ("https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/"
             "scoreboard?dates={}&groups=50&limit=400")


def ncaab_rows(day, get=None):
    """Slate-sheet-shaped rows for the day's men's college basketball games
    with a DraftKings moneyline on ESPN (no price-blind number: the blind
    model has no college data). For --ncaab only."""
    import slate_sheet as S
    get = get or S._get
    sb = get(NCAAB_URL.format(day.replace("-", ""))) or {}
    out = []
    for ev in sb.get("events") or []:
        sm = get(S.SUMMARY.format("basketball/mens-college-basketball", ev["id"])) or {}
        r = S.row("ncaab", None, ev, sm)
        r["blind_home"] = None
        out.append(r)
    return out


def ncaab_legs(rows, floor=NCAAB_FLOOR):
    """College favourites at `floor`+ no-vig as ticket legs (opt-in, --ncaab).
    Not on the default ticket: the user's Nov 23-24 ticket rules name NBA /
    NFL / NHL winners. The board's own record on college winners stated 90%+
    is 59 of 60 (33/34 then 26/26 by date half, 2026-11-24) -- calibrated,
    not ahead -- and each pays little (-1600 to -100000)."""
    games = {}
    for r in rows:
        mh = r.get("market_home")
        if mh is None or r.get("home_ml") is None or r.get("away_ml") is None:
            continue
        home = mh >= 0.5
        p = mh if home else 1 - mh
        if p < floor:
            continue
        team, price = (r["home"], r["home_ml"]) if home else (r["away"], r["away_ml"])
        price_s = f"{int(price):+d}" if isinstance(price, (int, float)) else str(price)
        games.setdefault(r["game"], []).append(dict(
            label=f"{team} moneyline {price_s} ({round(100 * p)}%, DraftKings no-vig; college, opt-in)",
            id=str(r.get("id")), lg="ncaab", kind="ml", team=team, price=price_s, chance=p))
    return games


def _goalie_fn(day):
    """team full name -> the NHL goalie note (tools/nhl_goalies.leg_note); a
    function giving "" when DailyFaceoff or the NHL cannot be reached."""
    try:
        import nhl_goalies as NG
        rows = NG.parse(NG.fetch(day))
        rosters = NG.team_goalies()
    except Exception:
        return lambda team: ""
    return lambda team: NG.leg_note(team, rows, rosters)


def fallback(day, rows=None, b2b_fn=None, props_fn=None, status_fn=None, minutes_fn=None, goalie_fn=None, logs_fn=None,
             nhl_b2b_fn=None):
    """Winners only, from DraftKings prices on ESPN (no-vig), when the board has
    not rebuilt for `day` (2026-11-24: every GitHub workflow switched off). Same
    winner checks: 75%+, our price-blind number not on the other side. Props
    need the board's FanDuel feed, so there are none here."""
    if rows is None:
        import slate_sheet
        rows = slate_sheet.main(day)
    if b2b_fn is None:
        try:
            import key_absences
            b2b_fn = key_absences.played_day_before
        except ImportError:
            b2b_fn = None
    games, left = {}, []
    for r in rows:
        mh = r.get("market_home")
        if mh is None or r.get("home_ml") is None or r.get("away_ml") is None:
            continue
        home = mh >= 0.5
        team, price = (r["home"], r["home_ml"]) if home else (r["away"], r["away_ml"])
        chance = round(100 * (mh if home else 1 - mh))
        bh = r.get("blind_home")
        blind = None if bh is None else (bh if home else 1 - bh)
        price_s = f"{int(price):+d}" if isinstance(price, (int, float)) else str(price)
        ok, why = judge_winner(dict(mc=chance), [], blind)
        label = f"{team} moneyline {price_s} ({chance}%, DraftKings no-vig)"
        if ok and r.get("lg") == "nba" and b2b_fn and b2b_fn(team, day):
            label += " -- caution: second night of a back-to-back (priced in on the record)"
        if ok and r.get("lg") == "nhl":
            try:
                import nhl_goalies as NG
                tri = {"UTAH": "UTA"}.get(team, team)
                if (nhl_b2b_fn or NG.played_day_before)(tri, day):
                    label += " -- caution: second night of a back-to-back (often the backup goalie; not tested)"
            except Exception:
                pass
        if ok and r.get("lg") == "nhl":
            if goalie_fn is None:
                goalie_fn = _goalie_fn(day)
            label += goalie_fn(r.get("home_name") if home else r.get("away_name"))
        if ok:
            games.setdefault(r["game"], []).append(dict(label=label, id=str(r.get("id")), lg=r["lg"], kind="ml", team=team,
                                                        price=price_s, chance=chance / 100))
        elif chance >= MIN_WIN - 15:
            left.append((label, why))
    note = ("The board has not rebuilt for this day: winners from DraftKings prices on ESPN, props straight "
            "from FanDuel (the card's ~87% lines, players on the official injury report left off). "
            "Check tools/key_absences.py before using any NBA leg.")
    if props_fn is None:
        props_fn = _fd_props
    try:
        pg = props_fn(rows)
    except Exception:
        pg = []
        note = note.replace("props straight from FanDuel", "no props (FanDuel unreachable)")
    if pg:
        if minutes_fn is None:
            import nba_minutes
            minutes_fn = nba_minutes.mpg_last5
        if logs_fn is None:
            import nba_minutes
            logs_fn = nba_minutes.gamelogs
        st = status_fn or _report_status(day)
        fav = {f"{r['lg']}:{r.get('id')}": round(100 * max(r["market_home"], 1 - r["market_home"]))
               for r in rows if r.get("market_home") is not None}
        tp = build({}, pg, key_out_fn=lambda r: [], blind_fn=lambda r: None, status_fn=st,
                   fav_fn=lambda gid: fav.get(gid, 0), prop_locks=(), minutes_fn=minutes_fn,
                   logs_fn=logs_fn)
        for m, L in tp["games"].items():
            games.setdefault(m, []).extend(L)
        left += tp["left_off"]
    # kickoff per game (2026-11-26: the ticket had none, and a 1:00 PM kickoff
    # was told to the user as 12:30) -- shown beside each game header
    starts = {r.get("game"): r.get("start") for r in rows if r.get("game") and r.get("start")}
    return dict(games=games, left_off=left, note=note, starts=starts)


def ladder_fallback(t, lo=2.0, hi=5.0, maxk=6):
    """The ladder's rule (one leg per game, up to 6, paying 2x-5x, highest
    chance that all win) on the fallback ticket's legs, for a day the board's
    8 AM Locks card does not exist. Labelled as a stand-in: the usual ladder
    legs are the Locks. [] when nothing pays in the band.

    2026-11-25: this ran ladder.best_combo, which only searches the 12
    likeliest legs; on the fallback those are 87% NHL shots legs at ~1.06x,
    so it said "nothing pays 2x" while six legs from six games paid 2.1x.
    Then a knapsack on rounded payouts, which a brute-force check showed
    missing or under-picking 19 of 300 random slates. Now an exact search:
    depth-first over games (skip, or one of its legs), cut when the chance
    so far cannot beat the best found (adding a leg only lowers it), when
    the payout passes `hi`, or at `maxk` legs. Ties go to fewer legs."""
    games = []
    for g in t["games"].values():
        opts = []
        for L in g:
            try:
                d = _dec(L["price"])
            except (KeyError, TypeError, ValueError):
                continue
            if L.get("chance") and d > 1:
                opts.append((L["chance"], d, L))
        if opts:
            games.append(sorted(opts, key=lambda o: -o[0]))
    games.sort(key=lambda g: -g[0][0])
    # reach[i][r]: the most r more legs from games i.. can multiply the payout by
    tops = [max(o[1] for o in g) for g in games]
    reach = []
    for i in range(len(games) + 1):
        rest = sorted(tops[i:], reverse=True)
        reach.append([math.prod(rest[:r]) for r in range(maxk + 1)])
    best = [0.0, []]

    def go(i, p, pay, legs):
        if legs and pay >= lo - 1e-12:
            if p > best[0] + 1e-12 or (abs(p - best[0]) <= 1e-12 and len(legs) < len(best[1])):
                best[0], best[1] = p, list(legs)
        if i == len(games) or len(legs) == maxk or p <= best[0] + 1e-12:
            return
        if pay * reach[i][maxk - len(legs)] < lo - 1e-12:
            return                       # 2x is out of reach from here
        for c, d, L in games[i]:
            if pay * d <= hi + 1e-12 and p * c > best[0] + 1e-12:
                legs.append(L)
                go(i + 1, p * c, pay * d, legs)
                legs.pop()
        go(i + 1, p, pay, legs)

    go(0, 1.0, 1.0, [])
    return best[1]


def ladder_text(combo):
    if not combo:
        return ("Ladder stand-in: nothing on today's fallback legs pays 2x-5x with one leg per game "
                "(the ladder allows 6 legs; ~87% props near -1000 pay about 1.1x each).")
    pays = math.prod(_dec(L["price"]) for L in combo)
    p = math.prod(L["chance"] for L in combo)
    return ("Ladder stand-in (the board's 8 AM Locks are missing -- your call whether to use it): "
            f"{len(combo)} legs, pays {pays:.2f}x, about {100 * p:.0f}% all win: "
            + "; ".join(L["label"] for L in sorted(combo, key=lambda L: -L["chance"])))


def _fd_props(rows):
    """[{id, match, props}] from FanDuel for each NBA / NHL / NFL game in the
    slate rows (fd_props, the board's own FanDuel reader and prop pricing)."""
    import fanduel
    import fd_props
    book = fanduel.load()
    out = []
    for r in rows:
        if r.get("lg") not in ("nba", "nhl", "nfl") or not r.get("home_name"):
            continue
        g = fanduel.find(book, r["lg"], r.get("away_name"), r.get("home_name"))
        if g:
            out.append(dict(id=f"{r['lg']}:{r.get('id')}", match=r["game"], props=fd_props.for_game(g, r["lg"])))
    return out


def _report_status(day, nfl_fetch=None):
    """player display name -> injury status for `day`: the NBA's official
    report, plus ESPN's NFL report. 2026-11-25: NFL legs (GB @ LAR) went on
    the ticket with no injury check at all -- only the NBA report was read."""
    import key_absences as K
    import nba_injury_report as R
    _, txt = R.latest()
    rows = R.parse(txt or "")["rows"] if txt else []
    mmdd = dt.date.fromisoformat(day).strftime("%m/%d/%Y")
    status = {r["player"]: r["status"] for r in rows if r["date"] == mmdd}
    status.update(nfl_status(nfl_fetch))
    return lambda name: K.status_of(name, status)


def nfl_status(fetch=None):
    """{player: status} from ESPN's NFL injury report ({} when it cannot be read)."""
    try:
        if fetch is None:
            sys.path.insert(0, ROOT)
            import injuries
            fetch = lambda: injuries.fetch({"nfl": "football/nfl"}).get("nfl") or {}
        return {p: st for rows in (fetch() or {}).values() for p, st in rows}
    except Exception:
        return {}


class StaleBoard(Exception):
    """The board's data is not for the requested day (the board did not rebuild)."""


MAX_AGE_H = 6.0


def board_age_h(D, now=None):
    """Hours since the board last built, from D["at"] ("Nov 23, 7:56 PM ET");
    None when it cannot be read."""
    at = str(D.get("at") or "").replace(" ET", "").strip()
    now = (now or dt.datetime.now(ET)).astimezone(ET)
    try:
        t = dt.datetime.strptime(f"{at} {now.year}", "%b %d, %I:%M %p %Y").replace(tzinfo=ET)
    except ValueError:
        return None
    if t > now + dt.timedelta(days=1):          # built in December, read in January
        t = t.replace(year=now.year - 1)
    return (now - t).total_seconds() / 3600


def board_slot(D, day, now=None):
    """The board slot ("today" / "tomorrow") holding `day` (ISO date). 2026-11-24:
    with the board workflow switched off, board.html still called Nov 23
    "today" -- a ticket for Nov 24 read from "today" would have used the wrong
    day's games without a word. And its "tomorrow" slot held Nov 24 from a
    build 12 hours old (last night's prices and props), which the 8 AM ticket
    then used -- so a board older than MAX_AGE_H hours is stale too."""
    age = board_age_h(D, now)
    if age is not None and age > MAX_AGE_H:
        raise StaleBoard(f"the board last built {age:.0f} hours ago ({D.get('at')}) -- "
                         "is the board workflow running?")
    want = day.replace("-", "")
    for slot, d in (D.get("dates") or {}).items():
        if str(d) == want:
            return slot
    raise StaleBoard(f"the board has no data for {day} (it holds {D.get('dates')}) -- "
                     "it has not rebuilt; is the board workflow running?")


def main(day):
    import line_moves
    import blind_model as bm
    import key_absences as K
    import nba_injury_report as R
    D = line_moves.board()
    slot = board_slot(D, day)
    slots = (D.get("slots") or {}).get(slot) or {}
    rows_by_lg = {lg: (slots.get(lg) or {}).get("rows") or [] for lg in WIN_LEAGUES}
    props_games = [g for g in ((D.get("props") or {}).get(slot) or {}).get("games") or []
                   if str(g.get("id", "")).split(":")[0] in ("nba", "nhl", "nfl")]
    # official report statuses, by player and team
    _, rep = R.latest()
    rows = R.parse(rep or "")["rows"] if rep else []
    mmdd = dt.date.fromisoformat(day).strftime("%m/%d/%Y")
    status = {r["player"]: r["status"] for r in rows if r["date"] == mmdd}
    # 2026-11-26: the board path read only the NBA report, so NFL props built
    # from the board had no injury check (the fallback path already had one)
    status.update(nfl_status())
    by_team = {}
    for r in rows:
        if r["date"] == mmdd:
            by_team.setdefault(r["team"], {})[r["player"]] = r["status"]
    # each board game's teams and our blind number, from ESPN's scoreboard
    games = {}
    models = {}
    for lg in WIN_LEAGUES:
        sb = K._get(f"https://site.api.espn.com/apis/site/v2/sports/{bm.SPORT[lg]}/scoreboard?dates={day.replace('-', '')}") or {}
        if os.path.exists(bm.cache_path(lg)):
            models[lg] = bm.fit(json.load(open(bm.cache_path(lg))), day, *bm.PARAMS[lg])
        for e in sb.get("events") or []:
            t = {c["homeAway"]: c["team"] for c in e["competitions"][0]["competitors"]}
            games[f"{lg}:{e['id']}"] = dict(lg=lg, home=t["home"], away=t["away"], match=e.get("shortName"))
    minutes_cache = {}

    def side(r):
        g = games.get(r["id"]) or {}
        for s in ("home", "away"):
            if (g.get(s) or {}).get("displayName") == r["mp"]:
                return g, s
        return g, None

    def key_out(r):
        g, s = side(r)
        if not s or g["lg"] != "nba":
            return []
        abbr = g[s]["abbreviation"]
        if abbr not in minutes_cache:
            minutes_cache[abbr] = K.recent_minutes(abbr, day)
        return K.key_missing(minutes_cache[abbr], by_team.get(g[s]["displayName"], {}))

    def b2b(r):
        g, s = side(r)
        return bool(s and g["lg"] == "nba" and K.played_day_before(g[s]["abbreviation"], day))

    def blind(r):
        g, s = side(r)
        m = models.get(g.get("lg")) if s else None
        if not m:
            return None
        al = {"nhl": {"UTAH": "UTA"}}.get(g["lg"], {})
        h, a = g["home"]["abbreviation"], g["away"]["abbreviation"]
        p = bm.predict(m, al.get(h, h), al.get(a, a))
        return None if not p else (p[2] if s == "home" else 1 - p[2])

    def fav(gid):
        best = 0
        for lg in WIN_LEAGUES:
            for r in rows_by_lg[lg]:
                if r.get("id") == gid:
                    best = max(best, r.get("mc") or 0)
        return best

    for lg in WIN_LEAGUES:
        for r in rows_by_lg[lg]:
            g, s = side(r)
            if s:
                r["abbr"] = g[s]["abbreviation"]
                r["match"] = g["match"]
    try:
        pl = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prop_locks.json")))
        lock_names = {L["name"] for L in ((pl.get("days") or {}).get(day) or {}).get("legs") or []}
    except (OSError, ValueError):
        lock_names = set()
    return build(rows_by_lg, props_games, key_out, blind,
                 lambda name: K.status_of(name, status), fav, prop_locks=lock_names, b2b_fn=b2b,
                 minutes_fn=__import__("nba_minutes").mpg_last5, logs_fn=__import__("nba_minutes").gamelogs)


# README 2026-11-25 "safest legs": on every graded board prop, priced -2500 or
# shorter won 342/364 (94.0%; 91.1% then 96.7% by date half), NHL -1500 to
# -2500 won 206/224 (92.0%); everything from -500 to -2500 elsewhere 84-86%.
# Built from those alone, a 6-leg day won every leg on 17 of 26 days.
# NFL (2026-11-25, Thanksgiving was an NFL-only day): FanDuel's NFL ladders stop
# near -1800, so the -2500 band left the safest ticket empty. NFL props at -1000
# or shorter won 119/130 (91.5%; 97/105 then 22/25 by date half, split 11-05)
# against 293/345 (84.9%) from -500 to -1000 -- the NFL's own safest band.
SAFEST = ((None, -2500), ("nhl", -1500), ("nfl", -1000))


SAFEST_MODE = {"on": False}


def safest_per_player(props, lg):
    """--safest: per player, his best-paying line that is still in a safest
    band (any prop at -2500 or shorter, NHL at -1500, NFL at -1000); players
    with none are left out. The default picks each player's LONGEST line at
    the floor (~-1000), so the heavy lines never reached the ticket."""
    best = {}
    for p in props:
        try:
            a = float(str(p.get("price")).replace("+", ""))
        except (TypeError, ValueError):
            continue
        if not any((g is None or g == lg) and a <= cut for g, cut in SAFEST):
            continue
        cur = best.get(p.get("name"))
        if cur is None or a > cur[0]:
            best[p.get("name")] = (a, p)
    return sorted((p for _, p in best.values()), key=lambda p: float(str(p.get("price")).replace("+", "")))


def safest(t):
    """Only the legs in the price bands that have lost least: any prop at
    -2500 or shorter, an NHL prop at -1500 or shorter, and a moneyline the
    market makes 90%+ (college favourites at 90%+ won 96% over 4 seasons).
    The user (2026-11-25): "if u know what the losses are, how are u not
    doing anything to improve it". Fewer, safer legs; each pays little."""
    keep = {}
    for m, legs in t["games"].items():
        ok = []
        for L in legs:
            if "caution:" in (L.get("label") or ""):
                # a leg the ticket already warns about (last-10 under 70%, low
                # minutes, blowout, unusual goalie) stays off the safest ticket:
                # last-10 cautions hit 81-82%, low minutes 70-77% (README)
                continue
            try:
                a = float(str(L.get("price")).replace("+", ""))
            except (TypeError, ValueError):
                continue
            if L.get("kind") == "prop" and any((lg is None or L.get("lg") == lg) and a <= cut for lg, cut in SAFEST):
                ok.append(L)
            elif L.get("kind") == "ml" and (L.get("chance") or 0) >= 0.90:
                ok.append(L)
        if ok:
            keep[m] = ok
    return dict(t, games=keep)


def weather_block(day, t, rows_fn=None, lines_fn=None):
    """Kickoff weather for the ticket's NFL games (tools/nfl_weather.py), or ''.
    Information only. 2026-11-26: three KC @ BUF passing / receiving legs sat
    in an all-game rain forecast and the ticket said nothing."""
    games = {m for m, legs in (t.get("games") or {}).items() if any(L.get("lg") == "nfl" for L in legs)}
    if not games:
        return ""
    try:
        if rows_fn is None:
            import slate_sheet
            rows_fn = slate_sheet.main
        if lines_fn is None:
            import nfl_weather
            lines_fn = nfl_weather.lines
        return "\n".join(lines_fn([r for r in rows_fn(day) if r.get("game") in games]))
    except Exception as ex:                       # never block the ticket
        return f"Kickoff weather unavailable ({type(ex).__name__})"


def save_ticket(t, save, combo=(), force=False, two=()):
    """Write the ticket (and the ladder stand-in as ticket_ladder.json beside
    it); returns the lines to print. Never replaces an existing file without
    `force`. 2026-11-24: a second run at 9:20 AM overwrote the 8 AM ticket the
    user had been sent -- FanDuel's lines had moved, so 4 of its 13 legs changed.
    2026-11-25: the stand-in was printed but never saved, so nothing graded it."""
    out = []
    if not save:
        return out
    if os.path.exists(save) and not force:
        return [f"\nnot saved: {save} already holds the ticket sent earlier (add --force to replace it)"]
    os.makedirs(os.path.dirname(save) or ".", exist_ok=True)
    json.dump(ticket_legs(t), open(save, "w"), indent=1)
    out.append(f"\nsaved: {save}")
    # beside ticket.json: ticket_ladder.json / ticket_2x.json; beside any other
    # name (ticket_safe.json): ticket_safe_ladder.json / ticket_safe_2x.json --
    # 2026-11-25: saving the safest ticket next to the wide one would have taken
    # the wide one's file names, and the second save printed "not saved"
    stem = os.path.splitext(os.path.basename(save))[0]
    pre = "ticket_" if stem == "ticket" else stem + "_"
    for legs, fname, what in ((combo, pre + "ladder.json", "the ladder stand-in"),
                              (two, pre + "2x.json", "the most likely 2x")):
        if not legs:
            continue
        lpath = os.path.join(os.path.dirname(save) or ".", fname)
        if os.path.exists(lpath) and not force:
            out.append(f"not saved: {lpath} already exists")
        else:
            json.dump(ticket_legs({"games": {"x": list(legs)}}), open(lpath, "w"), indent=1)
            out.append(f"saved: {lpath} ({what}, {len(legs)} legs)")
    return out


def two_x_legs(t):
    """The legs of the ticket's 'most likely 2x' line ([] when none)."""
    import recheck_ticket as R
    legs = [L for g in t["games"].values() for L in g]
    try:
        b = R.best_2x([(L, _dec(L["price"]), L["chance"]) for L in legs])
    except (KeyError, TypeError, ValueError):
        return []
    return b["legs"] if b and len(b["legs"]) < len(legs) else []



LOW_RUSH_NOTE = (" -- note: low rushing line (under 15 yards) -- 24/30 (80%) at -700 or shorter vs 90% for 15-39"
                 " (README 2026-11-26, on watch)")
CATCH3_NOTE = (" -- note: 3+ catches -- 25/37 (68%) since Nov 5 against 85% priced, 39/44 before"
               " (README 2026-11-27, on watch)")


EARLY_NOTE = (" -- note: early kickoff (before 3 PM ET) -- NFL props there ran 7.9 / 4.6 points under their"
              " price by date half vs about even later in the day (README 2026-11-27, on watch)")


def _early_et(start):
    """True when an ISO start is before 3 PM Eastern (EST, UTC-5; NFL season)."""
    try:
        t = dt.datetime.fromisoformat(str(start).replace("Z", "+00:00")) - dt.timedelta(hours=5)
    except ValueError:
        return False
    return t.hour < 15


def nfl_notes(t):
    """Information-only notes on NFL legs, from studies that did not reach the
    bar (README 2026-11-26). 'note:' never 'caution:', so --safest keeps them."""
    starts = t.get("starts") or {}
    for match, legs in (t.get("games") or {}).items():
        early = _early_et(starts[match]) if starts.get(match) else False
        for L in legs:
            if L.get("lg") == "nfl" and L.get("kind") == "prop" and early and "early kickoff" not in L.get("label", ""):
                L["label"] = L["label"] + EARLY_NOTE
            if L.get("lg") == "nfl" and L.get("market") == "Rushing Yards" and (L.get("line") or 99) < 15 \
                    and "low rushing line" not in L.get("label", ""):
                L["label"] = L["label"] + LOW_RUSH_NOTE
            if L.get("lg") == "nfl" and L.get("market") == "Receptions" and (L.get("line") or 0) >= 3 \
                    and "3+ catches" not in L.get("label", ""):
                L["label"] = L["label"] + CATCH3_NOTE
    return t


def shared_with_siblings(save):
    """'Also on ticket.json: Loveland, ...' when a player on the ticket just
    saved has a leg on the other saved ticket beside it (2026-11-26: Colston
    Loveland, 1 target, lost on both the safest ticket and the backup)."""
    folder = os.path.dirname(save) or "."
    me = os.path.basename(save)
    try:
        mine = {L.get("player") for L in json.load(open(save)) if L.get("player")}
    except (OSError, ValueError):
        return ""
    out = []
    for other in ("ticket.json", "ticket_safe.json"):
        if other == me or not os.path.exists(os.path.join(folder, other)):
            continue
        try:
            theirs = {L.get("player") for L in json.load(open(os.path.join(folder, other))) if L.get("player")}
        except (OSError, ValueError):
            continue
        both = sorted(mine & theirs)
        if both:
            out.append(f"Also on {other} (one bad game loses the leg on both): " + ", ".join(both))
    return "\n".join(out)


def record_both_sides(day, record_fn=None):
    """Log both sides of every FanDuel main line (tools/both_sides.py) whenever
    a ticket is saved, so the over-vs-under record (2026-11-25, the user: "see
    what other side brings") never depends on a step being remembered."""
    try:
        if record_fn is None:
            import both_sides
            record_fn = both_sides.record
        return f"both sides: {record_fn(day)} new lines logged (data/both_sides.json)"
    except Exception as ex:                       # never block the ticket
        return f"both sides: not logged ({type(ex).__name__})"


if __name__ == "__main__":
    args = sys.argv[1:]
    save = None
    args = [a for a in args if a not in ("--fallback", "--ncaab", "--force")]
    if "--save" in args:
        i = args.index("--save")
        save = args[i + 1]
        del args[i:i + 2]
    day = resolve_day(args[0] if args else None)
    SAFEST_MODE["on"] = "--safest" in sys.argv
    try:
        t = main(day)
    except StaleBoard as e:
        if "--fallback" not in sys.argv:
            print(f"No ticket: {e} (add --fallback for winners from DraftKings prices)")
            sys.exit(2)
        t = apply_record(fallback(day), prop_record())
        t["ladder_pending"] = True
    else:
        apply_record(t, prop_record())
    if "--ncaab" in sys.argv:
        for m, L in ncaab_legs(ncaab_rows(day)).items():
            t["games"].setdefault(m, []).extend(L)
    if "--safest" in sys.argv:
        t = safest(t)
        t["note"] = ((t.get("note") or "") + " SAFEST LEGS ONLY: props at -2500 or shorter, NHL props at -1500 or "
                     "shorter, NFL props at -1000 or shorter, moneylines at 90%+ (these won "
                     "94% / 92% / 91.5% / 96% on the record).").strip()
    t = nfl_notes(t)
    combo = []
    if t.pop("ladder_pending", False):
        # after the college legs join, so the stand-in sees what the 2x line sees
        combo = ladder_fallback(t)
        t["ladder"] = ladder_text(combo)
    print(text(t))
    w = weather_block(day, t)
    if w:
        print(w)
    for line in save_ticket(t, save, combo, force="--force" in sys.argv, two=two_x_legs(t) if save else ()):
        print(line)
    if save:
        print(record_both_sides(day))
        shared = shared_with_siblings(save)
        if shared:
            print(shared)

