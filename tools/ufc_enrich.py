"""Add ESPN's detailed data to each fight in ufc_history.json: DraftKings odds
(moneyline, open, total-rounds line and its prices), both fighters' fight
stats, and fighter bio (age at the fight, height, reach, stance; cached per
athlete in ufc_athletes.json). Only fights from `since` that lack it.

    python tools/ufc_enrich.py 2022-01-01
"""
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, "ufc_history.json")
ATH = os.path.join(ROOT, "ufc_athletes.json")
CORE = "https://sports.core.api.espn.com/v2/sports/mma"


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** i)
        except Exception:
            time.sleep(2 ** i)
    return None


def odds(eid, cid):
    d = get(f"{CORE}/leagues/ufc/events/{eid}/competitions/{cid}/odds") or {}
    it = (d.get("items") or [None])[0]
    if not it:
        return None
    # MMA has no home or away fighter and the two odds blocks are NOT in
    # competitor order (see picks.ufc_picks): key each price by the athlete
    # id its own $ref names, never by block position
    ml, op = {}, {}
    for k in ("awayAthleteOdds", "homeAthleteOdds"):
        v = it.get(k) or {}
        aid = str((v.get("athlete") or {}).get("$ref", "")).rsplit("/", 1)[-1].split("?")[0]
        if aid:
            ml[aid] = v.get("moneyLine")
            op[aid] = ((v.get("open") or {}).get("moneyLine") or {}).get("american")
    return dict(book=(it.get("provider") or {}).get("name"), ml=ml, open=op,
                ou=it.get("overUnder"), over=it.get("overOdds"), under=it.get("underOdds"))


def stats(eid, cid, aid):
    d = get(f"{CORE}/leagues/ufc/events/{eid}/competitions/{cid}/competitors/{aid}/statistics") or {}
    out = {}
    for c in (d.get("splits") or {}).get("categories") or []:
        for s in c.get("stats") or []:
            out[s.get("name")] = s.get("value")
    return out or None


def order(eid, cid):
    """{athlete id: 'home'|'away'} for the competition."""
    d = get(f"{CORE}/leagues/ufc/events/{eid}/competitions/{cid}/competitors") or {}
    return {x.get("id"): ("away" if x.get("order") == 1 else "home") for x in d.get("items") or []}


def bio(aid, cache):
    if aid in cache:
        return cache[aid]
    d = get(f"{CORE}/athletes/{aid}") or {}
    cache[aid] = dict(dob=(d.get("dateOfBirth") or "")[:10] or None, height=d.get("height"), reach=d.get("reach"),
                      stance=(d.get("stance") or {}).get("text"))
    return cache[aid]


def main(since):
    with open(HIST) as fh:
        book = json.load(fh)
    try:
        with open(ATH) as fh:
            cache = json.load(fh)
    except (OSError, ValueError):
        cache = {}
    todo = [(cid, f) for cid, f in sorted(book.items(), key=lambda kv: kv[1].get("date") or "")
            if (f.get("date") or "") >= since and f.get("eid") and not (f.get("odds") or {}).get("ml")]
    for i, (cid, f) in enumerate(todo):
        eid = f["eid"]
        f["odds"] = odds(eid, cid)
        f.pop("side", None)
        for x in (f["a"], f["b"]):
            x["stats"] = stats(eid, cid, x["id"])
            bio(x["id"], cache)
        if i % 50 == 49 or i == len(todo) - 1:
            with open(HIST, "w") as fh:
                json.dump(book, fh)
            with open(ATH, "w") as fh:
                json.dump(cache, fh)
            print(f"{i + 1}/{len(todo)} fights enriched", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2022-01-01")
