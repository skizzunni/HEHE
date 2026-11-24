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
        cand = daily_card.best_per_player([dict(p, match=g.get("match")) for p in g.get("props") or []
                                           if p.get("plays", True)], floor=PROP_FLOOR)
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
    return (f"Most likely 2x from these legs: {len(b['legs'])} legs, about {100 * b['chance']:.0f}% all win, "
            f"pays {b['pays']:.2f}x -- " + "; ".join(L["label"].split(" (")[0] for L in b["legs"]) + ".")


def ticket_legs(t):
    """The ticket's legs in tools/grade_picks.py's file format (what --save writes)."""
    return [{k: v for k, v in L.items() if k not in ("chance", "gid")} for g in t["games"].values() for L in g]


def text(t):
    legs = [L for g in t["games"].values() for L in g]
    out = ([f"NOTE: {t['note']}"] if t.get("note") else []) + [f"Your ticket, by game -- {len(legs)} legs, each judged on its own:"]
    for match, L in t["games"].items():
        out.append(f"  {match}")
        out += [f"    {x['label']}" for x in L]
    if legs:
        allwin = math.prod(x["chance"] for x in legs)
        try:
            pays = math.prod(_dec(x["price"]) for x in legs)
            out.append(f"All {len(legs)} win: about {100 * allwin:.0f}% -- pays about {pays:.2f}x as one ticket. "
                       f"Each leg stands on its own; the size is your call.")
        except (TypeError, ValueError):
            out.append(f"All {len(legs)} win: about {100 * allwin:.0f}%.")
    if t.get("ladder"):
        out.append(t["ladder"])
    two = two_x_text(legs)
    if two:
        out.append(two)
    if t["left_off"]:
        out.append("Left off, and why:")
        out += [f"  {lab} -- {why}" for lab, why in t["left_off"]]
    return "\n".join(out)


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
    return dict(games=games, left_off=left, note=note)


def ladder_fallback(t):
    """The ladder's own picker (ladder.best_combo: one leg per game, paying 2x-5x,
    highest chance that all win) run on the fallback ticket's legs, for a day the
    board's 8 AM Locks card does not exist. Labelled as a stand-in: the usual
    ladder legs are the Locks. [] when nothing pays in the band."""
    import ladder
    legs = [dict(L, p=L["chance"], gid=L.get("gid") or f"{L.get('lg')}:{L.get('id')}")
            for g in t["games"].values() for L in g]
    return ladder.best_combo(legs)


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


def _report_status(day):
    """player display name -> official injury report status for `day`."""
    import key_absences as K
    import nba_injury_report as R
    _, txt = R.latest()
    rows = R.parse(txt or "")["rows"] if txt else []
    mmdd = dt.date.fromisoformat(day).strftime("%m/%d/%Y")
    status = {r["player"]: r["status"] for r in rows if r["date"] == mmdd}
    return lambda name: K.status_of(name, status)


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


if __name__ == "__main__":
    args = sys.argv[1:]
    save = None
    args = [a for a in args if a not in ("--fallback", "--ncaab", "--force")]
    if "--save" in args:
        i = args.index("--save")
        save = args[i + 1]
        del args[i:i + 2]
    day = resolve_day(args[0] if args else None)
    try:
        t = main(day)
    except StaleBoard as e:
        if "--fallback" not in sys.argv:
            print(f"No ticket: {e} (add --fallback for winners from DraftKings prices)")
            sys.exit(2)
        t = apply_record(fallback(day), prop_record())
        t["ladder"] = ladder_text(ladder_fallback(t))
    else:
        apply_record(t, prop_record())
    if "--ncaab" in sys.argv:
        for m, L in ncaab_legs(ncaab_rows(day)).items():
            t["games"].setdefault(m, []).extend(L)
    print(text(t))
    if save and os.path.exists(save) and "--force" not in sys.argv:
        # 2026-11-24: a second run at 9:20 AM overwrote the 8 AM ticket the user
        # had been sent -- FanDuel's lines had moved, so 4 of its 13 legs changed
        print(f"\nnot saved: {save} already holds the ticket sent earlier (add --force to replace it)")
        save = None
    if save:
        os.makedirs(os.path.dirname(save) or ".", exist_ok=True)
        json.dump(ticket_legs(t), open(save, "w"), indent=1)
        print(f"\nsaved: {save}")
