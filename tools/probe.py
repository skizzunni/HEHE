"""Feed probe, run on GitHub's runners. Round 22: soccer picks have carried
no price since 2026-10-15 (95% did in September). What does ESPN's soccer
scoreboard odds block look like now, and does dashboard.raw_prices read it?"""
import datetime as dt
import json
import sys

sys.path.insert(0, ".")
import dashboard as D  # noqa: E402

day = dt.date.today()
for lg in ("eng.1", "esp.1", "ger.1", "usa.1", "arg.1", "eng.2"):
    for d in (day, day + dt.timedelta(days=1)):
        sb = D.get(f"{D.ESPN}/soccer/{lg}/scoreboard?dates={d.strftime('%Y%m%d')}")
        evs = sb.get("events") or []
        n = priced = 0
        sample = None
        for ev in evs:
            for c in ev.get("competitions") or []:
                n += 1
                pr = D.raw_prices(c, 3)
                priced += bool(pr)
                if sample is None:
                    sample = c.get("odds")
        print(f"{lg} {d}: {n} matches, raw_prices ok on {priced}")
        if sample is not None and lg in ("eng.1", "usa.1"):
            print("   odds block:", json.dumps(sample)[:1500])
        elif n and sample is None:
            print("   no 'odds' key on competitions; keys:",
                  sorted((evs[0].get("competitions") or [{}])[0].keys()))
# the per-event core odds endpoint, which the backtest reads
sb = D.get(f"{D.ESPN}/soccer/eng.1/scoreboard?dates={(day + dt.timedelta(days=1)).strftime('%Y%m%d')}")
for ev in (sb.get("events") or [])[:1]:
    eid = ev["id"]
    core = D.get(f"https://sports.core.api.espn.com/v2/sports/soccer/leagues/eng.1/events/{eid}/competitions/{eid}/odds")
    print("core odds items:", len((core or {}).get("items") or []))
    for it in ((core or {}).get("items") or [])[:2]:
        print("   ", (it.get("provider") or {}).get("name"),
              (it.get("awayTeamOdds") or {}).get("moneyLine"),
              (it.get("drawOdds") or {}).get("moneyLine"),
              (it.get("homeTeamOdds") or {}).get("moneyLine"))
