"""Feed probe, run on GitHub's runners. Round 8: Kalshi history -- settled
game markets, their results, and pre-game prices (candlesticks / trades)."""
import json
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
K = "https://api.elections.kalshi.com/trade-api/v2"


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code} {e.read()[:150]!r}"}
    except Exception as e:
        return {"_error": str(e)}


for ser in ("KXNHLTOTAL", "KXNFLSPREAD", "KXNBAGAME", "KXEPLTOTAL"):
    e = get(f"{K}/events?series_ticker={ser}&status=settled&with_nested_markets=true&limit=200")
    evs = e.get("events") or []
    print(f"\n== {ser}: settled events={len(evs)} cursor={bool(e.get('cursor'))} {e.get('_error','')}")
    if evs:
        ev = evs[-1]
        print("  event keys:", sorted(ev.keys()))
        print("  event:", {k: ev.get(k) for k in ("event_ticker", "title", "sub_title", "strike_date")})
        m = (ev.get("markets") or [{}])[0]
        print("  market time/result fields:", {k: m.get(k) for k in m if any(w in k for w in
              ("time", "result", "settle", "expir", "open", "close", "status", "strike"))})
        t = m.get("ticker")
        ct = m.get("close_time") or m.get("expected_expiration_time")
        # candlesticks over the 2 days before close
        try:
            end = int(time.mktime(time.strptime(ct[:19], "%Y-%m-%dT%H:%M:%S"))) if ct else int(time.time())
        except Exception:
            end = int(time.time())
        for path in (f"/series/{ser}/markets/{t}/candlesticks?start_ts={end-172800}&end_ts={end}&period_interval=60",
                     f"/markets/{t}/candlesticks?start_ts={end-172800}&end_ts={end}&period_interval=60",
                     f"/markets/trades?ticker={t}&limit=5"):
            d = get(K + path)
            print("  ", path.split("?")[0], "->", json.dumps(d)[:700])
    # how far back does settled history go?
    oldest = None
    cur = e.get("cursor")
    pages = 1
    while cur and pages < 15:
        d = get(f"{K}/events?series_ticker={ser}&status=settled&limit=200&cursor={cur}")
        x = d.get("events") or []
        if x:
            oldest = x[-1].get("event_ticker")
        cur = d.get("cursor")
        pages += 1
    print("  pages", pages, "oldest seen", oldest or (evs[-1].get("event_ticker") if evs else None),
          "newest", evs[0].get("event_ticker") if evs else None)
