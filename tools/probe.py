"""Feed probe, run on GitHub's runners. Round 27: does ESPN keep DraftKings'
prop prices for FINISHED NFL games? If so, anytime-TD chances can be
backtested against box scores."""
import sys
from collections import Counter

sys.path.insert(0, ".")
import player_props as PP  # noqa: E402
import dashboard as D  # noqa: E402

for day in ("20261012", "20261005", "20260921"):
    sb = D.get(f"{D.ESPN}/football/nfl/scoreboard?dates={day}")
    for ev in (sb.get("events") or [])[:2]:
        eid = ev["id"]
        items = PP.raw_items("nfl", eid)
        types = Counter(((it.get("type") or {}).get("name") or "?") for it in items)
        print(day, ev.get("shortName"), "items", len(items), types.most_common(8))
        td = [it for it in items if "touchdown" in str((it.get("type") or {}).get("name", "")).lower()]
        for it in td[:3]:
            print("    ", (it.get("type") or {}).get("name"), (it.get("athlete") or {}).get("$ref", "")[-30:],
                  (it.get("odds") or {}).get("american"), it.get("current"), it.get("total"))
