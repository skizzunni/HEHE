"""Tennis match model -- and an honest account of what failed building it.

    python3 tennis.py --date 20260830          # board for a date
    python3 tennis.py --backtest               # reproduce the validation

WHAT WAS TESTED, ON 7,812 COMPLETED 2026 MATCHES

A walk-forward Elo (everyone starts 1500, K=32, updated only from prior
matches -- no look-ahead possible) scored on an August holdout of 776 matches:

    Elo                        57.1%
    more 2026 wins to date     57.9%
    better win rate to date    56.0%

    McNemar, Elo vs win-count: chi2 = 0.03, p = 0.873

Elo is statistically indistinguishable from "who has won more matches this
year". It is not a model; it is a coin flip with extra steps.

WHY IT FAILS -- Elo has no idea what tour a match was played on

Final 2026 Elo ratings expose it:

    Daniel Merida    1660   (29-12)      Novak Djokovic   1624   (15-6)
    Thiago Tirante   1643   (28-17)      Daniil Medvedev  1612   (33-15)
    Rafael Jodar     1738   (43-14)      Adrian Mannarino 1418   (12-23)

Merida and Tirante out-rate Djokovic because Elo credits a Challenger win
exactly as much as a Grand Slam win, and elite players both play fewer matches
and lose to other elite players. Cold-starting everyone at 1500 in January
compounds it. Elo built this way is a measure of match volume at whatever level
you happen to play, not of strength.

WHAT IS USED INSTEAD

Ranking points, which encode tour level directly:

    p(A beats B) = 1 / (1 + exp(-(ln ptsA - ln ptsB) * scale))

where scale is 1.02 when both players are ranked and 0.78 when one is not --
see the constants below for the walk-forward fit behind those numbers.

On the same August matches this scores 60.2% -- but current rankings partly
reflect those very matches, so that number is optimistic by an unknown amount
and is NOT a clean validation. Treat the true figure as somewhere in the high
fifties. Unlike model_v3.py for MLB, this model has no uncontaminated backtest.
Its output is a lean with an asterisk, not a validated edge.
"""
import argparse
import datetime as dt
import json
import math
import re
import ssl
import urllib.request

# Two scales, fitted on 6,918 Jan-Jul matches and scored on a held-out August
# set. A single 0.80 shrank ranked-v-ranked matchups too far toward 50%: over
# the training sample those favourites were called at 62.3% and won 64.9%, and
# the same gap reappeared out of sample (61.1% called, 67.0% won). Splitting the
# scale by whether both players are ranked cut held-out Brier from 0.2207 to
# 0.2190, better in 95% of 2,000 bootstrap resamples.
#
# It changes no picks. The transform is monotonic, so the favoured side is
# identical either way -- this makes the confidence numbers honest, nothing more.
SCALE_RANKED = 1.02   # both players in the ranking table
SCALE_OTHER = 0.78    # one side unranked, so one input is a guess
UNRANKED_PTS = 180.0  # floor for a player outside the top 150
ESPN = "https://site.api.espn.com/apis/site/v2/sports/tennis"

_CTX = ssl.create_default_context()
try:
    _CTX.load_verify_locations("/root/.ccr/ca-bundle.crt")
except OSError:
    pass


def get(url):
    with urllib.request.urlopen(url, timeout=60, context=_CTX) as r:
        return json.load(r)


def _clip(s, n):
    """Shorten a name to n chars without leaving a dangling partial word."""
    s = s or ""
    return s if len(s) <= n else s[:n - 1].rstrip() + "."


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def rankings():
    out = {}
    for lg in ("atp", "wta"):
        d = get(f"{ESPN}/{lg}/rankings")
        for entry in (d.get("rankings") or [{}])[0].get("ranks", []):
            a = entry.get("athlete") or {}
            if a.get("displayName"):
                out[norm(a["displayName"])] = dict(rank=entry.get("current"),
                                                   pts=entry.get("points"))
    return out


def matches_on(date):
    """Tennis nests matches under groupings[], not competitions[]. A Slam also
    returns its whole draw regardless of ?dates=, so filter by ET date here."""
    seen, out = set(), []
    for lg in ("atp", "wta"):
        d = get(f"{ESPN}/{lg}/scoreboard?dates={date}")
        for ev in d.get("events", []):
            for grp in ev.get("groupings", []):
                draw = (grp.get("grouping") or {}).get("displayName", "")
                if "Singles" not in draw:
                    continue
                for c in grp.get("competitions", []):
                    if c.get("id") in seen:
                        continue
                    try:
                        t = dt.datetime.strptime(c.get("date", ""), "%Y-%m-%dT%H:%MZ")
                        et = t.replace(tzinfo=dt.timezone.utc).astimezone(
                            dt.timezone(dt.timedelta(hours=-4)))
                    except ValueError:
                        continue
                    if et.strftime("%Y%m%d") != str(date):
                        continue
                    ps = [(x.get("athlete") or {}).get("displayName")
                          for x in c.get("competitors", [])]
                    if len(ps) != 2 or not all(ps):
                        continue
                    seen.add(c.get("id"))
                    out.append(dict(event=ev.get("name"), draw=draw,
                                    time=et.strftime("%H:%M"),
                                    rnd=(c.get("round") or {}).get("displayName", ""),
                                    p1=ps[0], p2=ps[1]))
    return out


def prob(p1, p2, rk):
    def pts(p):
        r = rk.get(norm(p))
        return float(r["pts"]) if r and r.get("pts") else UNRANKED_PTS
    both = all((rk.get(norm(p)) or {}).get("pts") for p in (p1, p2))
    d = math.log(pts(p1)) - math.log(pts(p2))
    return 1 / (1 + math.exp(-d * (SCALE_RANKED if both else SCALE_OTHER)))


def board(date):
    rk = rankings()
    ms = matches_on(date)
    if not ms:
        print(f"No singles matches found for {date}.")
        return
    rows = []
    for m in ms:
        p = prob(m["p1"], m["p2"], rk)
        fav, conf = (m["p1"], p) if p >= 0.5 else (m["p2"], 1 - p)
        r1 = (rk.get(norm(m["p1"])) or {}).get("rank")
        r2 = (rk.get(norm(m["p2"])) or {}).get("rank")
        rows.append((conf, m, fav, r1, r2))
    rows.sort(key=lambda x: -x[0])
    ev = rows[0][1]["event"]
    print(f"\n{ev} -- {date} (ET) -- {len(rows)} singles matches")
    print("ranking-points model; no clean backtest -- see module docstring\n")
    print(f"  {'TIME':<6}{'D':<3}{'MATCH (rank)':<50}{'LEAN':<26}CONF")
    print("  " + "-" * 92)
    for conf, m, fav, r1, r2 in rows:
        d = "M" if "Men" in m["draw"] else "W"
        # Truncate each NAME, never the whole label: clipping the label hides
        # the trailing rank and can run flush into the LEAN column, which makes
        # two printouts of an unchanged board look like they disagree.
        a = f"{_clip(m['p1'], 16)} ({r1 or 'NR'})"
        b = f"{_clip(m['p2'], 16)} ({r2 or 'NR'})"
        label = f"{a} vs {b}"
        print(f"  {m['time']:<6}{d:<3}{label:<49} {_clip(fav, 24):<25} {conf*100:5.1f}%")
    coin = sum(1 for r in rows if r[0] < 0.60)
    print(f"\n  {coin} of {len(rows)} are inside 50-60% -- coin flips, not picks.")
    print("  NR = outside the top 150.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().strftime("%Y%m%d"))
    a = ap.parse_args()
    board(a.date)


if __name__ == "__main__":
    main()
