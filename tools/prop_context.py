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

NHL only, from ESPN box scores (position and ice time per player per game):
`--by position` splits Shots on Goal props by defencemen vs forwards (README
row 2026-11-28, rejected); `--by icetime` splits 1+ Shots on Goal props by the
player's average ice time over his last 3-5 box scores, under ICE_CUT minutes
vs more (README row 2026-11-28, on watch). `--by teamshots` / `--by oppshots`
split 1+ Shots on Goal props by the player's team's shots for, or the
opponent's shots allowed, over each team's last 4-10 box scores -- bottom third
vs the rest (README row 2026-11-28: rejected / on watch).

`--by band` (NHL): 1+ Shots on Goal by FanDuel price band (-1500 or shorter,
-1000 to -1499, -500 to -999), each band against its own price by date half
(README row 2026-11-28: every band short, the heavy band the closest).

`--by total` (NBA): props split by the game's over/under from ESPN's pickcenter,
highest third vs the rest and lowest third vs the rest (README row 2026-11-28,
"NBA player props by the game's total": high on watch, low rejected).

  python3 tools/prop_context.py nba|nhl|nfl [--by chance|weekend|early|position|icetime|teamshots|oppshots|total|band] [--cache DIR]
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


ICE_CUT, ICE_GAMES = 19.0, 5


def _mins(v):
    """'17:27' -> 17.45 minutes; None when it is not a clock."""
    try:
        m, sec = str(v).split(":")
        return int(m) + int(sec) / 60
    except ValueError:
        return None


def nhl_box(eid, get=_get):
    """{normalised player name: (position abbr, ice time in minutes or None)}
    from one NHL game's ESPN box score."""
    import props_ledger as PL
    s = get(SITE.format(SPORT["nhl"], f"summary?event={eid}"))
    out = {}
    for t in (s.get("boxscore") or {}).get("players") or []:
        for grp in t.get("statistics") or []:
            keys = grp.get("keys") or []
            for a in grp.get("athletes") or []:
                st = dict(zip(keys, a.get("stats") or []))
                pos = (a["athlete"].get("position") or {}).get("abbreviation")
                out[PL.norm_name(a["athlete"]["displayName"])] = (pos, _mins(st.get("timeOnIce")))
    return out


def position_tag(props, boxes):
    """[(prop, is_defenceman)] for props whose player has a skater position."""
    import props_ledger as PL
    out = []
    for e in props:
        pos = ((boxes.get(e["gid"].split(":", 1)[1]) or {}).get(PL.norm_name(e["name"])) or (None,))[0]
        if pos in ("D", "C", "LW", "RW", "F"):
            out.append((e, pos == "D"))
    return out


def icetime_tag(props, boxes, cut=ICE_CUT, games=ICE_GAMES, min_games=3):
    """[(prop, recent_ice_time_under_cut)] -- the average of the player's last
    `games` box scores dated before the prop (at least min_games of them).
    boxes: {event id: nhl_box()}; each event's date comes from the props."""
    import collections
    import props_ledger as PL
    day = {e["gid"].split(":", 1)[1]: e["date"] for e in props}
    hist = collections.defaultdict(list)
    for eid, m in boxes.items():
        for n, (_, toi) in m.items():
            if toi is not None and eid in day:
                hist[n].append((day[eid], toi))
    out = []
    for e in props:
        prev = sorted(x for x in hist[PL.norm_name(e["name"])] if x[0] < e["date"])[-games:]
        if len(prev) >= min_games:
            out.append((e, sum(v for _, v in prev) / len(prev) < cut))
    return out


def nhl_team_box(eid, get=_get):
    """{"shots": {team abbr: shots on goal}, "players": {normalised name: team abbr}}
    from one NHL game's ESPN box score."""
    import props_ledger as PL
    s = get(SITE.format(SPORT["nhl"], f"summary?event={eid}"))
    box = s.get("boxscore") or {}
    shots = {}
    for t in box.get("teams") or []:
        st = {x.get("name"): x.get("displayValue") for x in t.get("statistics") or []}
        v = st.get("shotsTotal")
        try:
            shots[t["team"]["abbreviation"]] = float(v)
        except (TypeError, ValueError):
            shots[t["team"]["abbreviation"]] = None
    players = {}
    for t in box.get("players") or []:
        for grp in t.get("statistics") or []:
            for a in grp.get("athletes") or []:
                players[PL.norm_name(a["athlete"]["displayName"])] = t["team"]["abbreviation"]
    return {"shots": shots, "players": players}


def shots_tag(props, teams, side="opp", games=10, min_games=4):
    """[(prop, in_bottom_third)] -- side "team": the player's team's shots for;
    "opp": the opponent's shots allowed; each averaged over that team's last
    `games` box scores dated before the prop (at least min_games).
    teams: {event id: nhl_team_box()}; event dates come from the props."""
    import collections
    import props_ledger as PL
    day = {e["gid"].split(":", 1)[1]: e["date"] for e in props}
    hist = collections.defaultdict(list)          # abbr -> [(date, shots for, shots against)]
    for eid, d in teams.items():
        ab = list(d["shots"])
        if len(ab) != 2 or eid not in day:
            continue
        for a, o in (ab, ab[::-1]):
            hist[a].append((day[eid], d["shots"][a], d["shots"][o]))

    def avg(tm, date, i):
        v = [x[i] for x in sorted(x for x in hist[tm] if x[0] < date)[-games:] if x[i] is not None]
        return sum(v) / len(v) if len(v) >= min_games else None
    vals = []
    for e in props:
        d = teams.get(e["gid"].split(":", 1)[1])
        tm = d and d["players"].get(PL.norm_name(e["name"]))
        if not tm or len(d["shots"]) != 2:
            continue
        opp = next(x for x in d["shots"] if x != tm)
        a = avg(tm, e["date"], 1) if side == "team" else avg(opp, e["date"], 2)
        if a is not None:
            vals.append((e, a))
    if not vals:
        return []
    cut = sorted(v for _, v in vals)[len(vals) // 3]
    return [(e, v < cut) for e, v in vals]


def game_total(lg, eid, get=_get):
    """The game's over/under from ESPN's pickcenter (the first provider with
    one), or None."""
    s = get(SITE.format(SPORT[lg], f"summary?event={eid}"))
    for pc in s.get("pickcenter") or []:
        try:
            return float(pc["overUnder"])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def total_tag(props, totals, third="high"):
    """[(prop, game_in_that_third)] for props whose game has a total:
    third "high" -- total at or above the upper-third cut; "low" -- under the
    lower-third cut. totals: {event id: over/under}."""
    rows = [(e, totals.get(e["gid"].split(":", 1)[1])) for e in props]
    rows = [(e, t) for e, t in rows if t]
    if not rows:
        return []
    v = sorted(t for _, t in rows)
    lo, hi = v[len(v) // 3], v[2 * len(v) // 3]
    return [(e, t >= hi if third == "high" else t < lo) for e, t in rows]


BANDS = ((-10**6, -1500, "-1500 or shorter"), (-1499, -1000, "-1000 to -1499"), (-999, -500, "-500 to -999"))


def band_halves(props, bands=BANDS):
    """[(band, half, won, n, priced, z)] -- each price band against FanDuel's
    implied chance, split at the band's own median date."""
    def price(e):
        try:
            return int(str(e.get("price")))
        except ValueError:
            return None
    out = []
    for lo, hi, name in bands:
        t = [e for e in props if price(e) is not None and lo <= price(e) <= hi]
        dates = sorted({e["date"] for e in t})
        if len(dates) < 2:
            continue
        mid = dates[len(dates) // 2]
        for half, f in (("first", lambda d: d < mid), ("second", lambda d: d >= mid)):
            x = [e for e in t if f(e["date"])]
            imp = [-price(e) / (-price(e) + 100) for e in x]
            w = sum(e["status"] == "won" for e in x)
            ex, v = sum(imp), sum(i * (1 - i) for i in imp)
            out.append((name, half, w, len(x), ex, (w - ex) / math.sqrt(v) if v else 0.0))
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
    if by in ("position", "icetime"):
        if lg != "nhl":
            print("--by position / icetime are NHL only")
            return
        props = [e for e in props if e.get("market") == "Shots on Goal"]
        boxes = {}
        for eid in sorted({e["gid"].split(":", 1)[1] for e in props}):
            f = os.path.join(cache, f"box-{eid}.json") if cache else None
            if f and os.path.exists(f):
                boxes[eid] = {k: tuple(v) for k, v in json.load(open(f)).items()}
                continue
            try:
                boxes[eid] = nhl_box(eid)
            except Exception:
                continue
            if f:
                os.makedirs(cache, exist_ok=True)
                json.dump(boxes[eid], open(f, "w"))
            time.sleep(0.1)
        if by == "position":
            rows, labels = position_tag(props, boxes), ("defencemen", "forwards")
        else:
            rows = icetime_tag([e for e in props if e.get("line") == "1+"], boxes)
            labels = (f"under {ICE_CUT:g} min lately", f"{ICE_CUT:g} min+")
        for i, (a, r, z) in enumerate(compare(rows)):
            print(f"{('earlier', 'later')[i]} half: {labels[0]} {a[0]}/{a[1]} ({100 * a[2]:+.1f} vs price), "
                  f"{labels[1]} {r[0]}/{r[1]} ({100 * r[2]:+.1f}), z {z:+.2f}")
        print(f"{len(rows)} of {len(props)} props placed")
        return
    if by == "band":
        sog = [e for e in props if e.get("market") == "Shots on Goal" and e.get("line") == "1+"]
        for name, half, w, n, ex, z in band_halves(sog):
            print(f"{name}, {half} half: {w}/{n} against {ex:.1f} priced (z {z:+.2f})")
        return
    if by == "total":
        totals = {}
        for eid in sorted({e["gid"].split(":", 1)[1] for e in props}):
            f = os.path.join(cache, f"total-{lg}-{eid}.json") if cache else None
            if f and os.path.exists(f):
                totals[eid] = json.load(open(f))
                continue
            try:
                totals[eid] = game_total(lg, eid)
            except Exception:
                continue
            if f:
                os.makedirs(cache, exist_ok=True)
                json.dump(totals[eid], open(f, "w"))
            time.sleep(0.1)
        for third in ("high", "low"):
            for i, (a, r, z) in enumerate(compare(total_tag(props, totals, third))):
                print(f"{('earlier', 'later')[i]} half: {third}est third of totals {a[0]}/{a[1]} "
                      f"({100 * a[2]:+.1f} vs price), rest {r[0]}/{r[1]} ({100 * r[2]:+.1f}), z {z:+.2f}")
        return
    if by in ("teamshots", "oppshots"):
        if lg != "nhl":
            print("--by teamshots / oppshots are NHL only")
            return
        props = [e for e in props if e.get("market") == "Shots on Goal" and e.get("line") == "1+"]
        teams = {}
        for eid in sorted({e["gid"].split(":", 1)[1] for e in props}):
            f = os.path.join(cache, f"team-{eid}.json") if cache else None
            if f and os.path.exists(f):
                teams[eid] = json.load(open(f))
                continue
            try:
                teams[eid] = nhl_team_box(eid)
            except Exception:
                continue
            if f:
                os.makedirs(cache, exist_ok=True)
                json.dump(teams[eid], open(f, "w"))
            time.sleep(0.1)
        rows = shots_tag(props, teams, "team" if by == "teamshots" else "opp")
        lab = "team shoots least (bottom third)" if by == "teamshots" else "opponent allows fewest (bottom third)"
        for i, (a, r, z) in enumerate(compare(rows)):
            print(f"{('earlier', 'later')[i]} half: {lab} {a[0]}/{a[1]} ({100 * a[2]:+.1f} vs price), "
                  f"rest {r[0]}/{r[1]} ({100 * r[2]:+.1f}), z {z:+.2f}")
        print(f"{len(rows)} of {len(props)} props placed")
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
