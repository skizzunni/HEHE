"""Feed probe, run on GitHub's runners. Round 24: UFC on FanDuel. Which
custom page lists MMA, what market types each fight carries (winner, method,
goes the distance, round betting, total rounds), and the runner shapes."""
import json
import sys
from collections import Counter

sys.path.insert(0, ".")
import fanduel as F  # noqa: E402

found = None
URLS = {p: f"{F.BASE}/content-managed-page?page=CUSTOM&customPageId={p}&_ak={F.AK}&timezone=America%2FNew_York"
        for p in ("ufc", "mma")}
# FanDuel's sport pages are keyed by eventTypeId; 26420387 is MMA on Betfair-
# family exchanges, which FanDuel's sbapi shares
for et in ("26420387", "7524"):
    URLS[f"sport-{et}"] = (f"{F.BASE}/content-managed-page?page=SPORT&eventTypeId={et}"
                           f"&_ak={F.AK}&timezone=America%2FNew_York")
URLS["search-ufc"] = f"{F.BASE}/search?query=ufc&_ak={F.AK}"
for page, url in URLS.items():
    d = F._get(url)
    att = (d or {}).get("attachments") or {}
    ev, mk = att.get("events") or {}, att.get("markets") or {}
    print(f"page {page}: events {len(ev)} markets {len(mk)}")
    if ev and not found:
        found = (page, ev, mk)
if found:
    page, ev, mk = found
    print("market types:", Counter(m.get("marketType") for m in mk.values()).most_common(10))
    for e in list(ev.values())[:3]:
        print("event:", e.get("eventId"), e.get("name"), e.get("openDate"))
    eid = list(ev.values())[0].get("eventId")
    base = (f"{F.BASE}/event-page?_ak={F.AK}&eventId={eid}"
            "&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
    d = F._get(base)
    tabs = ((d or {}).get("layout") or {}).get("tabs") or {}
    titles = [t.get("title") or "" for t in (tabs.values() if isinstance(tabs, dict) else tabs)]
    print("event tabs:", titles)
    seen = {}
    for t in [""] + titles:
        p = F._get(base + ("&tab=" + t.lower().replace(" ", "-") if t else ""))
        for m in (((p or {}).get("attachments") or {}).get("markets") or {}).values():
            seen.setdefault(m.get("marketName"), m)
    print("markets on the fight:", len(seen))
    for name, m in list(seen.items())[:25]:
        print("  ", m.get("marketType"), "|", name, "|",
              [(r.get("runnerName"), ((r.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds"))
               for r in (m.get("runners") or [])][:6])
