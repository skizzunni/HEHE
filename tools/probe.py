"""Feed probe, run on GitHub's runners (the dev sandbox cannot reach ESPN).
Round 2: the shape of player-prop items, so the parser matches real data."""
import datetime as dt
import json
import urllib.request

SITE = "https://site.api.espn.com/apis/site/v2/sports"
CORE = "https://sports.core.api.espn.com/v2/sports"


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}


day = dt.date.today()
days = [(day + dt.timedelta(days=k)).strftime("%Y%m%d") for k in range(0, 5)]
for sport, league, path in (("football", "nfl", "football/nfl"),
                            ("hockey", "nhl", "hockey/nhl"),
                            ("basketball", "nba", "basketball/nba"),
                            ("football", "college-football", "football/college-football"),
                            ("soccer", "eng.1", "soccer/eng.1")):
    eids = []
    for ds in days:
        d = get(f"{SITE}/{path}/scoreboard?dates={ds}")
        eids += [e["id"] for e in d.get("events") or []]
    print(f"\n##### {league}: {len(eids)} events")
    hit = 0
    for eid in eids[:6]:
        base = f"{CORE}/{sport}/leagues/{league}/events/{eid}/competitions/{eid}/odds/100/propBets?limit=1000"
        pb = get(base)
        n = pb.get("count")
        print(f"  event {eid}: propBets count={n} {pb.get('_error','')[:40]}")
        items = pb.get("items") or []
        if not items or hit:
            continue
        hit = 1
        seen = {}
        for x in items:
            t = (x.get("type") or {}).get("name")
            seen.setdefault(t, []).append(x)
        for t, xs in list(seen.items())[:40]:
            print(f"\n  TYPE {t} ({len(xs)})")
            for x in xs[:3]:
                y = {k: v for k, v in x.items() if k not in ("competition", "provider")}
                print("   ", json.dumps(y, sort_keys=True)[:700])
        ath = next((x["athlete"]["$ref"] for x in items if x.get("athlete")), None)
        if ath:
            a = get(ath.replace("http://", "https://"))
            print("\n  ATHLETE", {k: a.get(k) for k in ("id", "displayName", "shortName", "_error")},
                  "team", (a.get("team") or {}).get("$ref"))
        tm = next((x["team"]["$ref"] for x in items if x.get("team")), None)
        if tm:
            a = get(tm.replace("http://", "https://"))
            print("  TEAM", {k: a.get(k) for k in ("id", "displayName", "_error")})
