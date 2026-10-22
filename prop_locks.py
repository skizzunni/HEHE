"""Prop Locks: the day's likeliest player props, set once, logged, graded.

From FanDuel's props for today's games that have not started:

    eligible   the player is confirmed to play (participation.py), the
               market is settled from the box score (props_ledger.gradable),
               FanDuel's selection id is known, chance >= STANDARD
    chosen     strongest first, one per game and one per player, up to N

The card is set from PROP_HOUR (noon Eastern, when most prop lines are up),
frozen in prop_locks.json, and topped up as later games' props appear until
it has N legs -- a leg is never removed or replaced. Every leg is also logged
in the props ledger (props.json) at the price it was locked at, so the box
score grader settles it like every other prop.

The record is honest about what props cost: 482 graded FanDuel props at
80-90% returned -7.1% per $1 at their prices (README 2026-10-22). Prop
Locks are for winning often, not for profit.
"""
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "prop_locks.json")
N = 10
STANDARD = 0.70
PROP_HOUR = 12
ET = ZoneInfo("America/New_York")


def load(path=None):
    try:
        with open(path or PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"days": {}}


def save(book, path=None):
    with open(path or PATH, "w") as fh:
        json.dump(book, fh, indent=1, sort_keys=True)


def candidates(games, starts, now, standard=STANDARD):
    """Eligible props, strongest first. starts: {game id: ISO start}."""
    import freshness
    import participation
    import props_ledger
    out = []
    for g in games or []:
        st = freshness.parse(starts.get(g.get("id")))
        if st is None or st <= now:
            continue
        lg = (g.get("id") or "").split(":", 1)[0]
        for P in g.get("props") or []:
            if not P.get("fd") or (P.get("p") or 0) < standard or not P.get("name"):
                continue
            if not participation.eligible(P) or not props_ledger.gradable(lg, P.get("market")):
                continue
            out.append(dict(gid=g["id"], league=lg, match=g.get("match"), tip=g.get("tip"),
                            start=starts.get(g["id"]), name=P["name"], aid=P.get("aid"),
                            market=P["market"], line=P["line"], label=P["label"], price=P["price"],
                            p=P["p"], imp=P.get("imp"), fd=P["fd"], where=P.get("where"),
                            quoted=P.get("quoted")))
    out.sort(key=lambda x: (-x["p"], x["start"] or ""))
    return out


def update(games, starts, day, now=None, path=None, n=N):
    """Set or top up the day's Prop Locks; returns the day's record."""
    import props_ledger
    now = now or dt.datetime.now(dt.timezone.utc)
    book = load(path)
    rec = book["days"].setdefault(day, dict(legs=[]))
    if now.astimezone(ET).hour < PROP_HOUR or len(rec["legs"]) >= n:
        return rec
    games_used = {L["gid"] for L in rec["legs"]}
    players = {(L["gid"], L["name"]) for L in rec["legs"]}
    names = {L["name"] for L in rec["legs"]}
    add = []
    for c in candidates(games, starts, now):
        if len(rec["legs"]) + len(add) >= n:
            break
        if c["gid"] in games_used or c["name"] in names or (c["gid"], c["name"]) in players:
            continue
        games_used.add(c["gid"])
        names.add(c["name"])
        add.append(c)
    if not add:
        return rec
    t = now.isoformat(timespec="seconds")
    led = props_ledger.load()
    for c in add:
        c.update(set_at=t, rank=len(rec["legs"]) + 1, key=props_ledger.prop_key(c))
        rec["legs"].append(c)
        if c["key"] not in led:
            led[c["key"]] = dict(league=c["league"], gid=c["gid"], aid=c["aid"], name=c["name"],
                                 market=c["market"], line=c["line"], price=c["price"], imp=c.get("imp"),
                                 p=c["p"], label=c["label"], date=day, status="open", prop_lock=True)
        else:
            led[c["key"]]["prop_lock"] = True
    props_ledger.save(led)
    save(book, path)
    return rec


def _dec(price):
    import venues
    return venues.dec(price)


def report(path=None):
    """Per day and overall: legs won/lost/open, the chance stated, ROI at the
    locked prices, from the props ledger's grading."""
    import math
    import props_ledger
    led = props_ledger.load()
    days, allrows = [], []
    for day, rec in sorted(load(path)["days"].items(), reverse=True):
        st = [(L, (led.get(L.get("key")) or {}).get("status", "open")) for L in rec.get("legs") or []]
        won = sum(s == "won" for _, s in st)
        lost = sum(s == "lost" for _, s in st)
        days.append(dict(day=day, n=len(st), won=won, lost=lost, open=sum(s == "open" for _, s in st),
                         void=sum(s in ("void", "ungradable") for _, s in st)))
        allrows += [(L, s) for L, s in st if s in ("won", "lost")]
    if not allrows:
        return dict(days=days, n=0)
    n = len(allrows)
    w = sum(s == "won" for _, s in allrows)
    ret = [((_dec(L["price"]) or 1) - 1) if s == "won" else -1 for L, s in allrows]
    z = 1.96
    p = w / n
    lo = (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)
    hi = (p + z * z / (2 * n) + z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)
    return dict(days=days, n=n, won=w, hit=round(100 * p, 1), wilson95=[round(100 * lo, 1), round(100 * hi, 1)],
                stated=round(100 * sum(L["p"] for L, _ in allrows) / n, 1),
                roi=round(100 * sum(ret) / n, 1))


def props_record():
    """Every graded prop in the props ledger: overall and by market, with
    the chance stated and ROI at the logged price -- the Results tab's props
    section."""
    import props_ledger
    rows = [e for e in props_ledger.load().values() if isinstance(e, dict) and e.get("status") in ("won", "lost")]
    if not rows:
        return dict(n=0)

    def summ(rs):
        n = len(rs)
        ret = [((_dec(e.get("price")) or 1) - 1) if e["status"] == "won" else -1 for e in rs]
        return dict(n=n, won=sum(e["status"] == "won" for e in rs),
                    hit=round(100 * sum(e["status"] == "won" for e in rs) / n, 1),
                    stated=round(100 * sum(e.get("p") or 0 for e in rs) / n, 1),
                    roi=round(100 * sum(ret) / n, 1))
    by = {}
    for e in rows:
        by.setdefault(f'{e.get("league")} {e.get("market")}', []).append(e)
    dates = sorted(e.get("date") or "" for e in rows)
    return dict(all=summ(rows), dates=[dates[0], dates[-1]],
                markets=sorted(([k, summ(v)] for k, v in by.items() if len(v) >= 15), key=lambda x: -x[1]["n"]))
