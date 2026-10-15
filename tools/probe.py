"""Feed probe, run on GitHub's runners (the dev sandbox cannot reach ESPN).
Round 5: FanDuel New York -- event names, game market types, and whether the
event page carries alternate lines (what most stack legs are)."""
import json
import urllib.request
from collections import Counter

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/json"}
AK = "FhMFpcPWXMeyZxOx"
BASE = "https://sbapi.ny.sportsbook.fanduel.com/api"


def get(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}


for page in ("nfl", "nhl", "nba", "ncaaf", "ncaab", "college-football", "soccer",
             "epl", "champions-league", "mlb", "wnba", "ufc", "tennis"):
    d = get(f"{BASE}/content-managed-page?page=CUSTOM&customPageId={page}&_ak={AK}"
            f"&timezone=America%2FNew_York")
    att = d.get("attachments") or {}
    ev, mk = att.get("events") or {}, att.get("markets") or {}
    games = [e for e in ev.values() if " @ " in (e.get("name") or "") or " v " in (e.get("name") or "")]
    print(f"\n== {page}: {d.get('_error','')} events={len(ev)} games={len(games)} markets={len(mk)}")
    print("   names:", [e.get("name") for e in games[:4]])
    print("   types:", Counter(m.get("marketType") for m in mk.values()).most_common(12))
    if games and page in ("nhl", "nfl", "epl", "nba"):
        eid = games[0]["eventId"]
        for tab in ("", "&tab=popular", "&tab=goals", "&tab=totals", "&tab=all"):
            ep = get(f"{BASE}/event-page?eventId={eid}&_ak={AK}{tab}")
            em = (ep.get("attachments") or {}).get("markets") or {}
            print(f"   event-page {eid}{tab}: {ep.get('_error','')} markets={len(em)}",
                  Counter(m.get("marketType") for m in em.values()).most_common(25))
            alt = next((m for m in em.values() if "ALT" in (m.get("marketType") or "")
                        and "TOTAL" in (m.get("marketType") or "")), None)
            if alt:
                print("     alt sample:", alt.get("marketId"), alt.get("marketName"),
                      [(r.get("runnerName"), r.get("handicap"), r.get("selectionId"))
                       for r in (alt.get("runners") or [])[:6]])
            ml = next((m for m in em.values() if m.get("marketType") == "MONEY_LINE"), None)
            if ml:
                print("     ML sample:", ml.get("marketId"),
                      [(r.get("runnerName"), r.get("selectionId")) for r in ml.get("runners") or []])
