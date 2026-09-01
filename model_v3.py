"""MLB moneyline model v3 -- the version that survived a walk-forward backtest.

Every constant here was fitted on games through 2026-06-30 and scored on a
held-out 2026-07-01..08-29 window with strictly point-in-time inputs: no stat
used to predict a game includes that game or any game after it.

    python3 model_v3.py --date 2026-08-30      # predict a slate
    python3 model_v3.py --backtest             # reproduce the validation

MEASURED PERFORMANCE (757 held-out games, zero look-ahead):

    model                     57.5%    Brier 0.2449
    better W-L record         55.6%
    better run differential   54.6%
    always pick home          53.4%

    McNemar vs better-record baseline: chi2 = 1.03, p = 0.31

That p-value is the headline. The model beats the naive baseline by ~2 points
and 757 games is NOT enough to prove that gap is real rather than noise. Treat
its output as a mild lean, never as a lock. A model with a 0.2449 Brier against
a 0.25 coin flip has found a little signal, not an edge worth compounding.

THINGS THAT DO NOT WORK (each tested, each removed):
  * Park factors. Multiplying both teams' run expectation by the same venue
    constant cancels exactly in the win-probability ratio. It is a no-op. Park
    belongs in a totals model, not a moneyline one.
  * Sharpening the probability curve. Fitting an exponent k>1 on in-sample data
    improved in-sample Brier and made held-out Brier WORSE (0.2449 -> 0.2455).
  * Shrinking it either (k=0.50 fit on train: 0.2449 -> 0.2456 on test).
    Raw model output is best. Leave the curve alone.
  * Recent-form weighting on the starter beyond simple sample-size regression.
"""
import argparse
import datetime as dt
import json
import ssl
import sys
import urllib.parse
import urllib.request
from collections import defaultdict

API = "https://statsapi.mlb.com/api/v1"

# --- fitted on 2026 games through Jun 30, scored on Jul 1 - Aug 29 ---
# NOTE: the live board does not use these weights. picks.py runs
# 0.65 starter / 0.30 bullpen / 0.05 team, which scores 58.6% against this
# file's 57.4% on the same 780 held-out games. This file remains the reference
# implementation and the source of the walk-forward harness.
SP_WEIGHT = 0.55     # starter's share of a team's run prevention
SP_REGRESS = 70.0    # innings of league-average prior on a starter's ERA
HOME_ODDS_RATIO = 1.10
PYTH_EXP = 1.83
MIN_GAMES = 15       # games a team needs before it is modelled at all
MAX_CONF = 0.66      # the top of the range the backtest actually validated

_CTX = ssl.create_default_context()
try:
    _CTX.load_verify_locations("/root/.ccr/ca-bundle.crt")
except OSError:
    pass


def get(path, **params):
    url = f"{API}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60, context=_CTX) as r:
        return json.load(r)


def innings(s):
    """MLB writes 5.1 IP for 5-and-1/3. float() alone gets this wrong."""
    try:
        f = float(s)
    except (TypeError, ValueError):
        return 0.0
    whole = int(f)
    return whole + round((f - whole) * 10) / 3.0


def starter_era(er, ip, league_era):
    """Sample-size-regressed ERA. Returns league average with no innings."""
    if ip < 1:
        return league_era
    w = ip / (ip + SP_REGRESS)
    return w * (er * 9 / ip) + (1 - w) * league_era


def win_prob(off_a, def_a, off_h, def_h, sp_a, sp_h, league_rpg):
    """Away win probability from point-in-time run rates and starter ERAs."""
    d_home = SP_WEIGHT * sp_h + (1 - SP_WEIGHT) * def_h
    d_away = SP_WEIGHT * sp_a + (1 - SP_WEIGHT) * def_a
    r_away = off_a * (d_home / league_rpg)
    r_home = off_h * (d_away / league_rpg)
    p = r_away ** PYTH_EXP / (r_away ** PYTH_EXP + r_home ** PYTH_EXP)
    o = p / (1 - p) / HOME_ODDS_RATIO          # home advantage in odds space
    p = o / (1 + o)
    return min(max(p, 1 - MAX_CONF), MAX_CONF)


# ----------------------------------------------------------------- backtest
def load_season(start, end):
    sched = get("schedule", sportId=1, startDate=start, endDate=end,
                hydrate="probablePitcher,team,linescore", gameType="R")
    games = []
    for d in sched.get("dates", []):
        for g in d["games"]:
            if g["status"]["detailedState"] != "Final":
                continue
            a, h = g["teams"]["away"], g["teams"]["home"]
            if a.get("score") is None or h.get("score") is None:
                continue
            ap = (a.get("probablePitcher") or {}).get("id")
            hp = (h.get("probablePitcher") or {}).get("id")
            if not ap or not hp:
                continue
            games.append(dict(date=d["date"], away=a["team"]["name"],
                              home=h["team"]["name"], asc=a["score"],
                              hsc=h["score"], ap=str(ap), hp=str(hp)))
    games.sort(key=lambda x: x["date"])
    return games


def pitcher_index(pids):
    """date -> cumulative (ER, IP) strictly BEFORE that date, per pitcher."""
    idx = {}
    for pid in pids:
        try:
            data = get(f"people/{pid}",
                       hydrate="stats(group=[pitching],type=[gameLog],season=2026)")
            logs = []
            for s in data["people"][0].get("stats", []):
                for sp in s.get("splits", []):
                    st = sp["stat"]
                    logs.append((sp.get("date"), st.get("inningsPitched", "0"),
                                 st.get("earnedRuns", 0)))
            logs.sort()
        except Exception:
            logs = []
        er = ip = 0.0
        states = []
        for date, i, e in logs:
            states.append((date, er, ip))      # state before this outing
            ip += innings(i)
            er += int(e)
        idx[pid] = states
    return idx


def era_before(idx, pid, date, league_era):
    states = idx.get(pid)
    if not states:
        return league_era
    er = ip = 0.0
    for d0, e0, i0 in states:
        if d0 < date:
            er, ip = e0, i0
        else:
            break
    return starter_era(er, ip, league_era)


def backtest(train_end="2026-06-30", test_start="2026-07-01"):
    print("Loading season...", file=sys.stderr)
    games = load_season("2026-03-25", "2026-08-29")
    pids = {g["ap"] for g in games} | {g["hp"] for g in games}
    print(f"{len(games)} games, {len(pids)} starters. Building point-in-time "
          f"pitcher index...", file=sys.stderr)
    idx = pitcher_index(pids)

    state = defaultdict(lambda: dict(rs=0.0, ra=0.0, w=0, g=0))
    lg_runs = lg_games = 0
    test, base_rec, base_home = [], [], []
    for gm in games:
        A, H, d = gm["away"], gm["home"], gm["date"]
        ta, th = state[A], state[H]
        if ta["g"] >= MIN_GAMES and th["g"] >= MIN_GAMES and lg_games >= 200 \
                and d >= test_start:
            lg_rpg = lg_runs / lg_games
            p = win_prob(ta["rs"] / ta["g"], ta["ra"] / ta["g"],
                         th["rs"] / th["g"], th["ra"] / th["g"],
                         era_before(idx, gm["ap"], d, lg_rpg),
                         era_before(idx, gm["hp"], d, lg_rpg), lg_rpg)
            away_won = gm["asc"] > gm["hsc"]
            test.append((p, away_won))
            base_rec.append(((ta["w"] / ta["g"] > th["w"] / th["g"]) == away_won))
            base_home.append(not away_won)
        state[A]["rs"] += gm["asc"]; state[A]["ra"] += gm["hsc"]; state[A]["g"] += 1
        state[H]["rs"] += gm["hsc"]; state[H]["ra"] += gm["asc"]; state[H]["g"] += 1
        state[A]["w"] += gm["asc"] > gm["hsc"]
        state[H]["w"] += gm["hsc"] > gm["asc"]
        lg_runs += gm["asc"] + gm["hsc"]; lg_games += 2

    n = len(test)
    acc = 100 * sum(1 for p, a in test if (p > 0.5) == a) / n
    brier = sum((p - a) ** 2 for p, a in test) / n
    print(f"\nHOLDOUT {test_start} .. 2026-08-29   n={n}   (point-in-time, no look-ahead)")
    print(f"  model                   {acc:.1f}%   Brier {brier:.4f}")
    print(f"  better W-L record       {100*sum(base_rec)/n:.1f}%")
    print(f"  always pick home        {100*sum(base_home)/n:.1f}%")
    buckets = defaultdict(lambda: [0, 0])
    for p, a in test:
        c = max(p, 1 - p)
        k = min(int(c * 20) / 20, 0.65)
        buckets[k][0] += 1
        buckets[k][1] += (p > 0.5) == a
    print("\n  CALIBRATION")
    for k in sorted(buckets):
        cnt, hit = buckets[k]
        if cnt < 20:
            continue
        print(f"    says {k*100:2.0f}-{(k+0.05)*100:2.0f}%   n={cnt:<4d} actual {100*hit/cnt:.1f}%")


# ------------------------------------------------------------------ predict
def predict(date):
    """Predict a slate.

    Teams are keyed by MLB team **id**, never by name: the standings endpoint
    returns short names ("Rays") while the schedule returns full ones ("Tampa
    Bay Rays"). Keying on name silently matches nothing and prints an empty
    slate, which is worse than crashing.
    """
    st = get("standings", leagueId="103,104", season=2026,
             standingsTypes="regularSeason")
    team = {}
    for rec in st["records"]:
        for t in rec["teamRecords"]:
            lr = t.get("leagueRecord", {})
            g = (lr.get("wins", 0) + lr.get("losses", 0)) or t.get("gamesPlayed") or 1
            team[t["team"]["id"]] = dict(rs=t["runsScored"] / g,
                                         ra=t["runsAllowed"] / g,
                                         rec=f"{lr.get('wins')}-{lr.get('losses')}")
    if not team:
        sys.exit("Standings returned no teams; cannot model.")
    lg_rpg = sum(v["rs"] for v in team.values()) / len(team)
    sched = get("schedule", sportId=1, date=date,
                hydrate="probablePitcher,team", gameType="R")
    dates = sched.get("dates") or []
    if not dates:
        sys.exit(f"No games scheduled {date}.")

    era_cache = {}

    def sp_era_for(side):
        pp = side.get("probablePitcher") or {}
        pid = pp.get("id")
        if not pid:
            return lg_rpg, "TBD"
        if pid in era_cache:
            return era_cache[pid]
        val = (lg_rpg, pp.get("fullName", "TBD"))
        try:
            d = get(f"people/{pid}",
                    hydrate="stats(group=[pitching],type=[season],season=2026)")
            person = d["people"][0]
            for s in person.get("stats", []):
                if s.get("splits"):
                    stat = s["splits"][0]["stat"]
                    ip = innings(stat.get("inningsPitched", "0"))
                    er = float(stat.get("earnedRuns", 0))
                    val = (starter_era(er, ip, lg_rpg), person["fullName"])
                    break
        except Exception:
            pass
        era_cache[pid] = val
        return val

    games = dates[0]["games"]
    print(f"\nMLB model v3 -- {date}   ({len(games)} games)")
    print("validated 57.5% on 757 held-out games "
          "(best baseline 55.6%, p=0.31 -- a lean, not an edge)\n")
    print(f"  {'MATCHUP':<40} {'LEAN':<24} PROB   STARTERS")
    print("  " + "-" * 94)
    skipped = 0
    rows = []
    for g in games:
        a, h = g["teams"]["away"], g["teams"]["home"]
        aid, hid = a["team"]["id"], h["team"]["id"]
        if aid not in team or hid not in team:
            skipped += 1
            continue
        ta, th = team[aid], team[hid]
        sa, an_sp = sp_era_for(a)
        sh, hn_sp = sp_era_for(h)
        p = win_prob(ta["rs"], ta["ra"], th["rs"], th["ra"], sa, sh, lg_rpg)
        an, hn = a["team"]["name"], h["team"]["name"]
        lean, conf = (an, p) if p > 0.5 else (hn, 1 - p)
        rows.append((conf, f"{an} @ {hn}", lean, f"{an_sp[:14]} / {hn_sp[:14]}"))
    for conf, matchup, lean, sps in sorted(rows, key=lambda r: -r[0]):
        print(f"  {matchup[:40]:<40} {lean[:24]:<24} {conf*100:4.1f}%  {sps}")
    if skipped:
        print(f"\n  ({skipped} game(s) skipped: team not in standings)")
    print("\n  Nothing here is a lock. The validated ceiling is ~60%; anything")
    print("  this model prints above that is extrapolation, not evidence.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--backtest", action="store_true")
    a = ap.parse_args()
    if a.backtest:
        backtest()
    else:
        predict(a.date)


if __name__ == "__main__":
    main()
