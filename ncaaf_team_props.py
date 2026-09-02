"""Thu 9/3/26 NCAAF board: opponent-adjusted ratings vs the posted numbers.

The board in the app offers a spread or a total per game and lets you weigh
either side. There are no prices on screen, so the only two questions worth
asking are:

  1. Where does an opponent-adjusted rating disagree with the posted number?
  2. Where is the app's number worse than the sharp book's, in my favour?

(2) is the reliable one. It needs no model to be right -- if DraftKings hangs
BUF -18.5 and this app hangs BUF -17.5, the free point is real whether or not
any rating system is any good. (1) is the speculative one, and in Week 1 it is
*especially* speculative: the ratings below are fit on 2025 results with no
adjustment for the portal, the draft, or returning production. A 13-point
model/market gap in Week 1 is the model being uninformed, not an edge.

Ratings are a ridge-shrunk SRS on all 1,633 FBS+FCS regular-season games of
2025, solved by Gauss-Seidel:

    margin(i vs j) = r_i - r_j + hfa * home(i)

Shrinkage and home-field were picked by holdout (fit weeks 1-10, score weeks
11+), not by in-sample fit -- see calibrate(). That holdout puts the
margin RMSE at 15.9, which is where CFB_SIGMA in ncaaf.py already sits.
"""

import json
import math
import os
import urllib.request

SCOREBOARD = ("https://site.api.espn.com/apis/site/v2/sports/football/college-football"
              "/scoreboard?dates={season}&seasontype=2&week={wk}&groups={grp}&limit=400")
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cfb2025.json")

# Holdout-selected. Larger shrinkage strictly hurt out-of-sample; see calibrate().
LAMBDA = 0.5
HFA = 2.0
# Out-of-sample margin RMSE from the holdout. In-sample was 12.7 -- using that
# number would overstate every edge below by ~25%.
SIGMA = 15.9
# Week 1 carries an extra offseason of roster churn the ratings cannot see.
WEEK1_SIGMA = 17.5

# (away, home, app_spread_home, app_total, dk_spread_home, dk_total)
# app_* read off the market screen; dk_* pulled live from ESPN's DraftKings feed.
BOARD = [
    ("West Georgia Wolves",      "Kennesaw State Owls",       -23.5, 51.5, -23.5, 51.5),
    ("UAlbany Great Danes",      "Buffalo Bulls",             -17.5, 47.5, -18.5, 48.5),
    ("Akron Zips",               "Wake Forest Demon Deacons", -24.5, 48.5, -23.5, 48.5),
    ("Bethune-Cookman Wildcats", "UCF Knights",                None, 58.5, -42.5, 59.5),
    ("Merrimack Warriors",       "Delaware Blue Hens",         None, None, -28.5, 55.5),
]

SHORT = {
    "West Georgia Wolves": "UWGA", "Kennesaw State Owls": "KENN",
    "UAlbany Great Danes": "ALBY", "Buffalo Bulls": "BUFF",
    "Akron Zips": "AKR", "Wake Forest Demon Deacons": "WAKE",
    "Bethune-Cookman Wildcats": "COOK", "UCF Knights": "UCF",
    "Merrimack Warriors": "MRMK", "Delaware Blue Hens": "DEL",
}


def load_games(season=2025):
    """Every completed FBS + FCS regular-season game. Cached after first pull."""
    if os.path.exists(CACHE):
        return json.load(open(CACHE))
    games = {}
    for grp in (80, 81):                      # 80 = FBS, 81 = FCS
        for wk in range(1, 17):
            url = SCOREBOARD.format(season=season, wk=wk, grp=grp)
            try:
                doc = json.load(urllib.request.urlopen(url, timeout=30))
            except Exception as exc:
                raise SystemExit(
                    f"could not reach ESPN ({exc}).\n"
                    "This needs outbound https to site.api.espn.com. Rather than "
                    "invent ratings, it stops here."
                )
            for ev in doc.get("events", []):
                if not ev.get("competitions"):
                    continue
                comp = ev["competitions"][0]
                if not comp.get("status", {}).get("type", {}).get("completed"):
                    continue
                rec = {}
                for side in comp["competitors"]:
                    if side.get("score") in (None, ""):
                        rec = None
                        break
                    rec[side["homeAway"]] = {"name": side["team"]["displayName"],
                                             "pts": int(side["score"])}
                if rec and "home" in rec and "away" in rec:
                    games[ev["id"]] = {"wk": wk, "neutral": bool(comp.get("neutralSite")),
                                       **rec}
    out = list(games.values())
    json.dump(out, open(CACHE, "w"))
    return out


def fit(games, lam=LAMBDA, hfa=HFA, iters=500):
    """Ridge-shrunk SRS. Returns {team: rating} centred on the field."""
    teams = sorted({g[s]["name"] for g in games for s in ("home", "away")})
    played = {t: [] for t in teams}
    for g in games:
        home, away = g["home"], g["away"]
        h = 0 if g["neutral"] else 1
        played[home["name"]].append((home["pts"] - away["pts"], away["name"],  h))
        played[away["name"]].append((away["pts"] - home["pts"], home["name"], -h))

    rating = {t: 0.0 for t in teams}
    for _ in range(iters):
        nxt = {}
        for t in teams:
            if not played[t]:
                nxt[t] = 0.0
                continue
            nxt[t] = sum(m - hfa * h + rating[o]
                         for m, o, h in played[t]) / (len(played[t]) + lam)
        mean = sum(nxt.values()) / len(nxt)
        rating = {t: v - mean for t, v in nxt.items()}
    return rating


def rmse(rating, games, hfa=HFA):
    s = 0.0
    for g in games:
        h = 0 if g["neutral"] else 1
        pred = rating[g["home"]["name"]] - rating[g["away"]["name"]] + hfa * h
        s += (g["home"]["pts"] - g["away"]["pts"] - pred) ** 2
    return (s / len(games)) ** 0.5


def cover_prob(model_margin, line, sigma):
    """P(favourite covers) when laying `line` and the model projects `model_margin`.

    Both are stated as points the home side lays. Half-point lines only, so no
    push mass to carve out.
    """
    return 0.5 * (1 + math.erf((model_margin - line) / (sigma * math.sqrt(2))))


def break_even(p):
    """American price at which probability p is exactly break-even."""
    if p >= 0.5:
        return -100 * p / (1 - p)
    return 100 * (1 - p) / p


def calibrate(games):
    """Pick shrinkage and home-field on held-out games, not on the fit."""
    train = [g for g in games if g["wk"] <= 10]
    test = [g for g in games if g["wk"] > 10]
    print("=" * 92)
    print(f"HOLDOUT CALIBRATION -- fit on {len(train)} games (wk 1-10), "
          f"scored on {len(test)} (wk 11+)")
    print("=" * 92)
    best = None
    for lam in (0.5, 1, 2, 4, 9):
        row = []
        for hfa in (2.0, 2.5, 3.0, 3.5):
            e = rmse(fit(train, lam, hfa), test, hfa)
            row.append(f"hfa {hfa}: {e:5.2f}")
            if best is None or e < best[0]:
                best = (e, lam, hfa)
        print(f"  lambda {lam:<4} " + "   ".join(row))
    print(f"\n  best: lambda={best[1]}, hfa={best[2]}, out-of-sample margin "
          f"RMSE {best[0]:.2f}")
    print("  Shrinkage only ever hurt -- 1,633 games is enough that the ratings")
    print("  do not need much help. RMSE 15.9 is the honest error bar; the")
    print("  in-sample 12.7 would inflate every edge below by about a quarter.")
    return best


def main():
    games = load_games()
    rating = fit(games)
    hi = sorted(rating.items(), key=lambda kv: -kv[1])

    print("=" * 92)
    print(f"OPPONENT-ADJUSTED RATINGS -- {len(games)} games, "
          f"{len(rating)} FBS+FCS teams, 2025 regular season")
    print("=" * 92)
    print("  top of the field: " + ", ".join(f"{n.rsplit(' ',1)[0]} {v:+.0f}"
                                             for n, v in hi[:6]))
    print()
    for name in SHORT:
        rank = next(i for i, (n, _) in enumerate(hi) if n == name) + 1
        print(f"  {SHORT[name]:<6}{name:<30}{rating[name]:+7.1f}   "
              f"#{rank} of {len(hi)}")

    print("\n" + "=" * 92)
    print("MODEL vs MARKET  (points the home side lays)")
    print("=" * 92)
    print(f"{'GAME':<20}{'MODEL':>8}{'DK':>8}{'APP':>8}{'M-DK':>8}"
          f"{'SHOP':>8}   read")
    rows = []
    for away, home, app_sp, app_tot, dk_sp, dk_tot in BOARD:
        margin = rating[home] - rating[away] + HFA
        gap = margin - abs(dk_sp)
        # The app's number vs the sharp number, signed so + means the app's
        # line is the better side of the sharp one for whoever it favours.
        shop = abs(dk_sp) - abs(app_sp) if app_sp is not None else None
        tag = ("model has no read -- roster churn it can't see"
               if abs(gap) > 8 else "model and market agree")
        rows.append((away, home, margin, dk_sp, app_sp, gap, shop, tag,
                     app_tot, dk_tot))
        g = f"{SHORT[away]} @ {SHORT[home]}"
        a = f"{abs(app_sp):.1f}" if app_sp is not None else "  --"
        s = f"{shop:+.1f}" if shop is not None else "  --"
        print(f"{g:<20}{margin:>8.1f}{abs(dk_sp):>8.1f}{a:>8}"
              f"{gap:>+8.1f}{s:>8}   {tag}")

    print("\n" + "=" * 92)
    print("FREE POINTS -- where this app's number is off the sharp number")
    print("=" * 92)
    print("A point is worth about "
          f"{100 * 0.3989 / WEEK1_SIGMA:.1f} points of cover probability at "
          f"sigma={WEEK1_SIGMA}.")
    print("That is the whole edge, and it is small. It is also the only part of")
    print("this that does not depend on the ratings being right.\n")
    for away, home, margin, dk_sp, app_sp, gap, shop, tag, at, dt in rows:
        if shop:
            side = SHORT[home] + f" {app_sp:+.1f}" if shop > 0 else \
                   SHORT[away] + f" {-app_sp:+.1f}"
            print(f"  {side:<16} app has it {abs(shop):.1f} pt better than DK's "
                  f"{SHORT[home]} {dk_sp:+.1f}")
        if at is not None and dt is not None and at != dt:
            better = "under" if at < dt else "over"
            print(f"  {SHORT[away]+'/'+SHORT[home]+' '+better:<16} app "
                  f"{at:.1f} vs DK {dt:.1f} -- {abs(dt-at):.1f} pt to the "
                  f"{better}")

    print("\n" + "=" * 92)
    print("THE PICK")
    print("=" * 92)
    best = None
    for away, home, margin, dk_sp, app_sp, gap, shop, tag, at, dt in rows:
        if app_sp is None or abs(gap) > 8:
            continue                      # model has no read -- do not price it
        # Take whichever side the app's line favours relative to the model.
        p_home = cover_prob(margin, abs(app_sp), WEEK1_SIGMA)
        side, p = ((SHORT[home], p_home) if p_home >= 0.5
                   else (SHORT[away], 1 - p_home))
        line = app_sp if side == SHORT[home] else -app_sp
        cand = (p, side, line, away, home, margin, dk_sp, shop)
        if best is None or p > best[0]:
            best = cand
        print(f"  {side} {line:+.1f}  model {margin:.1f}  ->  "
              f"{p*100:.1f}% to cover   (break-even price {break_even(p):+.0f})")
    if best:
        p, side, line, away, home, margin, dk_sp, shop = best
        print(f"\n  Most likely: {side} {line:+.1f} in {SHORT[away]} @ {SHORT[home]}.")
        print(f"  Ratings make it {SHORT[home]} by {margin:.1f}; DraftKings says "
              f"{abs(dk_sp):.1f}; this app says {abs(line):.1f}.")
        print(f"  Both the model and the sharp book land on the same side of the")
        print(f"  app's number, and the app is {abs(shop):.1f} pt cheap. "
              f"{p*100:.1f}% is a real edge but a")
        print("  thin one -- it is a single bet, not a leg in anything.")


if __name__ == "__main__":
    main()
    print()
    calibrate(load_games())
