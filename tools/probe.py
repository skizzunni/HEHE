"""Feed probe, run on GitHub's runners (the dev sandbox cannot reach these).
Round 6: Kalshi sports markets and combos (multivariate collections), and
Polymarket sports markets."""
import json
import urllib.request
from collections import Counter

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/json"}
K = "https://api.elections.kalshi.com/trade-api/v2"


def get(url, data=None, method=None):
    try:
        req = urllib.request.Request(url, headers=dict(UA, **({"Content-Type": "application/json"} if data else {})),
                                     data=json.dumps(data).encode() if data else None, method=method)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}: {e.read()[:200]!r}"}
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}


def sh(o, n=900):
    return json.dumps(o)[:n]


print("=== Kalshi sports series")
s = get(f"{K}/series?category=Sports&limit=500")
ser = s.get("series") or []
print("series:", len(ser), s.get("_error", ""))
want = [x for x in ser if any(w in (x.get("ticker") or "") for w in
        ("NFL", "NHL", "NBA", "NCAAF", "CFB", "EPL", "UCL", "MLB", "WNBA", "NCAAMB", "MLS", "SOCCER", "MVE"))]
for x in want[:80]:
    print("  ", x.get("ticker"), "|", x.get("title"))

for st in ("KXNHLGAME", "KXNHLTOTAL", "KXNHLSPREAD", "KXNFLGAME", "KXNFLTOTAL", "KXNFLSPREAD",
           "KXNCAAFGAME", "KXNBAGAME", "KXNBATOTAL", "KXEPLGAME", "KXEPLTOTAL"):
    e = get(f"{K}/events?series_ticker={st}&status=open&with_nested_markets=true&limit=3")
    evs = e.get("events") or []
    print(f"\n--- {st}: events={len(evs)} {e.get('_error','')}")
    for ev in evs[:1]:
        print("  event", ev.get("event_ticker"), "|", ev.get("title"), "|", ev.get("sub_title"))
        for m in (ev.get("markets") or [])[:5]:
            print("    mkt", m.get("ticker"), "|", m.get("title"), "|", m.get("yes_sub_title"),
                  "| strike", m.get("floor_strike"), m.get("cap_strike"), m.get("strike_type"),
                  "| yes ask", m.get("yes_ask"), "no ask", m.get("no_ask"))

print("\n=== Kalshi multivariate (combo) collections")
c = get(f"{K}/multivariate_event_collections?status=open&limit=50")
cols = c.get("multivariate_contracts") or c.get("multivariate_event_collections") or []
print("keys:", list(c.keys())[:10], "count", len(cols), c.get("_error", ""))
for col in cols[:12]:
    print("  ", col.get("collection_ticker"), "|", col.get("title"), "| series", (col.get("series_ticker")),
          "| assoc", [a.get("ticker") if isinstance(a, dict) else a for a in (col.get("associated_events") or [])][:3],
          "| size", col.get("size_min"), col.get("size_max"))
if cols:
    t = cols[0].get("collection_ticker")
    one = get(f"{K}/multivariate_event_collections/{t}")
    print("\n  detail:", sh(one, 1500))
    lk = get(f"{K}/multivariate_event_collections/{t}/lookup", data={"selected_markets": []}, method="PUT")
    print("  lookup (no auth):", sh(lk, 400))
    hist = get(f"{K}/multivariate_event_collections/{t}/lookup?lookback_seconds=86400")
    print("  lookup history:", sh(hist, 600))

print("\n=== Polymarket")
for tag in ("nfl", "nhl", "nba", "soccer", "epl", "sports"):
    d = get(f"https://gamma-api.polymarket.com/events?tag_slug={tag}&closed=false&limit=3")
    if isinstance(d, list):
        print(f"  {tag}: {len(d)}", [(e.get('slug'), e.get('title'), len(e.get('markets') or [])) for e in d[:3]])
        if d:
            m = (d[0].get("markets") or [{}])[0]
            print("     market", {k: m.get(k) for k in ("question", "slug", "outcomes", "outcomePrices", "sportsMarketType", "line")})
    else:
        print(f"  {tag}:", sh(d, 200))
for u in ("https://gateway.polymarket.us/v1/markets?limit=2", "https://api.polymarket.us/v1/markets?limit=2"):
    print("  ", u, sh(get(u), 200))
