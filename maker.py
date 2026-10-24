"""Maker bids on Kalshi: the edge the taker price hides.

On 18,735 settled Kalshi legs (data/backtest_kalshi_legs.json, 2026-08-29 to
10-18), buying at the ASK lost money in nearly every price band: the taker
fee (0.07 P(1-P)) plus the one-cent spread eat the favourites' small edge.
Resting a BID instead -- buying at the best bid, paying the maker fee
(0.0175 P(1-P)) -- on legs of 50c or more whose sportsbook no-vig chance is
at least that all-in cost returned, assuming the bid fills:

    first half  (to 09-25)   1,369 legs   +4.2% per $1  (95% +-3.6)
    second half (from 09-26) 1,876 legs   +2.6% per $1  (95% +-3.0)
    taking the ask instead, same filter:  +1.1% and -7.6%

The assumption is the risk: a resting bid fills most readily when the price
is moving against it. So nothing is ordered here. Each build archives the
day's candidates (maker.json) at the bid they would rest at; after the start,
Kalshi's public trade tape decides whether each WOULD have filled:

    strict   a trade went through the bid (a better price than ours) --
             a fill is certain whatever the queue ahead
    touch    a trade printed at our price -- a fill only if the queue ahead
             was smaller than the trade

and Kalshi's own settlement grades it. report() gives ROI on strict fills
(the conservative number) and on touch fills, against the backtest.
"""
import datetime as dt
import json
import math
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "maker.json")
MAKER_FEE = 0.0175
MIN_PRICE = 0.50
MAX_SPREAD = 0.05
# only where the backtest held in both halves: NCAAF +3.5% / +5.3%, NFL
# +6.1% / +1.1%; NHL lost (-4.6%, N 206) and NBA/MLB were never tested
LEAGUES = ("ncaaf", "nfl")


def fee(p, k=MAKER_FEE):
    """Per-contract fee on a 100-contract order at price p, rounded up to the cent."""
    return math.ceil(round(k * 100 * p * (1 - p) * 100, 6)) / 100 / 100


def load(path=None):
    try:
        with open(path or PATH) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"bids": {}}


def save(book, path=None):
    with open(path or PATH, "w") as fh:
        json.dump(book, fh, indent=1, sort_keys=True)


def specs(row):
    """[(spec, label, fair)] -- moneyline sides, the spread and the total,
    each at its sportsbook no-vig chance (value_bets' Shin de-vig)."""
    import value_bets
    out = [(dict(t="win", team=team), team, fair) for _, team, fair, _ in value_bets._sides(row)]
    out += [(spec, label, fair) for spec, label, fair, _ in value_bets.line_markets(row)]
    return out


def candidates(league, row, KB):
    """Kalshi legs worth resting a bid on for one board game."""
    import kalshi
    if league not in LEAGUES:
        return []
    m = row.get("mkt") or {}
    out = []
    for spec, label, fair in specs(row):
        try:
            k = kalshi.leg(KB, league, m, spec)
        except Exception:
            k = None
        if not k or not k.get("price"):
            continue
        g = kalshi.find(KB, league, m) or {}
        mk = next((x for kind in ("GAME", "SPREAD", "TOTAL") for x in g.get(kind) or []
                   if x.get("ticker") == k["ticker"]), None)
        if not mk:
            continue
        other = mk["no_ask"] if k["side"] == "YES" else mk["yes_ask"]
        if not other:
            continue
        bid = round(1 - other, 2)
        ask = k["price"]
        if bid < MIN_PRICE or not 0 < ask - bid <= MAX_SPREAD:
            continue
        cost = bid + fee(bid)
        if fair < cost:
            continue
        out.append(dict(id=row.get("id"), league=league, match=row.get("label"), label=label, spec=spec,
                        ticker=k["ticker"], side=k["side"], bid=bid, ask=ask, cost=round(cost, 4),
                        fair=round(fair, 4), edge=round(fair / cost - 1, 4), start=m.get("start")))
    return out


def record(slot_rows, KB, now=None, path=None):
    """Archive each candidate the first time it is seen, before its start."""
    import freshness
    now = now or dt.datetime.now(dt.timezone.utc)
    book = load(path)
    found = []
    for lg, rows in (slot_rows or {}).items():
        for r in rows or []:
            st = freshness.parse((r.get("mkt") or {}).get("start"))
            if st is None or st <= now or not freshness.can_call(r, now):
                continue
            for c in candidates(lg, r, KB):
                found.append(c)
                key = f'{c["ticker"]}|{c["side"]}'
                if key not in book["bids"]:
                    book["bids"][key] = dict(c, posted=now.isoformat(timespec="seconds"), status="open",
                                             queue=queue_ahead(c["ticker"], c["side"], c["bid"]))
    save(book, path)
    found.sort(key=lambda x: -x["edge"])
    return found


def queue_ahead(ticker, side, bid, api=None):
    """Contracts already resting at `bid` on our side when we would post --
    a new bid waits behind all of them. None if the book cannot be read.
    (2026-10-24: an NFL total had 116,883 contracts at its best bid.)"""
    import kalshi
    d = _get(f'{api or kalshi.API}/markets/{ticker}/orderbook?depth=10', tries=1)
    book = (d or {}).get("orderbook_fp") or (d or {}).get("orderbook")
    if book is None:
        return None
    for px, qty in book.get("yes_dollars" if side == "YES" else "no_dollars") or []:
        try:
            if abs(float(px) - bid) < 1e-9:
                return float(qty)
        except (TypeError, ValueError):
            continue
    return 0.0


def _get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except Exception:
            time.sleep(1.5 * (i + 1))
    return None


def _ts(iso):
    import freshness
    t = freshness.parse(iso)
    return int(t.timestamp()) if t else None


def fill(trades, side, bid, queue=None):
    """How a resting bid at `bid` on `side` would have filled:

    'strict'  a trade went through the bid: filled whatever the queue
    'queue'   trades AT the bid added up to more than the queue that was
              ahead of it when posted: filled, in time priority
    'touch'   trades printed at the bid, but not enough (or the queue was
              never read) to be sure ours was reached
    None      nothing traded at or through the bid"""
    best, at = None, 0.0
    for t in trades:
        try:
            if side == "YES" and t.get("taker_side") == "no":
                px = float(t["yes_price_dollars"])
            elif side == "NO" and t.get("taker_side") == "yes":
                px = float(t["no_price_dollars"])
            else:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        if px < bid - 1e-9:
            return "strict"
        if abs(px - bid) < 1e-9:
            best = "touch"
            try:
                at += float(t.get("count_fp") or t.get("count") or 0)
            except (TypeError, ValueError):
                pass
    if best and queue is not None and at > queue:
        return "queue"
    return best


def grade(now=None, path=None, api=None, limit=60):
    """Settle bids whose market has a result: fill from the trade tape
    between posting and the start, outcome from Kalshi's settlement."""
    import kalshi
    api = api or kalshi.API
    now = now or dt.datetime.now(dt.timezone.utc)
    book = load(path)
    done = 0
    for key, b in book["bids"].items():
        if b.get("status") != "open" or done >= limit:
            continue
        st = _ts(b.get("start"))
        if st is None or st > now.timestamp():
            continue
        m = (_get(f'{api}/markets/{b["ticker"]}') or {}).get("market") or {}
        res = m.get("result")
        if res not in ("yes", "no"):
            if m.get("status") in ("settled", "finalized") or (now.timestamp() - st > 7 * 86400):
                b["status"] = "void"
            continue
        trades, cursor = [], ""
        for _ in range(10):
            d = _get(f'{api}/markets/trades?ticker={b["ticker"]}&min_ts={_ts(b["posted"])}&max_ts={st}&limit=1000'
                     + (f"&cursor={cursor}" if cursor else ""))
            if d is None:
                break
            trades += d.get("trades") or []
            cursor = d.get("cursor") or ""
            if not cursor:
                break
            time.sleep(0.3)
        b["fill"] = fill(trades, b["side"], b["bid"], b.get("queue"))
        b["won"] = int((res == "yes") == (b["side"] == "YES"))
        b["status"] = "graded"
        done += 1
        time.sleep(0.3)
    if done:
        save(book, path)
    return book


def report(path=None):
    bs = [b for b in load(path)["bids"].values() if b.get("status") == "graded"]
    out = dict(posted=len(load(path)["bids"]), graded=len(bs))
    if not bs:
        return out
    out["fill_strict"] = round(100 * sum(b["fill"] == "strict" for b in bs) / len(bs), 1)
    out["fill_any"] = round(100 * sum(b["fill"] in ("strict", "queue", "touch") for b in bs) / len(bs), 1)
    # 'realistic': only fills that are certain (through the bid) or that the
    # volume at the bid proves reached us past the queue (from 2026-10-24)
    out["fill_realistic"] = round(100 * sum(b["fill"] in ("strict", "queue") for b in bs) / len(bs), 1)
    for name, ok in (("strict", ("strict",)), ("realistic", ("strict", "queue")),
                     ("any", ("strict", "queue", "touch"))):
        f = [b for b in bs if b["fill"] in ok]
        if f:
            ret = [(b["won"] - b["cost"]) / b["cost"] for b in f]
            out[name] = dict(n=len(f), won=sum(b["won"] for b in f), roi=round(100 * sum(ret) / len(f), 2),
                             est=round(100 * sum(b["edge"] for b in f) / len(f), 2))
    unf = [b for b in bs if not b["fill"]]
    if unf:
        # what the bids that never filled would have done: adverse selection shows here
        out["unfilled_won"] = round(100 * sum(b["won"] for b in unf) / len(unf), 1)
        out["unfilled_n"] = len(unf)
    return out
