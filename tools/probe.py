"""Feed probe, run on GitHub's runners. Round 34: college touchdown scorers
on FanDuel games that have NOT started (round 31 only reached live games,
whose TD markets FanDuel had already pulled)."""
import datetime as dt
import re
import sys

sys.path.insert(0, ".")
import fanduel  # noqa: E402
import fd_props  # noqa: E402

now = dt.datetime.now(dt.timezone.utc)
d = fanduel._get(f"{fanduel.BASE}/content-managed-page?page=CUSTOM&customPageId=ncaaf"
                 f"&_ak={fanduel.AK}&timezone=America%2FNew_York")
ev = ((d or {}).get("attachments") or {}).get("events") or {}
up = sorted((e for e in ev.values() if " @ " in (e.get("name") or "")
             and fanduel._ts(e.get("openDate")) and fanduel._ts(e["openDate"]) > now),
            key=lambda e: e["openDate"])
print("upcoming college games on FanDuel:", len(up))
for e in up[:8]:
    base = (f"{fanduel.BASE}/event-page?_ak={fanduel.AK}&eventId={e['eventId']}"
            "&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
    p = fanduel._get(base)
    tabs = ((p or {}).get("layout") or {}).get("tabs") or {}
    titles = [t.get("title") or "" for t in (tabs.values() if isinstance(tabs, dict) else tabs)]
    names = set()
    for t in titles:
        q = fanduel._get(base + "&tab=" + t.lower().replace(" ", "-"))
        for m in (((q or {}).get("attachments") or {}).get("markets") or {}).values():
            n = m.get("marketName") or ""
            if re.search(r"touchdown|\btd\b", n, re.I):
                names.add((t, n, m.get("marketType"), len(m.get("runners") or [])))
    g = dict(id=str(e["eventId"]), away=e["name"].split(" @ ")[0], home=e["name"].split(" @ ")[1])
    props = fd_props.for_game(g, "ncaaf")
    print(e["openDate"], e["name"], "| tabs", titles)
    for x in sorted(names)[:6]:
        print("     ", x)
    print("     parsed props", len(props), "TD", sum(p.get("market") == "Anytime Touchdown Scorer" for p in props))
