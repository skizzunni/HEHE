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
    for tab in ("", "&tab=popular", "&tab=all", "&tab=alternates", "&tab=game-lines"):
        p = get(f"{BASE}/event-page?_ak={AK}&eventId={eid}{tab}&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
        mk = ((p.get("attachments") or {}).get("markets") or {})
        types = collections.Counter(m.get("marketType") for m in mk.values())
        print(f"  event-page{tab or ' (no tab)'}: {len(mk)} markets {p.get('_error', '')}")
        if mk:
            print("    types:", dict(types.most_common(40)))
            for m in mk.values():
                t = m.get("marketType") or ""
                if "ALT" in t or "HANDICAP" in t or "TOTAL" in t:
                    print(f"    e.g. {t} id={m.get('marketId')} name={m.get('marketName')!r} runners="
                          f"{[(r.get('runnerName'), r.get('handicap'), r.get('selectionId'), ((r.get('winRunnerOdds') or {}).get('americanDisplayOdds') or {}).get('americanOdds')) for r in (m.get('runners') or [])][:8]}")
            tabs = (p.get("layout") or {}).get("tabs")
            if tabs:
                print("    layout tabs:", [(t.get("id"), t.get("title")) for t in (tabs.values() if isinstance(tabs, dict) else tabs)][:20])
            break
