"""Record every prop the board recommends, grade it from the box score, and
re-fit the props' probabilities from what actually happened.

WHY

Prop probabilities are the book's one-sided price divided by an ASSUMED 7%
margin (player_props.ONE_SIDED_HOLD). Nothing checked that assumption, and
it cannot be backtested: ESPN removes prop prices once a game is final
(probed 2026-10-15 -- 0 priced items on every finished game). So the only
way to measure it is to write each prop down while it is still priced, then
settle it from the player's box-score line after the game.

WHAT GETS RECORDED

The legs of the Props tab's stacks (the props the board actually puts on a
ticket), once each, at the price first seen. props.json is committed by the
board workflow like ledger.json.

HOW IT TUNES

For each league, the margin that would have made the recorded probabilities
match the results is

    hold = sum(book implied probability) / props won

blended with the assumed 1.07 by PRIOR_PROPS pseudo-props, so a handful of
results cannot swing it. A league whose props win less often than priced
gets a larger margin, so fewer of its props clear the 75% floor for stacks.

Only markets the box score can settle are graded (yards, receptions,
touchdowns, tackles, sacks; goals, assists, points, shots, blocks, saves;
hits, runs, RBIs, homers, walks, strikeouts, pitchers' hits/walks/earned
runs). Others -- total bases, stolen bases, doubles, soccer -- stay
"ungradable" and never count.
"""
import datetime as dt
import json
import os
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "props.json")
CACHE = os.path.join(HERE, ".cache", "summaries")
SITE = "https://site.api.espn.com/apis/site/v2/sports"

ASSUMED_HOLD = 1.07
PRIOR_PROPS = 150          # pseudo-props at the assumed margin
HOLD_BOUNDS = (0.90, 1.60)
VOID_AFTER_DAYS = 5
MAX_EVENTS_PER_RUN = 30

SPORT = {"nfl": ("football", "nfl"), "ncaaf": ("football", "college-football"),
         "nhl": ("hockey", "nhl"), "mlb": ("baseball", "mlb"),
         "nba": ("basketball", "nba"), "wnba": ("basketball", "wnba"),
         "ncaab": ("basketball", "mens-college-basketball")}


def _s(*keys):
    """Sum of box-score stats, each 'group.key' or a bare key."""
    def f(st):
        tot = 0.0
        for k in keys:
            v = st.get(k)
            if v is None:
                return None
            tot += v
        return tot
    return f


def _diff(a, b):
    def f(st):
        if st.get(a) is None or st.get(b) is None:
            return None
        return st[a] - st[b]
    return f


_TD = ("rushing.rushingTouchdowns", "receiving.receivingTouchdowns")


def _tds(st):
    base = [st.get(k) for k in _TD]
    if all(v is None for v in base):
        return None
    extra = ("kickReturns.kickReturnTouchdowns", "puntReturns.puntReturnTouchdowns",
             "interceptions.interceptionTouchdowns")
    return sum(v or 0 for v in base) + sum(st.get(k) or 0 for k in extra)


FOOTBALL = {
    "Receiving Yards": _s("receiving.receivingYards"),
    "Total Receiving Yards": _s("receiving.receivingYards"),
    "Receptions": _s("receiving.receptions"),
    "Total Receptions": _s("receiving.receptions"),
    "Rushing Yards": _s("rushing.rushingYards"),
    "Total Rushing Yards": _s("rushing.rushingYards"),
    "Rushing + Receiving Yards": _s("rushing.rushingYards", "receiving.receivingYards"),
    "Total Rushing Plus Receiving Yards": _s("rushing.rushingYards", "receiving.receivingYards"),
    "Passing Yards": _s("passing.passingYards"),
    "Total Passing Yards": _s("passing.passingYards"),
    "Passing Touchdowns": _s("passing.passingTouchdowns"),
    "Total Passing Touchdowns": _s("passing.passingTouchdowns"),
    "Total Carries": _s("rushing.rushingAttempts"),
    "Tackles + Assists": _s("defensive.totalTackles"),
    "Total Tackles Plus Assists": _s("defensive.totalTackles"),
    "Tackles": _s("defensive.soloTackles"),
    "Total Tackles": _s("defensive.soloTackles"),
    "Assists (Football)": _diff("defensive.totalTackles", "defensive.soloTackles"),
    "Total Assists": _diff("defensive.totalTackles", "defensive.soloTackles"),
    "Sacks": _s("defensive.sacks"),
    "Total Sacks": _s("defensive.sacks"),
    "Anytime Touchdown Scorer": _tds,
    "Player to score 2 or more touchdowns": _tds,
    "Player to score 3 or more touchdowns": _tds,
}
HOCKEY = {
    "Goals": _s("goals"), "Anytime Goalscorer": _s("goals"),
    "To Score 2+ Goals": _s("goals"), "To Score 3+ Goals": _s("goals"),
    "Points": _s("goals", "assists"), "Total Points": _s("goals", "assists"),
    "Assists": _s("assists"), "Total Assists": _s("assists"),
    "Shots on Goal": _s("shotsTotal"), "Total Shots on Goal": _s("shotsTotal"),
    "Blocked Shots": _s("blockedShots"), "Total Blocked Shots": _s("blockedShots"),
    "Goalkeeper Saves": _s("saves"), "Total Saves": _s("saves"),
}
BASEBALL = {
    "Hits": _s("batting.hits"), "Total Hits": _s("batting.hits"),
    "RBIs": _s("batting.RBIs"), "Total RBIs": _s("batting.RBIs"),
    "Home Runs": _s("batting.homeRuns"),
    "Runs": _s("batting.runs"), "Total Runs Scored": _s("batting.runs"),
    "Hits + Runs + RBIs": _s("batting.hits", "batting.runs", "batting.RBIs"),
    "Total Hits + Runs + RBIs": _s("batting.hits", "batting.runs", "batting.RBIs"),
    "Runs + RBIs": _s("batting.runs", "batting.RBIs"),
    "Strikeouts (Batter)": _s("batting.strikeouts"),
    "Walks (Batter)": _s("batting.walks"), "Total Walks (Batter)": _s("batting.walks"),
    "Strikeouts Thrown": _s("pitching.strikeouts"), "Total Strikeouts": _s("pitching.strikeouts"),
    "Hits Allowed": _s("pitching.hits"), "Total Hits Allowed": _s("pitching.hits"),
    "Walks Allowed": _s("pitching.walks"), "Total Walks Allowed": _s("pitching.walks"),
    "Earned Runs Allowed": _s("pitching.earnedRuns"),
    "Hits + Walks + Earned Runs": _s("pitching.hits", "pitching.walks", "pitching.earnedRuns"),
    "Hits + Walks + Earned Runs Allowed": _s("pitching.hits", "pitching.walks", "pitching.earnedRuns"),
}
BASKETBALL = {
    "Points": _s("points"), "Total Points": _s("points"),
    "Rebounds": _s("rebounds"), "Total Rebounds": _s("rebounds"),
    "Assists": _s("assists"), "Total Assists": _s("assists"),
    "Threes Made": _s("threePointFieldGoalsMade"),
}
MARKETS = {"nfl": FOOTBALL, "ncaaf": FOOTBALL, "nhl": HOCKEY, "mlb": BASEBALL,
           "nba": BASKETBALL, "wnba": BASKETBALL, "ncaab": BASKETBALL}
# scorer markets with no line: the count they need
NEED = {"Anytime Touchdown Scorer": 1, "Player to score 2 or more touchdowns": 2,
        "Player to score 3 or more touchdowns": 3, "Anytime Goalscorer": 1,
        "To Score 2+ Goals": 2, "To Score 3+ Goals": 3}


def gradable(league, market):
    return market in (MARKETS.get(league) or {})


def won(league, market, line, value):
    """Did `value` clear the prop? Milestones read "50+" (at least 50); plain
    lines read "0.5" (over); scorer markets carry no line."""
    if market in NEED and not line:
        return value >= NEED[market]
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*\+\s*$", str(line))
    if m:
        return value >= float(m.group(1))
    try:
        x = float(line)
    except (TypeError, ValueError):
        return None
    return value > x if x != int(x) else value >= x


# ------------------------------------------------------------------ storage
def load():
    try:
        with open(LEDGER) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save(book):
    with open(LEDGER, "w") as fh:
        json.dump(book, fh, indent=1, sort_keys=True)


def record(slot, day):
    """Log each leg of the slot's prop stacks once, at the first price seen."""
    book = load()
    seen = 0
    day = str(day)
    if re.fullmatch(r"\d{8}", day):
        day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    for tickets in ((slot or {}).get("tickets") or {}).values():
        for t in tickets:
            for L in t["legs"]:
                if not L.get("gid") or not L.get("aid"):
                    continue
                key = f'{L["gid"]}|{L["aid"]}|{L["market"]}|{L["line"]}'
                if key in book:
                    continue
                league = L["gid"].split(":", 1)[0]
                book[key] = dict(league=league, gid=L["gid"], aid=L["aid"], name=L["name"],
                                 market=L["market"], line=L["line"], price=L["price"],
                                 imp=L.get("imp"), p=L["p"], label=L["label"], date=day,
                                 status="open" if gradable(league, L["market"]) else "ungradable")
                seen += 1
    save(book)
    return seen


# ------------------------------------------------------------------ grading
def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                timeout=25) as r:
        return json.load(r)


def summary(league, eid):
    """ESPN game summary; finished games are cached for good."""
    os.makedirs(CACHE, exist_ok=True)
    f = os.path.join(CACHE, f"{league}-{eid}.json")
    if os.path.exists(f):
        with open(f) as fh:
            return json.load(fh)
    sport, lg = SPORT[league]
    try:
        d = _get(f"{SITE}/{sport}/{lg}/summary?event={eid}")
    except Exception:
        return None
    comp = ((d.get("header") or {}).get("competitions") or [{}])[0]
    if ((comp.get("status") or {}).get("type") or {}).get("completed"):
        with open(f, "w") as fh:
            json.dump({"boxscore": d.get("boxscore"), "completed": True}, fh)
        return {"boxscore": d.get("boxscore"), "completed": True}
    return {"completed": False}


def box_stats(sm):
    """athlete id -> {'group.key': number, 'key': number}"""
    out = {}
    for team in ((sm or {}).get("boxscore") or {}).get("players") or []:
        for grp in team.get("statistics") or []:
            g = grp.get("name") or ""
            keys = grp.get("keys") or []
            for a in grp.get("athletes") or []:
                aid = str((a.get("athlete") or {}).get("id") or "")
                if not aid:
                    continue
                st = out.setdefault(aid, {})
                for k, v in zip(keys, a.get("stats") or []):
                    # "hits-atBats" = "1-3", "completions/passingAttempts" =
                    # "12/19": one stat per part
                    ks, vs = re.split(r"[-/]", k), re.split(r"(?<=\d)[-/]", str(v))
                    if len(ks) != len(vs):
                        ks, vs = [k], [str(v).split("/")[0]]
                    for kk, vv in zip(ks, vs):
                        try:
                            num = float(vv)
                        except ValueError:
                            continue
                        st[f"{g}.{kk}"] = num
                        st.setdefault(kk, num)
    return out


def grade():
    book = load()
    by_game = {}
    for k, e in book.items():
        if e["status"] == "open":
            by_game.setdefault(e["gid"], []).append(e)
    today = dt.date.today()
    for gid, es in list(by_game.items())[:MAX_EVENTS_PER_RUN]:
        league, eid = gid.split(":", 1)
        if league not in SPORT:
            continue
        sm = summary(league, eid)
        if not sm or not sm.get("completed"):
            for e in es:
                age = (today - dt.date.fromisoformat(e["date"])).days
                if age > VOID_AFTER_DAYS:
                    e["status"] = "void"
            continue
        stats = box_stats(sm)
        for e in es:
            st = stats.get(str(e["aid"]))
            if st is None:
                e["status"] = "void"            # did not play: books void these
                continue
            v = MARKETS[league][e["market"]](st)
            if v is None:
                e["status"] = "ungradable"
                continue
            ok = won(league, e["market"], e["line"], v)
            if ok is None:
                e["status"] = "ungradable"
                continue
            e["status"] = "won" if ok else "lost"
            e["value"] = v
        time.sleep(0.2)
    save(book)


# ------------------------------------------------------------------- tuning
HOLD = {}
TUNING = {}


def tune():
    """Per-league one-sided margin, fitted from graded props."""
    HOLD.clear()
    TUNING.clear()
    agg = {}
    for e in load().values():
        if e["status"] not in ("won", "lost") or not e.get("imp"):
            continue
        a = agg.setdefault(e["league"], [0, 0, 0.0, 0.0])
        a[0] += 1
        a[1] += e["status"] == "won"
        a[2] += e["imp"]
        a[3] += e["p"]
    for lg, (n, w, imp, said) in agg.items():
        live = imp / max(w, 1)
        k = (n * live + PRIOR_PROPS * ASSUMED_HOLD) / (n + PRIOR_PROPS)
        k = min(max(k, HOLD_BOUNDS[0]), HOLD_BOUNDS[1])
        HOLD[lg] = round(k, 3)
        TUNING[lg] = dict(graded=n, won=w, hit=round(100 * w / n, 1),
                          said=round(100 * said / n, 1), hold=HOLD[lg])


def hold(league):
    return HOLD.get(league, ASSUMED_HOLD)


tune()
