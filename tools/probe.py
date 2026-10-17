"""Feed probe, run on GitHub's runners. Round 23: tomorrow's 35 college
football games yield no FanDuel props for the 25-leg ticket. Does FanDuel's
NCAAF event page have prop tabs at all, which titles, and what does
fd_props.parse make of them?"""
import sys
from collections import Counter

sys.path.insert(0, ".")
import fanduel as F  # noqa: E402
import fd_props as P  # noqa: E402

FD = F.load()
games = FD.get("ncaaf") or []
print("ncaaf games on FanDuel:", len(games))
for g in games[:4]:
    base = (f"{F.BASE}/event-page?_ak={F.AK}&eventId={g['id']}"
            "&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
    d = F._get(base)
    tabs = ((d or {}).get("layout") or {}).get("tabs") or {}
    titles = [t.get("title") or "" for t in (tabs.values() if isinstance(tabs, dict) else tabs)]
    print(g.get("away"), "@", g.get("home"), "tabs:", titles)
    mk = ((d or {}).get("attachments") or {}).get("markets") or {}
    print("   main-page market names:", Counter(m.get("marketName", "")[:40] for m in mk.values()).most_common(12))
    for t in titles:
        tl = t.lower()
        if any(w in tl for w in ("player", "td", "touchdown", "passing", "rushing", "receiving")):
            p = F._get(base + "&tab=" + tl.replace(" ", "-"))
            m2 = ((p or {}).get("attachments") or {}).get("markets") or {}
            print(f"   tab {t!r}: {len(m2)} markets;",
                  Counter(m.get('marketName', '')[:40] for m in m2.values()).most_common(8))
    props = P.for_game(g, "ncaaf")
    print("   parsed props:", len(props), Counter(x["market"] for x in props).most_common(6))
print("SKIP_TAB", P.SKIP_TAB, "TAB_WORDS", P.TAB_WORDS)
