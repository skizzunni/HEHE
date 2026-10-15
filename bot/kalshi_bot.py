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

  BUY   a Kalshi-ready stack only if the best market-maker quote on the
        combo, after Kalshi's fee, pays at least (1 + MIN_EDGE) times the
        board's fair payout. Paying less than fair is a losing bet by the
        board's own, backtested numbers. Combos are priced by request for
        quote (one per ticket per day); quotes not taken are withdrawn. The
        first live quote trade is checked against Kalshi's positions and
        buying halts if it is not a YES holding.
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
STATUS_FILE = os.path.join(ROOT, "bot_status.json")              # the page's Bot tab
HISTORY = os.path.join(ROOT, ".cache", "bot_history.json")       # practice tickets
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
# Every order the bot places carries this client_order_id prefix. Spending,
# holdings, cash-outs and the record only ever look at orders with it, so the
# bot never counts -- or sells -- anything the account holder placed by hand.
BOT_TAG = "hehebot-"
# Combos have no standing order book: every one is a fresh market, and the
# price comes from a request for quote (RFQ) answered by market makers, the
# way the Kalshi app builds combos. Quote fills carry no client_order_id, so
# the bot records each quote trade here (committed to the repo -- the one
# record of them that cannot be lost with the Actions cache).
BOT_LEDGER = os.path.join(ROOT, "bot_trades.json")
RFQ_DIR = os.path.join(ROOT, ".cache", "bot_rfqs.json")          # one RFQ per ticket per day
RFQ_WAIT = 6.0             # seconds to collect quotes; makers answer in well under one


STATUS = dict(mode="live" if LIVE else "practice", ok=False, lines=[], considered=[],
              open=[], record=[], practice=[])


def log(*a):
    line = " ".join(str(x) for x in a)
    print("[kalshi-bot]" + ("" if LIVE else "[practice]"), line, flush=True)
    STATUS["lines"].append(line)


def money(obj, name):
    """A Kalshi money field in dollars: `<name>_dollars` if present, else the
    integer-cents field (a string with a decimal point is already dollars)."""
    v = obj.get(name + "_dollars")
    if v is not None:
        return float(v)
    v = obj.get(name)
    if v is None or v == "":
        return 0.0
    if isinstance(v, str) and "." in v:
        return float(v)
    return float(v) / 100


def count_of(obj):
    return float(obj.get("count_fp") or obj.get("count") or 0)


def load_history():
    try:
        with open(HISTORY) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def save_history(h):
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    with open(HISTORY, "w") as fh:
        json.dump(h[-500:], fh)


def write_status():
    STATUS["updated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    STATUS["lines"] = STATUS["lines"][-80:]
    with open(STATUS_FILE, "w") as fh:
        json.dump(STATUS, fh, indent=1)


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


def bot_orders(pages=10):
    """Every order this bot placed, newest first, from Kalshi's order list."""
    out, cursor = [], ""
    for _ in range(pages):
        st, d = api("GET", "/portfolio/orders?limit=200" + (f"&cursor={cursor}" if cursor else ""))
        if st != 200:
            raise RuntimeError(f"could not read the order list (HTTP {st}); "
                               "not trading blind")
        out += [o for o in (d or {}).get("orders") or []
                if str(o.get("client_order_id") or "").startswith(BOT_TAG)]
        cursor = (d or {}).get("cursor")
        if not cursor:
            break
    return out


def order_cost(o):
    """Dollars an order actually spent (filled part only, fees included)."""
    c = money(o, "taker_fill_cost") + money(o, "maker_fill_cost")
    if not c:
        side = "yes" if o.get("side") == "yes" else "no"
        filled = float(o.get("fill_count_fp") or o.get("fill_count") or 0)
        c = filled * money(o, f"{side}_price")
    return c + money(o, "taker_fees") + money(o, "maker_fees")


def quote_spend_today():
    today = STATUS["started"][:10]
    return sum(x["cost"] for x in trades["trades"] if x["ts"][:10] == today)


def spent_today(orders):
    """Dollars the BOT spent on buys today (UTC), from Kalshi's records."""
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    return sum(order_cost(o) for o in orders
               if o.get("action") == "buy" and str(o.get("created_time") or "")[:10] == today)


def taker_fee(count, price):
    """Kalshi's taker fee in dollars: 7% of count x P x (1-P), rounded up to a cent."""
    import math
    return math.ceil(round(7 * count * price * (1 - price), 6)) / 100


def load_json(path, default):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=1)


class Blocked(Exception):
    """Kalshi refused trading from where this runs (a location rule)."""


def where_am_i():
    """City/region of the machine the bot runs on, for the location error."""
    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=10) as r:
            d = json.load(r)
        return ", ".join(x for x in (d.get("city"), d.get("region"), d.get("country")) if x)
    except Exception:
        return "unknown"


def request_quote(combo, count):
    """Ask market makers for a price on `count` YES contracts of `combo`.
    Returns (rfq_id, best) where best is the cheapest YES offer:
    {quote, price}. Buying YES takes the maker's NO bid, so the YES price is
    1 - no_bid (Kalshi FIX spec: "BUY accepts the maker's NO quote")."""
    st, d = api("POST", "/communications/rfqs",
                dict(market_ticker=combo, contracts=int(count), rest_remainder=False))
    rid = (d or {}).get("id")
    code = str(((d or {}).get("error") or {}).get("code") or "")
    if st == 403 and "not_currently_allowed" in code.lower():
        raise Blocked(code.replace("_", " "))
    if st not in (200, 201) or not rid:
        log(f"{combo}: quote request refused ({st}) {json.dumps(d)[:160]}")
        return None, None
    best = None
    end = time.time() + RFQ_WAIT
    while time.time() < end:
        time.sleep(1)
        st, q = api("GET", f"/communications/quotes?rfq_id={rid}")
        for x in (q or {}).get("quotes") or []:
            if x.get("status") != "open":
                continue
            no_bid = money(x, "no_bid")
            if not 0 < no_bid < 1:
                continue                         # maker declined to sell YES
            price = round(1 - no_bid, 4)
            if best is None or price < best["price"]:
                best = dict(quote=x, price=price)
    return rid, best


def close_rfq(rid):
    if rid:
        api("DELETE", f"/communications/rfqs/{rid}")


def accept_quote(rid, quote):
    """Accept the YES side and wait for the maker's confirmation (combos have
    a 3-second window) and execution. Returns the final quote status."""
    qid = quote["id"]
    st, d = api("PUT", f"/communications/rfqs/{rid}/quotes/{qid}/accept",
                dict(accepted_side="yes"))
    if st not in (200, 204):
        log(f"  accept refused ({st}) {json.dumps(d)[:160]}")
        return "refused"
    status = "accepted"
    end = time.time() + 10
    while time.time() < end:
        time.sleep(1)
        st, d = api("GET", f"/communications/quotes/{qid}")
        status = ((d or {}).get("quote") or d or {}).get("status") or status
        if status in ("executed", "cancelled"):
            break
    return status


# -------------------------------------------------------------------- buy
trades = {"trades": []}      # bot_trades.json, loaded in run()
asked = {}                   # combo -> UTC date of the last quote request


def buy_tickets(board, sports, budget_left, open_n, held, history):
    """`held` is every combo ticker already owned (live) or already taken in
    practice, so the same ticket is never bought twice."""
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
    if LIVE and trades.get("halted"):
        log("buying halted:", trades["halted"])
        return
    for t in tickets:
        if open_n >= MAX_OPEN:
            log("open-position limit reached")
            return
        if budget_left < 1:
            log("daily limit reached")
            return
        labels = [f'{L["label"]} ({L["match"]})' for L in t["legs"]]
        seen = dict(n=t["n"], legs=labels, fair=round(t["fair"], 2), verdict="")
        STATUS["considered"].append(seen)
        legs = [L["kalshi"] for L in t["legs"]]
        coll = collection_for({k["event"] for k in legs})
        if not coll:
            log("no combo collection covers", t["n"], "legs; skipped")
            seen["verdict"] = "Kalshi offers no combo for these games"
            continue
        sel = [dict(event_ticker=k["event"], market_ticker=k["ticker"], side=k["side"].lower())
               for k in legs]
        st, d = api("POST", f"/multivariate_event_collections/{coll}", dict(selected_markets=sel))
        combo = (d or {}).get("market_ticker")
        if st not in (200, 201) or not combo:
            log("could not create combo market:", st, json.dumps(d)[:200])
            seen["verdict"] = "Kalshi refused the combo"
            continue
        seen["ticker"] = combo
        if combo in held:
            seen["verdict"] = "already holding it"
            continue
        fair = t["fair"]                           # payout multiple at the board's odds
        stake = min(MAX_STAKE, budget_left)
        # size the request for a price at fair; nothing is bought above fair
        # less the margin, so the real cost is always below the stake
        count = int(stake * fair)
        if count < 1:
            seen["verdict"] = "stake too small for one contract"
            continue
        today = STATUS["started"][:10]
        if asked.get(combo) == today:
            seen["verdict"] = "already asked for a quote today"
            continue
        asked[combo] = today
        try:
            rid, best = request_quote(combo, count)
        except Blocked as e:
            place = where_am_i()
            msg = (f"Kalshi refused trading from this server's location ({place}): {e}. "
                   "Kalshi checks where the bot runs, not only where the account is.")
            log(msg)
            STATUS["error"] = msg
            seen["verdict"] = "blocked by Kalshi's location rule"
            return
        if not best:
            close_rfq(rid)
            log(f"{combo}: no market maker offered YES")
            seen["verdict"] = "no market maker quoted it"
            continue
        price = best["price"]
        cost = count * price + taker_fee(count, price)
        pays = count / cost                        # payout multiple after the fee
        seen.update(ask=price, pays=round(pays, 2), count=count)
        log(f"{combo}: {t['n']} legs, quote {count} @ ${price:.2f} (+fee) pays {pays:.2f}x, "
            f"fair {fair:.2f}x")
        if pays < fair * (1 + MIN_EDGE):
            close_rfq(rid)
            log("  pays less than fair + margin; not buying")
            seen["verdict"] = f"Kalshi pays {pays:.2f}x, needs {fair * (1 + MIN_EDGE):.2f}x+"
            continue
        if cost > budget_left + 1e-9 or cost > STATUS.get("balance", 0) + (0 if LIVE else 1e9):
            close_rfq(rid)
            seen["verdict"] = f"costs ${cost:.2f}, over today's limit or balance"
            continue
        if not LIVE:
            close_rfq(rid)
            log(f"  WOULD BUY {count} @ ${price:.2f}")
            seen["verdict"] = f"practice buy: {count} @ ${price:.2f}"
            history.append(dict(ts=STATUS["started"], ticker=combo, n=t["n"], legs=labels,
                                count=count, ask=round(cost / count, 4), fair=round(fair, 2),
                                result=None))
            held.add(combo)
            budget_left -= cost
            open_n += 1
            continue
        status = accept_quote(rid, best["quote"])
        close_rfq(rid)
        log(f"  ACCEPT {count} @ ${price:.2f}: {status}")
        if status == "executed":
            seen["verdict"] = f"BOUGHT {count} @ ${price:.2f}"
            trades["trades"].append(dict(ts=STATUS["started"], ticker=combo, n=t["n"],
                                         legs=labels, count=count, price=price,
                                         cost=round(cost, 2), fair=round(fair, 2),
                                         rfq_id=rid, quote_id=best["quote"]["id"]))
            save_json(BOT_LEDGER, trades)
            held.add(combo)
            budget_left -= cost
            open_n += 1
            if not trades.get("verified"):
                verify_first_trade(combo)
                return                             # one trade until the side is verified
        else:
            seen["verdict"] = f"quote not filled ({status})"


def verify_first_trade(combo):
    """The first live quote trade is checked against Kalshi's positions: it
    must be a YES holding. If it is anything else, buying halts for good
    until a person looks (delete "halted" from bot_trades.json)."""
    st, pos = api("GET", f"/portfolio/positions?ticker={combo}&count_filter=position")
    p = next((x for x in (pos or {}).get("market_positions") or []
              if (x.get("ticker") or x.get("market_ticker")) == combo), None)
    n = float((p or {}).get("position_fp") or (p or {}).get("position") or 0)
    if n > 0:
        trades["verified"] = STATUS["started"]
        log(f"  first quote trade verified: holding {n:g} YES")
    else:
        trades["halted"] = f"first quote trade on {combo} did not show as a YES holding ({n:g})"
        log("  " + trades["halted"] + " -- buying halted")
        STATUS["error"] = trades["halted"]
    save_json(BOT_LEDGER, trades)


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
        STATUS["open"].append(dict(ticker=tk, title=m.get("title") or m.get("subtitle") or "",
                                   count=n, fair=round(fair, 2), bid=bid,
                                   legs=len(legs), won=sum(1 for v in vals if v == 1.0)))
        if not bid or bid < fair * (1 + SELL_EDGE):
            continue
        order = dict(ticker=tk, action="sell", side="yes", count=int(n), type="limit",
                     yes_price=int(round(bid * 100)), time_in_force="immediate_or_cancel",
                     client_order_id=BOT_TAG + str(uuid.uuid4()))
        if not LIVE:
            log("  WOULD SELL (bid beats fair value)", json.dumps(order))
            continue
        st, d = api("POST", "/portfolio/orders", order)
        log("  SELL", st, json.dumps(d)[:300])


# ---------------------------------------------------------------- record
def is_combo(ticker):
    return "MVE" in (ticker or "")


def live_record(mine):
    """Every combo the bot has traded, from Kalshi's own fills and
    settlements: what it cost, what came back, and the profit."""
    rec = {}
    st, d = api("GET", "/portfolio/fills?limit=200")
    for f in (d or {}).get("fills") or []:
        tk = f.get("ticker") or f.get("market_ticker")
        if tk not in mine:
            continue
        r = rec.setdefault(tk, dict(ticker=tk, bought=0.0, cost=0.0, sold=0.0,
                                    proceeds=0.0, payout=0.0, status="open",
                                    first=f.get("created_time")))
        side = "yes" if f.get("side") == "yes" else "no"
        amt = count_of(f) * money(f, f"{side}_price")
        fee = money(f, "fee_cost")
        if f.get("action") == "buy":
            r["bought"] += count_of(f)
            r["cost"] += amt + fee
        else:
            r["sold"] += count_of(f)
            r["proceeds"] += amt - fee
        r["first"] = min(filter(None, [r["first"], f.get("created_time")]), default=None)
    st, d = api("GET", "/portfolio/settlements?limit=200")
    for x in (d or {}).get("settlements") or []:
        tk = x.get("ticker") or x.get("market_ticker")
        if tk in rec:
            rec[tk]["payout"] = money(x, "revenue")
            rec[tk]["result"] = x.get("market_result")
            rec[tk]["status"] = "won" if rec[tk]["payout"] > 0 else "lost"
    for r in rec.values():
        if r["status"] == "open" and r["bought"] and r["sold"] >= r["bought"]:
            r["status"] = "cashed out"
        r["profit"] = round(r["proceeds"] + r["payout"] - r["cost"], 2) \
            if r["status"] != "open" else None
        for k in ("cost", "proceeds", "payout"):
            r[k] = round(r[k], 2)
    out = sorted(rec.values(), key=lambda r: r.get("first") or "", reverse=True)
    return out


def grade_practice(history, budget=25):
    """Settle practice tickets against Kalshi's result for the same combo."""
    for h in history:
        if h.get("result") or budget <= 0:
            continue
        budget -= 1
        st, d = api("GET", f"/markets/{h['ticker']}", auth=False)
        m = (d or {}).get("market") or {}
        if m.get("result") in ("yes", "no"):
            h["result"] = "won" if m["result"] == "yes" else "lost"
            h["profit"] = round(h["count"] * ((1 if h["result"] == "won" else 0) - h["ask"]), 2)


def summary(rows):
    done = [r for r in rows if r.get("profit") is not None]
    return dict(tickets=len(rows), settled=len(done),
                won=sum(1 for r in done if r["profit"] > 0),
                profit=round(sum(r["profit"] for r in done), 2),
                staked=round(sum(r.get("cost", r.get("count", 0) * r.get("ask", 0))
                                 for r in done), 2))


# ------------------------------------------------------------------- main
def main():
    if not KEY_ID or not KEY_PEM.strip():
        print("[kalshi-bot] no KALSHI_KEY_ID / KALSHI_PRIVATE_KEY secret set; bot is off")
        return 0
    STATUS["started"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    STATUS["limits"] = dict(stake=MAX_STAKE, daily=MAX_DAILY, open=MAX_OPEN,
                            min_edge=MIN_EDGE, sell_edge=SELL_EDGE)
    try:
        return run()
    except Exception as e:
        log("stopped on an error:", type(e).__name__, str(e)[:200])
        STATUS["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        return 1
    finally:
        write_status()


def run():
    st, bal = api("GET", "/portfolio/balance")
    if st != 200:
        log("authentication failed:", st, json.dumps(bal)[:200], "-- nothing else attempted")
        STATUS["error"] = f"Kalshi refused the key (HTTP {st}). Check the key is RSA " \
                          "and the whole private key, BEGIN to END, is in the secret."
        return 1
    STATUS["ok"] = True
    STATUS["balance"] = money(bal or {}, "balance")
    if (bal or {}).get("portfolio_value") is not None or (bal or {}).get("portfolio_value_dollars"):
        STATUS["portfolio_value"] = money(bal, "portfolio_value")
    log(f"connected; balance ${STATUS['balance']:.2f}; "
        f"limits ${MAX_STAKE:.2f}/ticket, ${MAX_DAILY:.2f}/day, {MAX_OPEN} open")
    st, pos = api("GET", "/portfolio/positions?limit=200&count_filter=position")
    positions = (pos or {}).get("market_positions") or []
    trades.clear()
    trades.update(load_json(BOT_LEDGER, {"trades": []}))
    trades.setdefault("trades", [])
    asked.clear()
    asked.update(load_json(RFQ_DIR, {}))
    orders = bot_orders()
    mine = {o.get("ticker") for o in orders if o.get("action") == "buy"} \
        | {x["ticker"] for x in trades["trades"]}
    positions = [p for p in positions if (p.get("ticker") or p.get("market_ticker")) in mine]
    held = {p.get("ticker") or p.get("market_ticker") for p in positions
            if float(p.get("position_fp") or p.get("position") or 0) > 0}
    cash_out(positions)
    STATUS["record"] = live_record(mine)
    STATUS["record_summary"] = summary(STATUS["record"])

    history = load_history()
    grade_practice(history)
    today = STATUS["started"][:10]
    if LIVE:
        # never plan to spend cash the account does not have
        left = min(MAX_DAILY - spent_today(orders) - quote_spend_today(), STATUS["balance"])
        open_n = len(held)
    else:
        # practice keeps its own books so it obeys the same limits
        left = MAX_DAILY - sum(h["count"] * h["ask"] for h in history if h["ts"][:10] == today)
        open_n = sum(1 for h in history if not h.get("result"))
        held |= {h["ticker"] for h in history}
    STATUS["spent_today"] = round(MAX_DAILY - left, 2)
    try:
        with open(STATE) as fh:
            board = json.load(fh)
    except (OSError, ValueError):
        log("no board snapshot; buying skipped")
        board = None
    if board:
        buy_tickets(board, allowed_sports(), left, open_n, held, history)
    save_history(history)
    today = STATUS["started"][:10]
    save_json(RFQ_DIR, {k: v for k, v in asked.items() if v == today})
    if trades.get("halted"):
        STATUS["error"] = trades["halted"]
    if not LIVE:
        STATUS["spent_today"] = round(sum(h["count"] * h["ask"] for h in history
                                          if h["ts"][:10] == today), 2)
    elif board:
        STATUS["spent_today"] = round(spent_today(bot_orders()) + quote_spend_today(), 2)
    STATUS["practice"] = list(reversed(history[-100:]))
    STATUS["practice_summary"] = summary(history)
    return 0


if __name__ == "__main__":
    sys.exit(main())
