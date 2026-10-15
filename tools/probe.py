"""Feed probe, run on GitHub's runners. Round 9: Kalshi settled markets by
event, their results, and where pre-game prices live."""
import json
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
K = "https://api.elections.kalshi.com/trade-api/v2"


def get(url):
    time.sleep(0.4)                        # stay well under the rate limit
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code} {e.read()[:150]!r}"}
    except Exception as e:
        return {"_error": str(e)}


for ser, ev in (("KXNHLTOTAL", "KXNHLTOTAL-26OCT14DALCOL"), ("KXNFLSPREAD", "KXNFLSPREAD-26OCT12BUFLAR")):
    d = get(f"{K}/markets?event_ticker={ev}&limit=50")
    ms = d.get("markets") or []
    print(f"\n== {ev}: markets={len(ms)} {d.get('_error','')}")
    if not ms:
        d = get(f"{K}/markets?event_ticker={ev}&status=settled&limit=50")
        ms = d.get("markets") or []
        print("   with status=settled:", len(ms), d.get("_error", ""))
    if not ms:
        continue
    m = ms[len(ms) // 2]
    print("   market:", {k: v for k, v in m.items() if any(w in k for w in
          ("ticker", "result", "time", "status", "strike", "settle", "yes_sub", "last_price", "ask", "bid"))})
    t = m["ticker"]
    close = m.get("close_time") or m.get("expiration_time")
    try:
        end = int(time.mktime(time.strptime(close[:19], "%Y-%m-%dT%H:%M:%S")))
    except Exception:
        end = int(time.time())
    for path in (f"/series/{ser}/markets/{t}/candlesticks?start_ts={end-86400}&end_ts={end}&period_interval=60",
                 f"/historical/markets/{t}/candlesticks?start_ts={end-86400}&end_ts={end}&period_interval=60",
                 f"/markets/trades?ticker={t}&limit=5&max_ts={end}",
                 f"/historical/trades?ticker={t}&limit=5",
                 f"/historical/markets/{t}"):
        r = get(K + path)
        print("  ", path.split("?")[0], "->", json.dumps(r)[:900])
