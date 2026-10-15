"""Kalshi bot: buys the board's Kalshi-ready stacks when Kalshi pays more than
fair, and cashes positions out when someone bids more than they are worth.

    python3 bot/kalshi_bot.py            # runs after each board rebuild

SAFETY, in order of precedence

  1. No key, no bot. Without KALSHI_KEY_ID and KALSHI_PRIVATE_KEY (GitHub
     repository secrets) it prints one line and exits.
  2. PRACTICE MODE unless KALSHI_LIVE is exactly "yes". In practice mode it
     authenticates, reads the account, creates combo markets to see their
     price, and logs every order it WOULD place -- and places none.
  3. Hard limits, checked against Kalshi's own records each run (not a local
     file that could be lost): stake per ticket, total spend per day, open
     combo positions.
  4. Only sports whose tickets met their promise in the backtest
     (data/backtest_stacks.json) -- NFL and NBA tickets fell short, so they
     are excluded until that changes.
  5. Orders are immediate-or-cancel limit orders with a maximum cost, so
     nothing rests on the book and nothing fills above the checked price.

THE RULES

  BUY   a Kalshi-ready stack only if Kalshi's ask on the combo pays at least
        (1 + MIN_EDGE) times the board's fair payout. Paying less than fair
        is a losing bet by the board's own, backtested numbers.
  SELL  a combo position when the best bid is at least (1 + SELL_EDGE) times
        what it is fairly worth now: legs already won count as 1, legs
        already lost as 0, open legs at Kalshi's own mid price. Selling for
        more than something is worth is the only cash-out rule that does not
        depend on guessing the outcome.

Nothing here guarantees a profit. It enforces "only at a better than fair
price", which is the most the data supports.
"""
import base64
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE = os.path.join(ROOT, ".cache", "last_board.json")
BACKTEST = os.path.join(ROOT, "data", "backtest_stacks.json")
HOST = "https://api.elections.kalshi.com"
PREFIX = "/trade-api/v2"

KEY_ID = os.environ.get("KALSHI_KEY_ID", "").strip()
KEY_PEM = os.environ.get("KALSHI_PRIVATE_KEY", "")
LIVE = os.environ.get("KALSHI_LIVE", "").strip().lower() == "yes"
MAX_STAKE = float(os.environ.get("KALSHI_MAX_STAKE", "2"))       # dollars per ticket
MAX_DAILY = float(os.environ.get("KALSHI_MAX_DAILY", "10"))      # dollars per day
MAX_OPEN = int(os.environ.get("KALSHI_MAX_OPEN", "5"))           # open combo positions
MIN_EDGE = float(os.environ.get("KALSHI_MIN_EDGE", "0.05"))      # buy only 5%+ over fair
SELL_EDGE = float(os.environ.get("KALSHI_SELL_EDGE", "0.05"))    # sell only 5%+ over fair
LEG_RANGE = (2, 6)                                                # ticket sizes it buys


def log(*a):
    print("[kalshi-bot]" + ("" if LIVE else "[practice]"), *a, flush=True)


# ------------------------------------------------------------------ signing
_key = None


def _private_key():
    global _key
    if _key is None:
        from cryptography.hazmat.primitives import serialization
        pem = KEY_PEM.replace("\\n", "\n").encode()
        _key = serialization.load_pem_private_key(pem, password=None)
    return _key


def _sign(ts, method, path):
    """RSA-PSS SHA-256 over timestamp + METHOD + path (no host, no query)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    msg = f"{ts}{method}{path.split('?')[0]}".encode()
    sig = _private_key().sign(msg, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                               salt_length=padding.PSS.DIGEST_LENGTH),
                              hashes.SHA256())
    return base64.b64encode(sig).decode()


def api(method, path, body=None, auth=True):
    """Kalshi request. Returns (status, json-or-None)."""
    full = PREFIX + path
    headers = {"Accept": "application/json", "User-Agent": "hehe-board-bot"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if auth:
        ts = str(int(time.time() * 1000))
        headers.update({"KALSHI-ACCESS-KEY": KEY_ID, "KALSHI-ACCESS-TIMESTAMP": ts,
                        "KALSHI-ACCESS-SIGNATURE": _sign(ts, method, full)})
    req = urllib.request.Request(HOST + full, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except ValueError:
            return e.code, None
    except Exception as e:
        log("request failed:", method, path, type(e).__name__)
        return None, None


# ---------------------------------------------------------------- helpers
def dollars(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v / 100 if v > 1.0001 else v


def best_yes_ask(book):
    """YES ask = 1 - best NO bid, from an orderbook response."""
    ob = (book or {}).get("orderbook_fp") or (book or {}).get("orderbook") or {}
    no = ob.get("no_dollars") or ob.get("no") or []
    prices = [dollars(p) for p, *_ in no if dollars(p)]
    return round(1 - max(prices), 4) if prices else None


def best_yes_bid(book):
    ob = (book or {}).get("orderbook_fp") or (book or {}).get("orderbook") or {}
    yes = ob.get("yes_dollars") or ob.get("yes") or []
    prices = [dollars(p) for p, *_ in yes if dollars(p)]
    return max(prices) if prices else None


def allowed_sports():
    """Sports whose backtested tickets won at least as often as promised."""
    try:
        with open(BACKTEST) as fh:
            bt = json.load(fh)
    except (OSError, ValueError):
        return set()
    ok = set()
    for k, v in (bt.get("sports") or {}).items():
        tk = v.get("tickets") or []
        won = sum(t["won"] for t in tk)
        exp = sum(t["expected"] for t in tk)
        if exp >= 20 and won >= exp:
            ok.add(k)
    return ok


def collection_for(events):
    """A combo collection whose events include every leg's event."""
    st, d = api("GET", "/multivariate_event_collections?status=open&limit=200", auth=False)
    for c in (d or {}).get("multivariate_contracts") or []:
        t = c.get("collection_ticker")
        st2, det = api("GET", f"/multivariate_event_collections/{t}", auth=False)
        assoc = set(((det or {}).get("multivariate_contract") or {}).get("associated_event_tickers") or [])
        if set(events) <= assoc:
            return t
    return None


def spent_today():
    """Dollars spent on buys today, from Kalshi's own fill records."""
    start = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    st, d = api("GET", f"/portfolio/fills?min_ts={int(start.timestamp())}&limit=200")
    total = 0.0
    for f in (d or {}).get("fills") or []:
        if f.get("action") != "buy":
            continue
        n = float(f.get("count_fp") or f.get("count") or 0)
        p = dollars(f.get("yes_price_dollars") if f.get("side") == "yes" else f.get("no_price_dollars")) \
            or dollars(f.get("yes_price") if f.get("side") == "yes" else f.get("no_price")) or 0
        total += n * p
    return total


# -------------------------------------------------------------------- buy
def buy_tickets(board, sports, budget_left, open_n):
    ks = ((board.get("kalshi_stacks") or {}).get("today") or {}).get("tickets") or {}
    tickets = [t for n, ts in ks.items() for t in ts]
    tickets = [t for t in tickets
               if LEG_RANGE[0] <= t["n"] <= LEG_RANGE[1]
               and t.get("kalshi_n") == t["n"]
               and all(L["league"] in sports or (L["league"] not in ("nfl", "nba", "ncaaf", "ncaab",
                                                                      "nhl", "wnba", "mlb")
                                                 and "soccer" in sports)
                       for L in t["legs"])]
    log(f"{len(tickets)} Kalshi-ready tickets in allowed sports ({', '.join(sorted(sports)) or 'none'})")
    for t in tickets:
        if open_n >= MAX_OPEN:
            log("open-position limit reached")
            return
        if budget_left < 1:
            log("daily limit reached")
            return
        legs = [L["kalshi"] for L in t["legs"]]
        coll = collection_for({k["event"] for k in legs})
        if not coll:
            log("no combo collection covers", t["n"], "legs; skipped")
            continue
        sel = [dict(event_ticker=k["event"], market_ticker=k["ticker"], side=k["side"].lower())
               for k in legs]
        st, d = api("POST", f"/multivariate_event_collections/{coll}", dict(selected_markets=sel))
        combo = (d or {}).get("market_ticker")
        if st not in (200, 201) or not combo:
            log("could not create combo market:", st, json.dumps(d)[:200])
            continue
        st, book = api("GET", f"/markets/{combo}/orderbook", auth=False)
        ask = best_yes_ask(book)
        fair = t["fair"]                           # payout multiple at the board's odds
        if not ask:
            log(f"{combo}: no ask on the book (Kalshi may need a quote request); skipped")
            continue
        pays = 1 / ask
        log(f"{combo}: {t['n']} legs, ask {ask:.2f} pays {pays:.2f}x, fair {fair:.2f}x")
        if pays < fair * (1 + MIN_EDGE):
            log("  pays less than fair + margin; not buying")
            continue
        stake = min(MAX_STAKE, budget_left)
        count = int(stake // ask)
        if count < 1:
            continue
        order = dict(ticker=combo, action="buy", side="yes", count=count, type="limit",
                     yes_price=int(round(ask * 100)), time_in_force="immediate_or_cancel",
                     buy_max_cost=int(round(stake * 100)), client_order_id=str(uuid.uuid4()))
        if not LIVE:
            log("  WOULD BUY", json.dumps(order))
            continue
        st, d = api("POST", "/portfolio/orders", order)
        log("  BUY", st, json.dumps(d)[:300])
        if st in (200, 201):
            budget_left -= count * ask
            open_n += 1


# ------------------------------------------------------------------- sell
def leg_value(leg):
    """Fair value of one combo leg now: settled 1/0, else Kalshi's mid."""
    st, d = api("GET", f"/markets/{leg['market_ticker']}", auth=False)
    m = (d or {}).get("market") or {}
    side = (leg.get("side") or "yes").lower()
    if m.get("result") in ("yes", "no"):
        return 1.0 if m["result"] == side else 0.0
    bid, ask = dollars(m.get("yes_bid_dollars")), dollars(m.get("yes_ask_dollars"))
    if bid is None or ask is None or ask <= 0:
        return None
    mid = (bid + ask) / 2
    return mid if side == "yes" else 1 - mid


def cash_out(positions):
    for p in positions:
        tk = p.get("ticker") or p.get("market_ticker")
        n = float(p.get("position_fp") or p.get("position") or 0)
        if not tk or n <= 0:
            continue
        st, d = api("GET", f"/markets/{tk}", auth=False)
        m = (d or {}).get("market") or {}
        legs = m.get("mve_selected_legs") or []
        if not legs:
            continue                               # not a combo the bot understands
        vals = [leg_value(L) for L in legs]
        if any(v is None for v in vals):
            log(f"{tk}: a leg has no price; holding")
            continue
        fair = 1.0
        for v in vals:
            fair *= v
        st, book = api("GET", f"/markets/{tk}/orderbook", auth=False)
        bid = best_yes_bid(book)
        log(f"{tk}: {int(n)} held, fair now {fair:.2f}, best bid {bid}")
        if not bid or bid < fair * (1 + SELL_EDGE):
            continue
        order = dict(ticker=tk, action="sell", side="yes", count=int(n), type="limit",
                     yes_price=int(round(bid * 100)), time_in_force="immediate_or_cancel",
                     client_order_id=str(uuid.uuid4()))
        if not LIVE:
            log("  WOULD SELL (bid beats fair value)", json.dumps(order))
            continue
        st, d = api("POST", "/portfolio/orders", order)
        log("  SELL", st, json.dumps(d)[:300])


# ------------------------------------------------------------------- main
def main():
    if not KEY_ID or not KEY_PEM.strip():
        print("[kalshi-bot] no KALSHI_KEY_ID / KALSHI_PRIVATE_KEY secret set; bot is off")
        return 0
    st, bal = api("GET", "/portfolio/balance")
    if st != 200:
        log("authentication failed:", st, json.dumps(bal)[:200], "-- nothing else attempted")
        return 1
    log(f"connected; balance ${dollars((bal or {}).get('balance')) or 0:.2f}; "
        f"limits ${MAX_STAKE:.2f}/ticket, ${MAX_DAILY:.2f}/day, {MAX_OPEN} open")
    st, pos = api("GET", "/portfolio/positions?limit=200&count_filter=position")
    positions = (pos or {}).get("market_positions") or []
    combos_open = sum(1 for p in positions if "MVE" in (p.get("ticker") or "")
                      and float(p.get("position_fp") or p.get("position") or 0) > 0)
    cash_out(positions)
    try:
        with open(STATE) as fh:
            board = json.load(fh)
    except (OSError, ValueError):
        log("no board snapshot; buying skipped")
        return 0
    left = MAX_DAILY - spent_today()
    buy_tickets(board, allowed_sports(), left, combos_open)
    return 0


if __name__ == "__main__":
    sys.exit(main())
