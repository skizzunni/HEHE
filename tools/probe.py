"""Feed probe, run on GitHub's runners. Round 18: FanDuel UFC -- which page id
lists the fights, and which markets each fight's own page carries (method of
victory, goes the distance, round betting, total rounds), with runner names
and prices, so the parser can be written against the real shapes."""
import sys
from collections import Counter

sys.path.insert(0, ".")
import fanduel as F  # noqa: E402

for page in ("ufc", "mma", "ufc-mma"):
    d = F._get(f"{F.BASE}/content-managed-page?page=CUSTOM&customPageId={page}"
               f"&_ak={F.AK}&timezone=America%2FNew_York")
    att = (d or {}).get("attachments") or {}
    ev = att.get("events") or {}
    mk = att.get("markets") or {}
    print(f"page {page}: events {len(ev)} markets {len(mk)}")
    if not ev:
        continue
    print("  market types:", Counter(m.get("marketType") for m in mk.values()).most_common(12))
    fights = list(ev.values())
    for e in fights[:2]:
        print("  event:", e.get("eventId"), e.get("name"), e.get("openDate"))
        for tab in ("popular", "method-of-victory", "rounds", "fight-props", None):
            q = f"&tab={tab}" if tab else ""
            p = F._get(f"{F.BASE}/event-page?_ak={F.AK}&eventId={e.get('eventId')}{q}"
                       "&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
            ms = ((p or {}).get("attachments") or {}).get("markets") or {}
            print(f"    tab={tab}: {len(ms)} markets")
            for m in list(ms.values())[:30]:
                rs = [(r.get("runnerName"), r.get("handicap"),
                       ((r.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds"))
                      for r in (m.get("runners") or [])[:6]]
                print(f"      {m.get('marketType')} | {m.get('marketName')} | {rs}")
            if ms:
                break
    break
