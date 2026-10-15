"""Feed probe, run on GitHub's runners (the dev sandbox cannot reach ESPN).
Round 3: compact prop shapes, and closing odds on FINISHED games (backtest)."""
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


def slim(x):
    c = x.get("current") or {}
    return dict(type=(x.get("type") or {}).get("name"),
                ath=bool(x.get("athlete")), team=bool(x.get("team")),
                target=(c.get("target") or {}).get("value"),
                over=(c.get("over") or {}).get("american"),
                under=(c.get("under") or {}).get("american"),
                odds=((x.get("odds") or {}).get("american") or {}).get("value"),
                keys=sorted(c.keys()))


day = dt.date.today()
days = [(day + dt.timedelta(days=k)).strftime("%Y%m%d") for k in range(0, 5)]
print("=== props")
for sport, league, path in (("football", "nfl", "football/nfl"),
                            ("hockey", "nhl", "hockey/nhl")):
    eids = []
    for ds in days:
        d = get(f"{SITE}/{path}/scoreboard?dates={ds}")
        eids += [e["id"] for e in d.get("events") or []]
    for eid in eids[:3]:
        pb = get(f"{CORE}/{sport}/leagues/{league}/events/{eid}/competitions/{eid}/odds/100/propBets?limit=2000")
        items = pb.get("items") or []
        if not items:
            continue
        print(f"\n## {league} event {eid}: {len(items)} items, pages={pb.get('pageCount')}")
        seen = {}
        for x in items:
            seen.setdefault((x.get("type") or {}).get("name"), []).append(x)
        for t, xs in seen.items():
            print(" ", json.dumps(slim(xs[0])), f"(n={len(xs)})")
        a = next((x["athlete"]["$ref"] for x in items if x.get("athlete")), None)
        if a:
            r = get(a.replace("http://", "https://"))
            print("  athlete:", r.get("displayName"), r.get("_error", ""))
        tm = next((x["team"]["$ref"] for x in items if x.get("team")), None)
        if tm:
            r = get(tm.replace("http://", "https://"))
            print("  team:", r.get("displayName"), r.get("_error", ""))
        break

print("\n=== closing odds on finished games")
for sport, league, path, ds in (("hockey", "nhl", "hockey/nhl", "20260115"),
                                ("football", "nfl", "football/nfl", "20251207"),
                                ("football", "college-football", "football/college-football", "20251018"),
                                ("basketball", "nba", "basketball/nba", "20260115"),
                                ("soccer", "eng.1", "soccer/eng.1", "20260117"),
                                ("hockey", "nhl", "hockey/nhl", "20261011")):
    d = get(f"{SITE}/{path}/scoreboard?dates={ds}")
    ev = (d.get("events") or [None])[0]
    if not ev:
        print(league, ds, "no events", d.get("_error", ""))
        continue
    eid = ev["id"]
    c = ev["competitions"][0]
    sc = {x["homeAway"]: x.get("score") for x in c["competitors"]}
    o = get(f"{CORE}/{sport}/leagues/{league}/events/{eid}/competitions/{eid}/odds")
    it = (o.get("items") or [{}])[0]
    print(f"\n{league} {ds} {eid} score {sc} n_events={len(d.get('events') or [])} "
          f"scoreboard_odds={bool(c.get('odds'))}")
    print("  provider", (it.get("provider") or {}).get("name"),
          "overUnder", it.get("overUnder"), "spread", it.get("spread"),
          "overOdds", it.get("overOdds"), "underOdds", it.get("underOdds"))
    for side in ("awayTeamOdds", "homeTeamOdds"):
        s = it.get(side) or {}
        print("  ", side, {k: s.get(k) for k in ("moneyLine", "spreadOdds", "favorite")},
              "close", json.dumps((s.get("close") or {}))[:300])
    print("   top keys", sorted(it.keys()))
    print("   close", json.dumps(it.get("close") or {})[:400])
    print("   current", json.dumps(it.get("current") or {})[:400])
