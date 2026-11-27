"""Back-to-back context for graded player props (research, information only).

2026-11-27: the README rows "NBA player props on the second night of a
back-to-back" (rejected) and "NHL Shots on Goal props on the second night of a
back-to-back" (on watch) came from one-off scripts; this reproduces them. Each
graded prop gets its player's team (from ESPN's box score for that game) and
whether that team also played the day before (ESPN's scoreboard), then the
two groups are compared with FanDuel's price by date half.

  python3 tools/prop_context.py nba|nhl [--cache DIR]
"""
import datetime as dt
import json
import math
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
SPORT = {"nba": "basketball/nba", "nhl": "hockey/nhl"}
SITE = "https://site.api.espn.com/apis/site/v2/sports/{}/{}"


def _get(u):
    req = urllib.request.Request(u, headers={"User-Agent": "prop-research"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def schedule(lg, start, end, get=_get):
    """{team abbr: set of dates it played} from ESPN's scoreboard, start..end."""
    out, day = {}, start
    while day <= end:
        try:
            sb = get(SITE.format(SPORT[lg], f"scoreboard?dates={day:%Y%m%d}"))
        except Exception:
            sb = {}
        for ev in sb.get("events") or []:
            for c in ev["competitions"][0]["competitors"]:
                out.setdefault(c["team"]["abbreviation"], set()).add(day.isoformat())
        day += dt.timedelta(days=1)
    return out


def team_map(lg, eid, get=_get):
    """{normalised player name: team abbr} from one game's box score."""
    import props_ledger as PL
    s = get(SITE.format(SPORT[lg], f"summary?event={eid}"))
    m = {}
    for t in (s.get("boxscore") or {}).get("players") or []:
        ab = t["team"]["abbreviation"]
        for grp in t.get("statistics") or []:
            for a in grp.get("athletes") or []:
                m[PL.norm_name(a["athlete"]["displayName"])] = ab
    return m


def tag(props, maps, sched):
    """[(prop, on_b2b)] for props whose player's team is known."""
    import props_ledger as PL
    out = []
    for e in props:
        tm = (maps.get(e["gid"].split(":", 1)[1]) or {}).get(PL.norm_name(e["name"]))
        if not tm or tm not in sched:
            continue
        prev = (dt.date.fromisoformat(e["date"]) - dt.timedelta(days=1)).isoformat()
        out.append((e, prev in sched[tm]))
    return out


def compare(rows):
    """Per date half: (b2b won, n, gap), (rested won, n, gap), z of the gap
    difference -- gap is points won above (+) or below FanDuel's implied chance."""
    dates = sorted({e["date"] for e, _ in rows})
    if len(dates) < 2:
        return []
    mid = dates[len(dates) // 2]

    def st(t):
        w = sum(e["status"] == "won" for e in t)
        ex = sum(e["imp"] for e in t)
        v = sum(e["imp"] * (1 - e["imp"]) for e in t)
        return w, len(t), (w - ex) / len(t) if t else 0.0, v / len(t) ** 2 if t else 0.0
    out = []
    for half in (lambda d: d < mid, lambda d: d >= mid):
        a = st([e for e, b in rows if b and half(e["date"])])
        r = st([e for e, b in rows if not b and half(e["date"])])
        z = (a[2] - r[2]) / math.sqrt(a[3] + r[3]) if a[1] and r[1] and (a[3] + r[3]) else 0.0
        out.append((a[:3], r[:3], z))
    return out


def main(argv):
    import props_ledger as PL
    lg = argv[1] if len(argv) > 1 else "nba"
    cache = argv[argv.index("--cache") + 1] if "--cache" in argv else None
    props = [e for e in PL.load().values() if e.get("league") == lg
             and e["status"] in ("won", "lost") and e.get("imp")]
    if not props:
        print(f"no graded {lg} props")
        return
    days = sorted(e["date"] for e in props)
    sched = schedule(lg, dt.date.fromisoformat(days[0]) - dt.timedelta(days=1), dt.date.fromisoformat(days[-1]))
    maps = {}
    for eid in sorted({e["gid"].split(":", 1)[1] for e in props}):
        f = os.path.join(cache, f"{lg}-{eid}.json") if cache else None
        if f and os.path.exists(f):
            maps[eid] = json.load(open(f))
            continue
        try:
            maps[eid] = team_map(lg, eid)
        except Exception:
            continue
        if f:
            os.makedirs(cache, exist_ok=True)
            json.dump(maps[eid], open(f, "w"))
        time.sleep(0.15)
    rows = tag(props, maps, sched)
    for i, (a, r, z) in enumerate(compare(rows)):
        print(f"{('earlier', 'later')[i]} half: back-to-back {a[0]}/{a[1]} ({100 * a[2]:+.1f} vs price), "
              f"rested {r[0]}/{r[1]} ({100 * r[2]:+.1f}), z {z:+.2f}")
    print(f"{len(rows)} of {len(props)} props placed")


if __name__ == "__main__":
    main(sys.argv)
