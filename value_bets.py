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
# An edge this large is more often a stale or mismatched quote than value:
# 2026-10-27, finds claiming 5%+ won 5 of 17 against 45% fair (-40.7%),
# while 0-5% ones broke about even. They are archived and graded apart as
# "suspect" -- not shown as value bets, not put in value parlays -- so the
# record keeps testing them.
MAX_EV = 0.05
LAST_SUSPECT = []
# A find whose fair chance rests on DraftKings' price alone ("single") is
# held out the same way, archived and graded apart as "single". 2026-10-28,
# 183 graded: single-source finds returned -6.5% / -35.5% in the two halves
# of the dates (n=55 / 41), confirmed ones +20.9% / -10.3% (n=44 / 43).
LAST_SINGLE = []


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


def _consensus(fair, src, league, row, spec, PM):
    """Average the fair chance with Polymarket's liquid price where it has one."""
    if not PM:
        return fair, src
    try:
        import polymarket
        p = polymarket.fair(PM, league, row.get("mkt") or {}, spec)
    except Exception:
        p = None
    if p is None:
        return fair, src
    return (fair + p) / 2, src + " + Polymarket"


def scan(league, row, FD=None, KB=None, min_ev=MIN_EV, OA=None, PM=None):
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
        # a source the scoreboard has PROVEN beats DraftKings (sources.best)
        # replaces the fair chance for straight wins; none qualifies yet
        try:
            import sources
            three = any(L.get("side") == "draw" for L in row.get("legs") or [])
            b = sources.best3() if three else sources.best()
            if b and src == "DraftKings (Shin)":
                if three:
                    snap = sources.snapshot3(league, row, PM=PM)
                    if b in snap:
                        fair, src = snap[b][0 if side == "home" else 2], f"{b} (proven best)"
                else:
                    snap = sources.snapshot(league, row, FD=FD, KB=KB, PM=PM, OA=OA)
                    if b in snap:
                        fair, src = (snap[b] if side == "home" else 1 - snap[b]), f"{b} (proven best)"
        except Exception:
            pass
        if not src.endswith("(proven best)"):
            fair, src = _consensus(fair, src, league, row, dict(t="win", team=team), PM)
        vs = venues.compare(league, row, team, price, row.get("price_book") or "DraftKings", FD, KB, OA)
        if not vs:
            continue
        best[side] = (team, vs[0])
        # Two-way games: each venue is judged against the consensus of the
        # OTHER venues' no-vig chances (DraftKings, FanDuel, Kalshi,
        # Polymarket), never against a single book that may lag the market
        # (2026-10-27: on 55 archived two-way finds, the ones the
        # leave-one-out consensus still rated as value went 14 of 22, the
        # rest 11 of 33 -- with hindsight in that test, so it is tracked).
        loo = {}
        if src.startswith("DraftKings") and not any(L.get("side") == "draw" for L in row.get("legs") or []):
            try:
                import sources
                snap = {k: v for k, v in sources.snapshot(league, row, FD=FD, KB=KB, PM=PM).items() if k != "blend"}
                for name, key in (("FanDuel", "fd"), ("Kalshi", "kalshi")):
                    refs = [p for k, p in snap.items() if k != key]
                    if len(refs) >= 2:
                        ph = sum(refs) / len(refs)
                        loo[name] = (ph if side == "home" else 1 - ph, f"consensus of {len(refs)} other venues")
            except Exception:
                loo = {}
        for v in vs:
            v_fair, v_src = loo.get(v["venue"], (fair, src))
            ev = v_fair * v["dec"] - 1
            if ev > min_ev and v["venue"] != (row.get("price_book") or "DraftKings"):
                if src.startswith("Pinnacle") and v["venue"] == "Pinnacle":
                    continue                     # the reference is never its own find
                value.append(dict(id=row["id"], league=league, side=side, team=team, venue=v["venue"],
                                  price=v.get("american") or v["price"], dec=v["dec"], fair=round(v_fair, 4),
                                  fair_source=v_src,
                                  ev=round(ev, 4), match=row.get("label"), tip=row.get("tip"),
                                  start=(row.get("mkt") or {}).get("start")))
    # spreads and totals: the same comparison on exactly the same line
    for spec, label, fair, dk in line_markets(row):
        fair, lsrc = _consensus(fair, "DraftKings (Shin)", league, row, spec, PM)
        for v in line_prices(league, row, spec, FD, KB):
            ev = fair * v["dec"] - 1
            if ev > min_ev:
                value.append(dict(id=row["id"], league=league, side=json.dumps(spec, sort_keys=True),
                                  team=label, market=spec["t"], spec=spec, venue=v["venue"],
                                  price=v.get("american") or v["price"], dec=v["dec"], fair=round(fair, 4),
                                  ev=round(ev, 4), dk=dk, fair_source=lsrc, match=row.get("label"), tip=row.get("tip"),
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


def confirmed(v):
    """True when the fair chance is backed by more than DraftKings alone:
    Polymarket's liquid price, a proven source, or the other venues' consensus."""
    src = v.get("fair_source") or ""
    return any(w in src for w in ("Polymarket", "proven", "consensus"))


def scan_all(slot_rows, FD=None, KB=None, now=None, OA=None, PM=None):
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
            v, s = scan(lg, r, FD, KB, OA=OA, PM=PM)
            value.extend(v)
            if s:
                sure.append(s)
    global LAST_SUSPECT, LAST_SINGLE
    LAST_SUSPECT = [v for v in value if v["ev"] > MAX_EV]
    value = [v for v in value if v["ev"] <= MAX_EV]
    LAST_SINGLE = [v for v in value if not confirmed(v)]
    value = [v for v in value if confirmed(v)]
    # slices the record has shown cannot break even stay out (autotune.py)
    try:
        import autotune
        off = autotune.value_benched()
        value = [v for v in value if autotune.value_slice(v) not in off]
    except Exception:
        pass
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
    for kind, held in (("suspect", LAST_SUSPECT), ("single", LAST_SINGLE)):
        for v in held:
            k = f'{v["id"]}|{v["side"]}|{v["venue"]}'
            if k not in book["finds"]:
                book["finds"][k] = dict(v, kind=kind, seen=t)
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
        if f.get("kind") not in ("value", "suspect", "single") or f.get("status") in ("won", "lost", "void"):
            continue
        st = settle(f, entries.get(f["id"]))
        if st:
            f["status"] = st
            changed = True
    if changed:
        save(book, path)
    return book


def report(path=None, kind="value"):
    fs = [f for f in load(path)["finds"].values() if f.get("kind") == kind and f.get("status") in ("won", "lost")]
    if not fs:
        return dict(n=0)
    ret = [(f["dec"] - 1) if f["status"] == "won" else -1 for f in fs]
    return dict(n=len(fs), won=sum(f["status"] == "won" for f in fs),
                est_ev=round(100 * sum(f["ev"] for f in fs) / len(fs), 2),
                roi=round(100 * sum(ret) / len(fs), 2),
                dates=[min(f["seen"][:10] for f in fs), max(f["seen"][:10] for f in fs)])


# ------------------------------------------------------- value parlays
# A parlay's expected return is the product of its legs': (1 + EV_1)(1 + EV_2)
# ... - 1. Legs that each pay above the fair chance make a parlay that does
# too -- the opposite of an ordinary parlay, whose margin compounds. Built per
# venue (a parlay is placed at one book; Kalshi combos are quoted separately,
# so Kalshi is left out), one leg per game, the likeliest combination that
# reaches each payout target.
PARLAY_TARGETS = (2.0, 3.0, 5.0, 10.0)
PARLAY_MAX_LEGS = 6


def value_parlays(value, targets=PARLAY_TARGETS, max_legs=PARLAY_MAX_LEGS):
    import tickets
    out = []
    by = {}
    for v in value:
        if v["venue"] == "Kalshi":
            continue
        by.setdefault(v["venue"], []).append(v)
    for venue, vs in sorted(by.items()):
        # one leg per game: the best-EV find of each game at this venue
        best = {}
        for v in sorted(vs, key=lambda x: -x["ev"]):
            best.setdefault(v["id"], v)
        legs = [dict(gid=v["id"], p=v["fair"], dec=v["dec"], league=v["league"], spec=dict(t="win"),
                     label=v["team"], find=v) for v in best.values()]
        for target in targets:
            r = tickets.optimize(legs, target, 0.0, max_legs=max_legs, kind_cap=max_legs)
            if not r.get("legs"):
                continue
            ls = [L["find"] for L in r["legs"]]
            prob = 1.0
            pay = 1.0
            for L in r["legs"]:
                prob *= L["p"]
                pay *= L["dec"]
            out.append(dict(venue=venue, target=target, legs=[dict(id=f["id"], team=f["team"], price=f["price"],
                                                                     side=f["side"], spec=f.get("spec"),
                                                                     fair=f["fair"], ev=f["ev"]) for f in ls],
                            prob=round(prob, 4), payout=round(pay, 3), ev=round(prob * pay - 1, 4)))
    return out


def record_parlays(parlays, now=None, path=None):
    """Archive each value parlay once, when first seen."""
    import datetime as _dt
    now = now or _dt.datetime.now(_dt.timezone.utc)
    book = load(path)
    added = 0
    for p in parlays:
        k = "parlay|" + p["venue"] + "|" + "|".join(sorted(f'{L["id"]}:{L["side"]}' for L in p["legs"]))
        if k not in book["finds"]:
            book["finds"][k] = dict(p, kind="parlay", seen=now.isoformat(timespec="seconds"))
            added += 1
    if added:
        save(book, path)
    return added


def grade_parlays(entries, path=None):
    book = load(path)
    changed = False
    for f in book["finds"].values():
        if f.get("kind") != "parlay" or f.get("status") in ("won", "lost", "void"):
            continue
        st = [settle(dict(team=L["team"], spec=L.get("spec")), entries.get(L["id"])) for L in f["legs"]]
        if "lost" in st:
            f["status"] = "lost"
        elif all(s == "won" for s in st):
            f["status"] = "won"
        elif None not in st:
            f["status"] = "void"                 # a pushed leg: the slip is re-priced, not graded here
        else:
            continue
        changed = True
    if changed:
        save(book, path)
    return book


def parlay_report(path=None):
    fs = [f for f in load(path)["finds"].values() if f.get("kind") == "parlay" and f.get("status") in ("won", "lost")]
    if not fs:
        return dict(n=0)
    ret = [(f["payout"] - 1) if f["status"] == "won" else -1 for f in fs]
    return dict(n=len(fs), won=sum(f["status"] == "won" for f in fs), roi=round(100 * sum(ret) / len(fs), 2),
                est_ev=round(100 * sum(f["ev"] for f in fs) / len(fs), 2),
                claimed=round(100 * sum(f["prob"] for f in fs) / len(fs), 1))


# ----------------------------------------------------------- prop value
def prop_value(games, now=None, min_ev=MIN_EV):
    """DraftKings' over price on a player prop against FanDuel's fair chance
    for the same player, stat and line -- only where FanDuel prices both
    sides (its de-vigged pair; a one-sided price has no honest fair). Each
    find is logged in the props ledger so the box-score grader settles it."""
    import freshness
    import venues
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    for g in games or []:
        for P in g.get("props") or []:
            alt = P.get("alt") or {}
            if not P.get("two_sided") or not alt.get("price") or str(P.get("line", "")).startswith("u"):
                continue
            if P["p"] < 0.40:
                continue          # a proportional pair overstates longshots: fair only near the middle
            d = venues.dec(alt["price"])
            if not d:
                continue
            ev = P["p"] * d - 1
            if ev > min_ev:
                out.append(dict(kind="prop", gid=g["id"], league=g["id"].split(":", 1)[0], match=g.get("match"),
                                tip=g.get("tip"), name=P["name"], market=P["market"], line=P["line"],
                                aid=P.get("aid"), label=P["label"], venue=alt.get("book", "DraftKings"),
                                price=alt["price"], dec=round(d, 4), fair=P["p"], fair_source="FanDuel (two-sided)",
                                fd_price=P.get("price"), ev=round(ev, 4)))
    out.sort(key=lambda x: -x["ev"])
    return out


def record_props(finds, day, now=None, path=None):
    """Archive prop finds once, and log each in the props ledger at the
    better book's price so the box-score grader settles it."""
    import props_ledger
    now = now or dt.datetime.now(dt.timezone.utc)
    book = load(path)
    led = props_ledger.load()
    added = 0
    for f in finds:
        key = props_ledger.prop_key(f)
        k = "prop|" + key
        if k in book["finds"]:
            continue
        book["finds"][k] = dict(f, ledger_key=key, seen=now.isoformat(timespec="seconds"))
        if key not in led:
            led[key] = dict(league=f["league"], gid=f["gid"], aid=f.get("aid"), name=f["name"], market=f["market"],
                            line=f["line"], price=f["price"], p=f["fair"], label=f["label"], date=day,
                            status="open" if props_ledger.gradable(f["league"], f["market"]) else "ungradable",
                            value_find=True)
        added += 1
    if added:
        save(book, path)
        props_ledger.save(led)
    return added


def prop_report(path=None):
    import props_ledger
    led = props_ledger.load()
    fs = []
    for f in load(path)["finds"].values():
        if f.get("kind") != "prop":
            continue
        st = (led.get(f.get("ledger_key")) or {}).get("status")
        if st in ("won", "lost"):
            fs.append((f, st))
    if not fs:
        return dict(n=0)
    ret = [(f["dec"] - 1) if s == "won" else -1 for f, s in fs]
    return dict(n=len(fs), won=sum(s == "won" for _, s in fs), roi=round(100 * sum(ret) / len(fs), 2),
                est_ev=round(100 * sum(f["ev"] for f, _ in fs) / len(fs), 2))
