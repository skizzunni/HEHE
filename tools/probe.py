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


for lg, eid in (("eng.3", "401880292"), ("usa.1", "761783"), ("eng.2", "401880292")):
    s = get(f"{SITE}/{lg}/summary?event={eid}")
    print(f"### {lg} {eid} err={s.get('_error', '')} keys={sorted(s.keys())[:25]}")
    if s.get("_error"):
        continue
    for team in (s.get("rosters") or [])[:1]:
        r = team.get("roster") or []
        print("   roster size", len(r))
        for pl in r[:2]:
            a = pl.get("athlete") or {}
            print("    ", a.get("id"), a.get("displayName"), "starter", pl.get("starter"), "subbedIn", pl.get("subbedIn"))
            print("      ", [(x.get("name"), x.get("value")) for x in pl.get("stats") or []])
    print("   boxscore.players present:", bool((s.get("boxscore") or {}).get("players")))
    break
