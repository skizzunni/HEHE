"""The daily 10-leg ticket: the ten likeliest lines on the board, one per game.

Built from locks.every_game -- each game's single likeliest line out of the
8 AM pool (winner, spread with points, total, team total, double chance or
player prop), graded like the Locks. American leagues fill the ticket first
(user, 2026-11-17: "if nfl doesnt exist then fill it with nba or other
american sports"); other sports only make up the count when fewer than ten
American games are on.

Replayed on every frozen 8 AM pool (record()): 2026-11-04 to 11-16 the
plain top ten cashed 11 of 13 days at about 1.64x, against 41% stated --
these are heavy favourites, so the payout is small. Ten legs never make a
lock: one miss loses it.
"""
import math

US = ("nfl", "nba", "ncaaf", "ncaab", "nhl", "mlb", "wnba")
N = 10


def _dec(price):
    try:
        a = float(str(price).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if a == 0:
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a)


def build(games, n=N, us=US):
    """games: locks.every_game rows. The n likeliest still open, American
    leagues first: dict(legs, n, chance, pays, us_only) or None if empty."""
    open_ = [g for g in games or [] if g.get("status", "open") == "open" and g.get("p")]
    key = lambda g: -g["p"]
    first = sorted((g for g in open_ if str(g.get("league") or "").lower() in us), key=key)
    rest = sorted((g for g in open_ if str(g.get("league") or "").lower() not in us), key=key)
    legs = (first + rest)[:n]
    if not legs:
        return None
    decs = [_dec(g.get("price")) for g in legs]
    return dict(legs=legs, n=len(legs), chance=round(math.prod(g["p"] for g in legs), 4),
                pays=round(math.prod(d for d in decs if d), 2) if all(decs) else None,
                us_only=len(first) >= len(legs))


def record(path=None, led=None, n=N):
    """The ticket replayed on every frozen 8 AM pool, graded:
    dict(days, cashed, stated, pays) -- stated and pays are averages."""
    import locks
    if led is None:
        import ledger
        led = ledger.load()
    days = cashed = 0
    stated, pays = [], []
    for d, x in sorted((locks.load(path).get("pools") or {}).items()):
        eg = locks.every_game(x.get("legs"), led)
        for g in eg:
            g["_st"], g["status"] = g["status"], "open"   # pick as at 8 AM, grade after
        t = build(eg, n)
        if not t or t["n"] < n or any(g["_st"] not in ("won", "lost", "void") for g in t["legs"]):
            continue
        days += 1
        cashed += all(g["_st"] != "lost" for g in t["legs"])
        stated.append(t["chance"])
        if t["pays"]:
            pays.append(t["pays"])
    if not days:
        return dict(days=0)
    return dict(days=days, cashed=cashed, stated=round(sum(stated) / len(stated), 3),
                pays=round(sum(pays) / len(pays), 2) if pays else None)


SIZES = (6, 8, 10, 12, 15)


def sizes(path=None, led=None, ns=SIZES):
    """record() at several ticket sizes, so the page can show the trade:
    fewer legs cash more often and pay less. [dict(n, days, cashed, pays)]."""
    if led is None:
        import ledger
        led = ledger.load()
    out = []
    for n in ns:
        r = record(path, led=led, n=n)
        if r.get("days"):
            out.append(dict(n=n, days=r["days"], cashed=r["cashed"], pays=r.get("pays")))
    return out
