#!/usr/bin/env python3
"""Grade a saved list of researched picks against the final scores.

The research picks (the "25" lists) need a record of their own, separate from
the board's, so it can be judged on results rather than on how sure it sounded.

    python3 tools/grade_picks.py work/slate_nov23/final_picks.json

The file is a list of picks:
    {"id": "401910036", "lg": "nba", "kind": "spread", "team": "MEM", "line": -2.5, "price": -116}
    {"id": "401910040", "lg": "nba", "kind": "under", "line": 222.5, "price": -105}
    {"id": "401892773", "lg": "nhl", "kind": "ml", "team": "NJ", "price": -205}
    {"id": "401910045", "lg": "nba", "kind": "prop", "player": "Keegan Murray", "stat": "PTS", "line": 5, "price": -4500}
kind is spread (team + line), ml (team), over or under (line), or prop: a
player reaching `line` or more of `stat` (PTS, REB, AST, 3PM, STL, BLK, or a
sum like PTS+AST) from the box score -- won as soon as he reaches it. Each pick is
graded won / lost / push / open from ESPN's final score, and the file's
record and flat $1 return are printed.
"""
import json
import os
import sys
import urllib.request

SPORT = {"nba": "basketball/nba", "nhl": "hockey/nhl", "nfl": "football/nfl", "ncaaf": "football/college-football",
         "ncaab": "basketball/mens-college-basketball"}
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/{}/summary?event={}"
VOID_STATES = ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED", "STATUS_SUSPENDED", "STATUS_FORFEIT")


def _num(v):
    try:
        return float(str(v).split("-")[0])
    except (TypeError, ValueError):
        return None


def _fold(name):
    """A name with accents and case dropped: FanDuel 'Luka Doncic' is ESPN's 'Luka Dončić'."""
    import unicodedata
    return unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower().strip()


def player_stat(summary, player, stat):
    """A player's stat (or a sum like PTS+AST) from an ESPN summary's box
    score; 3PM is made threes. None when he is not in the box score."""
    for t in ((summary or {}).get("boxscore") or {}).get("players") or []:
        for cat in t.get("statistics") or []:
            row = {_fold(a["athlete"]["displayName"]): dict(zip(cat.get("labels") or [], a.get("stats") or []))
                   for a in cat.get("athletes") or []}
            if _fold(player) not in row:
                continue
            got = row[_fold(player)]
            if not got:
                return 0.0                      # listed, did not play
            total = 0.0
            for part in stat.upper().split("+"):
                v = _num(got.get("3PT")) if part == "3PM" else _num(got.get(part))
                if v is None:
                    return None
                total += v
            return total
    return None


def _toi(summary, player):
    """An NHL skater's time on ice as ESPN prints it ('19:43'), or None."""
    for t in ((summary or {}).get("boxscore") or {}).get("players") or []:
        for cat in t.get("statistics") or []:
            labels = cat.get("labels") or cat.get("names") or []
            if "TOI" not in labels:
                continue
            for a in cat.get("athletes") or []:
                if _fold((a.get("athlete") or {}).get("displayName")) == _fold(player):
                    s = dict(zip(labels, a.get("stats") or [])).get("TOI")
                    return s if s and ":" in s else None
    return None


def _completed(summary):
    """True when an ESPN summary is for a finished game (never mid-game or pre-game)."""
    if (summary or {}).get("completed"):
        return True
    comp = (((summary or {}).get("header") or {}).get("competitions") or [{}])[0]
    return bool(((comp.get("status") or {}).get("type") or {}).get("completed"))


def _dnp_or_absent(summary, player):
    """True when the player is listed without stats, or not in the box at all."""
    if _dnp(summary, player):
        return True
    for t in ((summary or {}).get("boxscore") or {}).get("players") or []:
        for cat in t.get("statistics") or []:
            for a in cat.get("athletes") or []:
                if _fold((a.get("athlete") or {}).get("displayName")) == _fold(player):
                    return False
    return True


def _dnp(summary, player):
    """True when the player is in the box score with no stats (did not play)."""
    for t in ((summary or {}).get("boxscore") or {}).get("players") or []:
        for cat in t.get("statistics") or []:
            for a in cat.get("athletes") or []:
                if _fold((a.get("athlete") or {}).get("displayName")) == _fold(player):
                    return bool(a.get("didNotPlay")) or not a.get("stats")
    return False


def final(lg, gid, get=None, with_clock=False, raw=False):
    """{abbr: score} and completed flag for one game, from ESPN (and the
    game clock text, e.g. "9:51 - 3rd", when with_clock)."""
    def fetch(u):
        try:
            return json.load(urllib.request.urlopen(u, timeout=30))
        except Exception:
            return None
    d = (get or fetch)(SUMMARY.format(SPORT[lg], gid)) or {}
    comp = ((d.get("header") or {}).get("competitions") or [{}])[0]
    stype = (comp.get("status") or {}).get("type") or {}
    done = bool(stype.get("completed"))
    scores = {}
    if stype.get("name") in VOID_STATES:
        # 2026-11-24: a postponed game never reads "completed", so --watch would
        # wait on it forever; books void such legs, so it settles as a push
        scores, done = {"_void": stype.get("name")}, True
    for c in comp.get("competitors") or []:
        try:
            scores[c["team"]["abbreviation"]] = float(c["score"])
        except (KeyError, TypeError, ValueError):
            pass
    if with_clock:
        clock = ((comp.get("status") or {}).get("type") or {}).get("shortDetail") or ""
        return (scores, done, clock, d) if raw else (scores, done, clock)
    return (scores, done, d) if raw else (scores, done)


def standing(pick, scores):
    """How an unfinished pick stands right now, in plain words: the margin
    against its line so far ('ahead by 4.5', 'behind by 2', 'level')."""
    if len(scores) != 2:
        return "not started"
    total = sum(scores.values())
    if pick["kind"] == "over":
        need = pick["line"] - total
        return f"{total:g} so far, " + (f"needs {need:g} more" if need > 0 else "already over")
    if pick["kind"] == "under":
        room = pick["line"] - total
        return f"{total:g} so far, " + (f"{room:g} to spare before the line" if room > 0 else "already over the line -- lost")
    else:
        me = scores.get(pick["team"])
        if me is None:
            return "team not found"
        them = next(v for k, v in scores.items() if k != pick["team"])
        d = (me - them) + ((pick.get("line") or 0) if pick["kind"] == "spread" else 0)
        so_far = f"{me:g}-{them:g}"
    word = f"ahead by {d:g}" if d > 0 else f"behind by {-d:g}" if d < 0 else "level"
    return f"{so_far}, {word}"


def board_value(pick, summary):
    """(value, how) for a prop's player stat the way the board reads it
    (props_ledger's market -> stat map and player matching). value is None
    when the market is unknown or the player is not found; how is
    props_ledger's match note ('absent' = did not play)."""
    lg, market = pick.get("lg"), pick.get("market")
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        import props_ledger
        fn = (props_ledger.MARKETS.get(lg) or {}).get(market)
    except Exception:
        return None, None
    if not fn or not summary:
        return None, None
    st, how = props_ledger.resolve(props_ledger.box_stats(summary), {"name": pick["player"]})
    if how == "absent" and lg in ("nfl", "ncaaf") and \
            props_ledger.in_pbp(props_ledger.pbp_names(summary), pick["player"]):
        st, how = {"_played": 1.0}, "pbp"      # in the play-by-play, no stat: he played, 0
    if how == "absent" or st is None:
        return None, how
    if not st:
        # listed but no stats: dressed, did not play (ESPN didNotPlay, e.g. a
        # coach's decision). FanDuel voids such props; 2026-11-24 this graded LOST
        return None, "absent"
    try:
        return fn(st), how
    except Exception:
        return None, how


def board_prop(pick, summary):
    """('won'|'lost'|'void'|None) for a prop graded exactly as the board grades
    it (props_ledger: its market -> stat map, player matching, line rules);
    None when the pick carries no market the board knows. 2026-11-24: NHL
    'Shots on Goal' has no plain box-score label, so the label path returned
    nothing and a winning shots prop would have been graded LOST."""
    value, how = board_value(pick, summary)
    if how in ("absent", "unresolved"):
        # 'unresolved': only a surname matches (exact, alias and first-name
        # forms all failed), i.e. he is not in the box score -- a DNP, which
        # FanDuel voids. 2026-11-25: Dejounte Murray (did not play Nov 13,
        # Kris Murray did) graded LOST here.
        return "void"
    if value is None:
        return None
    import props_ledger
    ok = props_ledger.won(pick.get("lg"), pick.get("market"), pick.get("line_text") or f"{pick['line']:g}+", value)
    return None if ok is None else ("won" if ok else "lost")


def grade(pick, scores, done, summary=None):
    if scores.get("_void"):
        return "push"
    if pick["kind"] == "prop" and pick.get("market"):
        r = board_prop(pick, summary)
        if r == "won":
            return "won"
        if r == "lost":
            return "lost" if done else "open"
        if r == "void":
            return "push" if done else "open"
    if pick["kind"] == "prop":
        if _dnp(summary, pick["player"]):
            return "push" if done else "open"
        v = player_stat(summary, pick["player"], pick["stat"])
        if v is not None and v >= pick["line"]:
            return "won"
        return "lost" if done else "open"
    if not done or len(scores) != 2:
        return "open"
    total = sum(scores.values())
    kind = pick["kind"]
    if kind in ("over", "under"):
        d = (total - pick["line"]) * (1 if kind == "over" else -1)
    else:
        me = scores.get(pick["team"])
        if me is None:
            return "open"
        them = next(v for k, v in scores.items() if k != pick["team"])
        d = (me - them) + ((pick.get("line") or 0) if kind == "spread" else 0)
    return "won" if d > 0 else "lost" if d < 0 else "push"


def dropped_count(path):
    """How many of the saved ticket's legs the pre-game recheck dropped."""
    try:
        with open(path) as f:
            labels = {L.get("label") for L in json.load(f)}
    except (OSError, ValueError):
        return 0
    return len(labels) - len(load(path))


def load(path):
    """The ticket's legs, less any the pre-game recheck dropped
    (<ticket>.dropped, written by recheck_ticket --final)."""
    with open(path) as f:
        legs = json.load(f)
    gone = set()
    # its own drops, and the main ticket's for a file beside it (the ladder
    # stand-in is a subset of ticket.json; a leg dropped there is gone here too)
    sides = {path + ".dropped", os.path.join(os.path.dirname(path), "ticket.json.dropped")}
    base = os.path.basename(path)
    for tail in ("_2x.json", "_ladder.json"):          # ticket_safe_2x.json -> ticket_safe.json's drops
        if base.endswith(tail) and base != "ticket" + tail:
            sides.add(os.path.join(os.path.dirname(path), base[:-len(tail)] + ".json.dropped"))
    for side in sides:
        try:
            with open(side) as f:
                gone |= set(json.load(f))
        except (OSError, ValueError):
            pass
    return [L for L in legs if L.get("label") not in gone]


def payout(price):
    price = float(price)
    return price / 100 if price > 0 else 100 / -price


def summary(picks, results):
    done = [(p, r) for p, r in zip(picks, results) if r in ("won", "lost", "push")]
    w = sum(r == "won" for _, r in done)
    l = sum(r == "lost" for _, r in done)
    roi = sum(payout(p["price"]) if r == "won" else -1 if r == "lost" else 0 for p, r in done)
    return dict(won=w, lost=l, push=sum(r == "push" for _, r in done), open=len(picks) - len(done), units=round(roi, 2))


def main(path, get=None):
    picks = load(path)
    results = []
    for p in picks:
        scores, done, d = final(p["lg"], p["id"], get, raw=True)
        r = grade(p, scores, done, d)
        # a record counts a prop only at the final: reached mid-game is still
        # open (the daily review reads this; 2026-11-25 Klay read won in the 1st)
        results.append("open" if r == "won" and not done else r)
    return picks, results, summary(picks, results)


def _once(get):
    """A fetch that reads each URL once per round: legs on the same game share
    one ESPN call (13 legs on 4 games were 13 calls every 2 minutes)."""
    seen = {}

    def fetch(u):
        if u not in seen:
            seen[u] = (get or _fetch)(u)
        return seen[u]
    return fetch


def _fetch(u):
    try:
        return json.load(urllib.request.urlopen(u, timeout=30))
    except Exception:
        return None


def short(p):
    """'Trae Young 15+ Pts + Ast' / 'IOWA ML' / 'BOS -2.5' -- a leg in a few words."""
    k = p.get("kind")
    if k == "prop":
        return f"{p.get('player')} {p.get('line_text') or format(p.get('line', 0), 'g') + '+'} {p.get('market') or p.get('stat')}"
    if k == "ml":
        return f"{p.get('team')} ML"
    if k == "spread":
        return f"{p.get('team')} {p.get('line'):+g}"
    if k in ("over", "under"):
        return f"{k} {p.get('line'):g}"
    return p.get("label") or str(p)


PERIODS = {"nfl": (4, 15), "ncaaf": (4, 15), "nba": (4, 12), "wnba": (4, 10), "nhl": (3, 20), "ncaab": (2, 20)}
ORD = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4}


def pace(clock, lg):
    """'on pace for 22' from a live line '0:06 - 2nd: 11 of 15' -- the stat
    scaled to a full game at the current rate (2026-11-26: at half time a leg
    at 11 of 15 says nothing about whether it is on track). A rate, not a
    forecast; '' when the clock cannot be read or under a fifth has gone."""
    import re
    clock = re.sub(r"^\s*Halftime\b", "0:00 - 2nd", clock or "")               # ESPN's half-time clock
    clock = re.sub(r"^\s*End of (1st|2nd|3rd|4th)\b", r"0:00 - \1", clock)
    m = re.match(r"^\s*(\d+):(\d+)\s*-\s*(1st|2nd|3rd|4th)\s*:\s*(\d+(?:\.\d+)?) of (\d+(?:\.\d+)?)", clock)
    if not m or lg not in PERIODS:
        return ""
    n, length = PERIODS[lg]
    per = ORD[m.group(3)]
    if per > n:
        return ""
    elapsed = (per - 1) * length + (length - (int(m.group(1)) + int(m.group(2)) / 60))
    total = n * length
    if elapsed < total / 5:
        return ""
    v, need = float(m.group(4)), float(m.group(5))
    proj = v * total / elapsed
    return f"on pace for {proj:.0f}" + (" -- behind" if proj < need else "")


def brief(path, get=None):
    """The live view in short words, legs not yet started left out and counted:
    for check-ins during games (2026-11-24: the full labels ran 150 characters)."""
    get = _once(get)
    rows = live(path, get)
    picks = load(path)
    out, waiting = [], 0
    for p, line in zip(picks, rows):
        if line.split()[0] in ("WON", "LOST", "PUSH"):
            # what settled it -- "had 3" for a prop, the score for a game leg
            # (2026-11-25: Murray's LOST said nothing until a second lookup)
            try:
                scores, _, _, d = final(p["lg"], p["id"], get, with_clock=True, raw=True)
                out.append(f"{line.split()[0]:5} {short(p)}{detail(p, scores, d)}")
            except Exception:
                out.append(f"{line.split()[0]:5} {short(p)}")
            continue
        tail = line.split(" -- ", 1)[1] if " -- " in line else ""
        pre = tail.split(": not in the box score yet")[0]
        # 2026-11-26: a player with no stat yet in a game already under way
        # (LaPorta at 8:31 of the 1st) was counted "not started"; only a game
        # whose clock is still its start time (or none) is waiting
        if line.startswith("OPEN") and ("not started" in tail or "EST" in pre or "EDT" in pre or not pre):
            waiting += 1
            continue
        if "not in the box score yet" in tail:
            out.append(f"OPEN  {short(p)} -- {pre}: none yet")
            continue
        state = line.split()[0]
        # only an open leg has a clock; a settled leg's tail is the label's own note
        # (2026-11-25: Gafford's "caution: reached it in 6 of his last 10" showed after WON)
        clock = tail.split(" -- ")[-1] if tail and state in ("OPEN", "REACHED") else ""
        pc = pace(clock, p.get("lg")) if state == "OPEN" else ""
        out.append(f"{state:5} {short(p)}" + (f" -- {clock}" if clock else "") + (f" ({pc})" if pc else ""))
    if waiting:
        out.append(f"({waiting} not started yet)")
    states = [r.split()[0] for r in rows]
    won, lost, push = states.count("WON"), states.count("LOST"), states.count("PUSH")
    reached = states.count("REACHED")
    head = (f"{won} won, {lost} lost" + (f", {push} void" if push else "") + f", {len(rows) - won - lost - push} still open"
            + (f" ({reached} reached, settles at the final)" if reached else ""))
    gone = dropped_count(path)
    if gone:
        head += f" ({gone} dropped before tip, not counted)"
    return [head] + out


NAMES = {"ticket.json": "ticket", "ticket_2x.json": "2x combo", "ticket_ladder.json": "ladder stand-in",
         "ticket_td.json": "touchdown scorers", "ticket_safe.json": "safest ticket",
         "ticket_safe_2x.json": "safest 2x combo", "ticket_safe_ladder.json": "safest ladder stand-in",
         "ticket_other.json": "other-side card"}


def slate(folder, get=None):
    """One line per saved ticket in a slate folder (the ticket, the 2x combo,
    the ladder stand-in, any other ticket*.json): 'ladder stand-in, 6 legs:
    5 won, 0 lost, 1 still open' -- the end-of-night record in one call."""
    import glob
    get = _once(get)
    out = []
    files = sorted(glob.glob(os.path.join(folder, "ticket*.json")),
                   key=lambda f: (os.path.basename(f) not in NAMES, list(NAMES).index(os.path.basename(f))
                                  if os.path.basename(f) in NAMES else 0, f))
    for f in files:
        picks = load(f)
        head = brief(f, get)[0]
        all_won = head.startswith(f"{len(picks)} won")
        out.append(f"{NAMES.get(os.path.basename(f), os.path.basename(f))}, {len(picks)} legs: {head}"
                   + (" -- every leg won" if all_won and picks else ""))
        if os.path.basename(f) == "ticket.json":
            b = band_split(f, get)
            if b:
                out.append(b)
    return out


def in_safest(p):
    """Is this leg in build_ticket's safest bands (the --safest ticket's rule)?"""
    import build_ticket
    try:
        a = float(str(p.get("price")).replace("+", ""))
    except (TypeError, ValueError):
        return False
    if p.get("kind") == "ml":
        return (p.get("chance") or 0) >= 0.90
    return p.get("kind") == "prop" and any((lg is None or p.get("lg") == lg) and a <= cut
                                            for lg, cut in build_ticket.SAFEST)


def band_split(path, get=None):
    """'safest bands 22/25 (88%), the rest 33/42 (79%)' for a graded ticket --
    the nightly forward check of --safest (2026-11-25, counted by hand)."""
    picks, results, _ = main(path, get)
    cell = {True: [0, 0], False: [0, 0]}
    for p, r in zip(picks, results):
        if r in ("won", "lost"):
            c = cell[in_safest(p)]
            c[0] += r == "won"
            c[1] += 1
    if not (cell[True][1] or cell[False][1]):
        return ""
    fmt = lambda c: f"{c[0]}/{c[1]}" + (f" ({round(100 * c[0] / c[1])}%)" if c[1] else "")
    return f"  safest bands {fmt(cell[True])}, the rest {fmt(cell[False])}"


def live(path, get=None):
    """One line per pick: WON/LOST/PUSH when final, else the clock and where it stands."""
    out = []
    get = _once(get)
    for p in load(path):
        scores, done, clock, d = final(p["lg"], p["id"], get, with_clock=True, raw=True)
        r = grade(p, scores, done, d)
        if p["kind"] == "prop" and (r == "open" or (r == "won" and not done)):
            v = board_value(p, d)[0] if p.get("market") else None
            if v is None:
                v = player_stat(d, p["player"], p["stat"])
            have = "not in the box score yet" if v is None else f"{v:g} of {p['line']:g}"
            # reached mid-game is not won: a stat can be corrected before the
            # final (2026-11-24 Suggs 5 -> 4; 2026-11-25 Klay showed WON in the 1st)
            out.append(f"{'REACHED' if r == 'won' else 'OPEN':5} {p.get('label') or p} -- {clock}: {have}")
            continue
        tail = "" if r != "open" else f" -- {clock}: {standing(p, scores)}" if scores and any(scores.values()) else f" -- {clock or 'not started'}"
        out.append(f"{r.upper():5} {p.get('label') or p}{tail}")
    return out


def _seen_path(path):
    return path + ".seen"


def _load_seen(path):
    try:
        with open(_seen_path(path)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_seen(path, seen):
    try:
        with open(_seen_path(path), "w") as f:
            json.dump(seen, f)
    except OSError:
        pass


def _final_score(summary):
    """' (final: UTA 6, NSH 5, Final/SO)' from an ESPN summary; '' when unreadable."""
    try:
        c = summary["header"]["competitions"][0]
        teams = ", ".join(f"{x['team']['abbreviation']} {x['score']}"
                          for x in sorted(c["competitors"], key=lambda x: -int(x.get("score") or 0)))
        det = ((c.get("status") or {}).get("type") or {}).get("detail") or ""
        return f" (final: {teams}" + (f", {det}" if det and det != "Final" else "") + ")"
    except (KeyError, IndexError, TypeError, ValueError):
        return ""


def detail(pick, scores, summary):
    """' -- had 7' for a prop, ' -- 112-104' for a game leg: what settled it,
    for the live check-ins (2026-11-24: 'WON <label>' alone told the user nothing)."""
    try:
        if pick.get("kind") == "prop":
            v = board_value(pick, summary)[0] if pick.get("market") else None
            if v is None:
                v = player_stat(summary, pick["player"], pick.get("stat") or "")
            if v is None or _dnp(summary, pick["player"]):
                # 2026-11-25: "PUSH CJ Daniels: 5+ Receiving Yards" said nothing --
                # he was a game-day inactive, absent from the box score: a void
                if _completed(summary) and _dnp_or_absent(summary, pick["player"]):
                    return " -- did not play (not in the box score): void, the parlay pays on the rest"
                return ""
            # 2026-11-27: Stamkos lost 1+ shots with 0 in 17:27 -- in a 6-5 shootout;
            # the final score beside a settled prop says what kind of game it was
            fin = _final_score(summary) if _completed(summary) else ""
            if pick.get("lg") == "nhl":
                # ice time beside the stat: 2026-11-25 Lafreniere lost 1+ shots with 0
                # in 19:43 -- it tells a full-shift miss from a short night or injury
                toi = _toi(summary, pick["player"])
                return f" -- had {v:g}" + (f" in {toi} of ice time" if toi else "") + fin
            m = player_stat(summary, pick["player"], "MIN") if pick.get("lg") in ("nba", "ncaab", "wnba") else None
            # minutes beside the stat: 2026-11-25 Jaylen Brown lost 2+ assists with 1
            # in 17 minutes (31.2 a game) -- the minutes are the story of the loss
            return f" -- had {v:g}" + (f" in {m:g} min" if m else "") + fin
        if len(scores) == 2 and not scores.get("_void"):
            return " -- " + ", ".join(f"{k} {v:g}" for k, v in scores.items())
    except Exception:
        pass
    return ""


def watch(path, every=120, get=None, sleep=None, emit=print, remember=True):
    """Print each pick once when it settles (WON / LOST / PUSH), then a last
    line when none is left open. Settles already printed are remembered in
    <path>.seen, so a restarted watch (the live Monitor is re-armed every 30
    minutes) does not announce them again (2026-11-24)."""
    import time
    seen = _load_seen(path) if remember else {}
    picks = None
    while True:
        try:
            picks = load(path)
        except (OSError, ValueError):
            # 2026-11-24: a read that lands mid-write (or a moved file) must not
            # end hours of live tracking; keep the last good list and go on
            if picks is None:
                raise
        open_n = 0
        fetch = _once(get)                      # fresh each round, shared within it
        for p in picks:
            key = p.get("label") or json.dumps(p, sort_keys=True)
            if seen.get(key + "|final"):
                # 2026-11-27: a leg settled at the final never changes again (see
                # below) -- skip its ESPN read; a 61-leg ticket otherwise re-read
                # every finished game every two minutes until the last one ended
                continue
            scores, done, d = final(p["lg"], p["id"], fetch, raw=True)
            r = grade(p, scores, done, d)
            was = seen.get(key)
            if not done and (not (d or {}).get("header") or seen.get(key + "|final")):
                # 2026-11-25: a failed ESPN read (empty summary) on games already
                # final announced BACK BELOW for Kent Johnson, Hamilton and Coyle,
                # who had won. No data is not a correction, and a leg settled at
                # the final never goes back: skip this round, keep what we had.
                if not seen.get(key + "|final"):
                    open_n += 1
                continue
            if not done:
                # 2026-11-24: a prop read "won" the moment the box score reached
                # the line -- Suggs 5 reb+ast -- then ESPN corrected him to 4.
                # Mid-game it is only REACHED; it settles when the game is final.
                open_n += 1
                if r == "won" and was not in ("won", "reached"):
                    seen[key] = "reached"
                    emit(f"REACHED {key}{detail(p, scores, d)} (settles when the game ends)")
                elif r != "won" and was in ("won", "reached"):
                    seen[key] = "open"
                    emit(f"BACK BELOW {key}{detail(p, scores, d)} -- the box score was corrected; not won yet")
                else:
                    continue
                if remember:
                    _save_seen(path, seen)
                continue
            if r == "open":
                open_n += 1
            elif was != r or not seen.get(key + "|final"):
                seen[key] = r
                seen[key + "|final"] = True
                emit(f"{r.upper()} {key}{detail(p, scores, d)}" + (_standing(picks, seen) if r == "lost" else ""))
                if remember:
                    _save_seen(path, seen)
        if not open_n:
            res = [seen.get(p.get("label") or json.dumps(p, sort_keys=True), "open").lower() for p in picks]
            sm = summary(picks, res)
            emit(f"all picks settled: {sm['won']}-{sm['lost']}" + (f", {sm['push']} void" if sm["push"] else "")
                 + f"; all won: {'YES' if not sm['lost'] and sm['won'] else 'no'}" + _short_clause(picks, res))
            return seen
        (sleep or time.sleep)(every)


def _standing(picks, seen):
    """' (ticket now 6-1, 54 to go)' after a loss: where the ticket stands --
    2026-11-27, Stamkos's loss read alone gave no sense of the rest of the day."""
    keys = [p.get("label") or json.dumps(p, sort_keys=True) for p in picks]
    fin = [seen.get(k) for k in keys if seen.get(k + "|final")]
    w, l, v = fin.count("won"), fin.count("lost"), fin.count("push")
    # 2026-11-27: Owen Tippett's void (did not play) went uncounted, so the
    # live line and the brief disagreed by one; voids are named now
    return f" (ticket now {w}-{l}" + (f", {v} void" if v else "") + f", {len(keys) - len(fin)} to go)"


def _short_clause(picks, res):
    """'; short 6: 6-0 (all won)' -- the ticket's short-ticket line on its own
    results (daily_review.short_ticket_result), '' when it has no short ticket."""
    try:
        import daily_review
        sh = daily_review.short_ticket_result(picks, res)
    except Exception:
        return ""
    return f"; {sh}" if sh else ""


def shared_get(get=None, ttl=60, clock=None):
    """One ESPN read per URL per ttl seconds across every watched ticket.
    2026-11-27: the safest ticket, the backup and the TD card share most of
    their games, and each watch read every game itself each round."""
    import threading
    import time
    clock = clock or time.monotonic
    cache, lock = {}, threading.Lock()

    def fetch(u):
        with lock:
            hit = cache.get(u)
            if hit and clock() - hit[0] < ttl:
                return hit[1]
        d = (get or _fetch)(u)
        with lock:
            cache[u] = (clock(), d)
        return d
    return fetch


def merged_emit(emit, lock, wait=20.0, timer=None):
    """emit(name, msg) that prints one line per message with every ticket it
    came from: '[safest ticket, ticket] REACHED ...'. 2026-11-27: a leg on both
    tickets printed twice a few seconds apart (Raddysh, Marchenko); the watches
    run their rounds together, so messages within `wait` seconds are joined.
    'all picks settled' lines differ per ticket and print on their own."""
    import threading
    timer = timer or threading.Timer
    pending = {}

    def flush(msg):
        with lock:
            names = pending.pop(msg, [])
            if names:
                emit(f"[{', '.join(names)}] {msg}")

    def put(name, msg):
        if msg.startswith("all picks settled"):
            with lock:
                emit(f"[{name}] {msg}")
            return
        with lock:
            first = msg not in pending
            pending.setdefault(msg, [])
            if name not in pending[msg]:
                pending[msg].append(name)
        if first:
            t = timer(wait, flush, args=(msg,))
            t.daemon = True
            t.start()
    put.flush = flush
    put.flush_all = lambda: [flush(m) for m in list(pending)]
    return put


def watch_many(paths, emit=print, watch_fn=None):
    """One watch per ticket file, in parallel, each line tagged with the
    ticket's name -- 2026-11-26: the safest ticket, the backup, the TD list and
    the other-side card each needed its own Monitor."""
    import threading
    watch_fn = watch_fn or watch
    if len(paths) == 1:
        return watch_fn(paths[0], emit=emit)
    lock = threading.Lock()
    get = shared_get()
    merge = merged_emit(emit, lock)

    def run(path):
        name = NAMES.get(os.path.basename(path), os.path.basename(path))
        watch_fn(path, emit=lambda m: merge(name, m), get=get)
    threads = [threading.Thread(target=run, args=(p,), daemon=True) for p in paths]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    merge.flush_all()                  # every ticket done: print what is still waiting


if __name__ == "__main__":
    if "--watch" in sys.argv:
        watch_many([a for a in sys.argv[1:] if a != "--watch"], emit=lambda m: print(m, flush=True))
        sys.exit(0)
    if "--slate" in sys.argv:
        print("\n".join(slate([a for a in sys.argv[1:] if a != "--slate"][0])))
        sys.exit(0)
    if "--brief" in sys.argv:
        print("\n".join(brief([a for a in sys.argv[1:] if a != "--brief"][0])))
        sys.exit(0)
    if "--live" in sys.argv:
        print("\n".join(live([a for a in sys.argv[1:] if a != "--live"][0])))
        sys.exit(0)
    picks, results, s = main(sys.argv[1])
    for p, r in zip(picks, results):
        print(f"{r.upper():5} {p.get('label') or p}")
    print(f"Record {s['won']}-{s['lost']}" + (f"-{s['push']}" if s["push"] else "")
          + f", {s['open']} open, {s['units']:+.2f} units at $1 a pick")
