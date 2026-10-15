"""Feed probe, run on GitHub's runners. Round 14: FanDuel's alternate lines.
The content-managed league page carries only main markets; the event page
should carry alternate spreads/totals, which the locks need."""
import collections
import json
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36", "Accept": "application/json"}
AK = "FhMFpcPWXMeyZxOx"
BASE = "https://sbapi.ny.sportsbook.fanduel.com/api"


def get(url):
    time.sleep(0.4)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return json.load(r)
    except Exception as e:
        return {"_error": str(e)}


for lg in ("nhl", "mlb", "ncaaf"):
    d = get(f"{BASE}/content-managed-page?page=CUSTOM&customPageId={lg}&_ak={AK}&timezone=America%2FNew_York")
    evs = ((d.get("attachments") or {}).get("events") or {})
    ev = next((e for e in evs.values() if " @ " in (e.get("name") or "")), None)
    print(f"\n######## {lg}: {len(evs)} events {d.get('_error', '')}")
    if not ev:
        continue
    eid = ev["eventId"]
    print("event", eid, ev.get("name"))
    base = get(f"{BASE}/event-page?_ak={AK}&eventId={eid}&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
    tabs = (base.get("layout") or {}).get("tabs") or {}
    tabs = list(tabs.values()) if isinstance(tabs, dict) else tabs
    seen = set()
    for t in tabs:
        title = t.get("title") or ""
        slug = title.lower().replace(" & ", "-").replace("&", "").replace("/", "-").replace(" ", "-").replace("™", "")
        for cand in (slug, title.lower().replace(" ", "-")):
            if cand in seen:
                continue
            seen.add(cand)
            p = get(f"{BASE}/event-page?_ak={AK}&eventId={eid}&tab={cand}&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
            mk = ((p.get("attachments") or {}).get("markets") or {})
            alt = {m.get("marketType"): m for m in mk.values()
                   if any(w in (m.get("marketType") or "") for w in ("ALT", "HANDICAP", "TOTAL", "SPREAD", "LINE"))
                   and not any(w in (m.get("marketType") or "") for w in ("INNING", "PERIOD", "QUARTER", "HALF", "PLAYER"))}
            print(f"  tab={cand!r}: {len(mk)} markets; game-line-like: {sorted(alt)[:12]} {p.get('_error', '')}")
            for t2, m in list(alt.items())[:6]:
                print(f"     {t2} name={m.get('marketName')!r} runners="
                      f"{[(r.get('runnerName'), r.get('handicap'), r.get('selectionId'), ((r.get('winRunnerOdds') or {}).get('americanDisplayOdds') or {}).get('americanOdds')) for r in (m.get('runners') or [])][:10]}")
