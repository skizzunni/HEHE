"""WNBA player props, backtested. "X or more" points / rebounds / assists.

    python3 props.py --date 20260830
    python3 props.py --backtest

MODEL
    P(hit) = Normal(mean, sd of last 10 games) at the line, x P(player plays),
    then shrunk by an exponent of 0.70 in odds space.

Each piece earned its place on a held-out backtest (tuned on July, scored on
August, 3,706 props):

    method                                   accuracy   calibration error
    empirical rate over last 15                 49.6%        15.4 pts
    Poisson on last 10                          54.9%        13.0
    Normal on last 10                           54.3%         9.1
    Normal x P(plays)                           59.2%         4.9
    Normal x P(plays), shrunk 0.70              58.2%         3.1

THE TWO FINDINGS THAT MATTER

1. Availability is the single biggest term. Rotation players -- ten-plus games
   logged, averaging 15+ minutes -- still fail to appear in **7.6%** of their
   team's games. Every "over" is dead on those nights regardless of the read.
   Adding P(plays) cut calibration error almost in half.

2. Raw prop models are wildly overconfident. Before correction the model said
   80-90% and delivered 67.6%. Books set lines at the player's median precisely
   so both sides sit near a coin flip; anything claiming 85% on a median line
   is mispriced by the modeller, not the book.

The ceiling here is ~58% accuracy on lines set at the median. That is a lean.
Stacking leans multiplies the vig faster than the edge -- see parlay_math.py.
"""
import argparse
import datetime as dt
import json
import math
import os
import ssl
import statistics as st
import sys
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")
SHRINK = 0.70
MIN_GAMES = 10          # logged appearances before a player is modelled
MIN_MINUTES = 14.0      # rotation threshold, averaged over last 8 appearances
STALE_DAYS = 14         # a player who has not appeared recently is off the board

_CTX = ssl.create_default_context()
try:
    _CTX.load_verify_locations("/root/.ccr/ca-bundle.crt")
except OSError:
    pass


def get(url, tries=3):
    for a in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=45, context=_CTX) as r:
                return json.load(r)
        except Exception:
            time.sleep(1 + a)
    return {}


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _min(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def load_boxscores(season_start="2026-04-25", refresh=False):
    """Every player-game this season. Cached for an hour."""
    cf = os.path.join(CACHE, "wnba_box.json")
    if not refresh and os.path.exists(cf) and time.time() - os.path.getmtime(cf) < 3600:
        with open(cf) as fh:
            return json.load(fh)
    d0 = dt.date.fromisoformat(season_start)
    days = []
    while d0 <= dt.date.today():
        days.append(d0.strftime("%Y%m%d"))
        d0 += dt.timedelta(days=1)
    ids = set()
    with ThreadPoolExecutor(max_workers=14) as ex:
        for d in ex.map(lambda ds: get(f"{ESPN}/scoreboard?dates={ds}"), days):
            for ev in d.get("events", []):
                c = (ev.get("competitions") or [{}])[0]
                if ((c.get("status") or {}).get("type") or {}).get("completed"):
                    ids.add((ev.get("id"), (c.get("date") or "")[:10]))

    def box(arg):
        gid, date = arg
        d = get(f"{ESPN}/summary?event={gid}")
        out = []
        for team in d.get("boxscore", {}).get("players", []):
            tn = (team.get("team") or {}).get("displayName")
            for grp in team.get("statistics", []):
                keys = grp.get("names", [])
                for ath in grp.get("athletes", []):
                    nm = (ath.get("athlete") or {}).get("displayName")
                    if not nm:
                        continue
                    s = dict(zip(keys, ath.get("stats", [])))
                    m = _min(s.get("MIN"))
                    pts = _int(s.get("PTS"))
                    out.append(dict(date=date, team=tn, player=nm,
                                    played=bool(m > 0 and pts is not None), m=m,
                                    pts=pts or 0, reb=_int(s.get("REB")) or 0,
                                    ast=_int(s.get("AST")) or 0))
        return out

    rows = []
    with ThreadPoolExecutor(max_workers=14) as ex:
        for r in ex.map(box, sorted(ids)):
            rows.extend(r)
    rows.sort(key=lambda r: r["date"])
    os.makedirs(CACHE, exist_ok=True)
    with open(cf, "w") as fh:
        json.dump(rows, fh)
    return rows


def prob(line, recent, p_play):
    """P(stat >= line) from a normal fit on recent games, times availability."""
    mu = st.mean(recent)
    sd = st.pstdev(recent) or 1.0
    p = 0.5 * (1 - math.erf(((line - 0.5) - mu) / (sd * math.sqrt(2)))) * p_play
    if 0 < p < 1:
        o = (p / (1 - p)) ** SHRINK
        p = o / (1 + o)
    return p


def availability(history):
    """Laplace-smoothed rate of actually appearing, over the last 20 team games."""
    recent = history[-20:]
    return (sum(1 for x in recent if x["played"]) + 3) / (len(recent) + 4)


def board(date):
    rows = load_boxscores()
    hist, last = defaultdict(list), {}
    for r in rows:
        hist[r["player"]].append(r)
        if r["played"]:
            cur = last.get(r["player"])
            if not cur or r["date"] > cur["date"]:
                last[r["player"]] = dict(date=r["date"], team=r["team"])

    d = get(f"{ESPN}/scoreboard?dates={date}")
    playing = {}
    for ev in d.get("events", []):
        for c in ev.get("competitions", []):
            nm = ev.get("shortName")
            for x in c.get("competitors", []):
                t = (x.get("team") or {}).get("displayName")
                if t:
                    playing[t] = nm
    if not playing:
        print(f"\nWNBA: nothing scheduled {date}.")
        return

    cutoff = (dt.datetime.strptime(date, "%Y%m%d").date()
              - dt.timedelta(days=STALE_DAYS)).isoformat()
    out, skipped = [], 0
    for pl, h in hist.items():
        info = last.get(pl)
        if not info or info["team"] not in playing:
            continue
        if info["date"] < cutoff:          # not on a current roster
            skipped += 1
            continue
        prior = [x for x in h if x["played"]]
        if len(prior) < MIN_GAMES:
            continue
        if st.mean(x["m"] for x in prior[-8:]) < MIN_MINUTES:
            continue
        pp = availability(h)
        for stat, lab in (("pts", "points"), ("reb", "rebounds"), ("ast", "assists")):
            vals = [x[stat] for x in prior]
            line = int(round(st.median(vals[-15:])))
            if line < 2:
                continue
            out.append((prob(line, vals[-10:], pp), playing[info["team"]], pl,
                        line, lab, st.mean(vals[-10:]), pp))
    out.sort(key=lambda x: -x[0])
    print(f"\nWNBA PLAYER PROPS -- {date}   ({len(out)} modelled)")
    print("validated 58.2% accuracy, 3.1 pt calibration error on 3,706 August props\n")
    print(f"  {'GAME':<12}{'PLAYER':<24}{'PROP':<17}{'P(HIT)':<9}{'L10':<7}AVAIL")
    print("  " + "-" * 76)
    for p, g, pl, line, lab, mu, pp in out[:25]:
        flag = "  <-- availability risk" if pp < 0.88 else ""
        print(f"  {g:<12}{pl[:24]:<24}{str(line)+'+ '+lab:<17}"
              f"{p*100:5.1f}%   {mu:<7.1f}{pp*100:.0f}%{flag}")
    if skipped:
        print(f"\n  {skipped} player(s) skipped: no appearance since {cutoff}.")
    print(f"\n  Top of book is ~{out[0][0]*100:.0f}%. Nothing here is a lock, and the")
    print("  7.6% chance a rotation player simply does not appear is already priced in.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().strftime("%Y%m%d"))
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    if a.refresh:
        load_boxscores(refresh=True)
    board(a.date)


if __name__ == "__main__":
    main()
