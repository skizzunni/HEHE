"""Which price source predicts winners best -- measured, not assumed.

For every two-way game on the board (no draw), each build snapshots the
no-vig chance that the HOME side wins from every source that lists it:

    dk         DraftKings, Shin de-vig of both sides (the board's own price)
    fd         FanDuel moneyline, Shin de-vig
    kalshi     Kalshi, both sides' ask prices normalised to sum to 1
    pm         Polymarket moneyline (liquid markets only)
    pinnacle   Pinnacle via The Odds API, Shin de-vig (only with ODDS_API_KEY)
    blend      the plain average of whichever of the above are present

The snapshot kept is the LAST one taken before the start -- the closest to
the closing price each source offered. Once the game is graded, report()
scores every source on exactly the games where all compared sources quote,
by Brier score and log-loss (lower is better), with a paired bootstrap
interval on the difference to DraftKings. A source is only ever promoted to
pick from on that evidence; until then this is a forward archive.
"""
import datetime as dt
import json
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "sources.json")
SOURCES = ("dk", "fd", "kalshi", "pm", "pinnacle")


def load(path=None):
    try:
        with open(path or PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"games": {}}


def save(book, path=None):
    with open(path or PATH, "w") as fh:
        json.dump(book, fh, indent=1, sort_keys=True)


def _two(a, b):
    """Normalise two raw chances to sum to 1, or None."""
    if not a or not b or a <= 0 or b <= 0:
        return None
    return a / (a + b)


def snapshot(league, row, FD=None, KB=None, PM=None, OA=None):
    """{source: P(home wins)} for one board game, or {} for a three-way market."""
    import devig
    import venues
    m = row.get("mkt") or {}
    if any(L.get("side") == "draw" for L in row.get("legs") or []):
        return {}
    home, away = m.get("home"), m.get("away")
    if not home or not away:
        return {}
    out = {}
    legs = {L.get("side"): L for L in row.get("legs") or [] if L.get("price")}
    if "home" in legs and "away" in legs:
        fv = devig.fair_decimal(venues.dec(legs["home"]["price"]), venues.dec(legs["away"]["price"]), method="shin")
        if fv:
            out["dk"] = fv[0]
    if FD:
        try:
            import fanduel
            g = fanduel.find(FD, league, away, home)
            if g:
                rh, ra = fanduel._runner(g["ml"], home), fanduel._runner(g["ml"], away)
                ph, pa = (g.get("px") or {}).get(rh), (g.get("px") or {}).get(ra)
                fv = devig.fair_decimal(venues.dec(ph), venues.dec(pa), method="shin") if rh and ra and rh != ra else None
                if fv:
                    out["fd"] = fv[0]
        except Exception:
            pass
    if KB:
        try:
            import kalshi
            kh = kalshi.leg(KB, league, m, dict(t="win", team=home))
            ka = kalshi.leg(KB, league, m, dict(t="win", team=away))
            p = _two((kh or {}).get("price"), (ka or {}).get("price"))
            if p:
                out["kalshi"] = p
        except Exception:
            pass
    if PM:
        try:
            import polymarket
            ph = polymarket.fair(PM, league, m, dict(t="win", team=home))
            pa = polymarket.fair(PM, league, m, dict(t="win", team=away))
            p = _two(ph, pa) if ph and pa else ph
            if p:
                out["pm"] = p
        except Exception:
            pass
    if OA:
        try:
            import oddsapi
            p = oddsapi.sharp_fair(OA, league, m, home)
            if p:
                out["pinnacle"] = p
        except Exception:
            pass
    out = {k: round(v, 4) for k, v in out.items() if v and 0 < v < 1}
    if out:
        out["blend"] = round(sum(out.values()) / len(out), 4)
    return out


def record(slot_rows, now=None, path=None, **feeds):
    """Keep each unstarted game's latest snapshot; returns how many updated."""
    import freshness
    now = now or dt.datetime.now(dt.timezone.utc)
    book = load(path)
    n = 0
    for lg, rows in (slot_rows or {}).items():
        for r in rows or []:
            m = r.get("mkt") or {}
            st = freshness.parse(m.get("start"))
            if not r.get("id") or st is None or st <= now:
                continue
            snap = snapshot(lg, r, **feeds)
            if not snap:
                continue
            g = book["games"].setdefault(r["id"], dict(league=lg, home=m.get("home"), away=m.get("away"),
                                                      start=m.get("start"), status="open"))
            if g.get("status") != "open":
                continue
            g.update(p=snap, at=now.isoformat(timespec="seconds"))
            n += 1
    save(book, path)
    return n


def grade(entries, path=None):
    """entries: {game id: ledger entry with winner}. A draw or void is dropped."""
    book = load(path)
    changed = False
    for gid, g in book["games"].items():
        if g.get("status") != "open":
            continue
        e = entries.get(gid) or {}
        if e.get("status") == "void":
            g["status"] = "void"
            changed = True
            continue
        w = e.get("winner")
        if w is None or e.get("status") in (None, "open"):
            continue
        g["status"] = "graded"
        g["home_won"] = 1 if w == g["home"] else 0 if w == g["away"] else None
        if g["home_won"] is None:
            g["status"] = "void"
        changed = True
    if changed:
        save(book, path)
    return book


def _brier(p, y):
    return (p - y) ** 2


def _ll(p, y):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -math.log(p if y else 1 - p)


def report(path=None, boots=1000, seed=7):
    """Per source: N, Brier, log-loss and the paired difference to DraftKings
    on the games both quote (negative = better than DraftKings)."""
    gs = [g for g in load(path)["games"].values() if g.get("status") == "graded" and g.get("home_won") in (0, 1)]
    out = []
    rnd = random.Random(seed)
    for s in SOURCES[1:] + ("blend",):
        pairs = [(g["p"][s], g["p"]["dk"], g["home_won"]) for g in gs if s in g["p"] and "dk" in g["p"]]
        if not pairs:
            continue
        d = [_brier(a, y) - _brier(b, y) for a, b, y in pairs]
        mean = sum(d) / len(d)
        bs = sorted(sum(rnd.choice(d) for _ in d) / len(d) for _ in range(boots))
        out.append(dict(source=s, n=len(pairs),
                        brier=round(sum(_brier(a, y) for a, _, y in pairs) / len(pairs), 4),
                        brier_dk=round(sum(_brier(b, y) for _, b, y in pairs) / len(pairs), 4),
                        logloss=round(sum(_ll(a, y) for a, _, y in pairs) / len(pairs), 4),
                        logloss_dk=round(sum(_ll(b, y) for _, b, y in pairs) / len(pairs), 4),
                        diff=round(mean, 5), ci95=[round(bs[int(.025 * boots)], 5), round(bs[int(.975 * boots)], 5)],
                        better=bs[int(.975 * boots)] < 0))
    return dict(games=len(gs), sources=out)
