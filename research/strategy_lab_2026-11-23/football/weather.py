"""Kickoff weather for outdoor games in nfl.json / ncaaf.json from Open-Meteo's
historical archive (archive-api.open-meteo.com), one hourly request per venue
per season. Adds g["wx"] = {wind, gust, precip, temp}: mean wind (mph) and
gusts over the kickoff hour and the next two, precipitation (mm) summed over
those three hours. Domes (indoor=True) are skipped.

    python weather.py nfl.json ncaaf.json

NOTE: this is observed (reanalysis) weather, a stand-in for the forecast a
bettor would have had before kickoff -- an optimistic upper bound on what a
forecast-based rule could do.
"""
import concurrent.futures as cf
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
GEO = "https://geocoding-api.open-meteo.com/v1/search?count=10&language=en&format=json&name="
ARCH = ("https://archive-api.open-meteo.com/v1/archive?latitude={lat:.3f}&longitude={lon:.3f}"
        "&start_date={a}&end_date={b}&hourly=temperature_2m,precipitation,wind_speed_10m,wind_gusts_10m"
        "&wind_speed_unit=mph&temperature_unit=fahrenheit&timezone=UTC")
ST = dict(AL="Alabama", AK="Alaska", AZ="Arizona", AR="Arkansas", CA="California", CO="Colorado",
          CT="Connecticut", DE="Delaware", FL="Florida", GA="Georgia", HI="Hawaii", ID="Idaho",
          IL="Illinois", IN="Indiana", IA="Iowa", KS="Kansas", KY="Kentucky", LA="Louisiana",
          ME="Maine", MD="Maryland", MA="Massachusetts", MI="Michigan", MN="Minnesota",
          MS="Mississippi", MO="Missouri", MT="Montana", NE="Nebraska", NV="Nevada",
          NH="New Hampshire", NJ="New Jersey", NM="New Mexico", NY="New York", NC="North Carolina",
          ND="North Dakota", OH="Ohio", OK="Oklahoma", OR="Oregon", PA="Pennsylvania",
          RI="Rhode Island", SC="South Carolina", SD="South Dakota", TN="Tennessee", TX="Texas",
          UT="Utah", VT="Vermont", VA="Virginia", WA="Washington", WV="West Virginia",
          WI="Wisconsin", WY="Wyoming", DC="District of Columbia")


def get(url, path):
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except ValueError:
            pass
    for k in range(4):
        try:
            with urllib.request.urlopen(url, timeout=40) as r:
                j = json.load(r)
            json.dump(j, open(path, "w"))
            return j
        except Exception:
            time.sleep(2 + 3 * k)
    return None


def geo(city, state):
    p = os.path.join(CACHE, ("geo-%s-%s.json" % (city, state)).replace("/", "_").replace(" ", "_"))
    j = get(GEO + urllib.parse.quote(city), p) or {}
    want = ST.get(state, state)
    res = j.get("results") or []
    for r in res:
        if want and (r.get("admin1") == want or r.get("country") == want):
            return r["latitude"], r["longitude"]
    if res and not want:
        return res[0]["latitude"], res[0]["longitude"]
    return None


def main(files):
    data = {f: json.load(open(f)) for f in files}
    locs, need = {}, {}
    for f, G in data.items():
        for g in G.values():
            if g.get("indoor") or not g.get("odds") or not g.get("city"):
                continue
            k = (g["city"], g["state"])
            locs.setdefault(k, None)
    with cf.ThreadPoolExecutor(4) as ex:
        for k, v in zip(list(locs), ex.map(lambda k: geo(*k), list(locs))):
            locs[k] = v
    print(len(locs), "locations,", sum(v is None for v in locs.values()), "not found", flush=True)
    for f, G in data.items():
        for g in G.values():
            if g.get("indoor") or not g.get("odds") or not locs.get((g.get("city"), g.get("state"))):
                continue
            ll = locs[(g["city"], g["state"])]
            need.setdefault((round(ll[0], 3), round(ll[1], 3), g["season"]), []).append(g)
    keys = list(need)

    def fetch(k):
        lat, lon, s = k
        gs = need[k]
        a = min(g["date"][:10] for g in gs)
        b = max(g["date"][:10] for g in gs)
        b = (dt.date.fromisoformat(b) + dt.timedelta(days=1)).isoformat()
        return get(ARCH.format(lat=lat, lon=lon, a=a, b=b),
                   os.path.join(CACHE, f"wx-{lat:.3f}-{lon:.3f}-{a}-{b}.json"))
    n = 0
    with cf.ThreadPoolExecutor(4) as ex:
        for k, j in zip(keys, ex.map(fetch, keys)):
            h = (j or {}).get("hourly") or {}
            idx = {t: i for i, t in enumerate(h.get("time") or [])}
            for g in need[k]:
                t = dt.datetime.fromisoformat(g["date"].replace("Z", "+00:00")).replace(minute=0)
                ii = [idx.get((t + dt.timedelta(hours=d)).strftime("%Y-%m-%dT%H:%M")) for d in range(3)]
                if None in ii:
                    continue
                def vals(name):
                    return [h[name][i] for i in ii if h[name][i] is not None]
                w, gu, pr, te = vals("wind_speed_10m"), vals("wind_gusts_10m"), vals("precipitation"), vals("temperature_2m")
                if len(w) == 3 and len(pr) == 3:
                    g["wx"] = dict(wind=sum(w) / 3, gust=max(gu) if gu else None, precip=sum(pr),
                                   temp=sum(te) / len(te) if te else None)
                    n += 1
    for f, G in data.items():
        json.dump(G, open(f, "w"))
    print(n, "games with weather", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
