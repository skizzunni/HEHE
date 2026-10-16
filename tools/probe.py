"""Feed probe, run on GitHub's runners. Round 19: FanDuel PLAYER props.
For one upcoming game per league, list the event page's tabs and every
player-prop market type with sample runners and prices, so a parser can be
written against the real shapes (ESPN's prop feed is empty outside football)."""
import sys
from collections import Counter

sys.path.insert(0, ".")
import fanduel as F  # noqa: E402

FD = F.load()
for lg in ("nhl", "nfl", "ncaaf", "nba", "mlb"):
    games = FD.get(lg) or []
    print(f"== {lg}: {len(games)} games on FanDuel")
    if not games:
        continue
    g = games[0]
    print("   game:", g["away"], "@", g["home"], g["id"])
    base = (f"{F.BASE}/event-page?_ak={F.AK}&eventId={g['id']}"
            "&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
    d = F._get(base)
    lay = (d or {}).get("layout") or {}
    tabs = lay.get("tabs") or {}
    tl = [(t.get("title"), t.get("id")) for t in (tabs.values() if isinstance(tabs, dict) else tabs)]
    print("   tabs:", tl[:30])
    seen = Counter()
    for title, tid in tl:
        slug = (title or "").lower().replace(" ", "-")
        if not any(k in slug for k in ("player", "goal", "point", "pass", "rush", "receiv",
                                       "td", "touchdown", "shot", "hit", "strikeout", "rebound",
                                       "assist", "three")):
            continue
        p = F._get(base + f"&tab={slug}")
        ms = ((p or {}).get("attachments") or {}).get("markets") or {}
        for m in ms.values():
            t = m.get("marketType")
            if seen[t]:
                seen[t] += 1
                continue
            seen[t] += 1
            rs = [(r.get("runnerName"), r.get("handicap"),
                   ((r.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds"))
                  for r in (m.get("runners") or [])[:4]]
            print(f"     [{slug}] {t} | {m.get('marketName')} | {rs}")
    print("   market type counts:", seen.most_common(40))
