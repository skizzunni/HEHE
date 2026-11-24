"""Player-level NBA prop model: projected minutes x shrunk per-minute rates x
count/continuous distribution, mixed over minutes uncertainty.
Only games strictly before the prop game's start are used for a player's
history. The 'teammates out' input for historical tests is read from the prop
game's own box score (who did not play) -- a slight look-ahead proxy for the
injury report."""
import json, math, os, collections
import numpy as np
from scipy import stats as SS

HERE = os.path.dirname(os.path.abspath(__file__))
CUR = os.path.abspath(os.path.join(HERE, "..", "props", "cache"))
PREV = os.path.join(HERE, "cache_prev")
SEASON_START = "2026-10-20"
BASE = ("pts", "reb", "ast", "tpm")
COMBO = {"Points": ("pts",), "Rebounds": ("reb",), "Assists": ("ast",), "Threes Made": ("tpm",),
         "Pts + Ast": ("pts", "ast"), "Pts + Reb + Ast": ("pts", "reb", "ast"),
         "Pts + Reb": ("pts", "reb"), "Reb + Ast": ("reb", "ast")}
COUNT_MARKETS = {"Rebounds", "Assists", "Threes Made", "Reb + Ast"}   # NB / Poisson; others gamma

# structural hyper-parameters (fixed a priori, not tuned on props)
W_DECAY = 0.88       # weight of k-th most recent game: 0.88**k, last 10 games
K_MIN_PREV = 1.5     # prior-season minutes count as 1.5 games in the minutes mean
M_DEFAULT = 18.0     # minutes prior when no history at all (1 pseudo-game)
K_POS = 100.0        # pseudo-minutes of positional prior in the season rate
PREV_CAP = 600.0     # prior-season minutes counted at most this many
K_REC = 100.0        # pseudo-minutes of season rate when forming the recent rate
N0_PHI = 20.0        # pseudo-games of league dispersion
N0_MSD = 5.0         # pseudo-games of league minutes sd


def mins(s):
    try:
        if ":" in str(s):
            a, b = str(s).split(":"); return int(a) + int(b) / 60
        return float(s)
    except (TypeError, ValueError):
        return None


def _f(x):
    try:
        return float(str(x).split("-")[0])
    except (TypeError, ValueError):
        return 0.0


def load_games():
    games = {}
    for d, season in ((PREV, "2526"), (CUR, "2627")):
        for fn in os.listdir(d):
            if not fn.startswith("nba-"):
                continue
            sm = json.load(open(os.path.join(d, fn)))
            try:
                comp = sm["header"]["competitions"][0]
                start = comp["date"]
            except (KeyError, IndexError):
                continue
            if not ((comp.get("status") or {}).get("type") or {}).get("completed", True):
                continue
            if season == "2627" and start[:10] < SEASON_START:
                continue
            gid = "nba:" + fn[4:-5]
            teams = {}
            for team in (sm.get("boxscore") or {}).get("players") or []:
                abbr = (team.get("team") or {}).get("abbreviation")
                roster = teams.setdefault(abbr, {})
                for grp in team.get("statistics") or []:
                    keys = grp.get("keys") or []
                    for a in grp.get("athletes") or []:
                        ath = a.get("athlete") or {}
                        aid = str(ath.get("id") or "")
                        if not aid:
                            continue
                        st = dict(zip(keys, a.get("stats") or []))
                        m = mins(st.get("minutes")) or 0.0
                        pos = ((ath.get("position") or {}).get("abbreviation") or "F")[-1:]
                        pos = pos if pos in "GFC" else "F"
                        roster[aid] = dict(aid=aid, team=abbr, pos=pos, min=m, played=(m > 0 and not a.get("didNotPlay")),
                                           pts=_f(st.get("points")), reb=_f(st.get("rebounds")), ast=_f(st.get("assists")),
                                           tpm=_f(st.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted")),
                                           starter=bool(a.get("starter")), start=start, gid=gid, season=season,
                                           name=ath.get("displayName"))
            if len(teams) == 2:
                games[gid] = dict(start=start, season=season, teams=teams)
    return games


class DB:
    def __init__(self, games):
        self.games = games
        self.plog = collections.defaultdict(list)     # aid -> recs (played only), by start
        self.tlog = collections.defaultdict(list)     # (season, team) -> (start, gid, {aid: rec played})
        for gid, G in games.items():
            for abbr, ro in G["teams"].items():
                pl = {a: r for a, r in ro.items() if r["played"]}
                self.tlog[(G["season"], abbr)].append((G["start"], gid, pl))
                for r in pl.values():
                    self.plog[r["aid"]].append(r)
        for v in self.plog.values(): v.sort(key=lambda r: r["start"])
        for v in self.tlog.values(): v.sort(key=lambda t: t[0])
        self._league_priors()

    def _league_priors(self):
        """Positional per-minute rates, league dispersion per market and league
        minutes sd, all from the 2025-26 season only (entirely before any prop)."""
        tot = collections.defaultdict(lambda: collections.Counter())
        byp = collections.defaultdict(list)
        for aid, recs in self.plog.items():
            prev = [r for r in recs if r["season"] == "2526"]
            for r in prev:
                c = tot[r["pos"]]; c["min"] += r["min"]
                for s in BASE: c[s] += r[s]
            if len(prev) >= 20:
                byp[aid] = prev
        self.pos_rate = {p: {s: c[s] / c["min"] for s in BASE} for p, c in tot.items()}
        self.phi = {}
        for mk, comp in COMBO.items():
            num = den = 0.0
            for prev in byp.values():
                M = sum(r["min"] for r in prev); rate = sum(sum(r[s] for s in comp) for r in prev) / M
                for r in prev:
                    e = rate * r["min"]; x = sum(r[s] for s in comp)
                    num += (x - e) ** 2; den += e
            self.phi[mk] = num / den
        res = []
        for prev in byp.values():
            for i in range(5, len(prev)):
                res.append(prev[i]["min"] - np.mean([r["min"] for r in prev[max(0, i - 10):i]]))
        self.msd = float(np.std(res))
        # share of games a regular (trailing mean >= 20 min) plays < half his usual
        # minutes (injury exit, foul trouble, blowout): a left tail the normal misses
        lo = tot_n = 0
        for prev in byp.values():
            for i in range(5, len(prev)):
                m0 = np.mean([r["min"] for r in prev[max(0, i - 10):i]])
                if m0 >= 20:
                    tot_n += 1; lo += prev[i]["min"] < 0.5 * m0
        self.low_share = lo / tot_n

    def history(self, aid, before):
        recs = [r for r in self.plog.get(aid, []) if r["start"] < before]
        return [r for r in recs if r["season"] == "2627"], [r for r in recs if r["season"] == "2526"]

    def teammates_delta(self, aid, team, before, gid_today):
        """(freed_min, freed_usage) from teammates who are out (or back) today relative
        to how often they played in the player's own recent baseline games.
        'Today' = the prop game's box score (look-ahead proxy for the injury report)."""
        tg = [t for t in self.tlog.get(("2627", team), []) if t[0] < before][-10:]
        if not tg or gid_today not in self.games:
            return 0.0, 0.0
        today = {a for a, r in self.games[gid_today]["teams"].get(team, {}).items() if r["played"]}
        base_g = [t for t in tg if aid in t[2]]
        if not base_g:
            return 0.0, 0.0
        w = [W_DECAY ** k for k in range(len(base_g))][::-1]
        mates = collections.defaultdict(list)
        for t in tg:
            for a, r in t[2].items():
                if a != aid: mates[a].append(r)
        fm = fu = 0.0
        for a, rs in mates.items():
            if len(rs) < 2: continue
            pm = np.mean([r["min"] for r in rs])
            if pm < 12: continue
            ppg = np.mean([r["pts"] for r in rs])
            pres = sum(wi for wi, t in zip(w, base_g) if a in t[2]) / sum(w)
            d = pres - (1.0 if a in today else 0.0)
            fm += d * pm; fu += d * ppg / 115.0
        return fm, fu


def project(cur, prev, pos, freed_min, freed_usage, P, db_pos_rate, db_phi, db_msd, low_share=0.03):
    """Return dict(m, msd, rate{stat}, phi{market}) from prior games only."""
    last = cur[-10:][::-1]
    w = np.array([W_DECAY ** k for k in range(len(last))])
    mm = np.array([r["min"] for r in last])
    num, den = float((w * mm).sum()), float(w.sum())
    if prev:
        num += K_MIN_PREV * np.mean([r["min"] for r in prev[-30:]]); den += K_MIN_PREV
    if den == 0:
        num, den = M_DEFAULT, 1.0
    elif not prev and len(last) < 3:
        num += M_DEFAULT; den += 1.0
    m0 = num / den
    n = len(last)
    s2 = float(np.var(mm, ddof=1)) if n >= 3 else 0.0
    msd = math.sqrt(((n - 1) * s2 + N0_MSD * db_msd ** 2) / (max(n - 1, 0) + N0_MSD)) if n >= 3 else db_msd
    m = float(np.clip(m0 + P["c1"] * freed_min * m0 / 240.0, 1.0, 46.0))
    pr = db_pos_rate.get(pos, db_pos_rate["F"])
    Mc = sum(r["min"] for r in cur); pv = prev[-60:]; Mp = sum(r["min"] for r in pv)
    sc = min(1.0, PREV_CAP / Mp) if Mp else 0.0
    rate, base = {}, {}
    for s in BASE:
        Sc = sum(r[s] for r in cur); Sp = sum(r[s] for r in pv)
        b = (Sc + Sp * sc + K_POS * pr[s]) / (Mc + Mp * sc + K_POS)
        rx = float((w * np.array([r[s] for r in last])).sum()) if n else 0.0
        rm = float((w * mm).sum()) if n else 0.0
        base[s] = b
        rate[s] = (rx + K_REC * b) / (rm + K_REC) * max(0.5, 1.0 + P["c2"][s] * freed_usage)
    phi = {}
    g = pv[-30:] + cur
    for mk, comp in COMBO.items():
        rb = sum(base[s] for s in comp)
        e = np.array([rb * r["min"] for r in g]); x = np.array([sum(r[s] for s in comp) for r in g])
        ng = len(g)
        pi = float(((x - e) ** 2).sum() / e.sum()) if ng and e.sum() > 0 else db_phi[mk]
        phi[mk] = (ng * pi + N0_PHI * db_phi[mk]) / (ng + N0_PHI)
    return dict(q_low=low_share, m=m, m0=m0, msd=msd, rate=rate, base=base, phi=phi, n_cur=len(cur), n_prev=len(prev))


_Q = SS.norm.ppf((np.arange(15) + 0.5) / 15)


def p_reach(proj, market, line):
    """P(stat >= line) mixing over minutes: with prob 1-q_low N(m, msd) truncated
    to [1, 48]; with prob q_low uniform on [1, m/2] (early exit / blowout)."""
    q = proj.get("q_low", 0.0)
    a = _p_at(proj, market, line, np.clip(proj["m"] + proj["msd"] * _Q, 1.0, 48.0))
    b = _p_at(proj, market, line, np.linspace(1.0, max(1.0, proj["m"] / 2), 8))
    return float(np.clip((1 - q) * a + q * b, 1e-4, 1 - 1e-4))


def _p_at(proj, market, line, ms):
    comp = COMBO[market]
    r = sum(proj["rate"][s] for s in comp); phi = proj["phi"][market]
    mu = np.maximum(r * ms, 1e-3)
    if market in COUNT_MARKETS:
        if phi > 1.05:
            p = SS.nbinom.sf(line - 1, mu / (phi - 1.0), 1.0 / phi)
        else:
            p = SS.poisson.sf(line - 1, mu)
    else:
        phi = max(phi, 1.0)
        p = SS.gamma.sf(line - 0.5, mu / phi, scale=phi)
    return float(np.mean(p))
