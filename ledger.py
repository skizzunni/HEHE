"""Pick ledger: record every call, grade it, diagnose the losses, learn slowly.

    python3 ledger.py record      # snapshot today's picks (idempotent)
    python3 ledger.py grade       # settle finished games, diagnose losses
    python3 ledger.py report      # record, calibration, loss patterns
    python3 ledger.py cycle       # record + grade + report, for the hourly job

WHY IT DOES NOT AUTO-RETUNE ON LOSSES

A bad night and a bad model are indistinguishable at small n. A 57% process over
14 games has a standard deviation of 1.9 games, so 6 and 10 wins are both
ordinary. Earlier in this project a calibration curve fitted to a handful of
in-sample results *degraded* held-out Brier (0.2449 -> 0.2455). Retuning on the
last few losses is how a model gets worse while looking responsive.

So the ledger separates two things:

  * DIAGNOSIS runs on every loss immediately -- was the market on my side, was
    it a blowout or a coin flip, which confidence band, was a starter unknown.
    That is description, and description is safe at any n.

  * RETUNING is gated. `report` only recommends a parameter change when a
    pattern clears a significance bar (>=100 graded picks in a bucket and a
    calibration gap wider than two standard errors). Below that it says so and
    changes nothing.
"""
from record_eligibility import record_priced, selection_leg, quote_at, quote_book
import argparse
import datetime as dt
import json
import math
import os
import ssl
import sys
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "ledger.json")
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
from zoneinfo import ZoneInfo                                    # noqa: E402
ET = ZoneInfo("America/New_York")      # with daylight saving; see dashboard.ET

# The board and the grader have to agree on where a league lives, so this is
# derived from the board's own league table rather than kept as a second copy.
# It used to be hardcoded here and had drifted to 12 entries against the
# board's 45 -- every soccer competition except the Premier League was
# unknown to the grader, so 105 settled picks sat "open" forever and their
# results were silently thrown away.
import dashboard as _d                                       # noqa: E402

PATHS = {k: p for k, p, _ in _d.LEAGUES}
# Leagues that have since left the board still have picks in the ledger. With
# only the board's map, 102 soccer and tennis picks recorded before the
# 2026-09-05 cut could never find their games and sat "open" forever.
import anysport as _A                                        # noqa: E402
for _k, (_p, _, _) in _A.LEAGUES.items():
    PATHS.setdefault(_k, _p)
PATHS.setdefault("atp", "tennis/atp")
PATHS.setdefault("wta", "tennis/wta")
SOCCER = {k for k, p in PATHS.items() if p.startswith("soccer/")}
# A pick still open this long after its game date was postponed, cancelled,
# or dropped from the feed. It is voided, not counted as a win or a loss.
VOID_AFTER_DAYS = 7

_CTX = ssl.create_default_context()
try:
    _CTX.load_verify_locations("/root/.ccr/ca-bundle.crt")
except OSError:
    pass


def get(url, tries=2):
    for a in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=40, context=_CTX) as r:
                return json.load(r)
        except Exception:
            pass
    return {}


def load():
    try:
        with open(LEDGER) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save(d):
    # no indentation (as tickets/locks/lottery): 9.2 -> 7.3 MB on 2026-11-03,
    # headroom under GitHub's 100 MB limit, which this file hit on 2026-10-30
    with open(LEDGER, "w") as fh:
        json.dump(d, fh, separators=(",", ":"), sort_keys=True)


# ------------------------------------------------------------------ record
# what was shown. The policy fingerprint is kept in every entry but does not
# start one by itself: it includes the fallback model weight, refitted as
# games settle, so it moved nearly every build with the call unchanged.
VERSION_KEYS = ("pick", "dc", "price", "price_market", "price_book", "conf")


def _version(h):
    return {k: h.get(k) for k in VERSION_KEYS}


def compact_history(book):
    """Collapse runs of history entries that show the same version (only the
    quote time moved) to the first of each run -- when that version was first
    shown. Returns how many entries were dropped."""
    dropped = 0
    for e in book.values():
        h = e.get("history") if isinstance(e, dict) else None
        if not h:
            continue
        keep = [h[0]]
        for x in h[1:]:
            if _version(x) != _version(keep[-1]):
                keep.append(x)
        dropped += len(h) - len(keep)
        e["history"] = keep
    return dropped


# which code made a call: the commit the rebuild runs on (GitHub Actions)
POLICY = (os.environ.get("GITHUB_SHA") or "")[:7] or None


def _started(r):
    """True once the row's scheduled start has passed."""
    st = (r.get("mkt") or {}).get("start") or r.get("start")
    try:
        t = dt.datetime.fromisoformat(str(st).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t <= dt.datetime.now(dt.timezone.utc)


def _fix_first_prices(book):
    """Once: a double-chance call has no straight price, so a first_price on
    one was carried over from an earlier straight-win call on the same team
    (the bet changed, the entry price did not). Cleared, and marked."""
    for e in book.values():
        if e.get("dc") and e.get("price_market") != "double_chance" and e.get("first_price") and not e.get("first_price_cleared"):
            e["first_price_cleared"] = e.pop("first_price")


def record(state=None):
    """Snapshot the current board's picks. Safe to run repeatedly.

    `state` lets a caller that has already researched the slate hand its
    dashboard state in, so the hourly rebuild fetches everything once instead
    of twice.
    """
    if state is None:
        sys.path.insert(0, HERE)
        import dashboard as D
        D.refresh()
        state = D._STATE
    book = load()
    _fix_first_prices(book)
    added = 0
    dates = dict(zip(("today", "tomorrow"), state.get("dates") or ()))
    for slot in ("today", "tomorrow"):
        day = dates.get(slot)
        for lg, rows in (state["slots"].get(slot) or {}).items():
            for r in rows:
                if not r.get("mypick"):
                    continue
                # The board hides an undetermined competitor, but this did not,
                # so every "TBD" row was being recorded as a real pick and then
                # graded -- and a pick of "TBD" can never match a winner's name,
                # so it was an automatic loss every time. 18 of them reached the
                # ledger and all 10 that had settled were losses.
                if r["mypick"].strip().upper() == "TBD":
                    continue

                key = r["id"]                     # league:espn_competition_id
                if key in book and book[key].get("status") != "open":
                    continue                      # already settled, never rewrite
                if key in book and _started(r):
                    continue                      # the pregame call stands once play begins
                # no book price (a Kalshi or model number alone is a lean), or
                # one older than freshness.MAX_AGE_MIN or untimed: never
                # recorded; an earlier fresh version stands
                import freshness
                if not freshness.can_call(r):
                    continue
                leg = selection_leg(r)
                # the chance as published: whole percent, through the
                # walk-forward calibrator (calibration.py); p_raw keeps the
                # no-vig chance it started from, for the next fit
                import calibration
                pub_, cal_ = calibration.publisher(day and f"{day[:4]}-{day[4:6]}-{day[6:]}").publish(
                    lg, r["myconf"])
                entry = dict(league=lg, pick=r["mypick"], matchup=r["label"],
                             conf=pub_ or 0, p_raw=round((r["myconf"] or 0) * 100, 1), calib=cal_,
                             why=r.get("why", ""), tip=r.get("tip"),
                             price=(leg or {}).get("price"),
                             # the book and capture time behind the price
                             price_book=quote_book(r), price_at=quote_at(r),
                             price_market="double_chance" if r.get("dc") else "moneyline",
                             price_ref=(leg or {}).get("fd") or (leg or {}).get("dk"),
                             dog=bool((leg or {}).get("dog")),
                             # Whether the book made my side the favourite. Derive
                             # it from the price, not from the board's `pick`
                             # column -- that column holds the best historical ROI
                             # band, which is usually the underdog, so comparing
                             # against it labelled every favourite a market fade.
                             market_agrees=(None if not leg or not leg.get("price")
                                            else not leg.get("dog")),
                             p_model_away=r.get("p_model_away"),
                             p_market_away=r.get("p_market_away"),
                             myside=r.get("myside"),
                             dc=bool(r.get("dc")),
                             status="open", logged=dt.datetime.now(ET).isoformat()[:16])
                # the strong / close label as shown, frozen with the call: a
                # later refit of the cutoffs must not relabel past picks
                import calls
                import policy as _pv
                entry["strong"] = calls.is_call(lg, entry["conf"], quote=entry,
                                                as_of=day and f"{day[:4]}-{day[4:6]}-{day[6:]}")
                entry["policy_version"] = _pv.version()      # on every pick, as well as each history version
                # one of the day's calls (calls.update_daily): the record
                # counts these at the chance the call carries (re-derived only
                # by the move rule); a call pulled before its start does not count
                dc_ = calls.daily_ids(day).get(key) if (day and slot == "today") else None
                if dc_:
                    entry["call"] = dc_.get("status") != "pulled"
                    entry["call_pulled"] = dc_.get("status") == "pulled"
                    entry["call_rank"], entry["call_conf"] = dc_.get("rank"), dc_.get("conf")
                # The game's own ET date, so the grader knows where to look.
                # Without it the grader only searched the last three days, and
                # any game it missed in that window was never graded.
                if day:
                    entry["date"] = f"{day[:4]}-{day[4:6]}-{day[6:]}"
                if key not in book:
                    added += 1
                # Closing line value: the price when the call was first made
                # stays; `price` keeps updating to the last one before the
                # game (the close). Beating the close is the sharp bettor's
                # proof of skill; tools/daily_review.py reports it.
                # A bet is the team AND the market: "Middlesbrough" to win at
                # -210 and "Middlesbrough or draw" are different bets, and the
                # first kept the -210 when the call moved to double chance.
                prev = book.get(key, {})
                if prev.get("record_excluded"):
                    entry["record_excluded"] = prev["record_excluded"]
                same_bet = (prev.get("pick") == entry["pick"]
                            and bool(prev.get("dc")) == entry["dc"])
                if same_bet and "first_logged" in prev:
                    entry["first_price"] = prev.get("first_price")
                    entry["first_logged"] = prev.get("first_logged")
                else:
                    entry["first_price"] = entry.get("price")
                    entry["first_logged"] = entry["logged"]
                # append-only history: every published version of the call,
                # so a record can be judged on what was shown when, not only
                # on the last version before the game
                hist = list(prev.get("history") or [])
                # the inputs behind the call, as they were before play: both
                # sides' prices, the same-time market and model chances, the
                # model's share and the policy fingerprint (policy.version)
                import policy as _pol
                snap = dict(t=entry["logged"], pick=entry["pick"], dc=entry["dc"],
                            price=entry.get("price"), price_at=entry.get("price_at"),
                            price_book=entry.get("price_book"), price_market=entry.get("price_market"),
                            price_ref=entry.get("price_ref"),
                            conf=entry["conf"], why=entry["why"],
                            strong=entry["strong"], version=POLICY, policy=_pol.version(),
                            w=_pol.model_weight(lg), p_market_away=r.get("p_market_away"),
                            p_model_away=r.get("p_model_away"),
                            prices={L.get("side"): L.get("price") for L in r.get("legs") or []
                                    if L.get("side")})
                # a new version is a change in what was shown -- not a fresher
                # quote of the same price: price_at moves every build, and
                # counting it made ~500 copies per game (ledger.json passed
                # GitHub's 100 MB limit on 2026-10-30)
                if not hist or _version(hist[-1]) != _version(snap):
                    hist.append(snap)
                entry["history"] = hist
                if "first" not in prev:
                    entry["first"] = hist[0] if hist else snap       # the call as first published
                book[key] = {**prev, **entry}
    save(book)
    return added, len(book)


# ------------------------------------------------------------------- grade
def _played_on(comp):
    """ET calendar date of a competition from its own UTC timestamp, or None."""
    raw = comp.get("date") or comp.get("startDate") or ""
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            t = dt.datetime.strptime(raw, fmt).replace(tzinfo=dt.timezone.utc)
            return t.astimezone(ET).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _search_days(e):
    """Scoreboard dates to look for a pick's game on, most likely first."""
    now = dt.datetime.now(ET).date()
    days = []
    anchor = e.get("date") or (e.get("logged") or "")[:10]
    try:
        a = dt.date.fromisoformat(anchor)
        # a recorded game date is exact; a legacy entry only knows when it was
        # logged, and "tomorrow" picks are logged the day before
        span = (0, 1) if e.get("date") else (0, 1, 2, 3)
        days += [a + dt.timedelta(days=k) for k in span]
    except ValueError:
        pass
    days += [now - dt.timedelta(days=k) for k in (0, 1, 2)]
    out = []
    for x in days:
        if x <= now and x not in out:
            out.append(x)
    return [x.strftime("%Y%m%d") for x in out]


def _final(lg, comp_id, e=None):
    """Result dict once complete, a live dict while in progress, else None."""
    path = PATHS.get(lg)
    if not path:
        return None
    reached = True
    for day in _search_days(e or {}):
        d = get(f"{ESPN}/{path}/scoreboard?dates={day}")
        if not d:
            reached = False              # fetch failed -- absence proves nothing
        for ev in d.get("events", []):
            comps = list(ev.get("competitions") or [])
            for grp in ev.get("groupings") or []:
                comps.extend(grp.get("competitions") or [])
            for c in comps:
                if str(c.get("id")) != str(comp_id):
                    continue
                st = ((c.get("status") or {}).get("type") or {})
                cs = c.get("competitors") or []
                names, scores = {}, {}
                for x in cs:
                    who = ((x.get("team") or {}).get("displayName")
                           or (x.get("athlete") or {}).get("displayName"))
                    names[x.get("homeAway", x.get("order"))] = who
                    try:
                        scores[who] = int(x.get("score"))
                    except (TypeError, ValueError):
                        # tennis posts no aggregate score, only a set line
                        sets = []
                        for ls in x.get("linescores") or []:
                            try:
                                v = str(int(ls.get("value")))
                            except (TypeError, ValueError):
                                continue
                            tb = ls.get("tiebreak")
                            sets.append(f"{v}({tb})" if tb not in (None, "") else v)
                        scores[who] = " ".join(sets) if sets else None
                    if x.get("winner"):
                        names["winner"] = who
                if (st.get("name") or "") in ("STATUS_POSTPONED", "STATUS_CANCELED",
                                              "STATUS_CANCELLED", "STATUS_FORFEIT",
                                              "STATUS_ABANDONED"):
                    return dict(live=False, void=True, scores=scores,
                                state=st.get("shortDetail", ""), kind=_void_kind(st))
                # a tennis walkover: no match was played, so the bet is void
                # (FanDuel NY), whatever winner the feed lists
                if "WALKOVER" in (st.get("name") or "").upper() or \
                        "W/O" in (st.get("shortDetail") or "").upper() or \
                        "WALKOVER" in (st.get("shortDetail") or "").upper():
                    return dict(live=False, void=True, scores=scores, kind="walkover",
                                state=st.get("shortDetail", "") or "walkover")
                if not st.get("completed"):
                    # "pre" is a game that has not started -- not live, and
                    # nothing to show. Only state "in" is actually underway.
                    if st.get("state") != "in":
                        return None
                    return dict(live=True, state=st.get("shortDetail", ""),
                                scores=scores)
                name = (st.get("name") or "").upper()
                if lg in SOCCER and ("AET" in name or "PEN" in name or "EXTRA" in name):
                    # Soccer moneylines and totals settle on 90 minutes; the
                    # final score here includes extra time. Rebuild the
                    # 90-minute score from the two halves, or void the pick
                    # rather than grade it on the wrong score.
                    reg = {}
                    for x in cs:
                        who = ((x.get("team") or {}).get("displayName")
                               or (x.get("athlete") or {}).get("displayName"))
                        try:
                            ls = x.get("linescores") or []
                            reg[who] = int(ls[0].get("value")) + int(ls[1].get("value"))
                        except (IndexError, TypeError, ValueError, AttributeError):
                            reg = None
                            break
                    if not reg:
                        return dict(live=False, void=True, scores=scores,
                                    state="decided in extra time; 90-minute score unavailable")
                    scores = reg
                    names.pop("winner", None)
                win = names.get("winner")
                ints = [v for v in scores.values() if isinstance(v, int)]
                if len(ints) == 2 and ints[0] == ints[1]:
                    # A level score is a draw on the moneyline even when the
                    # feed flags a winner (penalties, or nothing at all). The
                    # old fallback took max() of two equal scores, which
                    # returns whichever team is listed first -- 21 soccer
                    # draws were graded as WINS that way.
                    win = DRAW
                elif win is None and len(ints) == 2:
                    win = max(scores, key=scores.get)
                # The day the game was PLAYED, from its own timestamp -- not
                # the scoreboard date it was found on. A tennis scoreboard
                # returns the tournament's entire draw on every date queried,
                # so a match from three days ago is "on" today's board too.
                return dict(live=False, winner=win, scores=scores,
                            state=st.get("shortDetail", ""),
                            date=_played_on(c) or f"{day[:4]}-{day[4:6]}-{day[6:]}")
    # Every date was fetched and the game is on none of them. Only that, never
    # a failed fetch, may let a pick age into a void.
    return dict(missing=True) if reached else None


DRAW = "Draw"
# A settled pick's explicit state. `status` keeps the settlement meaning every
# consumer reads (won / lost / push / void); `state` says which kind of void.
STATES = ("won", "lost", "push", "void", "postponed", "cancelled", "walkover", "abandoned", "no_result")


def _void_kind(st):
    n = (st.get("name") or "").upper()
    return ("postponed" if "POSTPONED" in n else "cancelled" if "CANCEL" in n
            else "walkover" if "FORFEIT" in n else "abandoned" if "ABANDON" in n else "void")


def _settle(e, win):
    """won / lost / push for a pick, given the result's winner (or DRAW)."""
    if win == DRAW:
        if e.get("pick") == DRAW or e.get("dc"):     # "X or draw" wins on a draw
            return "won"
        # a 3-way soccer moneyline loses on a draw; a two-way market (an NFL
        # tie) refunds the stake
        return "lost" if e.get("league") in SOCCER else "push"
    return "won" if win == e.get("pick") else "lost"


def _fix_draws(book):
    """Re-grade picks settled before draws were recognised. Idempotent."""
    n = 0
    for e in book.values():
        if e.get("status") not in ("won", "lost"):
            continue
        ints = [v for v in (e.get("scores") or {}).values() if isinstance(v, int)]
        if len(ints) != 2 or ints[0] != ints[1]:
            continue
        st = _settle(e, DRAW)
        if st != e["status"] or e.get("winner") != DRAW:
            e["winner"] = DRAW
            if st != e["status"]:
                e["regraded"] = f'{e["status"]} -> {st}: level score is a draw'
                e["status"] = st
                n += 1
            if st == "lost":
                e["diagnosis"] = diagnose(e, {"scores": e.get("scores")})
            else:
                e.pop("diagnosis", None)
    return n


def diagnose(e, res):
    """Describe a loss. Description only -- no parameter is changed from this."""
    bits = []
    scores = res.get("scores") or {}
    # set-scored sports carry a string line ("6 7(8)"), not a number -- read
    # the margin off the sets won rather than reporting nothing.
    strs = [v for v in scores.values() if isinstance(v, str)]
    if len(strs) == 2 and e["pick"] in scores:
        mine = scores[e["pick"]].split()
        other = next(v for k, v in scores.items() if k != e["pick"]).split()
        pairs = [(a, b) for a, b in zip(mine, other)]
        won = sum(1 for a, b in pairs
                  if a.split("(")[0].isdigit() and b.split("(")[0].isdigit()
                  and int(a.split("(")[0]) > int(b.split("(")[0]))
        lost = len(pairs) - won
        bits.append(f"lost {won}-{lost} in sets")
        if won == 0:
            bits.append("never won a set")
        elif won >= 1:
            bits.append("took it the distance")
    sc = [v for v in scores.values() if isinstance(v, int)]
    if len(sc) == 2:
        margin = abs(sc[0] - sc[1])
        bits.append(f"margin {margin}")
        if e["league"] == "mlb":
            bits.append("blowout" if margin >= 6 else
                        "comfortable" if margin >= 4 else
                        "one-run game" if margin == 1 else "close")
    if len(sc) == 2 and sc[0] == sc[1]:
        bits.append("drawn -- a draw loses a moneyline side")
    if e.get("market_agrees") is True:
        bits.append("the book had my side favoured too")
    elif e.get("market_agrees") is False:
        bits.append("I took the side the book had as less likely")
    if e.get("dog"):
        bits.append("I took the underdog")
    if "TBD" in (e.get("why") or ""):
        bits.append("a starter was unannounced when I called it")
    c = e.get("conf") or 0
    bits.append(f"called at {c:.0f}%")
    bits += [t for t in loss_tags(e, scores) if t not in bits]
    return " · ".join(bits)


# how many points makes a game close or a blowout, by sport
_MARGINS = dict(nba=(5, 15), wnba=(5, 15), ncaab=(5, 15), nfl=(7, 17), ncaaf=(7, 17),
                nhl=(1, 3), mlb=(1, 6))


def _implied(price):
    try:
        v = float(str(price).replace("+", ""))
    except (TypeError, ValueError):
        return None
    return -v / (-v + 100) if v < 0 else 100 / (v + 100)


def loss_tags(e, scores=None):
    """Short, countable reasons for one loss (description only, never a
    parameter): how likely it was ('coin flip' under 60%, 'upset' at 75%+,
    else 'favourite lost'), how it was lost ('close game' / 'blowout' by the
    sport's margins; soccer: 1 goal is close), and 'price moved against it'
    when the line drifted 3+ points the other way between the call and the
    last price before the start -- the mark late news leaves."""
    tags = []
    c = e.get("conf") or 0
    tags.append("coin flip" if c < 60 else "upset" if c >= 75 else "favourite lost")
    sc = [v for v in (scores if scores is not None else e.get("scores") or {}).values() if isinstance(v, int)]
    if len(sc) == 2 and sc[0] != sc[1]:
        m = abs(sc[0] - sc[1])
        close, blow = _MARGINS.get(e.get("league"), (1, 3))
        if m <= close:
            tags.append("close game")
        elif m >= blow:
            tags.append("blowout")
    a, b = _implied(e.get("first_price")), _implied(e.get("price"))
    if a is not None and b is not None and a - b >= 0.03:
        tags.append(f"price moved against it ({100 * (a - b):.0f} pts)")
    return tags


def _stale(e):
    anchor = e.get("date") or (e.get("logged") or "")[:10]
    try:
        a = dt.date.fromisoformat(anchor)
    except ValueError:
        return False
    return (dt.datetime.now(ET).date() - a).days > VOID_AFTER_DAYS


def grade():
    book = load()
    from record_eligibility import exclude_unpriced
    exclude_unpriced(book)
    _fix_draws(book)
    settled = []
    for key, e in book.items():
        if e.get("status") != "open":
            continue
        lg, comp = key.split(":", 1)
        res = _final(lg, comp, e)
        if res and res.get("void"):
            e.pop("live", None)
            e.pop("live_score", None)
            e["status"] = "void"
            e["state"] = res.get("kind") or "void"
            e["settled"] = dt.datetime.now(ET).isoformat()[:16]
            e["diagnosis"] = f'{e["state"]}: {res.get("state") or "game not played"}'
            settled.append((key, e))
            continue
        if not res or res.get("missing"):
            e.pop("live", None)          # was it ever marked live, it is not now
            e.pop("live_score", None)
            if res and _stale(e):
                e["status"] = "void"
                e["state"] = "no_result"
                e["settled"] = dt.datetime.now(ET).isoformat()[:16]
                e["diagnosis"] = (f"void: no final result found within "
                                  f"{VOID_AFTER_DAYS} days of the game date")
                settled.append((key, e))
            continue
        if res.get("live"):
            e["live"] = res.get("state")
            e["live_score"] = res.get("scores")
            continue
        win = res.get("winner")
        if not win:
            continue
        e.pop("live", None)
        e.pop("live_score", None)
        e["winner"] = win
        e["scores"] = res.get("scores")
        e["status"] = _settle(e, win)
        e["state"] = e["status"]
        e["settled"] = dt.datetime.now(ET).isoformat()[:16]
        # `settled` is when the grader ran; `played` is when the game was.
        # They diverge whenever grading lags -- when the league map was fixed,
        # 42 picks from Sep 1 graded on Sep 2 and the results feed showed
        # them as Sep 2 losses, which read as "lost all day" on a 16-9 day.
        e["played"] = res.get("date") or e["settled"][:10]
        if e["status"] == "lost":
            e["diagnosis"] = diagnose(e, res)
        settled.append((key, e))
    save(book)
    return settled


# ------------------------------------------------------------------ report
def _se(n):
    return math.sqrt(0.25 / n) * 100 if n else 0.0


def report():
    book = load()
    done = [e for e in book.values() if e.get("status") in ("won", "lost")
            and record_priced(e)]
    out = {"excluded_unpriced": sum(not record_priced(e) for e in book.values()),
           "graded": len(done), "open": sum(1 for e in book.values()
                                            if record_priced(e) and e.get("status") == "open")}
    if not done:
        return out, []
    out["won"] = sum(1 for e in done if e["status"] == "won")
    out["lost"] = len(done) - out["won"]
    out["hit"] = 100 * out["won"] / len(done)
    by_lg = defaultdict(lambda: [0, 0])
    band = defaultdict(lambda: [0, 0, 0.0])
    for e in done:
        by_lg[e["league"]][0] += 1
        by_lg[e["league"]][1] += e["status"] == "won"
        b = min(int((e.get("conf") or 50) / 5) * 5, 85)
        band[b][0] += 1
        band[b][1] += e["status"] == "won"
        band[b][2] += e.get("conf") or 0
    out["by_league"] = {k: dict(n=v[0], won=v[1], hit=100 * v[1] / v[0])
                        for k, v in by_lg.items()}
    out["calibration"] = {
        b: dict(n=v[0], said=v[2] / v[0], actual=100 * v[1] / v[0],
                gap=100 * v[1] / v[0] - v[2] / v[0], se=_se(v[0]))
        for b, v in sorted(band.items())}
    # a recommendation only where the sample can carry one
    recs = []
    for b, c in out["calibration"].items():
        if c["n"] >= 100 and abs(c["gap"]) > 2 * c["se"]:
            recs.append(f'{b}-{b+5}% band: said {c["said"]:.1f}%, hit '
                        f'{c["actual"]:.1f}% over {c["n"]} picks '
                        f'({c["gap"]:+.1f}, {abs(c["gap"])/c["se"]:.1f} s.e.) '
                        f'— large enough to act on')
    return out, recs


# ----------------------------------------------------------- site payload
UPSET_MIN = 0.40      # an underdog with at least this chance is "live"


def upset_view(book, today):
    """Upset watch: every underdog with a real chance (40%+), considered each
    day and kept on record. Today's live underdogs with their signals (my
    price-blind model picks them; the price has moved 3+ points their way),
    and how all such underdogs have done against their price, by date half.
    Display and tracking only: they reach the board's picks only once they
    beat their price in both halves."""
    rows, today_ = [], []
    for k, e in book.items():
        if not record_priced(e) or e.get("dc") or e.get("market_agrees") is False:
            continue
        c = e.get("conf")
        if not isinstance(c, (int, float)) or 1 - c / 100 < UPSET_MIN:
            continue
        H = [h for h in e.get("history") or [] if h.get("p_model_away") is not None and h.get("p_market_away") is not None]
        model = bool(H) and (H[-1]["p_model_away"] > 0.5) != (H[-1]["p_market_away"] > 0.5)
        a, b = _implied(e.get("first_price")), _implied(e.get("price"))
        move = a is not None and b is not None and a - b >= 0.03
        d = e.get("date") or ""
        if e.get("status") in ("won", "lost") and d < today:
            rows.append((d, e["status"] == "lost", 1 - c / 100))
        if d == today and e.get("status") in ("open", "won", "lost"):
            teams = (e.get("matchup") or "").split(" @ ")
            dog = None
            if H and len(teams) == 2:
                dog = teams[1] if H[-1]["p_market_away"] > 0.5 else teams[0]
            today_.append(dict(league=k.split(":")[0], match=e.get("matchup"), favourite=e["pick"], dog=dog,
                               chance=round(100 - c), tip=e.get("tip"),
                               result=("open" if e["status"] == "open" else "won" if e["status"] == "lost" else "lost"),
                               score=e.get("scores") or {},
                               signals=[x for x, on in (("my model picks them", model),
                                                        ("price moving their way", move)) if on]))
    today_.sort(key=lambda x: (-len(x["signals"]), -x["chance"]))
    rec = dict(n=len(rows))
    if rows:
        days = sorted({r[0] for r in rows})
        mid = days[len(days) // 2]
        def part(S):
            return dict(n=len(S), won=sum(r[1] for r in S), said=round(100 * sum(r[2] for r in S) / len(S), 1)) if S else None
        rec.update(part(rows), halves=[part([r for r in rows if r[0] < mid]), part([r for r in rows if r[0] >= mid])])
        H2 = rec["halves"]
        rec["beating"] = all(h and h["won"] / h["n"] * 100 > h["said"] for h in H2)
    return dict(today=today_, record=rec, min=round(100 * UPSET_MIN))


def own_view(book, today, since_days=30):
    """My own picks with the prices hidden: each game's side by the model
    alone (ratings, form, home edge -- the history's p_model_away), against
    the market's side. Graded head to head on the same games over the last
    since_days, plus today's games where the two disagree."""
    since = (dt.date.fromisoformat(today) - dt.timedelta(days=since_days)).isoformat()
    n = own = mkt = 0
    split = []
    split_rec = {}
    for k, e in book.items():
        H = [h for h in e.get("history") or [] if h.get("p_model_away") is not None and h.get("p_market_away") is not None]
        if not H or not record_priced(e):
            continue
        h, d = H[-1], e.get("date") or ""
        model_away, mkt_away = h["p_model_away"] > 0.5, h["p_market_away"] > 0.5
        teams = (e.get("matchup") or "").split(" @ ")
        if e.get("status") in ("won", "lost") and since <= d < today:
            mkt_won = (e["status"] == "won") == (e.get("market_agrees") is not False)
            n += 1
            mkt += mkt_won
            own += mkt_won if model_away == mkt_away else not mkt_won
            if model_away != mkt_away:              # the games where I would differ
                lg_ = k.split(":")[0]
                a_, n_ = split_rec.get(lg_, (0, 0))
                split_rec[lg_] = (a_ + (not mkt_won), n_ + 1)
        elif e.get("status") == "open" and d == today and model_away != mkt_away and len(teams) == 2:
            split.append(dict(league=k.split(":")[0], match=e.get("matchup"), own=teams[0] if model_away else teams[1],
                              own_p=round(100 * (h["p_model_away"] if model_away else 1 - h["p_model_away"])),
                              market=teams[0] if mkt_away else teams[1],
                              market_p=round(100 * (h["p_market_away"] if mkt_away else 1 - h["p_market_away"]))))
    return dict(n=n, own=own, market=mkt, since=since, today=sorted(split, key=lambda x: x["league"]),
                splits=[dict(league=k, mine=a_, n=n_) for k, (a_, n_) in sorted(split_rec.items(), key=lambda x: -x[1][1])])


def _tip_min(tip):
    """'7:30 PM' -> minutes after midnight (None when unreadable)."""
    try:
        hm, ap = str(tip).strip().split()
        h, m = (int(x) for x in hm.split(":"))
        return (h % 12 + (12 if ap.upper() == "PM" else 0)) * 60 + m
    except (ValueError, AttributeError):
        return None


def next_up(book, today, n=3):
    """Today's next priced picks still to start, earliest first."""
    rows = [(m, e) for e in book.values()
            if record_priced(e) and e.get("status") == "open" and (e.get("date") or "") == today
            and not e.get("live_score") and (m := _tip_min(e.get("tip"))) is not None]
    rows.sort(key=lambda x: x[0])
    return [dict(tip=e.get("tip"), league=e.get("league"), match=e.get("matchup"), conf=e.get("conf"),
                 pick=e["pick"] + (" or draw" if e.get("dc") else ""), price=e.get("price")) for _, e in rows[:n]]


def live_winning(e):
    """Whether a pick in play would win if it ended now: my side ahead (or,
    for 'or draw', not behind). None when the score cannot be read."""
    sc = e.get("live_score") or {}
    mine = sc.get(e.get("pick"))
    other = [v for k, v in sc.items() if k != e.get("pick")]
    try:
        mine, other = float(mine), float(other[0])
    except (TypeError, ValueError, IndexError):
        return None
    return mine >= other if e.get("dc") else mine > other


def call_cautions(book, min_n=40, gap=8.0):
    """Calls by (league, 10-point chance band, 50%+) that won under their
    stated chance in BOTH date halves and by `gap`+ points overall, on
    `min_n`+ graded calls: [{league, band, won, n, said}]. A caution beside
    calls, never a pick rule. 2026-11-07: college football at 70-80% 28/47
    (54% then 68% vs 75%) -- the only one; z ~ -2.4, short of the 99.5% bar."""
    R = [e for e in book.values() if e.get("status") in ("won", "lost") and e.get("conf") and e.get("date") and e.get("league")]
    if not R:
        return []
    days = sorted({e["date"] for e in R})
    mid = days[len(days) // 2]
    g = {}
    for e in R:
        b = int(min(e["conf"], 99.9) // 10 * 10)
        if b >= 50:
            g.setdefault((e["league"], b), {False: [], True: []})[e["date"] >= mid].append(e)
    out = []
    for (lg, b), H in sorted(g.items()):
        A = H[False] + H[True]
        if len(A) < min_n or not (H[False] and H[True]):
            continue
        hit = lambda X: 100 * sum(e["status"] == "won" for e in X) / len(X)
        said = lambda X: sum(e["conf"] for e in X) / len(X)
        if all(hit(X) < said(X) for X in H.values()) and said(A) - hit(A) >= gap:
            out.append(dict(league=lg, band=b, won=sum(e["status"] == "won" for e in A), n=len(A), said=round(said(A))))
    return out


def like_record(book, e, band=5):
    """Graded picks like a lost one -- same league, same bet (win or double
    chance), called within `band` points: dict(won, n, said), or None under
    10. Tells a bad beat on a sound kind of pick from a leak."""
    c = e.get("conf")
    if c is None:
        return None
    R = [x for x in book.values() if x is not e and x.get("status") in ("won", "lost") and x.get("league") == e.get("league")
         and bool(x.get("dc")) == bool(e.get("dc")) and x.get("conf") is not None and abs(x["conf"] - c) <= band]
    if len(R) < 10:
        return None
    return dict(won=sum(x["status"] == "won" for x in R), n=len(R), said=round(sum(x["conf"] for x in R) / len(R)))


def draw_losses(book):
    """Straight-win picks in sports with a draw (three-way price recorded):
    dict(n, lost, drawn) -- how many of their losses were draws, the case a
    double chance ("or draw") covers. 2026-11-07: 234 picks, 38 lost, 21 of
    them drawn."""
    S = [e for e in book.values() if e.get("status") in ("won", "lost") and not e.get("dc")
         and "draw" in (((e.get("first") or {}).get("prices")) or {}) and e.get("scores")]
    L = [e for e in S if e["status"] == "lost"]
    return dict(n=len(S), lost=len(L), drawn=sum(len(set(e["scores"].values())) == 1 for e in L))


def moves_halves(book, move=0.03):
    """Every graded pick whose price moved `move`+ between the call and the
    start, all time, split by date half: {"for"|"against": [[won, n, close%],
    [won, n, close%]]} against the closing price. 2026-11-08: for 72/88 then
    116/146 (82%, 79% vs 77% close); against 39/50 then 37/64 (78% vs 70%,
    58% vs 72%: mixed)."""
    R = []
    for e in book.values():
        if e.get("status") not in ("won", "lost") or not e.get("date"):
            continue
        a, b = _implied(e.get("first_price")), _implied(e.get("price"))
        if a is None or b is None or abs(b - a) < move:
            continue
        R.append((e["date"], "for" if b > a else "against", b, e["status"] == "won"))
    if not R:
        return {}
    days = sorted({r[0] for r in R})
    mid = days[len(days) // 2]
    out = {}
    for k in ("for", "against"):
        H = []
        for h in (False, True):
            X = [r for r in R if r[1] == k and (r[0] >= mid) == h]
            H.append([sum(r[3] for r in X), len(X), round(100 * sum(r[2] for r in X) / len(X), 1) if X else None])
        out[k] = H
    return out


def band_records(book, width=5, min_n=10):
    """Graded calls by league, bet (win or double chance) and `width`-point
    chance band: {"league|dc|band": [won, n, said]} with `min_n`+ calls --
    the record shown beside every open call ("calls like this")."""
    g = {}
    for e in book.values():
        if e.get("status") not in ("won", "lost") or e.get("conf") is None or not e.get("league"):
            continue
        b = int(min(e["conf"], 99.9) // width * width)
        a = g.setdefault(f"{e['league']}|{int(bool(e.get('dc')))}|{b}", [0, 0, 0.0])
        a[0] += e["status"] == "won"
        a[1] += 1
        a[2] += e["conf"]
    return {k: [w, n, round(p / n, 1)] for k, (w, n, p) in g.items() if n >= min_n}


def day_rarity(rows):
    """How unusual a day's losses were, given the chances each pick was called
    at: losses expected, the chance of that many losses or more (picks taken as
    independent), and which leagues the losses came from."""
    ps = [min(max((e.get("conf") or 0) / 100, 0.0), 1.0) for e in rows if e.get("status") in ("won", "lost")]
    if not ps:
        return {}
    dist = [1.0]                       # dist[k] = chance of exactly k losses
    for p in ps:
        q = 1 - p
        nxt = [0.0] * (len(dist) + 1)
        for k, v in enumerate(dist):
            nxt[k] += v * p
            nxt[k + 1] += v * q
        dist = nxt
    lost = sum(e.get("status") == "lost" for e in rows)
    by = {}
    for e in rows:
        if e.get("status") == "lost":
            by[e.get("league")] = by.get(e.get("league"), 0) + 1
    exp = {}
    for e in rows:
        if e.get("status") in ("won", "lost"):
            exp[e.get("league")] = exp.get(e.get("league"), 0.0) + 1 - min(max((e.get("conf") or 0) / 100, 0.0), 1.0)
    return dict(expected_losses=round(sum(1 - p for p in ps), 1),
                as_bad_pct=round(100 * sum(dist[lost:]), 1),
                lost_by_league=dict(sorted(by.items(), key=lambda kv: -kv[1])),
                expected_by_league={k: round(exp.get(k, 0.0), 1) for k in by})


def sweep_days(done, day_of, today, n=14):
    """The whole board, day by day: priced picks won and lost on each of the
    last n days before today ([{day, won, lost}], newest first), for the
    board-sweep tile."""
    g = {}
    for e in done:
        d = day_of(e)
        if d and d < today:
            w, l = g.get(d, (0, 0))
            g[d] = (w + (e["status"] == "won"), l + (e["status"] == "lost"))
    return [dict(day=d, won=w, lost=l) for d, (w, l) in sorted(g.items(), reverse=True)[:n]]


def board_payload(limit=40):
    """Everything the published page shows on its Results tab.

    Live scores, the running record, calibration, and the loss feed. Built
    from the same ledger the CLI reports on, so the page and the terminal can
    never disagree.
    """
    book = load()
    r, recs = report()
    live = [dict(league=e["league"], pick=e["pick"] + (" or draw" if e.get("dc") else ""), matchup=e.get("matchup", ""),
                 state=e.get("live", ""), conf=e.get("conf"),
                 score=e.get("live_score") or {}, winning=live_winning(e))
            for e in book.values()
            if record_priced(e) and e.get("status") == "open" and e.get("live")]
    live.sort(key=lambda x: (x["league"], x["pick"]))

    done = [e for e in book.values() if e.get("status") in ("won", "lost")
            and record_priced(e)]
    done.sort(key=lambda e: (e.get("played") or (e.get("settled") or "")[:10],
                             e.get("settled") or e.get("logged") or ""), reverse=True)
    feed = [dict(league=e["league"], pick=e["pick"] + (" or draw" if e.get("dc") else ""), status=e["status"],
                 conf=e.get("conf"), price=e.get("price"), dog=e.get("dog"),
                 score=e.get("scores") or {},
                 why=(e.get("diagnosis") if e["status"] == "lost"
                      else e.get("why") or ""),
                 when=(e.get("played") or e.get("settled") or e.get("logged") or "")[:10])
            for e in done[:limit]]

    # The page shows TODAY only (Eastern): the day's settled calls and its
    # record. Every earlier result stays in ledger.json and in the daily
    # review log (review/log.json); the page just does not show history.
    today = dt.datetime.now(ET).date().isoformat()
    day_of = lambda e: (e.get("played") or e.get("date") or (e.get("settled") or "")[:10]
                        or (e.get("logged") or "")[:10])
    todays = [e for e in done if day_of(e) == today]
    feed_today = [dict(league=e["league"], pick=e["pick"] + (" or draw" if e.get("dc") else ""), status=e["status"],
                       strong=_strong(e),
                       conf=e.get("conf"), price=e.get("price"), dog=e.get("dog"),
                       score=e.get("scores") or {},
                       why=(e.get("diagnosis") if e["status"] == "lost" else e.get("why") or ""),
                       when=today)
                  for e in todays]
    open_today = sum(1 for e in book.values()
                     if record_priced(e) and e.get("status") == "open" and (e.get("date") or "") == today)
    board_days = sweep_days(done, day_of, today)
    _lt = sorted((e for e in todays if e["status"] == "lost"), key=lambda e: e.get("settled") or "")
    broke_on = (dict(pick=_lt[0]["pick"] + (" or draw" if _lt[0].get("dc") else ""), conf=_lt[0].get("conf"),
                     score=_lt[0].get("scores") or {}) if _lt else None)
    # yesterday's board: its record and every loss with why (diagnose)
    _yk = (dt.date.fromisoformat(today) - dt.timedelta(days=1)).isoformat()
    _yd = [e for e in done if day_of(e) == _yk]
    _yl = sorted((e for e in _yd if e["status"] == "lost"), key=lambda e: e.get("settled") or "")
    yesterday = dict(day=_yk, won=sum(e["status"] == "won" for e in _yd), lost=len(_yl),
                     losses=[dict(league=e["league"], pick=e["pick"] + (" or draw" if e.get("dc") else ""),
                                  conf=e.get("conf"), price=e.get("price"), score=e.get("scores") or {},
                                  why=e.get("diagnosis") or "", tags=loss_tags(e), like=like_record(book, e)) for e in _yl])
    yesterday.update(day_rarity(_yd))
    own = own_view(book, today)
    # picks whose price moved 3+ points between the call and the start, last
    # 14 days: how they did against their final price (the badge's record)
    moves = {}
    for e in done:
        if not (_since_m := (dt.date.fromisoformat(today) - dt.timedelta(days=14)).isoformat()) <= (day_of(e) or "") < today:
            continue
        a_, b_ = _implied(e.get("first_price")), _implied(e.get("price"))
        if a_ is None or b_ is None or abs(b_ - a_) < 0.03:
            continue
        k_ = "for" if b_ > a_ else "against"
        m_ = moves.setdefault(k_, [0, 0, 0.0])
        m_[0] += 1
        m_[1] += e["status"] == "won"
        m_[2] += b_
    moves = {k: dict(n=n, won=w, price=round(100 * p / n, 1)) for k, (n, w, p) in moves.items()}
    # why the last 14 days' losses happened, counted (loss_tags)
    _since = (dt.date.fromisoformat(today) - dt.timedelta(days=14)).isoformat()
    _rs = {}
    for e in done:
        if e["status"] == "lost" and _since <= (day_of(e) or "") < today:
            for t in loss_tags(e):
                t = t.split(" (")[0]
                _rs[t] = _rs.get(t, 0) + 1
    loss_reasons = dict(since=_since, n=sum(1 for e in done if e["status"] == "lost" and _since <= (day_of(e) or "") < today),
                        tags=[dict(tag=k, n=v) for k, v in sorted(_rs.items(), key=lambda x: -x[1])])
    # the chance every still-open priced pick today wins, from each pick's own
    # stated chance (independent games): what the sweep tile calls the odds
    # of finishing clean
    import math as _m
    _open_p = [e["conf"] / 100 for e in book.values()
               if record_priced(e) and e.get("status") == "open" and (e.get("date") or "") == today
               and isinstance(e.get("conf"), (int, float))]
    sweep_chance = round(_m.prod(_open_p), 10) if _open_p else None

    # the day's calls and their record (calls.update_daily): N, dates, Wilson
    import calls as _calls
    cl = [e for e in done if e.get("call")]
    cw = sum(e["status"] == "won" for e in cl)
    calls_rec = dict(n=len(cl), won=cw, lost=len(cl) - cw,
                     hit=round(100 * cw / len(cl), 1) if cl else None,
                     stated=round(sum(e.get("call_conf") or e.get("conf") or 0 for e in cl) / len(cl), 1) if cl else None,
                     ci95=_wilson(cw, len(cl)),
                     dates=[min(map(day_of, cl)), max(map(day_of, cl))] if cl else None,
                     # by sport (calls._group), most calls first
                     by_sport=[dict(sport=g, won=sum(e["status"] == "won" for e in cl if _calls._group(e["league"]) == g),
                                    n=sum(1 for e in cl if _calls._group(e["league"]) == g))
                               for g in sorted({_calls._group(e["league"]) for e in cl},
                                               key=lambda g: -sum(1 for e in cl if _calls._group(e["league"]) == g))])
    todays_calls = []
    daily_rec = _calls.load_daily()["days"].get(today) or {}
    live_candidates = [dict(c, status=(book.get(c["id"]) or {}).get("status", "open"))
                       for c in (daily_rec.get("candidate_observations") or {}).values()]
    for c in sorted(daily_rec.get("calls") or [],
                    key=lambda c: -c["conf"]):
        e = book.get(c["id"]) or {}
        # strong/close by the cut-offs frozen for this window (constant inside
        # it), not the label at set time: 2026-10-20's calls were set minutes
        # before the first freeze and carried the old daily refit's labels
        todays_calls.append(dict(c, close=not _calls.is_call(c["league"], c["conf"], quote=c, as_of=today),
                                 status=("pulled" if c.get("status") == "pulled" else e.get("status", "open")),
                                 live=e.get("live"),
                                 score=e.get("scores") or e.get("live_score") or {}))
    gate = recs or []
    # epoch ms of this capture, so the page can show its own age at render
    # time. The page cannot fetch, so honesty about staleness is the only
    # substitute for freshness.
    captured = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    from tennis_eligibility import report as tennis_report
    return dict(live_candidates=live_candidates, tennis_record=tennis_report(book.values(), today, _calls.TARGET),
                captured=captured, excluded_unpriced=r["excluded_unpriced"],
                graded=r.get("graded", 0), open=r.get("open", 0),
                won=r.get("won", 0), lost=r.get("lost", 0),
                hit=round(r["hit"], 1) if r.get("graded") else None,
                by_league=[dict(lg=k, n=v["n"], won=v["won"],
                                hit=round(v["hit"], 1))
                           for k, v in sorted(r.get("by_league", {}).items(),
                                              key=lambda x: -x[1]["n"])],
                calibration=[dict(band=b, n=c["n"], said=round(c["said"], 1),
                                  actual=round(c["actual"], 1),
                                  gap=round(c["gap"], 1), thin=c["n"] < 30)
                             for b, c in sorted(r.get("calibration", {}).items())],
                live=live, feed=feed, gate=gate, calls=todays_calls, calls_record=calls_rec,
                calls_top=_calls.TOP_N,
                today=today, today_won=sum(e["status"] == "won" for e in todays),
                today_expected=round(sum((e.get("conf") or 0) / 100 for e in todays), 1),
                today_rarity=day_rarity(todays),
                today_losses_by=[dict(league=k, n=v) for k, v in sorted(
                    ((lg_, sum(1 for e in todays if e["status"] == "lost" and e["league"] == lg_))
                     for lg_ in {e["league"] for e in todays if e["status"] == "lost"}), key=lambda x: -x[1])],
                today_lost=sum(e["status"] == "lost" for e in todays),
                today_open=open_today, feed_today=feed_today, board_days=board_days, broke_on=broke_on, sweep_chance=sweep_chance, own=own, moves=moves, upsets=upset_view(book, today), call_cautions=call_cautions(book), draw_losses=draw_losses(book), moves_halves=moves_halves(book), band_records=band_records(book), yesterday=yesterday, loss_reasons=loss_reasons, next_up=next_up(book, today),
                # the same split the pick tabs use: strong calls vs close games
                today_strong_won=sum(e["status"] == "won" for e in todays if _strong(e)),
                today_strong_lost=sum(e["status"] == "lost" for e in todays if _strong(e)))


def _wilson(w, n, z=1.96):
    if not n:
        return None
    p = w / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round(100 * (c - h) / d, 1), round(100 * (c + h) / d, 1)]


def _strong(e):
    """The label the pick was published with; older entries, recorded
    before labels were frozen, fall back to today's cutoff."""
    if not record_priced(e):
        return False
    if e.get("league") in ("atp", "wta"):
        from tennis_eligibility import captured_quote
        if not captured_quote(e):
            return False
    if "strong" in e:
        return e["strong"]
    import calls
    return calls.is_call(e.get("league"), e.get("conf"), quote=e,
                         as_of=e.get("date"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["record", "grade", "report", "cycle"])
    a = ap.parse_args()
    if a.cmd in ("record", "cycle"):
        added, total = record()
        print(f"recorded {added} new pick(s); ledger holds {total}")
    if a.cmd in ("grade", "cycle"):
        s = grade()
        print(f"settled {len(s)} pick(s)")
        for k, e in s:
            mark = {"won": "WON ", "lost": "LOST"}.get(e["status"], e["status"].upper())
            sc = e.get("scores") or {}
            line = " ".join(f"{k2} {v}" for k2, v in sc.items() if v is not None)
            print(f"  {mark} {e['pick'][:26]:<26} {line}")
            if e["status"] in ("lost", "void"):
                print(f"       why: {e['diagnosis']}")
    if a.cmd in ("report", "cycle"):
        r, recs = report()
        if not r.get("graded"):
            print(f"\nnothing graded yet ({r['open']} open)")
            return
        print(f"\nRECORD  {r['won']}-{r['lost']}  ({r['hit']:.1f}%)  "
              f"| {r['open']} still open")
        for lg, v in sorted(r["by_league"].items(), key=lambda x: -x[1]["n"]):
            print(f"  {lg:<6} {v['won']}-{v['n']-v['won']}  {v['hit']:.1f}%")
        print("\nCALIBRATION")
        for b, c in r["calibration"].items():
            flag = "" if c["n"] >= 30 else "   (thin)"
            print(f"  said {c['said']:.0f}%  n={c['n']:<4} actual {c['actual']:.1f}%"
                  f"  gap {c['gap']:+.1f}{flag}")
        print("\nUPGRADE GATE")
        if recs:
            for x in recs:
                print("  " + x)
        else:
            print("  no bucket has both 100+ graded picks and a gap beyond two")
            print("  standard errors. Nothing here justifies a parameter change.")


if __name__ == "__main__":
    main()
