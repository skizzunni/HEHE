"""Feed probe, run on GitHub's runners. Round 7: which fields hold Kalshi's
prices on a live game market."""
import json
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
K = "https://api.elections.kalshi.com/trade-api/v2"


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return json.load(r)
    except Exception as e:
        return {"_error": str(e)}


for ser in ("KXNHLTOTAL", "KXNFLSPREAD", "KXNBAGAME"):
    e = get(f"{K}/events?series_ticker={ser}&status=open&with_nested_markets=true&limit=1")
    for ev in e.get("events") or []:
        m = (ev.get("markets") or [{}])[0]
        print(ser, "nested market price-ish fields:",
              {k: v for k, v in m.items() if any(w in k for w in ("ask", "bid", "price", "last", "volume"))})
        one = get(f"{K}/markets/{m.get('ticker')}")
        mm = one.get("market") or {}
        print(ser, "single market price-ish fields:",
              {k: v for k, v in mm.items() if any(w in k for w in ("ask", "bid", "price", "last", "volume"))})
        ob = get(f"{K}/markets/{m.get('ticker')}/orderbook")
        print(ser, "orderbook:", json.dumps(ob)[:300])
