"""Recent NBA minutes for the daily card's prop caution.

Strategy lab, 2026-11-23 (README): NBA props on players who averaged under 20
minutes over their prior 5 games hit 71.8% vs 83.5% stated (z -3.97 then -1.54
by date half) -- short in both halves but past the 2.8 bar in only one, so it
is shown as a caution beside the prop, never used to drop one.

mpg_last5(gid, names) looks the game's two rosters up on ESPN, then each named
player's game log, and returns {name: minutes per game over his last 5 games
played}. Any failure returns what it has; the card never waits on it."""
import json
import urllib.request

LOW_MPG = 20.0
NOTE = "under 20 min a game lately; props like it hit 72% vs 84% stated"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={}"
ROSTER = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{}/roster"
GAMELOG = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba/athletes/{}/gamelog"


def _get(url, timeout=15):
    try:
        return json.load(urllib.request.urlopen(url, timeout=timeout))
    except Exception:
        return None


def last5(gamelog):
    """Minutes per game over the last 5 games he played (MIN > 0), newest by
    game date, from an ESPN gamelog payload; None with no games."""
    if not gamelog:
        return None
    labels = gamelog.get("labels") or []
    if "MIN" not in labels:
        return None
    i = labels.index("MIN")
    dates = {k: (v or {}).get("gameDate") or "" for k, v in (gamelog.get("events") or {}).items()}
    rows = []
    for st in gamelog.get("seasonTypes") or []:
        if "Regular" not in (st.get("displayName") or ""):
            continue
        for cat in st.get("categories") or []:
            for ev in cat.get("events") or []:
                try:
                    m = float(ev["stats"][i])
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
                if m > 0:
                    rows.append((dates.get(ev.get("eventId"), ""), m))
    rows.sort(reverse=True)
    rows = rows[:5]
    return round(sum(m for _, m in rows) / len(rows), 1) if rows else None


def mpg_last5(gid, names, get=_get):
    """{name: mpg over last 5} for the named players in this NBA game."""
    eid = str(gid).split(":")[-1]
    s = get(SUMMARY.format(eid)) or {}
    comps = (((s.get("header") or {}).get("competitions") or [{}])[0]).get("competitors") or []
    want = {n.lower(): n for n in names}
    ids = {}
    for c in comps:
        r = get(ROSTER.format((c.get("team") or {}).get("id"))) or {}
        for a in r.get("athletes") or []:
            n = (a.get("displayName") or "").lower()
            if n in want:
                ids[want[n]] = a.get("id")
    out = {}
    for name, aid in ids.items():
        v = last5(get(GAMELOG.format(aid)))
        if v is not None:
            out[name] = v
    return out
