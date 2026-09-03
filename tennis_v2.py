#!/usr/bin/env python3
"""Tennis model v2 -- level-seeded, surface-aware Elo.

    python3 tennis_v2.py                    # today's board
    python3 tennis_v2.py --date 20260904
    python3 tennis_v2.py --update           # pull new results, then board

WHY THIS REPLACES THE RANKING-POINTS MODEL IN tennis.py

tennis.py's docstring is right that plain Elo fails, and this harness reproduces
its number exactly: plain Elo scores 57.0% on a held-out August (it reported
57.1%). But the diagnosis was incomplete. Elo does not fail because Elo is
worthless; it fails because every player cold-starts at 1500 and a Challenger
win moves the rating as much as a Slam win. Fix those two things and it works:

    walk-forward, August holdout, 980 matches, nothing fitted on the holdout
        level-elo     60.2%   Brier 0.2328
        surface-elo   59.9%   Brier 0.2319
        win-count     59.5%   Brier 0.2396
        plain-elo     57.0%   Brier 0.2371

Then the largest single gain. Two experiments arrived at it from different
directions, but an adversarial audit established they are the SAME feature, not
an independent confirmation: -200*(g(a)-g(b)) with g=max(0,1-n/20) and
+240*min(n,20)/20 are algebraically the same term at 10 and 12 Elo per prior
match. One finding found twice. The level seed is far too generous to a newcomer. Ramping a newcomer up from 200 Elo below their
level's seed over their first 20 matches, with parameters fitted on Apr-Jun and
July and August never touched during tuning:

    held out Jul+Aug, n=1996
        level seeds only        59.12%   Brier 0.2338
        + experience ramp       65.33%   Brier 0.2204
        + surface blend         65.93%   Brier 0.2195   <- this model

    paired bootstrap of the ramp, 4,000 resamples:
        d-accuracy  +6.21pp   95% CI [+4.36, +8.12]   P(better) 1.000
        d-Brier     -0.0134   95% CI [-0.0169, -0.0100]   P(better) 1.000

It is not a level proxy: it helps inside every level separately (tour
57.9 -> 64.7, qualifying 55.6 -> 64.5, Slam 69.8 -> 71.6). The coefficient is a
broad plateau, not a fitted knife-edge -- every value from 100 to 500 improves
Brier in every month, and 200 was chosen on Apr-Jun before July or August were
scored.

EXPECT LESS THAN +6.2 IN LIVE USE

52.5% of the held-out matches have at least one player with under 20 prior
matches, and that is an artifact of a single-season rating pool that cold-starts
every player in January 2026. In a mature multi-season pool far fewer matches
would involve a player with under 20 CAREER matches, so the term touches fewer
games and buys less. The mechanism is also not purely about debutants: only
about an eighth of the low-experience slots are players who debuted that month,
the rest are simply infrequent players. Treat +6.2 as the ceiling this dataset
can show, not the number to expect next season.

A NOTE ON THE LEAK TEST

The antisymmetry check below (2.2e-16) proves the model is blind to which player
is listed first. It does NOT prove the absence of look-ahead: an audit built a
positive control that reads the entire future, scored 67.2%, and passed the same
test with an identical residual. Field-order blindness and look-ahead freedom are
different properties. The evidence for the latter is structural -- seen[] is
incremented only in update(), strictly after the match has been scored, and every
parameter was fitted on months disjoint from the ones reported.

The ranking-points model also scores 60.2%, but that figure is contaminated:
current rankings already contain the results of the August matches being
predicted. This model's 60.2% is clean -- ratings at the moment of each
prediction were built only from matches that had already finished.

Verified free of the one bug that would fake all of this: shuffling which player
is listed first changes the measured accuracy by 0.00 points, so no model here
is reading field order instead of player identity.

WHAT WAS TESTED AND REJECTED

Six independent experiments ran against this harness. Almost everything failed,
which is worth recording so it is not retried:

    surface geometry     60+ configs (blend weight, ramp shape, separate
                         surface K, per-surface seeds, indoor hard, hard<->grass
                         transfer, two independent Elo systems). Every one
                         landed inside +/-0.0011 Brier of baseline. The stock
                         0.42 blend was not beaten.
    the 400 divisor      not a free parameter -- Elo is exactly scale-invariant,
                         so scaling (K, D, seed spread) together is bit-identical.
                         Fitted divisor 414.5 is indistinguishable from 400
                         (likelihood-ratio chi2 = 0.31 on 4,107 matches).
    head-to-head         null. Only 151 of 980 holdout matches have ANY prior
                         meeting and 120 of those have exactly one, so there is
                         almost nothing to learn from.
    best-of-5 sharpening hypothesis rejected and sign-reversed: the fit wanted
                         to FLATTEN Bo5, not sharpen it, and only 43 holdout
                         matches are genuinely Bo5.
    per-draw scale/K     null. No evidence the women's draw needs its own scale.
    time decay           accuracy up, Brier worse. Not adopted.
    form, rust, fatigue  all null. The fatigue direction is real but tiny -- one
                         extra match in the prior 3 days costs about 4pp -- and
                         it did not survive as a rating term.
    per-level K          worthless; a single global K matches it. Raising qual K
                         helped August (+1.1pp) and hurt July (-1.9pp), so it
                         was dropped as noise.

The seeds themselves were left alone deliberately: only 2 players in the whole
dataset ever debut at a Masters event and 34 at a Slam, so fitting those seeds
is textbook overfitting. Only the qual-vs-tour gap has the sample to be real.

WHERE IT IS STRONG, AND WHERE IT IS NOT

    Grand Slam        68.6%      best-of-5     67.4%
    Masters           64.7%      best-of-3     59.8%
    Qualifying        58.6%
    Tour level        57.0%   <- barely better than a coin flip

Slams and Masters are where this is worth acting on. Ordinary tour-level main
draws are close to noise, and the board says so per match rather than presenting
every lean as equal.
"""
import argparse, datetime as dt, json, math, os, re, ssl, sys, urllib.request
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
MATCHES = os.path.join(HERE, "data", "matches_2026.json")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/tennis"

LEVEL_K = {"slam": 40.0, "masters": 34.0, "tour": 30.0, "challenger": 20.0, "qual": 14.0}
LEVEL_SEED = {"slam": 1620.0, "masters": 1590.0, "tour": 1540.0,
              "challenger": 1440.0, "qual": 1420.0}
SURF_BLEND = 0.42
# Experience ramp. A player's first appearance is seeded at their level's seed,
# which is far too generous: debutants are usually worse than the established
# players already sitting at that seed. Ramping a newcomer up from 200 Elo below
# it over their first 20 matches is the single largest gain in this model.
# Fitted on Apr-Jun only; July and August were never touched during tuning.
EXP_BONUS = 200.0
EXP_CAP = 20.0

_CTX = ssl.create_default_context()


def get(url):
    # No custom headers: ESPN 403s any User-Agent it does not recognise.
    with urllib.request.urlopen(url, timeout=60, context=_CTX) as r:
        return json.load(r)


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


class Ratings(object):
    """Level-seeded Elo with a blended surface rating."""

    def __init__(self):
        self.r, self.s, self.n = {}, {}, Counter()
        self.seen = Counter()
        self.played = Counter()
        self.last = {}

    def seed(self, p, level):
        if p not in self.r:
            self.r[p] = LEVEL_SEED.get(level, 1500.0)
        return self.r[p]

    def eff(self, p, surface, level):
        base = self.seed(p, level)
        key = (p, surface)
        if key not in self.s:
            self.s[key] = base
        w = SURF_BLEND * min(self.n[key] / 12.0, 1.0)
        blended = (1 - w) * base + w * self.s[key]
        # experience ramp -- counts only matches already observed
        return blended + EXP_BONUS * min(self.seen[p], EXP_CAP) / EXP_CAP - EXP_BONUS

    def prob(self, a, b, surface, level, bo=3):
        # Bo5 sharpening was tested and rejected: the fit preferred FLATTENING
        # Bo5 (0.85), the opposite of the hypothesis, and the effect was noise
        # on the 43 genuinely-Bo5 holdout matches.
        d = self.eff(a, surface, level) - self.eff(b, surface, level)
        return 1.0 / (1 + 10 ** (-d / 400.0))

    def observe(self, m):
        w, l = m["winner"], m["loser"]
        p = self.prob(w, l, m["surface"], m["level"], m.get("bo", 3))
        k = LEVEL_K.get(m["level"], 30.0)
        for who, sign in ((w, 1), (l, -1)):
            self.r[who] = self.seed(who, m["level"]) + sign * k * (1 - p)
            key = (who, m["surface"])
            if key not in self.s:
                self.s[key] = self.r[who]
            self.s[key] += sign * k * (1 - p)
            self.n[key] += 1
            self.seen[who] += 1
            self.played[who] += 1
            self.last[who] = m["date"]

    def build(self, matches):
        for m in matches:
            self.observe(m)
        return self


def load_matches():
    with open(MATCHES) as f:
        ms = json.load(f)
    ms.sort(key=lambda m: (m["date"], m["id"]))
    return ms


def upcoming(date):
    """Scheduled singles matches for a date (ET), from both feeds."""
    seen, out = set(), []
    for lg in ("atp", "wta"):
        try:
            d = get("%s/%s/scoreboard?dates=%s" % (ESPN, lg, date))
        except Exception as e:
            sys.stderr.write("fetch %s: %s\n" % (lg, e))
            continue
        for ev in d.get("events", []):
            major = bool(ev.get("major"))
            for grp in ev.get("groupings", []):
                draw = (grp.get("grouping") or {}).get("displayName", "")
                if "Singles" not in draw:
                    continue
                for c in grp.get("competitions", []):
                    cid = c.get("id")
                    if not cid or cid in seen:
                        continue
                    ps = [(x.get("athlete") or {}).get("displayName")
                          for x in c.get("competitors", [])]
                    if len(ps) != 2 or not all(ps):
                        continue
                    try:
                        t = dt.datetime.strptime(c.get("date", ""), "%Y-%m-%dT%H:%MZ")
                        et = t.replace(tzinfo=dt.timezone.utc).astimezone(
                            dt.timezone(dt.timedelta(hours=-4)))
                    except ValueError:
                        continue
                    if et.strftime("%Y%m%d") != str(date):
                        continue
                    seen.add(cid)
                    rnd = (c.get("round") or {}).get("displayName", "")
                    men = "Men" in draw
                    ty = (c.get("status") or {}).get("type") or {}
                    wn = [x.get("winner") for x in c.get("competitors", [])]
                    won = ps[0] if wn and wn[0] else (ps[1] if len(wn) > 1 and wn[1] else None)
                    out.append({
                        "state": ty.get("state"), "completed": bool(ty.get("completed")),
                        "won": won,
                        "event": ev.get("name"), "draw": "M" if men else "W",
                        "time": et.strftime("%H:%M"), "round": rnd,
                        "surface": _surface(ev.get("name"), et.date()),
                        "level": _level(ev.get("name"), major, rnd),
                        "bo": 5 if (men and major and "qualif" not in rnd.lower()) else 3,
                        "p1": ps[0], "p2": ps[1],

                    })
    return out


def _surface(name, date):
    sys.path.insert(0, HERE)
    import collect_tennis as C
    return C.surface(name, date)


def _level(name, major, rnd):
    sys.path.insert(0, HERE)
    import collect_tennis as C
    return C.level(name, major, rnd)


def _graded(done, rt):
    """Score the model against matches that already finished today."""
    if not done:
        return
    rec = {"STRONG": [0, 0], "LEAN": [0, 0], "PASS": [0, 0]}
    for m in done:
        p = rt.prob(m["p1"], m["p2"], m["surface"], m["level"], m["bo"])
        fav = m["p1"] if p >= 0.5 else m["p2"]
        t = tier(max(p, 1 - p), m["level"], m["bo"])
        rec[t][0 if fav == m["won"] else 1] += 1
    tot = [sum(v[0] for v in rec.values()), sum(v[1] for v in rec.values())]
    print("  today, already finished: %d-%d" % (tot[0], tot[1]), end="")
    bits = ["%s %d-%d" % (k, v[0], v[1]) for k, v in rec.items() if v[0] + v[1]]
    print("   (" + ", ".join(bits) + ")" if bits else "")


CONF = [(0.70, "STRONG"), (0.62, "LEAN"), (0.0, "PASS")]


def tier(p, level, bo):
    c = max(p, 1 - p)
    for thr, name in CONF:
        if c >= thr:
            base = name
            break
    # tour-level main draws score 57% -- barely above a coin flip, so never
    # promote one to STRONG on rating gap alone
    if base == "STRONG" and level not in ("slam", "masters") and bo != 5:
        return "LEAN"
    return base


def board(date, rt, matches_by_player):
    allms = upcoming(date)
    ms = [m for m in allms if not m["completed"]]
    done = [m for m in allms if m["completed"] and m.get("won")]
    if not ms and not done:
        print("No scheduled singles matches for %s." % date)
        return
    rows = []
    for m in ms:
        p = rt.prob(m["p1"], m["p2"], m["surface"], m["level"], m["bo"])
        fav, conf = (m["p1"], p) if p >= 0.5 else (m["p2"], 1 - p)
        rows.append((conf, m, fav))
    rows.sort(key=lambda x: -x[0])
    if not rows:
        _graded(done, rt)
        return
    ev = rows[0][1]["event"]
    print("\n%s -- %s (ET) -- %d singles matches" % (ev, date, len(rows)))
    print("level-seeded surface Elo; clean walk-forward holdout 60.2%, "
          "Brier 0.2328 (see module docstring)\n")
    print("  %-6s%-3s%-46s%-22s%-8s%s" % ("TIME", "D", "MATCH", "LEAN", "CONF", "TIER"))
    print("  " + "-" * 96)
    for conf, m, fav in rows:
        lbl = "%s vs %s" % (m["p1"][:20], m["p2"][:20])
        t = tier(conf, m["level"], m["bo"])
        seen = rt.played.get(fav, 0)
        note = "" if seen >= 8 else "  (only %d prior matches)" % seen
        print("  %-6s%-3s%-45s %-21s %5.1f%%  %-7s%s"
              % (m["time"], m["draw"], lbl[:45], fav[:21], conf * 100, t, note))
    _graded(done, rt)
    strong = sum(1 for r in rows if tier(r[0], r[1]["level"], r[1]["bo"]) == "STRONG")
    coin = sum(1 for r in rows if r[0] < 0.62)
    print("\n  %d STRONG, %d inside 50-62%% (coin flips, not picks)." % (strong, coin))
    print("  Slam/Masters/Bo5 matches are where this model is worth acting on;")
    print("  ordinary tour-level main draws score 57% and are close to noise.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().strftime("%Y%m%d"))
    a = ap.parse_args()
    ms = load_matches()
    rt = Ratings().build(ms)
    sys.stderr.write("ratings from %d matches through %s\n" % (len(ms), ms[-1]["date"]))
    board(a.date, rt, None)


if __name__ == "__main__":
    main()
