"""Ladder challenge: $1 to $10,000 on the day's 5 likeliest Locks.

Each day's ticket is the 5 highest-chance legs of that day's Locks card (set
at 8 AM Eastern and recorded in locks.json, one leg per game), as one parlay.
A win rolls the whole bank into the next day's ticket; a single loss ends the
run, and the next day starts a new run from $1. A leg that voids or pushes
drops out of the parlay (pays 1x), as sportsbooks settle it.

Nothing is stored here: the ladder is replayed from the locks ledger on every
build, from START, so it can never drift from the graded record.

Odds, honestly: on 16 graded cards before the start, all 5 top legs won on 5
days (31%, against 32% stated) and the parlay paid about 3.05x. Reaching
$10,000 from $1 takes 9 wins in a row at that price -- about 1 in 40,000.
"""
import math

import locks

START = "2026-11-03"
BANK0 = 1.0
TARGET = 10000.0
LEGS = 5


def ticket(book, day, n=LEGS):
    """The day's n likeliest Locks legs, or [] when the card is short."""
    keys = book["days"].get(day) or []
    if isinstance(keys, dict):
        keys = keys.get("legs") or []
    legs = sorted((dict(book["legs"][k], key=k) for k in keys if k in book["legs"]), key=lambda L: -L["p"])
    return legs[:n] if len(legs) >= n else []


def settle(legs):
    """('won', payout) / ('lost', 0) / ('open', None) for one parlay."""
    st = [L.get("status") for L in legs]
    if "lost" in st:
        return "lost", 0.0
    if any(s not in ("won", "void", "push") for s in st):
        return "open", None
    return "won", math.prod(locks._dec(L["price"]) if L.get("status") == "won" else 1.0 for L in legs)


def replay(book=None, start=START, target=TARGET):
    """Every run from start: [{start, days: [...], status, bank}]; the last
    run is the live one. Stops at the first unsettled day."""
    book = book or locks.load()
    runs, cur = [], None
    for day in sorted(d for d in book["days"] if d >= start):
        legs = ticket(book, day)
        if not legs:
            continue
        if cur is None or cur["status"] in ("lost", "reached"):
            cur = dict(start=day, days=[], status="live", bank=BANK0)
            runs.append(cur)
        res, pay = settle(legs)
        stake = cur["bank"]
        entry = dict(day=day, stake=round(stake, 2), result=res,
                     prob=round(math.prod(L["p"] for L in legs), 4),
                     pays=round(math.prod(locks._dec(L["price"]) for L in legs), 3),
                     legs=[dict(label=L["label"], price=L["price"], p=L["p"], match=L.get("match"),
                                tip=L.get("tip"), lg=L.get("lg") or L.get("league"), score=L.get("score"),
                                gid=L.get("gid"),
                                status=L.get("status") or "open") for L in legs])
        cur["days"].append(entry)
        if res == "open":
            break
        if res == "lost":
            cur["status"], cur["bank"] = "lost", 0.0
        else:
            cur["bank"] = round(stake * pay, 2)
            if cur["bank"] >= target:
                cur["status"] = "reached"
    return runs


def live(legs):
    """Attach the game clock and score (the picks ledger's live fields, by
    game id) to each open leg, so the ticket can be followed in play."""
    try:
        import ledger
        book = ledger.load()
    except Exception:
        return
    for L in legs:
        e = book.get(L.get("gid")) or {}
        if L.get("status") in (None, "open") and e.get("live") and e.get("live_score"):
            L["live"] = e["live"]
            L["live_score"] = " - ".join(f"{t} {v}" for t, v in e["live_score"].items())


def report(book=None, start=START, target=TARGET):
    runs = replay(book, start, target)
    cur = runs[-1] if runs else None
    bank = cur["bank"] if cur and cur["status"] == "live" else BANK0
    today = cur["days"][-1] if cur and cur["days"] and cur["days"][-1]["result"] == "open" else None
    if today:
        live(today["legs"])
    pays = (today or {}).get("pays") or 3.05
    need = max(0, math.ceil(math.log(target / bank) / math.log(pays))) if pays > 1 and bank < target else 0
    p = (today or {}).get("prob")
    return dict(start=start, target=target, bank=round(bank, 2), runs=len(runs),
                reached=sum(r["status"] == "reached" for r in runs),
                best=round(max([r["bank"] for r in runs if r["status"] != "lost"] +
                               [max([d["stake"] for d in r["days"]] or [BANK0]) for r in runs] + [BANK0]), 2),
                streak=sum(1 for d in (cur or {}).get("days", []) if d["result"] == "won") if cur else 0,
                today=today, wins_needed=need,
                chance_to_target=round(p ** need, 8) if p and need else None,
                history=[dict(start=r["start"], status=r["status"], days=len(r["days"]),
                              peak=max([d["stake"] for d in r["days"]] + [r["bank"]])) for r in runs][-10:])
