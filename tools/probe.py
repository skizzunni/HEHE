"""Feed probe, run on GitHub's runners. Round 12: what it takes to grade
player props -- prop market names in ESPN's propBets, and the box-score
stats in the game summary that would settle them."""
import collections
import json
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
CORE = "https://sports.core.api.espn.com/v2/sports"
SITE = "https://site.api.espn.com/apis/site/v2/sports"


def get(url):
    time.sleep(0.3)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return json.load(r)
    except Exception as e:
        return {"_error": str(e)}


for sport, lg, days in (("football", "nfl", "20261012"),
                        ("soccer", "eng.1", "20261004"),
                        ("hockey", "nhl", "20261013"),
                        ("baseball", "mlb", "20261012")):
    sb = get(f"{SITE}/{sport}/{lg}/scoreboard?dates={days}")
    evs = [e for e in sb.get("events") or [] if (e.get("status") or {}).get("type", {}).get("completed")]
    print(f"\n######## {lg}: {len(evs)} finished events {sb.get('_error', '')}")
    if not evs:
        continue
    eid = evs[0]["id"]
    print("event", eid, evs[0].get("name"))
    p = get(f"{CORE}/{sport}/leagues/{lg}/events/{eid}/competitions/{eid}/odds/100/propBets?limit=1000&page=1")
    items = p.get("items") or []
    print("propBets items:", len(items), p.get("_error", ""), "pages", p.get("pageCount"))
    types = collections.Counter((x.get("type") or {}).get("name") for x in items)
    priced = collections.Counter((x.get("type") or {}).get("name") for x in items
                                 if ((x.get("current") or {}).get("over") or {}).get("american"))
    for t, n in types.most_common(45):
        print(f"   {n:4d} priced {priced.get(t, 0):4d}  {t}")
    if items:
        ex = next((x for x in items if ((x.get("current") or {}).get("over") or {}).get("american")), items[0])
        print("example item:", json.dumps({k: ex.get(k) for k in ("type", "athlete", "current", "id")})[:700])
    s = get(f"{SITE}/{sport}/{lg}/summary?event={eid}")
    bx = (s.get("boxscore") or {}).get("players") or []
    print("summary keys:", sorted(s.keys()) if isinstance(s, dict) else s)
    for team in bx[:1]:
        for st in team.get("statistics") or []:
            a0 = (st.get("athletes") or [{}])[0]
            print(f"   [{st.get('name') or st.get('type')}] labels={st.get('labels') or st.get('names')} keys={st.get('keys')}")
            print(f"       e.g. {a0.get('athlete', {}).get('id')} {a0.get('athlete', {}).get('displayName')} {a0.get('stats')}")
    if sport == "soccer":
        print("keyEvents types:", collections.Counter((k.get("type") or {}).get("text") for k in s.get("keyEvents") or []))
        r = (s.get("rosters") or [{}])[0].get("roster") or []
        if r:
            print("roster stat names:", [x.get("name") for x in (r[0].get("stats") or [])])
