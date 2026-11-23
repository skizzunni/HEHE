"""ESPN history for college basketball and MLB: every regular-season game, its
closing moneyline / spread (run line) / total, matched to teams by team id.
MLB also gets per-pitcher box-score lines from the game summary.

    python fetch.py ncaab data/ncaab.json 2022 2023 2024 2025   # season start years
    python fetch.py mlb   data/mlb.json   2022 2023 2024 2025
    python fetch.py mlbbox data/mlb.json                          # adds pitching lines

Odds book preference: DraftKings (40), ESPN BET (58), then any other real
book (no consensus/teamrankings/accuscore, no Live). A side's line is the
book's 'current' value after the game was final (= its last pre-game line),
falling back to 'close', then the top-level field; '+0' placeholders are
rejected. Both sides must fit together (same points, overround 0-12%).
At most 8 concurrent requests. Research only."""
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request

CFG = {
    "ncaab": ("basketball", "mens-college-basketball", "&groups=50&limit=400"),
    "mlb": ("baseball", "mlb", "&limit=100"),
}


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception:
            time.sleep(0.5 + i)
    return None


def days(sport, y):
    if sport == "ncaab":
        d, end = dt.date(y, 11, 1), dt.date(y + 1, 3, 17)
    else:
        d, end = dt.date(y, 3, 15), dt.date(y, 10, 6)
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def num(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("+", "").strip()
    if s.upper() in ("EVEN", "EV", "PK"):
        return 100.0 if s.upper() != "PK" else 0.0
    try:
        return float(s)
    except ValueError:
        return None


def imp(a):
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def stat(t, name):
    for s in t.get("statistics") or []:
        if s.get("name") == name:
            return num(s.get("displayValue"))
    return None


def games_on(args):
    sport, day = args
    s, l, extra = CFG[sport]
    j = get(f"https://site.api.espn.com/apis/site/v2/sports/{s}/{l}/scoreboard?dates={day:%Y%m%d}{extra}") or {}
    out = []
    for e in j.get("events", []):
        c = (e.get("competitions") or [{}])[0]
        if (e.get("season") or {}).get("type") != 2:
            continue
        if not ((c.get("status") or {}).get("type") or {}).get("completed"):
            continue
        side = {}
        for t in c.get("competitors", []):
            d = dict(id=t["team"]["id"], name=t["team"].get("displayName"), abbr=t["team"].get("abbreviation"),
                     conf=(t["team"].get("conferenceId")), score=int(float(t.get("score") or 0)))
            if sport == "ncaab":
                d.update(fga=stat(t, "fieldGoalsAttempted"), fta=stat(t, "freeThrowsAttempted"))
            else:
                pr = [p for p in t.get("probables") or [] if p.get("name") == "probableStartingPitcher"]
                d["probable"] = (pr[0].get("athlete") or {}).get("id") if pr else None
                d["hits"] = t.get("hits")
            side[t["homeAway"]] = d
        if "home" in side and "away" in side:
            g = dict(id=e["id"], date=e["date"], day=day.isoformat(), season=(e.get("season") or {}).get("year"),
                     neutral=bool(c.get("neutralSite")), conf_game=bool(c.get("conferenceCompetition")),
                     home=side["home"], away=side["away"])
            if sport == "mlb":
                g["innings"] = len((c.get("competitors") or [{}])[0].get("linescores") or [])
            out.append(g)
    return out


def _side_val(x, key, top):
    """Last pre-game value of x[key]: current, then close, then top-level."""
    for blk in ("current", "close"):
        v = (x.get(blk) or {}).get(key)
        if isinstance(v, dict):
            val = num(v.get("american") if v.get("american") is not None else v.get("alternateDisplayValue"))
            if val is not None and val != 0:      # '+0' is ESPN's empty placeholder
                return val
    return num(x.get(top)) if top else None


def odds_for(args):
    sport, g = args
    s, l, _ = CFG[sport]
    j = get(f"https://sports.core.api.espn.com/v2/sports/{s}/leagues/{l}/events/{g['id']}/competitions/{g['id']}/odds") or {}
    items = [i for i in j.get("items", []) if "Live" not in ((i.get("provider") or {}).get("name") or "")
             and str((i.get("provider") or {}).get("id")) not in ("1001", "1002", "1004")
             and "consensus" not in ((i.get("provider") or {}).get("name") or "").lower()]
    pref = {"40": 0, "58": 1}
    items.sort(key=lambda i: pref.get(str((i.get("provider") or {}).get("id")), 2))
    out = {}
    for it in items:
        by = {}
        for k in ("awayTeamOdds", "homeTeamOdds"):
            x = it.get(k) or {}
            m = re.search(r"/teams/(\d+)", ((x.get("team") or {}).get("$ref") or ""))
            if not m:
                continue
            by[m.group(1)] = dict(ml=_side_val(x, "moneyLine", "moneyLine"),
                                  pt=_side_val(x, "pointSpread", None),
                                  sp=_side_val(x, "spread", "spreadOdds"))
        h, a = by.get(g["home"]["id"]), by.get(g["away"]["id"])
        if not h or not a:
            continue
        book = (it.get("provider") or {}).get("name")
        if "ml" not in out and h["ml"] and a["ml"] and abs(h["ml"]) >= 100 and abs(a["ml"]) >= 100 \
                and 1.0 <= imp(h["ml"]) + imp(a["ml"]) <= 1.12:
            out.update(ml=dict(book=book, home=h["ml"], away=a["ml"]))
        if "spread" not in out and h["pt"] is not None and a["pt"] is not None and h["pt"] == -a["pt"] and h["pt"] != 0 \
                and h["sp"] and a["sp"] and 1.0 <= imp(h["sp"]) + imp(a["sp"]) <= 1.12:
            out.update(spread=dict(book=book, home_pts=h["pt"], home=h["sp"], away=a["sp"]))
        ou, oo, uo = num(it.get("overUnder")), num(it.get("overOdds")), num(it.get("underOdds"))
        if "total" not in out and ou and oo and uo and 1.0 <= imp(oo) + imp(uo) <= 1.12:
            out.update(total=dict(book=book, line=ou, over=oo, under=uo))
        if len(out) == 3:
            break
    return out


def box_for(g):
    j = get(f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary?event={g['id']}")
    if not j:
        return None
    res = {}
    for p in (j.get("boxscore") or {}).get("players") or []:
        tid = str((p.get("team") or {}).get("id"))
        for s in p.get("statistics") or []:
            if s.get("type") != "pitching":
                continue
            names = s.get("names") or s.get("labels")
            rows = []
            for a in s.get("athletes") or []:
                st = dict(zip(names, a.get("stats") or []))
                rows.append(dict(pid=a["athlete"]["id"], starter=bool(a.get("starter")),
                                 ip=st.get("IP"), h=st.get("H"), er=st.get("ER"), bb=st.get("BB"),
                                 k=st.get("K"), hr=st.get("HR"), pc=st.get("PC")))
            res[tid] = rows
    return res


def main():
    sport, out = sys.argv[1], sys.argv[2]
    have = json.load(open(out)) if os.path.exists(out) else {}
    if sport == "mlbbox":
        todo = [g for g in have.values() if "box" not in g]
        print("box todo", len(todo), flush=True)
        with cf.ThreadPoolExecutor(8) as ex:
            for i, (g, b) in enumerate(zip(todo, ex.map(box_for, todo))):
                g["box"] = b
                if i % 1000 == 999:
                    print(i + 1, flush=True)
                    json.dump(have, open(out, "w"))
        json.dump(have, open(out, "w"))
        return
    years = [int(y) for y in sys.argv[3:]]
    ds = [(sport, d) for y in years for d in days(sport, y)]
    with cf.ThreadPoolExecutor(8) as ex:
        for gs in ex.map(games_on, ds):
            for g in gs:
                have.setdefault(g["id"], g)
    print(len(have), "games", flush=True)
    todo = [g for g in have.values() if "odds" not in g]
    with cf.ThreadPoolExecutor(8) as ex:
        for i, (g, o) in enumerate(zip(todo, ex.map(odds_for, [(sport, g) for g in todo]))):
            g["odds"] = o
            if i % 2000 == 1999:
                print(i + 1, flush=True)
                json.dump(have, open(out, "w"))
    json.dump(have, open(out, "w"))
    n = len(have)
    print(n, "games;", {k: sum(1 for g in have.values() if k in (g.get("odds") or {})) for k in ("ml", "spread", "total")})


if __name__ == "__main__":
    main()
