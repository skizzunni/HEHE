"""Fetch ESPN scoreboards + game summaries (box scores) for NBA/NHL/NFL games
since the season start, into work/strategy_lab/props/cache/. Read-only w.r.t.
the bot's files (props.json is only read; .cache/summaries is only read)."""
import datetime as dt, json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
C = os.path.join(HERE, "cache")
SITE = "https://site.api.espn.com/apis/site/v2/sports"
SP = {"nba": "basketball/nba", "nhl": "hockey/nhl", "nfl": "football/nfl"}
START = {"nba": dt.date(2026, 10, 1), "nhl": dt.date(2026, 10, 1), "nfl": dt.date(2026, 9, 1)}
END = dt.date(2026, 11, 22)

def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
                return json.load(r)
        except Exception as ex:
            err = ex; time.sleep(1 + i)
    print("fail", url, err, file=sys.stderr); return None

def scoreboard(lg, d):
    p = os.path.join(C, f"sb-{lg}-{d:%Y%m%d}.json")
    if os.path.exists(p):
        return json.load(open(p))
    j = get(f"{SITE}/{SP[lg]}/scoreboard?dates={d:%Y%m%d}&limit=100")
    if j is not None:
        json.dump(j, open(p, "w"))
    return j

def summary(lg, eid):
    p = os.path.join(C, f"{lg}-{eid}.json")
    if os.path.exists(p):
        return
    q = os.path.join(ROOT, ".cache", "summaries", f"{lg}-{eid}.json")
    if False:   # the bot's cached summaries are slimmed (no header/start time): always fetch
        j = None
    else:
        j = get(f"{SITE}/{SP[lg]}/summary?event={eid}")
    if j is not None:
        json.dump(j, open(p, "w"))

jobs = []
for lg in SP:
    d = START[lg]
    days = []
    while d <= END:
        days.append(d); d += dt.timedelta(days=1)
    with ThreadPoolExecutor(8) as ex:
        sbs = list(ex.map(lambda x: (x, scoreboard(lg, x)), days))
    for d, sb in sbs:
        for ev in (sb or {}).get("events") or []:
            st = ((ev.get("season") or {}).get("type"))
            done = ((ev.get("status") or {}).get("type") or {}).get("completed")
            if st == 2 and done:
                jobs.append((lg, ev["id"]))
# plus every graded prop game in these leagues
book = json.load(open(os.path.join(ROOT, "props.json")))
for e in book.values():
    lg, eid = e["gid"].split(":", 1)
    if lg in SP:
        jobs.append((lg, eid))
jobs = sorted(set(jobs))
print(len(jobs), "summaries")
with ThreadPoolExecutor(8) as ex:
    list(ex.map(lambda j: summary(*j), jobs))
print("done", len([f for f in os.listdir(C) if not f.startswith("sb-")]))
