"""Tickets from the day's calls -- and only from them.

    legs       the day's calls (calls.json) not pulled and not started,
               strongest first; at most MAX_LEGS
    banned     two legs from the same game, or sharing an outcome driver:
               a team (or player) in both, or the same event
    joint      the product of the legs' published chances, times PENALTY for
               every leg after the first
    payout     fair (1 / joint) beside actual (the product of the decimal
               prices the calls were published at)

PENALTY is not a fitted correlation -- on 45 days of graded picks before
2026-10-15, pairs of same-day picks from different games won together 4.7%
MORE often than the product of their chances (after each leg's own
calibration), 95% range 0.982 to 1.140. A ticket is still given the lower end
of that range, so its joint chance is never stated above what the record
supports.

ticket(n) is the strongest n-leg ticket: the top calls, skipping any leg that
would share a game or driver with a stronger one.
"""
import math

MAX_LEGS = 3
PENALTY = 0.982


def dec(american):
    try:
        v = int(str(american).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if v == 0:
        return None
    return 1 + (v / 100 if v > 0 else 100 / -v)


def drivers(c):
    """What decides the leg: its game, its event and each side's name."""
    out = {("game", c["id"])}
    if c.get("event"):
        out.add(("event", c["event"]))
    for side in (c.get("match") or "").replace(" vs ", " @ ").split(" @ "):
        if side.strip():
            out.add(("team", side.strip().casefold()))
    out.add(("team", (c.get("pick") or "").strip().casefold()))
    return out


def eligible(calls_today, started=None):
    started = started or (lambda c: False)
    legs = [c for c in calls_today if c.get("status") != "pulled" and not started(c) and dec(c.get("price"))]
    return sorted(legs, key=lambda c: (-c["conf"], c.get("rank") or 0))


def ticket(legs, n):
    """The strongest n-leg ticket, or None when n legs cannot be found."""
    if not 2 <= n <= MAX_LEGS:
        return None
    pick, used = [], set()
    for c in legs:
        d = drivers(c)
        if d & used:
            continue                          # same game or a shared driver
        pick.append(c)
        used |= d
        if len(pick) == n:
            break
    if len(pick) < n:
        return None
    raw = math.prod(c["conf"] / 100 for c in pick)
    joint = raw * PENALTY ** (n - 1)
    actual = math.prod(dec(c["price"]) for c in pick)
    return dict(legs=[{k: c.get(k) for k in ("id", "league", "pick", "match", "conf", "price", "tip")} for c in pick],
                joint=round(joint, 4), independent=round(raw, 4), penalty=PENALTY,
                fair_payout=round(1 / joint, 2), actual_payout=round(actual, 2),
                value=round(joint * actual - 1, 3))


def build(calls_today, started=None):
    legs = eligible(calls_today, started)
    return [t for t in (ticket(legs, n) for n in range(2, MAX_LEGS + 1)) if t]
