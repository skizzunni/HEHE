#!/usr/bin/env python3
"""Collect every completed 2026 ATP/WTA singles match from ESPN, with the
context the current model throws away: surface, tour level, round, best-of.

    python3 collect_tennis.py 2026-01-01 2026-09-03
"""
import json, os, sys, time, re, datetime as dt, urllib.request

ESPN = "https://site.api.espn.com/apis/site/v2/sports/tennis"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data", "espn_cache")
OUT = os.path.join(HERE, "data", "matches_2026.json")

# Surface by tournament name. Falls back to a calendar heuristic, which is
# right for the overwhelming majority of the tour but not all of it.
CLAY = ["roland garros", "french open", "monte", "madrid", "rome", "italian",
        "barcelona", "munich", "estoril", "houston", "marrakech", "bucharest",
        "gstaad", "umag", "kitzbuhel", "bastad", "hamburg", "geneva", "lyon",
        "santiago", "buenos aires", "rio", "cordoba", "charleston", "stuttgart wta",
        "strasbourg", "rabat", "iasi", "palermo", "warsaw", "prague", "parma"]
GRASS = ["wimbledon", "queen", "halle", "stuttgart", "s-hertogenbosch", "hertogenbosch",
         "eastbourne", "mallorca", "newport", "birmingham", "nottingham", "berlin"]


def surface(name, date):
    n = (name or "").lower()
    for k in GRASS:
        if k in n:
            return "grass"
    for k in CLAY:
        if k in n:
            return "clay"
    m = date.month, date.day
    if (4, 1) <= m <= (6, 12):
        return "clay"
    if (6, 13) <= m <= (7, 20):
        return "grass"
    return "hard"


def level(name, major, rnd):
    n = (name or "").lower()
    if "qualif" in (rnd or "").lower():
        return "qual"
    if major:
        return "slam"
    if any(k in n for k in ("masters", "indian wells", "miami open", "monte-carlo",
                            "madrid open", "italian open", "canadian", "cincinnati",
                            "shanghai", "paris masters", "finals")):
        return "masters"
    if "challenger" in n or "itf" in n:
        return "challenger"
    return "tour"


def get(url, key):
    p = os.path.join(CACHE, key + ".json")
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            pass
    for attempt in range(3):
        try:
            # No custom headers: ESPN 403s any User-Agent it does not recognise,
            # which is why tennis.py's own get() sends none either.
            with urllib.request.urlopen(url, timeout=45) as r:
                d = json.load(r)
            os.makedirs(CACHE, exist_ok=True)
            with open(p, "w") as f:
                json.dump(d, f)
            return d
        except Exception:
            time.sleep(0.8 * (attempt + 1))
    return None


def main():
    start = dt.date.fromisoformat(sys.argv[1])
    end = dt.date.fromisoformat(sys.argv[2])
    out, seen = [], set()
    d = start
    n_days = 0
    while d <= end:
        ds = d.strftime("%Y%m%d")
        for tour in ("atp", "wta"):
            js = get("%s/%s/scoreboard?dates=%s" % (ESPN, tour, ds), "%s_%s" % (tour, ds))
            if not js:
                continue
            for ev in js.get("events", []):
                ename, major = ev.get("name"), bool(ev.get("major"))
                for grp in ev.get("groupings", []):
                    draw = (grp.get("grouping") or {}).get("displayName", "")
                    if "Singles" not in draw:
                        continue
                    for c in grp.get("competitions", []):
                        cid = c.get("id")
                        if not cid or cid in seen:
                            continue
                        comps = c.get("competitors", [])
                        if len(comps) != 2:
                            continue
                        names = [(x.get("athlete") or {}).get("displayName") for x in comps]
                        wins = [x.get("winner") for x in comps]
                        if not all(names) or wins.count(True) != 1:
                            continue
                        cd = (c.get("date") or "")[:10]
                        try:
                            mdate = dt.date.fromisoformat(cd)
                        except ValueError:
                            mdate = d
                        rnd = (c.get("round") or {}).get("displayName", "")
                        seen.add(cid)
                        w = 0 if wins[0] else 1
                        out.append({
                            # NOT the endpoint queried: combined events are returned
                            # by both feeds, so derive the tour from the draw.
                            "id": cid, "date": mdate.isoformat(),
                            "tour": "atp" if "Men" in draw else "wta",
                            "event": ename, "draw": "M" if "Men" in draw else "W",
                            "round": rnd, "surface": surface(ename, mdate),
                            "level": level(ename, major, rnd),
                            # ESPN reports periods:5 for every match including
                            # women's and Bo3 tour events, so it is unusable.
                            # Men play Bo5 only in Slam main draw.
                            "bo": 5 if ("Men" in draw and major
                                        and "qualif" not in (rnd or "").lower()) else 3,
                            "winner": names[w], "loser": names[1 - w],
                        })
        n_days += 1
        if n_days % 25 == 0:
            sys.stderr.write("%s ... %d matches\n" % (d, len(out)))
            sys.stderr.flush()
        d += dt.timedelta(days=1)
    out.sort(key=lambda m: (m["date"], m["id"]))
    with open(OUT, "w") as f:
        json.dump(out, f)
    print("collected %d matches -> %s" % (len(out), OUT))
    from collections import Counter
    print("by surface:", dict(Counter(m["surface"] for m in out)))
    print("by level:  ", dict(Counter(m["level"] for m in out)))
    print("by draw:   ", dict(Counter(m["draw"] for m in out)))


if __name__ == "__main__":
    main()
