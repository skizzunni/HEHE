"""Fetch 2025-26 NBA regular-season box scores (prior-season priors). Slimmed to
header date + boxscore.players. At most 8 concurrent requests."""
import datetime as dt, json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, "cache_prev")
SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
def get(url, tries=3):
    err = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=25) as r:
                return json.load(r)
        except Exception as ex:
            err = ex; time.sleep(1 + i)
    print("fail", url, err, file=sys.stderr); return None
def sb(d):
    p = os.path.join(C, f"sb-{d:%Y%m%d}.json")
    if os.path.exists(p): return json.load(open(p))
    j = get(f"{SITE}/scoreboard?dates={d:%Y%m%d}&limit=100")
    if j is None: return None
    ev = [dict(id=e["id"], st=(e.get("season") or {}).get("type"),
               done=((e.get("status") or {}).get("type") or {}).get("completed")) for e in j.get("events") or []]
    json.dump(ev, open(p, "w")); return ev
def summ(eid):
    p = os.path.join(C, f"nba-{eid}.json")
    if os.path.exists(p): return
    j = get(f"{SITE}/summary?event={eid}")
    if j is None: return
    comp = j["header"]["competitions"][0]
    slim = dict(header=dict(competitions=[dict(date=comp["date"], status=comp.get("status"),
                competitors=[dict(id=c.get("id"), homeAway=c.get("homeAway")) for c in comp.get("competitors", [])])]),
                boxscore=dict(players=(j.get("boxscore") or {}).get("players") or []))
    json.dump(slim, open(p, "w"))
days = []; d = dt.date(2025, 10, 21)
while d <= dt.date(2026, 4, 13): days.append(d); d += dt.timedelta(days=1)
with ThreadPoolExecutor(8) as ex: sbs = list(ex.map(sb, days))
ids = sorted({e["id"] for s in sbs for e in (s or []) if e["st"] == 2 and e["done"]})
print(len(ids), "games", flush=True)
with ThreadPoolExecutor(8) as ex: list(ex.map(summ, ids))
print("done", len([f for f in os.listdir(C) if f.startswith("nba-")]))
