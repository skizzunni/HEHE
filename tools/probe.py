"""Feed probe, run on GitHub's runners. Round 32: FanDuel soccer. Which
competitions, how fixtures are named, and which market types (match result,
double chance, totals, alternates) a match page carries -- to bring soccer
into the locks' pool."""
import collections
import sys

sys.path.insert(0, ".")
import fanduel  # noqa: E402

for etid in ("1",):
    d = fanduel._get(f"{fanduel.BASE}/content-managed-page?page=SPORT&eventTypeId={etid}"
                     f"&_ak={fanduel.AK}&timezone=America%2FNew_York")
    att = (d or {}).get("attachments") or {}
    ev = att.get("events") or {}
    comps = att.get("competitions") or {}
    print("eventType", etid, "events", len(ev), "competitions", len(comps))
    for c in list(comps.values())[:40]:
        print("  comp", c.get("competitionId"), c.get("name"))
    names = collections.Counter()
    for e in list(ev.values())[:12]:
        print("  event", e.get("eventId"), repr(e.get("name")), e.get("competitionId"), e.get("openDate"))
    mt = collections.Counter(m.get("marketType") for m in (att.get("markets") or {}).values())
    print("  sport-page market types:", mt.most_common(15))
    # one match page in full
    for e in list(ev.values())[:2]:
        base = (f"{fanduel.BASE}/event-page?_ak={fanduel.AK}&eventId={e['eventId']}"
                "&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
        p = fanduel._get(base)
        tabs = ((p or {}).get("layout") or {}).get("tabs") or {}
        titles = [t.get("title") for t in (tabs.values() if isinstance(tabs, dict) else tabs)]
        mk = ((p or {}).get("attachments") or {}).get("markets") or {}
        print("  page", e.get("name"), "tabs", titles)
        for m in list(mk.values())[:25]:
            rs = [(r.get("runnerName"), r.get("handicap"),
                   ((r.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds"))
                  for r in (m.get("runners") or [])[:4]]
            print("     ", m.get("marketType"), "|", m.get("marketName"), "|", rs)
