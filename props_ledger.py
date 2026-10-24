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
import unicodedata
import time
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "props.json")
CACHE = os.path.join(HERE, ".cache", "summaries")
SITE = "https://site.api.espn.com/apis/site/v2/sports"

ASSUMED_HOLD = 1.07
PRIOR_PROPS = 150          # pseudo-props at the assumed margin
PRIOR_MARKET = 40          # pseudo-props at the league's margin, per market
MARKET_HOLD = {}           # (league, market) -> fitted margin
HOLD_BOUNDS = (0.90, 1.60)
VOID_AFTER_DAYS = 5
MAX_EVENTS_PER_RUN = 30

SPORT = {"nfl": ("football", "nfl"), "ncaaf": ("football", "college-football"),
         "nhl": ("hockey", "nhl"), "mlb": ("baseball", "mlb"),
         "nba": ("basketball", "nba"), "wnba": ("basketball", "wnba"),
         "ncaab": ("basketball", "mens-college-basketball"),
         "epl": ("soccer", "eng.1"), "esp": ("soccer", "esp.1"), "ger": ("soccer", "ger.1"),
         "ita": ("soccer", "ita.1"), "fra": ("soccer", "fra.1"), "mls": ("soccer", "usa.1"),
         "ucl": ("soccer", "uefa.champions"), "uel": ("soccer", "uefa.europa")}


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


def _diff0(a, b):
    def f(st):
        if not st:
            return None
        return (st.get(a) or 0.0) - (st.get(b) or 0.0)
    return f


def _s0(*keys):
    """Football: a player's box score lists only the stat groups he recorded
    something in, so a resolved player with no receiving line caught nothing
    -- 0, not 'ungradable' (2026-10-18: Josh Cameron played, kick returns only,
    and his Receiving Yards 5+ was set aside instead of graded lost)."""
    def f(st):
        if not st:
            return None
        return float(sum(st.get(k) or 0.0 for k in keys))
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
    if not st:                                  # not in the box score at all
        return None
    extra = ("kickReturns.kickReturnTouchdowns", "puntReturns.puntReturnTouchdowns",
             "interceptions.interceptionTouchdowns")
    return sum(v or 0 for v in base) + sum(st.get(k) or 0 for k in extra)


FOOTBALL = {
    "Receiving Yards": _s0("receiving.receivingYards"),
    "Total Receiving Yards": _s0("receiving.receivingYards"),
    "Receptions": _s0("receiving.receptions"),
    "Total Receptions": _s0("receiving.receptions"),
    "Rushing Yards": _s0("rushing.rushingYards"),
    "Total Rushing Yards": _s0("rushing.rushingYards"),
    "Rushing + Receiving Yards": _s0("rushing.rushingYards", "receiving.receivingYards"),
    "Total Rushing Plus Receiving Yards": _s0("rushing.rushingYards", "receiving.receivingYards"),
    "Passing Yards": _s0("passing.passingYards"),
    "Total Passing Yards": _s0("passing.passingYards"),
    "Passing Touchdowns": _s0("passing.passingTouchdowns"),
    "Total Passing Touchdowns": _s0("passing.passingTouchdowns"),
    "Total Carries": _s0("rushing.rushingAttempts"),
    "Tackles + Assists": _s0("defensive.totalTackles"),
    "Total Tackles Plus Assists": _s0("defensive.totalTackles"),
    "Tackles": _s0("defensive.soloTackles"),
    "Total Tackles": _s0("defensive.soloTackles"),
    "Assists (Football)": _diff0("defensive.totalTackles", "defensive.soloTackles"),
    "Total Assists": _diff0("defensive.totalTackles", "defensive.soloTackles"),
    "Sacks": _s0("defensive.sacks"),
    "Total Sacks": _s0("defensive.sacks"),
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
    # FanDuel's combination markets
    "Pts + Reb + Ast": _s("points", "rebounds", "assists"),
    "Pts + Reb": _s("points", "rebounds"),
    "Pts + Ast": _s("points", "assists"),
    "Reb + Ast": _s("rebounds", "assists"),
}
# ESPN soccer summaries (rosters[].roster[].stats, probed 2026-10-15) carry
# goals, assists, shots, shots on target, cards, fouls, saves -- NOT tackles,
# so tackle props stay ungradable. Several spellings of each market are
# listed because the feed's soccer market names vary by competition.
SOCCER = {}
for _names, _f in (
        (("Anytime Goalscorer", "Anytime Goal Scorer", "To Score"), _s("totalGoals")),
        (("To Score 2+ Goals", "To Score 2 or More Goals"), _s("totalGoals")),
        (("Shots", "Total Shots", "Player Shots"), _s("totalShots")),
        (("Shots on Target", "Total Shots on Target", "Player Shots on Target",
          "Shots On Target"), _s("shotsOnTarget")),
        (("Assists", "Total Assists", "Player Assists", "To Assist"), _s("goalAssists")),
        (("To Be Booked", "Player To Be Booked", "To Be Carded", "Player to be Carded",
          "Cards", "Player Cards"), _s("yellowCards", "redCards")),
        (("Goalkeeper Saves", "Saves", "Total Saves"), _s("saves"))):
    for _n in _names:
        SOCCER[_n] = _f
MARKETS = {"epl": SOCCER, "esp": SOCCER, "ger": SOCCER, "ita": SOCCER, "fra": SOCCER,
           "mls": SOCCER, "ucl": SOCCER, "uel": SOCCER,
           "nfl": FOOTBALL, "ncaaf": FOOTBALL, "nhl": HOCKEY, "mlb": BASEBALL,
           "nba": BASKETBALL, "wnba": BASKETBALL, "ncaab": BASKETBALL}
# scorer markets with no line: the count they need
NEED = {"Anytime Goal Scorer": 1, "To Score": 1, "To Score 2 or More Goals": 2,
        "To Be Booked": 1, "Player To Be Booked": 1, "To Be Carded": 1,
        "Player to be Carded": 1, "To Assist": 1,
        "Anytime Touchdown Scorer": 1, "Player to score 2 or more touchdowns": 2,
        "Player to score 3 or more touchdowns": 3, "Anytime Goalscorer": 1,
        "To Score 2+ Goals": 2, "To Score 3+ Goals": 3}


# Markets the record says not to offer. Soccer shot milestones (Europa League,
# 2026-10-15): 23 graded "1+ / 2+ shots" props priced -900 to -2500 (84%
# claimed) hit 11 -- ESPN's box scores confirm the zeros. Six of the misses
# were substitutes: the price assumes a full game, a late sub still counts as
# action. Until lineups can be confirmed before pricing, they stay off.
SOCCER = {"epl", "esp", "ger", "ita", "fra", "mls", "ucl", "uel"}
# every league that is not soccer: the shots rule must cover ALL soccer
# leagues (Championship, Conference League, ...), not only the eight above
NOT_SOCCER = {"nfl", "ncaaf", "nba", "ncaab", "wnba", "mlb", "nhl", "ufc", "atp", "wta", "pga"}


def offered(league, market):
    return not (league not in NOT_SOCCER and market.lower().startswith(("shots", "total shots",
                                                                        "player shots")))


def gradable(league, market):
    if league == "ufc":
        import ufc_props
        return market in ufc_props.MARKETS
    return market in (MARKETS.get(league) or {})


def won(league, market, line, value):
    """Did `value` clear the prop? Milestones read "50+" (at least 50); plain
    lines read "0.5" (over) or "u0.5" (under); scorer markets carry no line."""
    if market in NEED and not line:
        return value >= NEED[market]
    u = re.match(r"^\s*u\s*(\d+(?:\.\d+)?)\s*$", str(line))
    if u:
        return value < float(u.group(1))
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


def _key_name(n):
    """The name part of a record key. Frozen at the original normalisation so
    keys already written (and the Locks / Lottery legs that look them up)
    stay valid; matching players to box scores uses norm_name()."""
    n = re.sub(r"[^a-z ]", "", (n or "").lower().replace("-", " "))
    return " ".join(w for w in n.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def prop_key(L):
    who = L.get("aid") or "n:" + _key_name(L.get("name"))
    return f'{L["gid"]}|{who}|{L["market"]}|{L["line"]}'


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
                if not L.get("gid") or not (L.get("aid") or L.get("name")):
                    continue
                key = prop_key(L)
                if key in book:
                    continue
                league = L["gid"].split(":", 1)[0]
                book[key] = dict(league=league, gid=L["gid"], aid=L["aid"], name=L["name"],
                                 market=L["market"], line=L["line"], price=L["price"],
                                 imp=L.get("imp"), p=L["p"], label=L["label"], date=day,
                                 p_fair=L.get("p_fair"), edge=L.get("edge"),
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
        keep = {"boxscore": d.get("boxscore"), "rosters": d.get("rosters"), "completed": True}
        with open(f, "w") as fh:
            json.dump(keep, fh)
        return keep
    return {"completed": False}


def norm_name(n):
    """'Tim Stützle' -> 'tim stutzle'; 'Sebastian Aho (CAR)' -> 'sebastian aho'.
    Accents are folded, not dropped: dropping them turned Stützle into
    'sttzle', which matched nobody, and the prop was voided as a DNP."""
    n = re.sub(r"\([^)]*\)", " ", n or "")
    n = unicodedata.normalize("NFKD", n.replace("ø", "o").replace("Ø", "O")
                              .replace("ł", "l").replace("đ", "d"))
    n = n.encode("ascii", "ignore").decode().lower().replace("-", " ").replace(".", " ")
    n = re.sub(r"[^a-z ]", "", n)
    return " ".join(w for w in n.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def team_hint(n):
    """'Sebastian Aho (CAR)' -> 'car': FanDuel's tag for players who share a name."""
    m = re.search(r"\(([A-Za-z]{2,4})\)", n or "")
    return m.group(1).lower() if m else None


# Reviewed spellings that differ between FanDuel and ESPN beyond accents and
# short first names. Keys and values are norm_name() forms.
ALIASES = {}


# Given names and the familiar forms that are not simple prefixes of them
# ('kenny' is not a prefix of 'kenneth'): 2026-10-24, FanDuel's "Kenneth
# Gainwell" is ESPN's "Kenny Gainwell", and his prop sat unsettled. Matching
# still needs the same surname and exactly one such player in the box score.
NICKNAMES = [
    {"kenneth", "kenny", "ken"}, {"william", "will", "bill", "billy", "willie"},
    {"robert", "rob", "bob", "bobby", "robbie"}, {"james", "jim", "jimmy", "jamie"},
    {"joseph", "joe", "joey"}, {"michael", "mike", "mikey"}, {"christopher", "chris"},
    {"nicholas", "nick", "nicky"}, {"anthony", "tony"}, {"daniel", "dan", "danny"},
    {"thomas", "tom", "tommy"}, {"richard", "rick", "ricky", "rich", "dick"},
    {"edward", "ed", "eddie", "ted"}, {"charles", "charlie", "chuck"}, {"matthew", "matt"},
    {"zachary", "zach", "zack"}, {"benjamin", "ben", "benny"}, {"jonathan", "jon", "jonny"},
    {"andrew", "andy", "drew"}, {"samuel", "sam", "sammy"}, {"theodore", "ted", "teddy", "theo"},
    {"gregory", "greg"}, {"timothy", "tim", "timmy"}, {"jacob", "jake"},
    {"nathaniel", "nathan", "nate"}, {"patrick", "pat"}, {"stephen", "steven", "steve"},
    {"cameron", "cam"}, {"joshua", "josh"}, {"jeffrey", "jeff"}, {"douglas", "doug"},
    {"gerald", "jerry"}, {"lawrence", "larry"}, {"ronald", "ron", "ronnie"},
    {"donald", "don", "donnie"}, {"frederick", "fred", "freddie"}, {"walter", "walt"},
    {"vincent", "vince"}, {"mitchell", "mitch"}, {"maximilian", "max"}, {"isaiah", "ike"},
]
_NICK = {}
for _g in NICKNAMES:
    for _n in _g:
        _NICK.setdefault(_n, set()).update(_g)


def _first_ok(a, b):
    """First names that can be the same person: equal, one a short form of
    the other ('mitch' / 'mitchell', 'alex' / 'alexander'), or a familiar
    form of it ('kenny' / 'kenneth')."""
    return (a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a)))
            or b in _NICK.get(a, ()))


def resolve(stats, e):
    """(stats, how) for one prop's player in a box score, where how is 'id',
    'name', 'fuzzy' or 'alias'; (None, 'absent') when no player in the box
    shares the surname (did not dress / did not play); (None, 'unresolved')
    when someone could be the player but not uniquely -- that must be
    retried or reviewed, never graded as a DNP."""
    if e.get("aid") and str(e["aid"]) in stats:
        return stats[str(e["aid"])], "id"
    nm = norm_name(e.get("name"))
    hint = team_hint(e.get("name"))
    people = stats.get("_people") or []           # [(norm name, team abbr, stats)]

    def pick(cands, how):
        if hint and len(cands) > 1:
            cands = [c for c in cands if c[1] == hint]
        return (cands[0][2], how) if len(cands) == 1 else None

    got = pick([c for c in people if c[0] == nm], "name")
    if got:
        return got
    if nm in ALIASES:
        got = pick([c for c in people if c[0] == ALIASES[nm]], "alias")
        if got:
            return got
    w = nm.split()
    if not w:
        return None, "unresolved"
    same_last = [c for c in people if c[0].split()[-1:] == w[-1:]]
    got = pick([c for c in same_last if _first_ok(c[0].split()[0], w[0])], "fuzzy")
    if got:
        return got
    if not people and "name:" + nm in stats:      # older callers: name keys only
        return stats["name:" + nm], "name"
    return (None, "unresolved") if same_last else (None, "absent")


def box_stats(sm):
    """athlete id -> {'group.key': number, 'key': number}; also
    'name:<normalised name>' -> the same dict, for props keyed by name."""
    out = {}
    # soccer: per-player stats under rosters; a squad player who never came
    # on (appearances 0) did not play, so he is left out and the prop voids
    for team in (sm or {}).get("rosters") or []:
        for pl in team.get("roster") or []:
            aid = str((pl.get("athlete") or {}).get("id") or "")
            st = {x.get("name"): x.get("value") for x in pl.get("stats") or []
                  if isinstance(x.get("value"), (int, float))}
            if aid and st.get("appearances"):
                out[aid] = st
                nm = norm_name((pl.get("athlete") or {}).get("displayName"))
                if nm:
                    out["name:" + nm] = st
                    out.setdefault("_people", []).append(
                        (nm, ((team.get("team") or {}).get("abbreviation") or "").lower(), st))
    for team in ((sm or {}).get("boxscore") or {}).get("players") or []:
        abbr = ((team.get("team") or {}).get("abbreviation") or "").lower()
        for grp in team.get("statistics") or []:
            # MLB groups carry their name in "type" ("batting") with name
            # null: keyed "" before 2026-10-18, every batting prop ungradable
            g = grp.get("name") or grp.get("type") or ""
            keys = grp.get("keys") or []
            for a in grp.get("athletes") or []:
                aid = str((a.get("athlete") or {}).get("id") or "")
                if not aid:
                    continue
                fresh = aid not in out
                st = out.setdefault(aid, {})
                nm = norm_name((a.get("athlete") or {}).get("displayName"))
                if nm:
                    out.setdefault("name:" + nm, st)
                    if fresh:
                        out.setdefault("_people", []).append((nm, abbr, st))
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
    # UFC fights grade from ESPN's MMA results, not a box score
    ufc = [e for e in book.values() if e["status"] == "open" and e.get("league") == "ufc"]
    if ufc:
        try:
            import ufc_props
            ufc_props.grade(ufc)
        except Exception as ex:                            # never block the rest
            print(f"props: ufc grading failed: {ex}", file=sys.stderr)
    # once: records voided or set aside before 2026-10-18 by the name /
    # MLB-group bugs are re-checked by the fixed grader (idempotent)
    for e in book.values():
        if e["status"] in ("void", "ungradable") and e.get("league") in SPORT \
                and not e.get("rechecked"):
            e["rechecked"] = e["status"]
            e["status"] = "open"
    # once more for football: records set aside because a played player had
    # no line in the stat's group are graded at 0 now (_s0)
    for e in book.values():
        if e["status"] == "ungradable" and e.get("void_why") == "schema_error" \
                and e.get("league") in ("nfl", "ncaaf") and not e.get("rechecked_fb"):
            e["rechecked_fb"] = True
            e["status"] = "open"
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
            st, how = resolve(stats, e)
            if how == "absent":
                e["status"], e["void_why"] = "void", "not in box score"   # did not play
                e["state"] = "dnp"                                         # explicit: a DNP void
                continue
            if st is None:
                # a name that could be someone in the box: never a DNP. Kept
                # open and retried; after VOID_AFTER_DAYS it is set aside for
                # review, out of every record (2026-10-18: Aho (CAR), Stützle
                # and Marner were voided this way although all three played)
                e["unresolved"] = True
                if (today - dt.date.fromisoformat(e["date"])).days > VOID_AFTER_DAYS:
                    e["status"], e["void_why"] = "ungradable", "identity_unresolved"
                continue
            e.pop("unresolved", None)
            if how != "id":
                e["matched"] = how
            f = (MARKETS.get(league) or {}).get(e["market"])
            if f is None:                       # no reader for it: never crash the run
                e["status"], e["void_why"] = "ungradable", "no grader for market"
                continue
            v = f(st)
            if v is None:
                e["status"], e["void_why"] = "ungradable", "schema_error"
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
    # and per market within a league, shrunk toward that league's margin: one
    # sport's props are not one market (NHL "shots on goal" vs "points")
    MARKET_HOLD.clear()
    per = {}
    for e in load().values():
        if e["status"] not in ("won", "lost") or not e.get("imp"):
            continue
        a = per.setdefault((e["league"], e["market"]), [0, 0, 0.0])
        a[0] += 1
        a[1] += e["status"] == "won"
        a[2] += e["imp"]
    for (lg, mk), (n, w, imp) in per.items():
        base = HOLD.get(lg, ASSUMED_HOLD)
        k = (n * (imp / max(w, 1)) + PRIOR_MARKET * base) / (n + PRIOR_MARKET)
        MARKET_HOLD[(lg, mk)] = round(min(max(k, HOLD_BOUNDS[0]), HOLD_BOUNDS[1]), 3)


def hold(league, market=None):
    if market is not None and (league, market) in MARKET_HOLD:
        return MARKET_HOLD[(league, market)]
    return HOLD.get(league, ASSUMED_HOLD)


tune()
