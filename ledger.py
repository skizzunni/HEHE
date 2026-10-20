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
    with open(LEDGER, "w") as fh:
        json.dump(d, fh, indent=1, sort_keys=True)


# ------------------------------------------------------------------ record
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
        if e.get("dc") and e.get("first_price") and not e.get("first_price_cleared"):
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
                leg = next((L for L in r["legs"]
                            if L.get("side") and L["side"] == r.get("myside")), None)
                if r.get("dc"):
                    leg = None        # "or draw": the straight price is not this bet's
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
                             price_book=r.get("price_book"), price_at=r.get("price_at"),
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
                entry["strong"] = calls.is_call(lg, entry["conf"])
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
                            price=entry.get("price"), price_at=r.get("price_at"),
                            price_book=r.get("price_book"),
                            conf=entry["conf"], why=entry["why"],
                            strong=entry["strong"], version=POLICY, policy=_pol.version(),
                            w=_pol.model_weight(lg), p_market_away=r.get("p_market_away"),
                            p_model_away=r.get("p_model_away"),
                            prices={L.get("side"): L.get("price") for L in r.get("legs") or []
                                    if L.get("side")})
                if not hist or {k: hist[-1].get(k) for k in ("pick", "dc", "price", "conf", "policy")} != \
                        {k: snap.get(k) for k in ("pick", "dc", "price", "conf", "policy")}:
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
                                state=st.get("shortDetail", ""))
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
    return " · ".join(bits)


def _stale(e):
    anchor = e.get("date") or (e.get("logged") or "")[:10]
    try:
        a = dt.date.fromisoformat(anchor)
    except ValueError:
        return False
    return (dt.datetime.now(ET).date() - a).days > VOID_AFTER_DAYS


def grade():
    book = load()
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
            e["settled"] = dt.datetime.now(ET).isoformat()[:16]
            e["diagnosis"] = f'void: {res.get("state") or "game not played"}'
            settled.append((key, e))
            continue
        if not res or res.get("missing"):
            e.pop("live", None)          # was it ever marked live, it is not now
            e.pop("live_score", None)
            if res and _stale(e):
                e["status"] = "void"
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
    done = [e for e in book.values() if e.get("status") in ("won", "lost")]
    out = {"graded": len(done), "open": sum(1 for e in book.values()
                                            if e.get("status") == "open")}
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
                 score=e.get("live_score") or {})
            for e in book.values()
            if e.get("status") == "open" and e.get("live")]
    live.sort(key=lambda x: (x["league"], x["pick"]))

    done = [e for e in book.values() if e.get("status") in ("won", "lost")]
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
                     if e.get("status") == "open" and (e.get("date") or "") == today)

    gate = recs or []
    # epoch ms of this capture, so the page can show its own age at render
    # time. The page cannot fetch, so honesty about staleness is the only
    # substitute for freshness.
    captured = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000)
    return dict(captured=captured,
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
                live=live, feed=feed, gate=gate,
                today=today, today_won=sum(e["status"] == "won" for e in todays),
                today_lost=sum(e["status"] == "lost" for e in todays),
                today_open=open_today, feed_today=feed_today,
                # the same split the pick tabs use: strong calls vs close games
                today_strong_won=sum(e["status"] == "won" for e in todays if _strong(e)),
                today_strong_lost=sum(e["status"] == "lost" for e in todays if _strong(e)))


def _strong(e):
    """The label the pick was published with; older entries, recorded
    before labels were frozen, fall back to today's cutoff."""
    if "strong" in e:
        return e["strong"]
    import calls
    return calls.is_call(e.get("league"), e.get("conf"))


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
