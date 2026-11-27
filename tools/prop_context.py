"""Back-to-back context for graded player props (research, information only).

2026-11-27: the README rows "NBA player props on the second night of a
back-to-back" (rejected) and "NHL Shots on Goal props on the second night of a
back-to-back" (on watch) came from one-off scripts; this reproduces them. Each
graded prop gets its player's team (from ESPN's box score for that game) and
whether that team also played the day before (ESPN's scoreboard), then the
two groups are compared with FanDuel's price by date half.

The same props can be split by the player's team's chance to win instead
(DraftKings no-vig from sources.json): `--by chance` compares the team at
DOG_MAX or under (blowout risk, starters sit) with the team at FAV_MIN or over,
the README rows "NBA / NHL player props by the player's team's chance to win".

`--by weekend` splits by Saturday / Sunday vs Monday-Friday (no fetch needed),
the README row "NBA / NHL props on weekends vs weekdays" (on watch).

`--by early` splits by kickoff before 3 PM ET vs later (start from sources.json;
EST, UTC-5), the README row "NFL props by kickoff slot" (on watch).

  python3 tools/prop_context.py nba|nhl|nfl [--by chance|weekend|early] [--cache DIR]
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
SPORT = {"nba": "basketball/nba", "nhl": "hockey/nhl", "nfl": "football/nfl"}
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


DOG_MAX, FAV_MIN = 0.4, 0.6


def abbr_names(maps, games):
    """{team abbr: full name} -- the name that sits beside the abbr in every
    game it played (box scores carry abbrs, sources.json full names)."""
    import collections
    cand = {}
    for eid, m in maps.items():
        g = games.get(eid)
        ab = sorted(set(m.values()))
        if not g or len(ab) != 2:
            continue
        for a in ab:
            cand.setdefault(a, collections.Counter()).update([g["home"], g["away"]])
    return {a: c.most_common(1)[0][0] for a, c in cand.items()}


def chance_tag(props, maps, games, dog_max=DOG_MAX, fav_min=FAV_MIN):
    """[(prop, team_is_underdog)] for props whose player's team is at dog_max
    or under, or fav_min or over (DK no-vig chance; the middle is left out).
    games: {event id: sources.json game with p.dk the home chance}."""
    import props_ledger as PL
    names = abbr_names(maps, games)
    out = []
    for e in props:
        eid = e["gid"].split(":", 1)[1]
        g, m = games.get(eid), maps.get(eid) or {}
        tm = m.get(PL.norm_name(e["name"]))
        ph = ((g or {}).get("p") or {}).get("dk") if isinstance((g or {}).get("p"), dict) else None
        if not tm or ph is None or names.get(tm) not in (g["home"], g["away"]):
            continue
        p = ph if names[tm] == g["home"] else 1 - ph
        if p <= dog_max or p >= fav_min:
            out.append((e, p <= dog_max))
    return out


def early_tag(props, games, hour=15):
    """[(prop, kickoff_before_hour_ET)] for props whose game has a start in
    sources.json (games: {event id: game})."""
    out = []
    for e in props:
        st = (games.get(e["gid"].split(":", 1)[1]) or {}).get("start")
        if not st:
            continue
        try:
            t = dt.datetime.fromisoformat(str(st).replace("Z", "+00:00")) - dt.timedelta(hours=5)
        except ValueError:
            continue
        out.append((e, t.hour < hour))
    return out


def weekend_tag(props):
    """[(prop, on_a_weekend)] by the prop's ET date."""
    return [(e, dt.date.fromisoformat(e["date"]).weekday() >= 5) for e in props]


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
    by = argv[argv.index("--by") + 1] if "--by" in argv else None
    if by == "early":
        src = (json.load(open(os.path.join(os.path.dirname(HERE), "sources.json"))).get("games") or {})
        games = {k.split(":", 1)[1]: v for k, v in src.items() if k.startswith(lg + ":")}
        for i, (a, r, z) in enumerate(compare(early_tag(props, games))):
            print(f"{('earlier', 'later')[i]} half: before 3 PM ET {a[0]}/{a[1]} ({100 * a[2]:+.1f} vs price), "
                  f"later {r[0]}/{r[1]} ({100 * r[2]:+.1f}), z {z:+.2f}")
        return
    if by == "weekend":
        for i, (a, r, z) in enumerate(compare(weekend_tag(props))):
            print(f"{('earlier', 'later')[i]} half: weekend {a[0]}/{a[1]} ({100 * a[2]:+.1f} vs price), "
                  f"weekday {r[0]}/{r[1]} ({100 * r[2]:+.1f}), z {z:+.2f}")
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
    if by == "chance":
        src = (json.load(open(os.path.join(os.path.dirname(HERE), "sources.json"))).get("games") or {})
        games = {k.split(":", 1)[1]: v for k, v in src.items() if k.startswith(lg + ":")}
        rows, labels = chance_tag(props, maps, games), (f"team {int(100 * DOG_MAX)}% or under",
                                                         f"team {int(100 * FAV_MIN)}%+")
    else:
        rows, labels = tag(props, maps, sched), ("back-to-back", "rested")
    for i, (a, r, z) in enumerate(compare(rows)):
        print(f"{('earlier', 'later')[i]} half: {labels[0]} {a[0]}/{a[1]} ({100 * a[2]:+.1f} vs price), "
              f"{labels[1]} {r[0]}/{r[1]} ({100 * r[2]:+.1f}), z {z:+.2f}")
    print(f"{len(rows)} of {len(props)} props placed")


if __name__ == "__main__":
    main(sys.argv)
