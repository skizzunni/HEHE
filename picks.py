"""My model's pick and reasoning for any game, in any league it can rate.

    from picks import mlb_picks, elo_picks, tennis_picks

Every league gets a real forecast rather than an echo of the price:

  MLB      starter ERA/FIP (regressed) .65 + bullpen ERA .30 + team run rates .05
  team     margin-of-victory Elo or point-differential power ratings, whichever
  sports   won that league's own held-out backtest (see anysport.TUNED)
  tennis   ranking points, p = 1/(1+exp(-(ln ptsA - ln ptsB)*scale)),
           scale 1.02 both ranked / 0.78 otherwise

Each pick carries the numbers that produced it, so the reasoning is inspectable
rather than asserted. Held-out accuracy by league is recorded in the README;
nothing here has been shown to beat a closing price.
"""
import datetime as dt
import json
import math
import re
import ssl
import statistics as st
import urllib.request
from concurrent.futures import ThreadPoolExecutor

MLB = "https://statsapi.mlb.com/api/v1"
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
FIP_C = 3.085
W_SP, W_BP, W_FIP, W_T, HFA = 0.65, 0.30, 0.50, 0.05, 1.10

_CTX = ssl.create_default_context()
try:
    _CTX.load_verify_locations("/root/.ccr/ca-bundle.crt")
except OSError:
    pass


def get(url, tries=2):
    for a in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=40, context=_CTX) as r:
                return json.load(r)
        except Exception:
            pass
    return {}


def _ip(s):
    try:
        f = float(s)
    except (TypeError, ValueError):
        return 0.0
    w = int(f)
    return w + round((f - w) * 10) / 3.0


# ------------------------------------------------------------------ MLB
def mlb_picks(day):
    """day: YYYYMMDD. -> {(away_full, home_full): dict(pick, conf, why)}"""
    year = day[:4]
    stand = get(f"{MLB}/standings?leagueId=103,104&season={year}"
                f"&standingsTypes=regularSeason")
    team = {}
    for rec in stand.get("records", []):
        for t in rec.get("teamRecords", []):
            lr = t.get("leagueRecord", {})
            gp = (lr.get("wins", 0) + lr.get("losses", 0)) or 1
            sp = t.get("records", {}).get("splitRecords", [])
            l10 = next((f'{x["wins"]}-{x["losses"]}' for x in sp
                        if x.get("type") == "lastTen"), "?")
            team[t["team"]["id"]] = dict(rs=t["runsScored"] / gp,
                                         ra=t["runsAllowed"] / gp, l10=l10)
    if not team:
        return {}
    lg = st.mean(v["rs"] for v in team.values())
    pen = {}
    bs = get(f"{MLB}/teams/stats?season={year}&sportId=1&group=pitching"
             f"&stats=statSplits&sitCodes=rp")
    try:
        for s in bs["stats"][0]["splits"]:
            pen[s["team"]["id"]] = float(s["stat"]["era"])
    except (KeyError, IndexError, ValueError):
        pass

    sched = get(f"{MLB}/schedule?sportId=1&date={day[:4]}-{day[4:6]}-{day[6:]}"
                f"&hydrate=probablePitcher,team&gameType=R")
    ids = set()
    for d in sched.get("dates", []):
        for g in d.get("games", []):
            for s in ("away", "home"):
                pp = g["teams"][s].get("probablePitcher") or {}
                if pp.get("id"):
                    ids.add(pp["id"])

    def arm(pid):
        j = get(f"{MLB}/people/{pid}?hydrate=stats(group=[pitching],"
                f"type=[season],season={year})")
        try:
            p = j["people"][0]
            for s in p.get("stats", []):
                if s.get("splits"):
                    x = s["splits"][0]["stat"]
                    ip = _ip(x.get("inningsPitched", "0"))
                    if ip < 1:
                        break
                    era = float(x["era"])
                    k = int(x.get("strikeOuts", 0))
                    bb = int(x.get("baseOnBalls", 0)) + int(x.get("hitBatsmen", 0))
                    hr = int(x.get("homeRuns", 0))
                    fip = (13 * hr + 3 * bb - 2 * k) / ip + FIP_C
                    w = ip / (ip + 70.0)
                    blend = W_FIP * fip + (1 - W_FIP) * era
                    return pid, (w * blend + (1 - w) * lg, p["fullName"], era, fip, ip)
            return pid, (lg, j["people"][0]["fullName"], None, None, 0)
        except Exception:
            return pid, (lg, "TBD", None, None, 0)

    arms = {}
    if ids:
        with ThreadPoolExecutor(max_workers=12) as ex:
            for pid, v in ex.map(arm, ids):
                arms[pid] = v

    out = {}
    for d in sched.get("dates", []):
        for g in d.get("games", []):
            a, h = g["teams"]["away"], g["teams"]["home"]
            ai, hi = a["team"]["id"], h["team"]["id"]
            if ai not in team or hi not in team:
                continue
            ta, th = team[ai], team[hi]
            ea = arms.get((a.get("probablePitcher") or {}).get("id"),
                          (lg, "TBD", None, None, 0))
            eh = arms.get((h.get("probablePitcher") or {}).get("id"),
                          (lg, "TBD", None, None, 0))
            da = W_SP * ea[0] + W_BP * pen.get(ai, lg) + W_T * ta["ra"]
            dh = W_SP * eh[0] + W_BP * pen.get(hi, lg) + W_T * th["ra"]
            ra, rh = ta["rs"] * (dh / lg), th["rs"] * (da / lg)
            e = 1.83
            p = ra ** e / (ra ** e + rh ** e)
            o = p / (1 - p) / HFA
            p = o / (1 + o)                       # away win probability
            away = p > 0.5
            pick = a["team"]["name"] if away else h["team"]["name"]
            mine, theirs = (ea, eh) if away else (eh, ea)
            mypen = pen.get(ai if away else hi, lg)
            oppen = pen.get(hi if away else ai, lg)
            bits = []
            if mine[2] is not None and theirs[2] is not None:
                bits.append(f"{mine[1].split()[-1]} {mine[2]:.2f} ERA"
                            + (f"/{mine[3]:.2f} FIP" if mine[3] else "")
                            + f" vs {theirs[1].split()[-1]} {theirs[2]:.2f}")
            elif mine[1] != "TBD" or theirs[1] != "TBD":
                bits.append(f"{mine[1].split()[-1]} vs {theirs[1].split()[-1]}")
            if abs(mypen - oppen) >= 0.35:
                bits.append(f"pen {mypen:.2f} v {oppen:.2f}")
            fa, fh = (ta, th) if away else (th, ta)
            if fa["l10"] != fh["l10"]:
                bits.append(f'L10 {fa["l10"]} v {fh["l10"]}')
            out[(a["team"]["name"], h["team"]["name"])] = dict(
                pick=pick, conf=max(p, 1 - p), why=" · ".join(bits) or "team rates only")
    return out


# ------------------------------------------------- team sports via anysport
def elo_picks(league, day):
    """Ratings-based pick for any anysport league. -> {(away,home): dict}"""
    import anysport as A
    if league not in A.LEAGUES:
        return {}
    key, k, hfa, cap = A.TUNED.get(league, ("elo", 20, 50, None))
    name, fn, _ = A.METHODS[key]
    games = A.fetch_games(league, A.season_dates(league))
    if len(games) < 40:
        return {}
    _, R, n = fn(games, k, hfa, cap=cap)
    form = {}
    for g in games[-400:]:
        for t, won in ((g["home"], g["hs"] > g["as_"]), (g["away"], g["as_"] > g["hs"])):
            form.setdefault(t, []).append(won)
    d = get(f'{ESPN}/{A.LEAGUES[league][0]}/scoreboard?dates={day}')
    out = {}
    for ev in d.get("events", []):
        for c in ev.get("competitions", []):
            cs = {x.get("homeAway"): x for x in (c.get("competitors") or [])}
            if "home" not in cs or "away" not in cs:
                continue
            hn = (cs["home"].get("team") or {}).get("displayName")
            an = (cs["away"].get("team") or {}).get("displayName")
            if not hn or not an:
                continue
            if key == "power":
                margin = R[hn] - R[an] + hfa
                ph = 0.5 * (1 + math.erf(margin / (12.0 * math.sqrt(2))))
            else:
                ph = 1 / (1 + 10 ** (-((R[hn] + hfa) - R[an]) / 400))
            home = ph > 0.5
            pick = hn if home else an
            gap = abs(R[hn] - R[an])
            f = form.get(pick, [])[-10:]
            bits = [f"rating {R[pick]:.0f} v {R[an if home else hn]:.0f} (+{gap:.0f})"]
            if len(f) >= 5:
                bits.append(f"last {len(f)}: {sum(f)}-{len(f)-sum(f)}")
            if home:
                bits.append("at home")
            out[(an, hn)] = dict(pick=pick, conf=max(ph, 1 - ph),
                                 why=" · ".join(bits), model=name)
    return out


# ------------------------------------------------------------- tennis
def tennis_picks(day, tour=None):
    """Ranking-points model over the day's singles matches.

    `tour` limits the result to one feed ("atp" or "wta"); without it the ATP and
    WTA tabs both render every match on both tours.
    """
    def norm(s):
        return re.sub(r"\s+", " ", (s or "").strip()).lower()
    rank = {}
    for lgk in ("atp", "wta"):
        d = get(f"{ESPN}/tennis/{lgk}/rankings")
        for e in (d.get("rankings") or [{}])[0].get("ranks", []):
            a = e.get("athlete") or {}
            if a.get("displayName"):
                rank[norm(a["displayName"])] = dict(rank=e.get("current"),
                                                    pts=e.get("points"))
    UN = 180.0
    # Scales fitted on Jan-Jul and validated on August; see tennis.py for the
    # backtest. A single 0.80 was under-confident whenever both players were
    # ranked. Picks are unchanged -- only the stated confidence moves.
    S_RANKED, S_OTHER = 1.02, 0.78
    def pts(p):
        r = rank.get(norm(p))
        return float(r["pts"]) if r and r.get("pts") else UN
    def scaled(p):
        r = rank.get(norm(p))
        return bool(r and r.get("pts"))
    out, seen = {}, set()
    for lgk in ([tour] if tour else ["atp", "wta"]):
        d = get(f"{ESPN}/tennis/{lgk}/scoreboard?dates={day}")
        for ev in d.get("events", []):
            for grp in ev.get("groupings", []):
                gname = (grp.get("grouping") or {}).get("displayName", "")
                if "Singles" not in gname:
                    continue
                if tour == "atp" and "Women" in gname:
                    continue
                if tour == "wta" and "Men" in gname:
                    continue
                for c in grp.get("competitions", []):
                    if c.get("id") in seen:
                        continue
                    try:
                        t = dt.datetime.strptime(c.get("date", ""), "%Y-%m-%dT%H:%MZ")
                    except ValueError:
                        continue
                    et = t.replace(tzinfo=dt.timezone.utc).astimezone(
                        dt.timezone(dt.timedelta(hours=-4)))
                    if et.strftime("%Y%m%d") != day:
                        continue
                    ps = [(x.get("athlete") or {}).get("displayName")
                          for x in c.get("competitors", [])]
                    if len(ps) != 2 or not all(ps):
                        continue
                    seen.add(c.get("id"))
                    lp = math.log(pts(ps[0])) - math.log(pts(ps[1]))
                    sc = S_RANKED if (scaled(ps[0]) and scaled(ps[1])) else S_OTHER
                    p1 = 1 / (1 + math.exp(-lp * sc))
                    pick = ps[0] if p1 >= 0.5 else ps[1]
                    r1 = (rank.get(norm(ps[0])) or {}).get("rank")
                    r2 = (rank.get(norm(ps[1])) or {}).get("rank")
                    # name the PICK's rank first -- otherwise the reason reads as
                    # though the winner is the lower-ranked player
                    mine, theirs = (r1, r2) if pick == ps[0] else (r2, r1)
                    out[(ps[0], ps[1])] = dict(
                        pick=pick, conf=max(p1, 1 - p1),
                        why=f'rank {mine or "NR"} vs {theirs or "NR"}')
    return out
