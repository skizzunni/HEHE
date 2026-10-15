"""Feed probe, run on GitHub's runners. Round 13: soccer player stats in the
ESPN summary, to grade soccer props (tackles, shots, goals, cards)."""
import json
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
SITE = "https://site.api.espn.com/apis/site/v2/sports/soccer"


def get(url):
    time.sleep(0.3)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return json.load(r)
    except Exception as e:
        return {"_error": str(e)}


done = False
for lg in ("eng.1", "uefa.europa", "esp.1"):
    for day in ("20261004", "20261005", "20260927", "20260928", "20261002"):
        sb = get(f"{SITE}/{lg}/scoreboard?dates={day}")
        evs = [e for e in sb.get("events") or [] if (e.get("status") or {}).get("type", {}).get("completed")]
        if not evs:
            continue
        eid = evs[0]["id"]
        s = get(f"{SITE}/{lg}/summary?event={eid}")
        print(f"### {lg} {day} event {eid} {evs[0].get('name')} keys={sorted(s.keys())}")
        for team in (s.get("rosters") or [])[:1]:
            r = team.get("roster") or []
            print("roster size", len(r))
            for pl in r[:3]:
                print("  ", (pl.get("athlete") or {}).get("id"), (pl.get("athlete") or {}).get("displayName"),
                      "starter", pl.get("starter"), "subbedIn", pl.get("subbedIn"))
                print("     ", [(x.get("name"), x.get("value")) for x in pl.get("stats") or []])
        bx = (s.get("boxscore") or {}).get("players")
        print("boxscore.players present:", bool(bx))
        done = True
        break
    if done:
        break
