"""Value bets and sure bets across venues -- forward-tested, never assumed.

For every game on the board with a sportsbook price, each side is priced at
the venues that list it (venues.compare: DraftKings via ESPN, FanDuel,
Kalshi after its fee) against the market's own fair chance, DraftKings'
prices de-vigged by Shin's method (FAIR_METHOD):

    value bet   a venue pays more than the fair chance is worth:
                EV = fair x decimal - 1 > MIN_EV
    sure bet    the best price on each side of a two-way game, together,
                cost less than the payout: 1/d_a + 1/d_b < 1 -- staking
                each side in proportion to 1/d returns the same on either
                result, more than was staked

Neither predicts anything better than the market: they buy the market's own
estimate below its price. On 389 past Kalshi game contracts with a
DraftKings close, the 44 where Kalshi paid above DraftKings' fair returned
+6.7% (estimated +1.6%) -- too few, and against a later price, to count as
proof (README 2026-10-22). So every find is archived the moment it is seen,
before the game, in value.json, never revised, and graded from the ledger's
results; the record says whether it works.
"""
import datetime as dt
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "value.json")
MIN_EV = 0.01                    # one cent per dollar, below which prices are noise


# The fair chance is Shin's de-vig of the reference book's prices, not the
# board's proportional one: proportional spreads the margin evenly and so
# overstates a longshot's chance (the favourite-longshot bias measured in
# data/fav_band_study.json), which made +600 underdogs look like value on
# the first live scan (2026-10-22).
FAIR_METHOD = "shin"


def _sides(row):
    import devig
    import venues
    m = row.get("mkt") or {}
    legs = [L for L in row.get("legs") or [] if L.get("side") and L.get("price")]
    fv = devig.fair_decimal(*[venues.dec(L["price"]) for L in legs], method=FAIR_METHOD) if legs else None
    if not fv:
        return []
    out = []
    for L, p in zip(legs, fv):
        side = L.get("side")
        if side not in ("away", "home"):
            continue
        team = m.get(side) or L.get("who")
        if team:
            out.append((side, team, p, L["price"]))
    return out


def line_markets(row):
    """[(spec, label, fair, DraftKings price)] for the game's spread and
    total, fair by Shin's de-vig of DraftKings' two prices."""
    import devig
    import venues
    m = row.get("mkt") or {}
    out = []
    h, a = m.get("ps_home"), m.get("ps_away")
    if h and a and abs(h[0] + a[0]) < 1e-9:
        fv = devig.fair_decimal(venues.dec(h[1]), venues.dec(a[1]), method=FAIR_METHOD)
        if fv:
            for (side, (line, price)), p in zip((("home", h), ("away", a)), fv):
                team = m.get(side)
                out.append((dict(t="spread", team=team, line=line), f"{team} {line:+g}", p, price))
    o, u, tot = m.get("over"), m.get("under"), m.get("total")
    if o and u and tot is not None:
        fv = devig.fair_decimal(venues.dec(o), venues.dec(u), method=FAIR_METHOD)
        if fv:
            out.append((dict(t="over", line=tot), f"over {tot:g}", fv[0], o))
            out.append((dict(t="under", line=tot), f"under {tot:g}", fv[1], u))
    return out


def line_prices(league, row, spec, FD=None, KB=None):
    """[{venue, price, dec}] for a spread or total at FanDuel and Kalshi, on
    exactly the same line."""
    import venues
    m = row.get("mkt") or {}
    out = []
    if FD:
        try:
            import fanduel
            g = fanduel.find(FD, league, m.get("away"), m.get("home"))
            if g:
                if spec["t"] == "spread":
                    v = fanduel._runner(g["spread"], spec["team"])
                else:
                    v = g["total"].get(spec["t"])
                if v and v[0] is not None and abs(float(v[0]) - spec["line"]) < 1e-9:
                    px = (g.get("px") or {}).get(v[1])
                    d = venues.dec(px)
                    if d:
                        out.append(dict(venue="FanDuel", price=str(px), dec=round(d, 4), ref=v[1]))
        except Exception:
            pass
    if KB:
        try:
            import kalshi
            k = kalshi.leg(KB, league, m, spec)
            kd = venues.kalshi_dec((k or {}).get("price"))
            if kd:
                out.append(dict(venue="Kalshi", price=f'{round(100 * k["price"])}¢', dec=round(kd, 4),
                                american=venues.american(kd), ticker=k.get("ticker")))
        except Exception:
            pass
    return out


def scan(league, row, FD=None, KB=None, min_ev=MIN_EV, OA=None):
    """(value bets, sure bet or None) for one board game."""
    import venues
    sides = _sides(row)
    best, value = {}, []
    for side, team, fair, price in sides:
        # Pinnacle's fair chance where The Odds API has it (oddsapi.py)
        src = "DraftKings (Shin)"
        if OA:
            try:
                import oddsapi
                sf = oddsapi.sharp_fair(OA, league, row.get("mkt") or {}, team)
                if sf:
                    fair, src = sf, "Pinnacle (Shin)"
            except Exception:
                pass
        vs = venues.compare(league, row, team, price, row.get("price_book") or "DraftKings", FD, KB, OA)
        if not vs:
            continue
        best[side] = (team, vs[0])
        for v in vs:
            ev = fair * v["dec"] - 1
            if ev > min_ev and v["venue"] != (row.get("price_book") or "DraftKings"):
                if src.startswith("Pinnacle") and v["venue"] == "Pinnacle":
                    continue                     # the reference is never its own find
                value.append(dict(id=row["id"], league=league, side=side, team=team, venue=v["venue"],
                                  price=v.get("american") or v["price"], dec=v["dec"], fair=round(fair, 4),
                                  fair_source=src,
                                  ev=round(ev, 4), match=row.get("label"), tip=row.get("tip"),
                                  start=(row.get("mkt") or {}).get("start")))
    # spreads and totals: the same comparison on exactly the same line
    for spec, label, fair, dk in line_markets(row):
        for v in line_prices(league, row, spec, FD, KB):
            ev = fair * v["dec"] - 1
            if ev > min_ev:
                value.append(dict(id=row["id"], league=league, side=json.dumps(spec, sort_keys=True),
                                  team=label, market=spec["t"], spec=spec, venue=v["venue"],
                                  price=v.get("american") or v["price"], dec=v["dec"], fair=round(fair, 4),
                                  ev=round(ev, 4), dk=dk, match=row.get("label"), tip=row.get("tip"),
                                  start=(row.get("mkt") or {}).get("start")))
    sure = None
    if len(best) == 2 and not any(L.get("side") == "draw" for L in row.get("legs") or []):
        (ta, va), (tb, vb) = best["away"], best["home"]
        cost = 1 / va["dec"] + 1 / vb["dec"]
        if cost < 1:
            sure = dict(id=row["id"], league=league, match=row.get("label"),
                        legs=[dict(team=ta, venue=va["venue"], price=va.get("american") or va["price"],
                                   stake_share=round((1 / va["dec"]) / cost, 4)),
                              dict(team=tb, venue=vb["venue"], price=vb.get("american") or vb["price"],
                                   stake_share=round((1 / vb["dec"]) / cost, 4))],
                        profit=round(1 / cost - 1, 4))
    return value, sure


def scan_all(slot_rows, FD=None, KB=None, now=None, OA=None):
    """Over every fresh, priced, unstarted game: value bets (best EV first)
    and sure bets."""
    import freshness
    now = now or dt.datetime.now(dt.timezone.utc)
    value, sure = [], []
    for lg, rows in (slot_rows or {}).items():
        for r in rows or []:
            st = freshness.parse((r.get("mkt") or {}).get("start"))
            if not freshness.can_call(r, now) or st is None or st <= now:
                continue
            v, s = scan(lg, r, FD, KB, OA=OA)
            value.extend(v)
            if s:
                sure.append(s)
    value.sort(key=lambda x: -x["ev"])
    sure.sort(key=lambda x: -x["profit"])
    return value, sure


# ------------------------------------------------------------- archive
def load(path=None):
    try:
        with open(path or PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"finds": {}}


def save(book, path=None):
    with open(path or PATH, "w") as fh:
        json.dump(book, fh, indent=1, sort_keys=True)


def record(value, sure, now=None, path=None):
    """Archive each find the first time it is seen; never revise it."""
    now = now or dt.datetime.now(dt.timezone.utc)
    book = load(path)
    t = now.isoformat(timespec="seconds")
    added = 0
    for v in value:
        k = f'{v["id"]}|{v["side"]}|{v["venue"]}'
        if k not in book["finds"]:
            book["finds"][k] = dict(v, kind="value", seen=t)
            added += 1
    for s in sure:
        k = f'{s["id"]}|sure'
        if k not in book["finds"]:
            book["finds"][k] = dict(s, kind="sure", seen=t)
            added += 1
    if added:
        save(book, path)
    return added


def settle(f, e):
    """won / lost / void for a find, from the ledger entry of its game
    (winner and final scores), or None while unsettled."""
    if not e or e.get("status") in (None, "open"):
        return None
    if e.get("status") == "void":
        return "void"
    spec = f.get("spec")
    if not spec:
        w = e.get("winner")
        return None if w is None else ("won" if w == f["team"] else "lost")
    sc = {k: v for k, v in (e.get("scores") or {}).items() if isinstance(v, (int, float))}
    if len(sc) != 2:
        return None
    if spec["t"] == "spread":
        mine = sc.get(spec["team"])
        if mine is None:
            return None
        other = next(v for k, v in sc.items() if k != spec["team"])
        m = mine + spec["line"] - other
    else:
        m = (sum(sc.values()) - spec["line"]) * (1 if spec["t"] == "over" else -1)
    return "void" if abs(m) < 1e-9 else ("won" if m > 0 else "lost")


def grade(entries, path=None):
    """entries: {game id: ledger entry}. Settles every find it can."""
    book = load(path)
    changed = False
    for k, f in book["finds"].items():
        if f.get("kind") != "value" or f.get("status") in ("won", "lost", "void"):
            continue
        st = settle(f, entries.get(f["id"]))
        if st:
            f["status"] = st
            changed = True
    if changed:
        save(book, path)
    return book


def report(path=None):
    fs = [f for f in load(path)["finds"].values() if f.get("kind") == "value" and f.get("status") in ("won", "lost")]
    if not fs:
        return dict(n=0)
    ret = [(f["dec"] - 1) if f["status"] == "won" else -1 for f in fs]
    return dict(n=len(fs), won=sum(f["status"] == "won" for f in fs),
                est_ev=round(100 * sum(f["ev"] for f in fs) / len(fs), 2),
                roi=round(100 * sum(ret) / len(fs), 2),
                dates=[min(f["seen"][:10] for f in fs), max(f["seen"][:10] for f in fs)])
