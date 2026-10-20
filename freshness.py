"""No timestamp, no price; no fresh price, no call.

Every price on the board carries the book it came from and the time it was
captured (dashboard.collect stamps each leg with `book` and `at`, the row with
`price_at` and `price_book`). The capture time is when this pipeline received
the price from ESPN's scoreboard (a fresh fetch, or the cache file's own time
when the cache served it) -- not the book's own quote time, which ESPN does not
give. A price is fresh while it is at most MAX_AGE_MIN minutes old.

At publish time a pick whose price is older than that, or has no capture time,
is STALE: it is shown with a stale badge, it is not a call, the ledger does
not record it (an earlier fresh call stands), and it is kept out of every
ticket, stack, Locks pool and the Lottery (fresh_slots).

Until 2026-10-20 the board had no capture times at all: the scoreboard cache
served copies up to 15 minutes old as current, and up to six hours old when
ESPN refused the request, and a call published from either looked the same as
one priced a minute earlier.
"""
import datetime as dt
from zoneinfo import ZoneInfo

MAX_AGE_MIN = 15
ET = ZoneInfo("America/New_York")


def parse(at):
    try:
        t = dt.datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def age_min(at, now=None):
    """Minutes since capture, or None without a usable timestamp."""
    t = parse(at)
    if t is None:
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    return (now - t).total_seconds() / 60


def is_fresh(at, now=None):
    a = age_min(at, now)
    return a is not None and a <= MAX_AGE_MIN


def priced(r):
    """Does the row carry a sportsbook price at all?"""
    return bool(r.get("legs"))


def stale(r, now=None):
    """A priced row whose price is too old, or has no capture time."""
    return priced(r) and not is_fresh(r.get("price_at"), now)


def can_call(r, now=None):
    """May the row be a call, be recorded and feed a ticket? Only with a
    verifiable book price (no price, no call: a Kalshi or model number alone
    makes a lean) that is fresh."""
    return priced(r) and not stale(r, now)


def fresh_slots(rows_by_league, now=None):
    """{league: rows} with a fresh book price only: what tickets, stacks,
    Locks pools and the Lottery may draw on."""
    return {lg: [r for r in rs or [] if can_call(r, now)]
            for lg, rs in (rows_by_league or {}).items()}


def fresh_days(slots, now=None):
    """The same for {slot: {league: rows}}."""
    return {s: fresh_slots(v, now) for s, v in (slots or {}).items()}


def as_of(ats):
    """'h:MM AM ET' of the OLDEST capture among `ats`, or None."""
    ts = [t for t in (parse(a) for a in ats or []) if t]
    if not ts:
        return None
    return min(ts).astimezone(ET).strftime("%-I:%M %p ET")
