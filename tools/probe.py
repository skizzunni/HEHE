"""Feed probe, run on GitHub's runners. Round 28: the full shape of a past
NFL 'Anytime Touchdown Scorer' prop item, so td_lab reads its price."""
import json
import sys

sys.path.insert(0, ".")
import player_props as PP  # noqa: E402
import dashboard as D  # noqa: E402

sb = D.get(f"{D.ESPN}/football/nfl/scoreboard?dates=20261012")
eid = sb["events"][0]["id"]
items = PP.raw_items("nfl", eid)
td = [it for it in items if "Anytime Touchdown" in ((it.get("type") or {}).get("name") or "")]
print(eid, len(items), "anytime td items", len(td))
for it in td[:2]:
    print(json.dumps(it)[:1500])
