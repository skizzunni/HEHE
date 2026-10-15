"""Feed probe, run on GitHub's runners. Round 13b: soccer player stats in
the ESPN summary, to grade soccer props (tackles, shots, goals, cards)."""
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


for lg, day in (("usa.1", "20261004"), ("uefa.europa", "20261002"), ("eng.1", "20260927"),
                ("uefa.champions", "20261001")):
    sb = get(f"{SITE}/{lg}/scoreboard?dates={day}")
    evs = sb.get("events") or []
    st = [((e.get("status") or {}).get("type") or {}).get("state") for e in evs]
    print(f"### {lg} {day}: {len(evs)} events states={st[:8]} {sb.get('_error', '')}")
    post = [e for e in evs if ((e.get("status") or {}).get("type") or {}).get("state") == "post"]
    if not post:
        continue
    eid = post[0]["id"]
    s = get(f"{SITE}/{lg}/summary?event={eid}")
    print(f"   event {eid} {post[0].get('name')} keys={sorted(s.keys())}")
    for team in (s.get("rosters") or [])[:1]:
        r = team.get("roster") or []
        print("   roster size", len(r))
        for pl in r[:2]:
            a = pl.get("athlete") or {}
            print("    ", a.get("id"), a.get("displayName"), "starter", pl.get("starter"), "subbedIn", pl.get("subbedIn"))
            print("      ", [(x.get("name"), x.get("value")) for x in pl.get("stats") or []])
    print("   boxscore.players present:", bool((s.get("boxscore") or {}).get("players")))
    break
