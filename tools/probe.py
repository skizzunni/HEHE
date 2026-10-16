"""Feed probe, run on GitHub's runners. Round 17: what does ESPN's per-game
odds feed carry for finished games -- opening lines? several books? Needed
for the edge lab (contradictions between markets, and price drift)."""
import json
import sys
import urllib.request

sys.path.insert(0, "tools")
import backtest as B  # noqa: E402

CORE = "https://sports.core.api.espn.com/v2/sports"
for key, sport, league in (("nfl", "football", "nfl"), ("mlb", "baseball", "mlb"),
                           ("ncaaf", "football", "college-football")):
    import datetime as dt
    ds = [(dt.date(2026, 10, 12) - dt.timedelta(days=i)).strftime("%Y%m%d") for i in range(4)]
    games = B.finished_games(key, sport, league, ds)
    print(key, "finished games:", len(games))
    if not games:
        continue
    eid = games[0][1]
    d = json.load(urllib.request.urlopen(urllib.request.Request(
        f"{CORE}/{sport}/leagues/{league}/events/{eid}/competitions/{eid}/odds",
        headers={"User-Agent": "Mozilla/5.0"}), timeout=25))
    items = d.get("items") or []
    print("  providers:", [(it.get("provider") or {}).get("name") for it in items])
    if items:
        it = items[0]
        print("  top-level keys:", sorted(it.keys()))
        print("  awayTeamOdds:", json.dumps(it.get("awayTeamOdds"))[:1500])
        for k in ("open", "close", "current"):
            if k in it:
                print(f"  {k}:", json.dumps(it[k])[:800])
