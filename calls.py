"""Which games count as a CALL, and which are only a lean.

Every game still gets a side on the board, but only games whose favourite is
strong enough are recorded as calls and counted in the record. On 1,068 past
priced games (ledger.json, 2026-10-16) the market's favourite hit:

    chance >= 50%   67.9%   (every game)
    chance >= 55%   72.7%
    chance >= 60%   76.5%   (635 games)
    chance >= 65%   81.8%   (456 games)
    chance >= 70%   88.0%

Every pick is recorded and counted. The cutoff only labels each one "strong"
or "close" on the board, so it is clear which picks carry the record.
tools/daily_review.py freezes each league's cutoff for 14 days (fit_frozen):
the lowest one whose prior-window record reaches TARGET on 150+ picks with a
Wilson lower bound of TARGET - 3 points, Holm-corrected across leagues, in
review/call_min.json. A league with no qualifying record gets no strong
calls (soccer qualifies as one group).
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "review", "call_min.json")
TARGET = 0.75

try:
    with open(PATH) as _fh:
        _J = json.load(_fh)
    _MIN = {k: float(v) for k, v in (_J.get("cutoffs") or {}).items() if v is not None}
except (OSError, ValueError, TypeError):
    _MIN = {}


def _group(league):
    """Soccer leagues qualify together (tools/daily_review.call_group)."""
    try:
        import ledger
        return "soccer" if league in ledger.SOCCER else league
    except Exception:
        return league


def call_min(league):
    """The cutoff for a strong call, or None: only a league (or the soccer
    group) whose own record qualified gets strong calls. No defaults and no
    exceptions -- until 2026-10-19 soccer got 75% without a test and leagues
    with no record (NBA, college basketball) got 60%."""
    return _MIN.get(_group(league))


def is_call(league, conf):
    """conf is the pick's chance as a fraction (0.63) or a percent (63.0)."""
    if conf is None or call_min(league) is None:
        return False
    c = conf / 100 if conf > 1 else conf
    return c >= call_min(league)


# ---------------------------------------------------------- the day's calls
# Every day the board publishes its calls: the TOP_N highest published
# chances among today's games that have a fresh, verifiable sportsbook price
# (freshness.can_call) and have not started, strongest first. Fewer games,
# fewer calls -- never "no calls today" while a priced game is left, and never
# a softer probability to fill the list. The honest dial is TOP_N = 3.
#
# The set is chosen at the first build from CALL_HOUR (8:00 AM Eastern, with
# the Locks card) and is then frozen in calls.json: a call is never taken back
# or replaced. If fewer than TOP_N games qualify at that moment, later builds
# add the next strongest until there are TOP_N. "Or draw" picks are not calls:
# the double-chance bet has no quoted price of its own. Every call counts in
# the record at the chance it was published with; one under its league's
# strong cut-off is labelled a close call.
import datetime as _dt
from zoneinfo import ZoneInfo as _ZI

TOP_N = 5
CALL_HOUR = 8
DAILY = os.path.join(HERE, "calls.json")
_ET = _ZI("America/New_York")


def load_daily(path=None):
    try:
        with open(path or DAILY) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"days": {}}


def save_daily(book, path=None):
    with open(path or DAILY, "w") as fh:
        json.dump(book, fh, indent=1, sort_keys=True)


def _iso(day):
    day = str(day)
    return f"{day[:4]}-{day[4:6]}-{day[6:]}" if len(day) == 8 else day


def candidates(rows_by_league, day, now):
    """Today's games that may be a call, with their published chance."""
    import freshness
    import calibration
    pub = calibration.publisher(_iso(day))
    out = []
    for lg, rows in (rows_by_league or {}).items():
        for r in rows or []:
            if not r.get("mypick") or r["mypick"].strip().upper() == "TBD" or r.get("dc"):
                continue
            if not r.get("myconf") or not freshness.can_call(r, now):
                continue
            st = freshness.parse((r.get("mkt") or {}).get("start"))
            if st is None or st <= now:
                continue
            leg = next((L for L in r.get("legs") or [] if L.get("side") == r.get("myside")), None)
            if not leg or not leg.get("price"):
                continue
            pct, how = pub.publish(lg, r["myconf"])
            out.append(dict(id=r["id"], league=lg, pick=r["mypick"], side=r.get("myside"), match=r.get("label"),
                            tip=r.get("tip"), start=(r.get("mkt") or {}).get("start"),
                            conf=pct, price=leg["price"], book=r.get("price_book"),
                            price_at=r.get("price_at"), calib=how,
                            close=not is_call(lg, pct)))
    out.sort(key=lambda c: (-c["conf"], c["start"] or ""))
    return out


def _row_chance(r, side):
    """The market's no-vig chance of `side` on a board row, or None."""
    leg = next((L for L in r.get("legs") or [] if L.get("side") == side), None)
    return leg.get("prob") if leg else None


def watch(rec, rows_by_league, now, summary=None):
    """News gates and the move rule on the day's calls (news.py). Returns
    True if anything changed. A call is never changed after its start."""
    import freshness
    import news
    summary = summary or news.summary
    rows = {r["id"]: (lg, r) for lg, rs in (rows_by_league or {}).items() for r in rs or []}
    t = now.isoformat(timespec="seconds")
    changed = False
    live = []
    for c in rec["calls"]:
        st = freshness.parse(c.get("start"))
        if c.get("status") == "pulled" or (st is not None and st <= now) or c["id"] not in rows:
            continue
        lg, r = rows[c["id"]]
        ok, what, fp = news.status(c["league"], r, summary(c["league"], c["id"]))
        if c.get("fp") and fp != c["fp"]:
            rec.setdefault("news", {})[c["league"]] = t
            c.setdefault("log", []).append(dict(t=t, event="news", what=what))
        if c.get("fp") != fp or (c.get("gate") or {}).get("what") != what:
            c["fp"], c["gate"] = fp, dict(ok=ok, what=what)
            changed = True
        live.append((c, r))
    # a league with news since its newest price waits for a re-pull
    frozen = {lg for lg, tn in (rec.get("news") or {}).items()
              if not any((freshness.parse(r.get("price_at")) or now) > freshness.parse(tn)
                         for r in (rows_by_league or {}).get(lg) or [] if r.get("price_at"))}
    rec["frozen"] = sorted(frozen)
    for c, r in live:
        if c["league"] in frozen or not freshness.can_call(r, now):
            continue
        # calls set before 2026-10-20 13:30 UTC carry no side: the row's, if
        # the row still picks the same team
        side = c.get("side") or (r.get("myside") if r.get("mypick") == c["pick"] else None)
        p = _row_chance(r, side)
        if p is None or abs(100 * p - c["conf"]) <= news.MOVE_PTS:
            continue
        old = c["conf"]
        if p < 0.5:
            c["status"] = "pulled"
            c.setdefault("log", []).append(dict(t=t, event="pulled", from_=old, market=round(100 * p, 1),
                                                why=f"moved {100 * p - old:+.1f} pts; side no longer the favourite"))
        else:
            c["conf"] = int(round(100 * p))
            c.setdefault("log", []).append(dict(t=t, event="re-derived", from_=old, to=c["conf"],
                                                why=f"moved {100 * p - old:+.1f} pts since published"))
        changed = True
    return changed


def update_daily(state, now=None, path=None, n=None, summary=None):
    """Set (or top up) today's calls, then apply the news gates and the move
    rule (watch); returns today's record of them."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    n = n or TOP_N
    day = (state.get("dates") or [None])[0]
    if not day:
        return None
    iso = _iso(day)
    book = load_daily(path)
    rec = book["days"].setdefault(iso, dict(calls=[]))
    if now.astimezone(_ET).hour < CALL_HOUR:
        return rec
    today = (state.get("slots") or {}).get("today")
    changed = watch(rec, today, now, summary) if rec["calls"] else False
    if len(rec["calls"]) < n:
        have = {c["id"] for c in rec["calls"]}
        frozen = set(rec.get("frozen") or [])
        add = [c for c in candidates(today, day, now)
               if c["id"] not in have and c["league"] not in frozen][:n - len(rec["calls"])]
        t = now.isoformat(timespec="seconds")
        for c in add:
            rec["calls"].append(dict(c, set_at=t, rank=len(rec["calls"]) + 1, conf_first=c["conf"]))
        if add:
            watch(rec, today, now, summary)        # each new call's gate and news baseline
            changed = True
    if changed:
        save_daily(book, path)
    return rec


def daily_ids(day, path=None):
    """{game id: call} for the day's calls."""
    rec = load_daily(path)["days"].get(_iso(day)) or {}
    return {c["id"]: c for c in rec.get("calls") or []}
