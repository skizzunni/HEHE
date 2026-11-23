"""NHL API boxscores (starting goalies, shots on goal) for regular-season games.
    python nhl_box.py raw/box.json 2022 2023 2024 2025 2026
Game ids are {season}02{NNNN}; stops a season after 15 consecutive misses.
6 concurrent requests, 3 retries."""
import concurrent.futures as cf, json, sys, time, urllib.request, os

def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research script)"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return "404"
            time.sleep(1 + i)
        except Exception:
            time.sleep(1 + i)
    return None

def slim(j):
    if not isinstance(j, dict) or j.get("gameType") != 2 or j.get("gameState") not in ("OFF", "FINAL"):
        return None
    out = dict(id=j["id"], date=j["gameDate"], start=j.get("startTimeUTC"),
               last=(j.get("gameOutcome") or {}).get("lastPeriodType"))
    for s in ("homeTeam", "awayTeam"):
        t = j[s]
        gs = []
        for g in j["playerByGameStats"][s]["goalies"]:
            gs.append(dict(pid=g["playerId"], name=g["name"]["default"], starter=bool(g.get("starter")),
                           sa=g.get("shotsAgainst", 0), sv=g.get("saves", 0), toi=g.get("toi")))
        out[s[:4]] = dict(tri=t["abbrev"], score=t["score"], sog=t.get("sog"), goalies=gs)
    return out

def main(out, years):
    have = {}
    if os.path.exists(out):
        have = json.load(open(out))
    for y in years:
        n, step = 1, 48
        while True:
            ids = [f"{y}02{k:04d}" for k in range(n, n + step) if f"{y}02{k:04d}" not in have]
            with cf.ThreadPoolExecutor(6) as ex:
                res = list(ex.map(lambda i: get(f"https://api-web.nhle.com/v1/gamecenter/{i}/boxscore"), ids))
            miss = 0
            for i, r in zip(ids, res):
                s = slim(r)
                if s: have[i] = s
                else: miss += 1
            if n > 1320 or (ids and miss == len(ids)):
                break
            n += step
        json.dump(have, open(out, "w"))
        print(y, sum(1 for k in have if k.startswith(str(y))), flush=True)

if __name__ == "__main__":
    main(sys.argv[1], [int(x) for x in sys.argv[2:]])
