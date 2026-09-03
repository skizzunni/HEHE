"""My model's pick and reasoning for any game, in any league it can rate.

    from picks import mlb_picks, elo_picks, tennis_picks

Every league gets a real forecast rather than an echo of the price:

  MLB      logistic on regressed run differential + the shrunk starter blend,
           then anchored to the de-vigged close at a fifth weight. Fitted and
           reported on disjoint slices of all 2,100 completed 2026 games with
           real closing prices; 56.8% raw against the line's 58.0%, and the
           anchor is what makes it usable -- its top calls go 71.7% where the
           run-rate chain it replaced went 56.7%.
  team     margin-of-victory Elo or point-differential power ratings, whichever
  sports   won that league's own held-out backtest (see anysport.TUNED)
  tennis   level-seeded surface Elo with an experience ramp (tennis_v2.py);
           ranking points remain only as the displayed reason and a fallback,
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
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

MLB = "https://statsapi.mlb.com/api/v1"
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
FIP_C = 3.085
W_SP, W_BP, W_FIP, W_T, HFA = 0.65, 0.30, 0.50, 0.05, 1.10

# ---------------------------------------------------------------- MLB weights
# The run-rate chain this file used to run -- team runs scored scaled by a
# blended opposing run allowed, then Pythagenpat, then a flat home bump --
# was scored against the real de-vigged DraftKings close on all 2,100 completed
# 2026 games, every input rebuilt as of each game morning so nothing saw its
# own result. It called 53.8% (Brier 0.2550) where the close called 56.5%
# (0.2449), and its confidence ran the wrong way: the games it liked most were
# the ones it lost. Worse, on the 55 games where it disagreed with the close by
# ten points or more it hit 47.3%.
#
# Replacing it with a logistic fit on the two inputs that survived a
# fit/choose/report split (regressed run differential, and the shrunk starter
# blend) lifted the untouched slice to 56.8% / 0.2438. Bullpen ERA, bullpen
# innings over the previous three days, starter rest and rest days were all
# fitted and all failed to earn their place.
#
# These are those coefficients folded into raw units, so p(away) is just
# sigmoid(MLB_B + sum of coefficient times feature). The features are built in
# mlb_picks below and must stay in the units they were fitted in: runs per game.
MLB_B = -0.096678
MLB_C_RATE = 0.227043          # (away rs-ra) - (home rs-ra), regressed
MLB_C_SP = 0.312014            # home starter runs - away starter runs
MLB_REG = 60.0                 # games of league average mixed into a team rate
MLB_SP_SHRINK = 70.0           # innings at which a starter is trusted by half

# Even refitted the model does not beat the close: on the untouched slice it
# scored 0.2438 against the line's 0.2408. So where a price exists the pick is
# taken from the line with the model allowed a fifth of the say. That weight
# was the best or joint-best of ten tried across three different feature sets,
# and it is what turns the model's own top calls from 56.7% into 71.7%: the
# picks it loses are the ones where it argued hardest with the price.
MLB_MKT_W = 0.20


def mlb_anchor(p_model, p_market):
    """Blend a model probability into a de-vigged price, in log-odds."""
    def _l(x):
        x = min(max(x, 1e-6), 1 - 1e-6)
        return math.log(x / (1 - x))
    z = (1 - MLB_MKT_W) * _l(p_market) + MLB_MKT_W * _l(p_model)
    return 1 / (1 + math.exp(-max(min(z, 30), -30)))

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
                                         ra=t["runsAllowed"] / gp, gp=gp, l10=l10)
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
                    w = ip / (ip + MLB_SP_SHRINK)
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
            # Team rates are regressed toward the league before they are used:
            # a club forty games in has a run differential that is a third
            # sampling noise, and the old chain took it at face value.
            def rate(t):
                w = t["gp"] / (t["gp"] + MLB_REG)
                return (w * t["rs"] + (1 - w) * lg, w * t["ra"] + (1 - w) * lg)

            ars, ara = rate(ta)
            hrs, hra = rate(th)
            f_rate = (ars - ara) - (hrs - hra)
            f_sp = eh[0] - ea[0]                  # lower runs allowed is better
            z = MLB_B + MLB_C_RATE * f_rate + MLB_C_SP * f_sp
            p = 1 / (1 + math.exp(-max(min(z, 30), -30)))   # away win probability
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
                pick=pick, conf=max(p, 1 - p), p_away=p,
                why=" · ".join(bits) or "team rates only")
    return out


# ------------------------------------------------- team sports via anysport
def elo_picks(league, day):
    """Ratings-based pick for any anysport league. -> {(away,home): dict}"""
    import anysport as A
    if league not in A.LEAGUES:
        return {}
    key, k, hfa, cap = A.TUNED.get(league, ("elo", 20, 50, None))
    # A soccer draw loses a 3-way moneyline, but Elo scores it as half a win, so
    # its raw expectation runs ~13 points hot on "does my side win outright".
    # This maps it onto the real rate; fitted on the pooled training half of
    # 12,460 matches and verified on the held-out half, where it cut Brier from
    # 0.2567 to 0.2436.
    soccer = A.LEAGUES[league][0].startswith("soccer/")
    DRAW_A, DRAW_B = -0.591, 1.485
    name, fn, _ = A.METHODS[key]
    games = A.fetch_games(league, A.season_dates(league))
    # Ratings start from last season's finish, regressed toward the mean,
    # instead of 1500 flat. Early in a season that is most of the signal.
    init = A.prior_ratings(league, key, k, hfa, cap)
    if len(games) < 40 and not init:
        return {}
    _, R, n = fn(games, k, hfa, cap=cap, init=init)
    sigma = getattr(A.run_power, "sigma", None) or 12.0
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
                # The spread of game margins, taken from the league's own games.
                # This was hardcoded at 12.0 -- a basketball number. Applied to
                # soccer, where a goal margin has a spread near 1.7, it divided
                # every edge by seven and squashed the whole league to 50-58%.
                # The backtest never saw it: anysport derives sigma from the
                # data, so the validated model and the shipped one disagreed.
                ph = 0.5 * (1 + math.erf(margin / (sigma * math.sqrt(2))))
            else:
                ph = 1 / (1 + 10 ** (-((R[hn] + hfa) - R[an]) / 400))
            if soccer:
                # The correction maps a raw Elo expectation onto "wins
                # OUTRIGHT". It has to be applied to BOTH sides: the old code
                # corrected the home number and then used 1 - ph for the away
                # side, which in a three-way market is P(away) + P(draw). Any
                # home favourite whose outright chance dipped under 50% flipped
                # to an away pick wearing the draw's probability -- hence the
                # model taking the underdog 38 times in 49 and those dogs
                # hitting 36.8% against a claimed ~58%.
                def outright(p):
                    p = min(max(p, 1e-6), 1 - 1e-6)
                    return 1 / (1 + math.exp(-(DRAW_A + DRAW_B * math.log(p / (1 - p)))))
                p_home, p_away = outright(ph), outright(1 - ph)
                home = p_home >= p_away
                ph = p_home if home else 1 - p_away      # so max(ph, 1-ph) is our side's outright chance
            else:
                home = ph > 0.5
            pick = hn if home else an
            gap = abs(R[hn] - R[an])
            f = form.get(pick, [])[-10:]
            # Elo sits near 1500; power ratings are a goal/point margin near
            # zero, so rounding both to integers printed every soccer rating
            # as "0 v -1 (+1)".
            fmt = (lambda v: f"{v:+.2f}") if key == "power" else (lambda v: f"{v:.0f}")
            bits = [f"rating {fmt(R[pick])} v {fmt(R[an if home else hn])} "
                    f"({'+' if key != 'power' else ''}{gap:.2f}" +
                    (" goals)" if key == "power" else ")")]
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
    # Ranking points are retained ONLY for the displayed reason string and as a
    # fallback. The probability now comes from tennis_v2's rating model.
    #
    # Why the switch: the ranking-points model scored 60.2% on August, but that
    # number is contaminated -- current rankings already contain the results of
    # the matches being predicted, and there is no dated rankings endpoint
    # (every ?date=/?week=/?season= variant returns the same current table).
    # The rating model is walk-forward, so its numbers are clean:
    #
    #   held out Jul+Aug, n=1996, tuned on Apr-Jun only
    #     level seeds only          59.12%   Brier 0.2338
    #     + experience ramp         65.33%   Brier 0.2204
    #     + surface blend           65.93%   Brier 0.2195
    #
    #   paired bootstrap of the ramp, 4000 resamples:
    #     d-accuracy +6.21pp, 95% CI [+4.36, +8.12], P(better) 1.000
    #     d-Brier   -0.0134,  95% CI [-0.0169, -0.0100], P(better) 1.000
    #
    # Antisymmetry is 2.2e-16 and shuffling which player is listed first moves
    # accuracy by 0.000, so the model is blind to field order. That is NOT proof
    # of no look-ahead -- an audit's positive control that reads the whole future
    # passes the same test. The look-ahead argument is structural: prior-match
    # counts are incremented only after scoring, and every parameter was fitted
    # on months disjoint from those reported.
    #
    # Expect less than +6.2pp live: 52.5% of held-out matches involve a player
    # with under 20 prior matches, which is an artifact of a rating pool that
    # cold-starts everyone in January. That coverage falls in a mature pool.
    def pts(p):
        r = rank.get(norm(p))
        return float(r["pts"]) if r and r.get("pts") else UN
    _rt = None
    try:
        import tennis_v2 as _TV
        _rt = _TV.Ratings().build(_TV.load_matches())
    except Exception as _e:
        sys.stderr.write("tennis: rating model unavailable (%s), "
                         "falling back to ranking points\n" % _e)
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
                    # A draw slot that has not been filled yet is published as
                    # "TBD". Rating it as an unranked 180-point player produced
                    # real-looking picks against an opponent who does not exist:
                    # four legs were sitting in the board's top tier at 73-83%
                    # confidence, labelled "strong", against nobody. Those
                    # matches are neither modellable nor bettable, so they are
                    # skipped until the draw resolves.
                    if any(p.strip().upper() == "TBD" for p in ps):
                        continue
                    seen.add(c.get("id"))
                    if _rt is not None:
                        major = bool(ev.get("major"))
                        rnd = (c.get("round") or {}).get("displayName", "")
                        men = "Men" in gname
                        p1 = _rt.prob(ps[0], ps[1],
                                      _TV._surface(ev.get("name"), et.date()),
                                      _TV._level(ev.get("name"), major, rnd),
                                      5 if (men and major and "qualif" not in rnd.lower()) else 3)
                    else:
                        lp = math.log(pts(ps[0])) - math.log(pts(ps[1]))
                        p1 = 1 / (1 + math.exp(-lp * 1.02))
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
