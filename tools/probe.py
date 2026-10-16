"""Feed probe, run on GitHub's runners. Round 20: tennis prices. ESPN carries
no tennis odds, so tennis picks are the model's alone. Does FanDuel list
ATP/WTA matches (which page id, which market type), and does Kalshi?"""
import json
import sys
from collections import Counter

sys.path.insert(0, ".")
import fanduel as F  # noqa: E402

for page in ("tennis", "atp", "wta", "tennis-atp", "tennis-wta"):
    d = F._get(f"{F.BASE}/content-managed-page?page=CUSTOM&customPageId={page}"
               f"&_ak={F.AK}&timezone=America%2FNew_York")
    att = (d or {}).get("attachments") or {}
    ev, mk = att.get("events") or {}, att.get("markets") or {}
    print(f"fanduel page {page}: events {len(ev)} markets {len(mk)}")
    if ev:
        print("  types:", Counter(m.get("marketType") for m in mk.values()).most_common(8))
        for e in list(ev.values())[:4]:
            print("  event:", e.get("name"), e.get("openDate"), e.get("competitionId"))
        for m in list(mk.values())[:4]:
            print("  market:", m.get("marketType"), m.get("marketName"),
                  [(r.get("runnerName"), ((r.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds"))
                   for r in m.get("runners") or []])

import urllib.request
K = "https://api.elections.kalshi.com/trade-api/v2"
for ser in ("KXATPMATCH", "KXWTAMATCH", "KXATPGAME", "KXWTAGAME", "KXTENNISMATCH"):
    try:
        d = json.load(urllib.request.urlopen(urllib.request.Request(
            f"{K}/events?series_ticker={ser}&status=open&with_nested_markets=true&limit=5",
            headers={"User-Agent": "Mozilla/5.0"}), timeout=20))
    except Exception as e:
        print("kalshi", ser, "error", e)
        continue
    evs = d.get("events") or []
    print(f"kalshi {ser}: {len(evs)} open events")
    for ev in evs[:3]:
        print("  ", ev.get("event_ticker"), ev.get("title"),
              [(m.get("yes_sub_title"), m.get("yes_ask_dollars") or m.get("yes_ask"),
                m.get("no_ask_dollars") or m.get("no_ask")) for m in ev.get("markets") or []])
