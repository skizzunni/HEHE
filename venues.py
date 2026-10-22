"""Where a pick pays most: the same bet at DraftKings, FanDuel and Kalshi.

The pick and its chance never change here -- only where to place it. A
better price is profit with no extra risk: on 44 graded picks priced at both
books, taking the better of DraftKings and FanDuel each time lifted ROI from
-6.97% to -6.18%; on 203 graded picks also listed on Kalshi, the best of
DraftKings and Kalshi lifted it from -10.07% to -9.66% (README, 2026-10-22).

Kalshi's taker fee is 0.07 x C x P x (1 - P) dollars for C contracts at
price P, rounded up to the cent; per contract on a 100-contract order that is
FEE x P x (1 - P), which is what the effective payout below uses.

compare() returns every venue that lists the exact bet (straight win only:
a double chance or spread is a different bet) with its decimal payout, and
the best of them; expected_per_100 is what $100 is expected to return at
each venue, from the market's own no-vig chance -- negative everywhere means
the venue's margin, not a forecast.
"""
import math

FEE = 0.07


def dec(american):
    try:
        v = float(str(american).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or abs(v) < 100:
        return None
    return 1 + (v / 100 if v > 0 else 100 / -v)


def kalshi_dec(ask):
    """Effective decimal payout buying at `ask` (dollars) after the fee."""
    if ask is None or not 0 < ask < 1:
        return None
    total = math.ceil(round(FEE * 100 * ask * (1 - ask) * 100, 6)) / 100   # 100 contracts, up to the cent
    return 1 / (ask + total / 100)


def american(d):
    if not d or d <= 1:
        return None
    return f"+{round(100 * (d - 1))}" if d >= 2 else str(round(-100 / (d - 1)))


def compare(league, row, team, book_price, book_name, FD=None, KB=None):
    """[{venue, price, dec}] for a straight-win bet on `team`, best first."""
    out = []
    d = dec(book_price)
    if d:
        out.append(dict(venue=book_name or "DraftKings", price=str(book_price), dec=round(d, 4)))
    m = row.get("mkt") or {}
    if FD:
        try:
            import fanduel
            g = fanduel.find(FD, league, m.get("away"), m.get("home"))
            ref = fanduel._runner(g["ml"], team) if g else None
            px = (g.get("px") or {}).get(ref) if ref else None
            fd = dec(px)
            if fd:
                out.append(dict(venue="FanDuel", price=str(px), dec=round(fd, 4), ref=ref))
        except Exception:
            pass
    if KB:
        try:
            import kalshi
            k = kalshi.leg(KB, league, m, dict(t="win", team=team))
            kd = kalshi_dec((k or {}).get("price"))
            if kd:
                out.append(dict(venue="Kalshi", price=f'{round(100 * k["price"])}¢', dec=round(kd, 4),
                                american=american(kd), ticker=k.get("ticker")))
        except Exception:
            pass
    out.sort(key=lambda x: -x["dec"])
    return out


def expected_per_100(p, d):
    """Expected return on $100 at decimal payout d for no-vig chance p."""
    return round(100 * (p * d - 1), 2) if p and d else None
