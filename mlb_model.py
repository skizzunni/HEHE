"""MLB moneyline model: team strength + starting pitcher, priced against the market.

Data source: MLB StatsAPI (public, no key). Run:
    python3 mlb_model.py                    # today's slate
    python3 mlb_model.py --date 2026-08-29
    python3 mlb_model.py --odds TOR=-155 ATL=-190   # add market prices for EV

NOTE: this needs outbound access to statsapi.mlb.com. Some sandboxed
environments block it; the script says so plainly rather than guessing.
"""

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://statsapi.mlb.com/api/v1"

# Home teams win ~53.5% of MLB games across the modern era.
HOME_EDGE = 0.535
# How much of a game's outcome the starting pitcher accounts for.
SP_WEIGHT = 0.35
LEAGUE_ERA = 4.20


def get(path, **params):
    url = f"{API}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        sys.exit(f"Could not reach statsapi.mlb.com ({e}).\n"
                 "This network blocks it. Run from an unrestricted machine.")


def pythagorean(runs_scored, runs_allowed, exp=1.83):
    """Pythagenpat win expectancy -- more stable than raw W-L this late."""
    if runs_scored + runs_allowed == 0:
        return 0.5
    rs, ra = runs_scored ** exp, runs_allowed ** exp
    return rs / (rs + ra)


def log5(p_a, p_b):
    """Bill James log5: P(A beats B) given each team's win pct vs the league."""
    num = p_a - p_a * p_b
    den = p_a + p_b - 2 * p_a * p_b
    return num / den if den else 0.5


def apply_home_edge(p):
    """Shift a neutral-field probability by home advantage in odds space."""
    h = HOME_EDGE / (1 - HOME_EDGE)
    o = (p / (1 - p)) * h
    return o / (1 + o)


def team_strength():
    """Pythagorean win pct per team id, blended with actual record."""
    data = get("standings", leagueId="103,104", season=dt.date.today().year,
               standingsTypes="regularSeason")
    out = {}
    for rec in data.get("records", []):
        for t in rec.get("teamRecords", []):
            tid = t["team"]["id"]
            gp = t.get("gamesPlayed") or 1
            rs = t.get("runsScored", 0)
            ra = t.get("runsAllowed", 0)
            pyth = pythagorean(rs, ra)
            actual = t.get("leagueRecord", {}).get("pct")
            actual = float(actual) if actual else pyth
            # Pythagorean is the better predictor; keep a little of the record.
            out[tid] = {
                "name": t["team"]["name"],
                "pct": 0.75 * pyth + 0.25 * actual,
                "record": f"{t['leagueRecord']['wins']}-{t['leagueRecord']['losses']}",
                "rs": rs, "ra": ra, "gp": gp,
            }
    return out


def pitcher_factor(pid):
    """Multiplier on team strength from the starter's season ERA vs league.

    Returns 1.0 for an unknown/rookie starter rather than inventing a number.
    """
    if not pid:
        return 1.0, "TBD", None
    data = get(f"people/{pid}", hydrate=f"stats(group=pitching,type=season,season={dt.date.today().year})")
    person = data["people"][0]
    name = person["fullName"]
    try:
        splits = person["stats"][0]["splits"][0]["stat"]
        era = float(splits["era"])
        ip = float(splits["inningsPitched"])
    except (KeyError, IndexError, ValueError):
        return 1.0, name, None
    if ip < 20:
        return 1.0, name, era
    # Regress toward league mean based on sample size.
    reliability = min(ip / 120.0, 1.0)
    adj_era = era * reliability + LEAGUE_ERA * (1 - reliability)
    factor = (LEAGUE_ERA / adj_era) ** SP_WEIGHT
    return max(0.80, min(1.20, factor)), name, era


def american_to_decimal(odds):
    return 1 + (odds / 100 if odds > 0 else 100 / -odds)


def to_american(p):
    dec = 1 / p
    return round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))


def kelly(p, dec, fraction=0.25):
    b = dec - 1
    edge = (p * b - (1 - p)) / b
    return max(0.0, edge * fraction)


def run(date, market):
    strengths = team_strength()
    sched = get("schedule", sportId=1, date=date,
                hydrate="probablePitcher,linescore,team")
    dates = sched.get("dates", [])
    if not dates:
        sys.exit(f"No games scheduled {date}.")

    print(f"\nMLB model -- {date}\n" + "=" * 78)
    plays = []
    for game in dates[0]["games"]:
        away = game["teams"]["away"]
        home = game["teams"]["home"]
        aid, hid = away["team"]["id"], home["team"]["id"]
        if aid not in strengths or hid not in strengths:
            continue
        a, h = strengths[aid], strengths[hid]

        af, aname, aera = pitcher_factor((away.get("probablePitcher") or {}).get("id"))
        hf, hname, hera = pitcher_factor((home.get("probablePitcher") or {}).get("id"))

        a_adj = min(max(a["pct"] * af, 0.20), 0.80)
        h_adj = min(max(h["pct"] * hf, 0.20), 0.80)
        p_home = apply_home_edge(log5(h_adj, a_adj))

        status = game["status"]["detailedState"]
        ls = game.get("linescore", {})
        live = ""
        if ls.get("currentInning"):
            lt = ls.get("teams", {})
            live = (f"  [{ls.get('inningState','')} {ls['currentInning']} -- "
                    f"{lt.get('away',{}).get('runs',0)}-"
                    f"{lt.get('home',{}).get('runs',0)}]")

        print(f"\n{a['name']} ({a['record']}) at {h['name']} ({h['record']})"
              f"   {status}{live}")
        print(f"  SP: {aname} (ERA {aera if aera is not None else 'n/a'})"
              f"  vs  {hname} (ERA {hera if hera is not None else 'n/a'})")
        print(f"  Model: {h['name']} {p_home*100:.1f}% ({to_american(p_home):+d})"
              f"   |   {a['name']} {(1-p_home)*100:.1f}% ({to_american(1-p_home):+d})")

        for side, prob, tm in ((home, p_home, h), (away, 1 - p_home, a)):
            abbr = side["team"].get("abbreviation")
            if abbr in market:
                dec = american_to_decimal(market[abbr])
                ev = prob * dec - 1
                flag = "VALUE" if ev > 0.02 else "pass"
                print(f"  Market {abbr} {market[abbr]:+d}: EV {ev*100:+.1f}%  {flag}"
                      + (f"  stake {kelly(prob, dec)*100:.1f}% bankroll"
                         if ev > 0.02 else ""))
                if ev > 0.02:
                    plays.append((abbr, tm["name"], market[abbr], ev, prob))

    if market:
        print("\n" + "=" * 78)
        if plays:
            print("PLAYS (positive expected value, bet as SINGLES):")
            for abbr, name, odds, ev, prob in sorted(plays, key=lambda x: -x[3]):
                print(f"  {name} {odds:+d}   model {prob*100:.1f}%   EV {ev*100:+.1f}%")
        else:
            print("No +EV plays. The correct number of bets today is zero.")
    print("\nParlay check: see parlay_math.py. Every leg you add multiplies the")
    print("hold against you -- a 55% edge goes negative by roughly 4 legs.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--odds", nargs="*", default=[],
                    help="Market moneylines, e.g. TOR=-155 ATL=-190")
    args = ap.parse_args()
    market = {}
    for pair in args.odds:
        k, _, v = pair.partition("=")
        market[k.upper()] = int(v)
    run(args.date, market)


if __name__ == "__main__":
    main()
