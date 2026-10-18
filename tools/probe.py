"""Feed probe, run on GitHub's runners. Round 33: one FanDuel soccer MATCH
page in full (round 32 only reached outright events), and the 3-way runner
names on the sport page."""
import sys

sys.path.insert(0, ".")
import fanduel  # noqa: E402

d = fanduel._get(f"{fanduel.BASE}/content-managed-page?page=SPORT&eventTypeId=1"
                 f"&_ak={fanduel.AK}&timezone=America%2FNew_York")
att = (d or {}).get("attachments") or {}
ev = {k: e for k, e in (att.get("events") or {}).items() if " v " in (e.get("name") or "")}
for m in list((att.get("markets") or {}).values())[:3]:
    print("3way", m.get("marketType"), m.get("eventId"), [(r.get("runnerName"), r.get("selectionId")) for r in m.get("runners") or []])
for e in list(ev.values())[:2]:
    base = (f"{fanduel.BASE}/event-page?_ak={fanduel.AK}&eventId={e['eventId']}"
            "&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
    p = fanduel._get(base)
    tabs = ((p or {}).get("layout") or {}).get("tabs") or {}
    titles = [t.get("title") for t in (tabs.values() if isinstance(tabs, dict) else tabs)]
    print("MATCH", e.get("name"), "tabs", titles)
    for t in [""] + [x for x in titles if x and x.lower() in ("goals", "popular", "match", "main")]:
        q = fanduel._get(base + ("&tab=" + t.lower().replace(" ", "-") if t else ""))
        for m in list((((q or {}).get("attachments") or {}).get("markets") or {}).values())[:40]:
            rs = [(r.get("runnerName"), r.get("handicap"),
                   ((r.get("winRunnerOdds") or {}).get("americanDisplayOdds") or {}).get("americanOdds"))
                  for r in (m.get("runners") or [])[:6]]
            print("   [" + (t or "main") + "]", m.get("marketType"), "|", m.get("marketName"), "|", rs)
