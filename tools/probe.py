"""Feed probe, run on GitHub's runners. Round 31: why no college touchdown
scorers? FanDuel's NCAAF event pages -- their tabs, and any touchdown market
names -- next to one NFL game's."""
import re
import sys

sys.path.insert(0, ".")
import fanduel  # noqa: E402
import fd_props  # noqa: E402

FD = fanduel.load()
for league in ("ncaaf", "nfl"):
    gs = FD.get(league) or []
    print(league, "games on FanDuel:", len(gs))
    for g in gs[:6 if league == "ncaaf" else 1]:
        base = (f"{fanduel.BASE}/event-page?_ak={fanduel.AK}&eventId={g['id']}"
                "&useCombinedTouchdownsVirtualMarket=true&usePulse=true&useQuickBets=true")
        d = fanduel._get(base)
        tabs = ((d or {}).get("layout") or {}).get("tabs") or {}
        titles = [t.get("title") or "" for t in (tabs.values() if isinstance(tabs, dict) else tabs)]
        print(" ", g["away"], "@", g["home"], "tabs:", titles)
        names = set()
        for t in titles:
            p = fanduel._get(base + "&tab=" + t.lower().replace(" ", "-"))
            for m in (((p or {}).get("attachments") or {}).get("markets") or {}).values():
                n = m.get("marketName") or ""
                if re.search(r"touchdown|\btd\b", n, re.I):
                    names.add((t, n, m.get("marketType"), len(m.get("runners") or [])))
        for x in sorted(names)[:8]:
            print("     ", x)
        props = fd_props.for_game(g, league)
        print("     parsed props:", len(props), "TD:", sum(p.get("market") == "Anytime Touchdown Scorer" for p in props))
