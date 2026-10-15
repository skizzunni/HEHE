"""Feed probe, run on GitHub's runners (the dev sandbox cannot reach ESPN).

Prints what the feeds actually carry, so parsers are written against real
data rather than guesses. Safe to delete once the formats are known.
"""
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


def short(o, n=2500):
    s = json.dumps(o, sort_keys=True)
    return s[:n] + ("..." if len(s) > n else "")


day = dt.date.today()
days = [(day + dt.timedelta(days=k)).strftime("%Y%m%d") for k in range(0, 4)]

print("=== 1. scoreboard odds objects")
for path in ("football/nfl", "basketball/nba", "hockey/nhl", "football/college-football",
             "soccer/uefa.champions", "soccer/eng.1", "mma/ufc", "tennis/atp"):
    for ds in days:
        d = get(f"{SITE}/{path}/scoreboard?dates={ds}")
        evs = d.get("events") or []
        c = next((c for e in evs for c in e.get("competitions") or [] if c.get("odds")), None)
        if c:
            print(f"\n--- {path} {ds} event {c.get('id')}")
            print(short(c["odds"][0], 3000))
            break
    else:
        print(f"\n--- {path}: no odds in next 4 days ({d.get('_error','')})")

print("\n=== 2. core odds + prop bets")
for sport, league, path in (("football", "nfl", "football/nfl"),
                            ("basketball", "nba", "basketball/nba"),
                            ("hockey", "nhl", "hockey/nhl"),
                            ("football", "college-football", "football/college-football")):
    eid = None
    for ds in days:
        d = get(f"{SITE}/{path}/scoreboard?dates={ds}")
        for e in d.get("events") or []:
            if (e.get("competitions") or [{}])[0].get("status", {}).get("type", {}).get("state") == "pre":
                eid = e["id"]
                break
        if eid:
            break
    if not eid:
        print(f"--- {league}: no upcoming event")
        continue
    base = f"{CORE}/{sport}/leagues/{league}/events/{eid}/competitions/{eid}/odds"
    od = get(base)
    print(f"\n--- {league} event {eid} odds list: count={od.get('count')} {od.get('_error','')}")
    for it in (od.get("items") or [])[:6]:
        prov = it.get("provider") or {}
        print("   provider", prov.get("id"), prov.get("name"), "keys", sorted(it.keys())[:30])
    for it in (od.get("items") or [])[:3]:
        pid = (it.get("provider") or {}).get("id")
        pb = get(f"{base}/{pid}/propBets?limit=1000")
        print(f"   propBets provider {pid}: count={pb.get('count')} {pb.get('_error','')}")
        items = pb.get("items") or []
        if items:
            print("   first:", short(items[0], 1500))
            types = {}
            for x in items:
                t = (x.get("type") or {}).get("name") or (x.get("type") or {}).get("id")
                types[t] = types.get(t, 0) + 1
            print("   types:", short(types, 2500))
            break

print("\n=== 3. candidate leagues (events next 4 days / with odds)")
CANDS = [
    "basketball/womens-college-basketball", "football/cfl", "football/ufl",
    "hockey/mens-college-hockey", "baseball/college-baseball",
    "golf/lpga", "golf/eur", "golf/liv", "racing/f1", "mma/pfl", "boxing",
    "soccer/usa.nwsl", "soccer/eng.w.1", "soccer/conmebol.libertadores",
    "soccer/conmebol.sudamericana", "soccer/concacaf.champions", "soccer/eng.fa",
    "soccer/eng.league_cup", "soccer/esp.copa_del_rey", "soccer/ger.dfb_pokal",
    "soccer/ita.coppa_italia", "soccer/fra.coupe_de_france", "soccer/ger.2",
    "soccer/esp.2", "soccer/ita.2", "soccer/fra.2", "soccer/ned.2", "soccer/por.2",
    "soccer/fifa.worldq.uefa", "soccer/fifa.friendly", "soccer/uefa.nations",
    "soccer/chn.1", "soccer/ind.1", "soccer/aus.1", "soccer/sco.2", "soccer/tur.2",
    "soccer/usa.usl.1", "soccer/mex.2", "soccer/rus.1", "soccer/pol.1", "soccer/cze.1",
    "soccer/rou.1", "soccer/cro.1", "soccer/srb.1", "soccer/isr.1", "soccer/egy.1",
    "soccer/uefa.europa.conf", "soccer/uefa.europa", "soccer/afc.champions",
    "basketball/nbl", "basketball/wnba", "lacrosse/pll", "rugby/164205",
    "australian-football/afl", "cricket/8048",
]
for path in CANDS:
    n = o = 0
    err = ""
    for ds in days:
        d = get(f"{SITE}/{path}/scoreboard?dates={ds}")
        err = d.get("_error", "") or err
        for e in d.get("events") or []:
            for c in e.get("competitions") or []:
                n += 1
                o += bool(c.get("odds"))
    print(f"{path:45} events={n:4} with_odds={o:4} {err[:60]}")
