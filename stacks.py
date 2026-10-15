"""Daily "stack" parlays: many high-probability legs, the way the big Kalshi
combos are built.

    python3 stacks.py            # today's and tomorrow's stacks from the last rebuild
    python3 stacks.py report     # graded record of every stack leg and ticket

WHAT A STACK IS

The winning combos people post are not built from picks. They are built from
legs that are each very likely -- "Over 0.5 goals", "Over 3.5 goals" in the
NHL, "No: Sharks win by over 2.5", a college total set 10 points under the
book's number -- and then multiplied together. Every leg is 80-97%; the
ticket is long because each leg pays so little.

HOW EACH LEG IS PRICED

The book already prices each game three ways: who wins (moneyline), by how
much (spread) and how many points (total). Those three numbers pin down a
full distribution of final scores:

  * hockey, soccer -- two independent Poisson scoring rates, solved so the
    model reproduces the book's win probability and its total;
  * football, basketball -- final margin and total points as normals centred
    on the spread and the total, with spreads measured for each sport.

Any line can then be read off that distribution, including alternate lines
the feed never prices. A same-game pair (an over plus a margin leg) is priced
JOINTLY from the same distribution, not multiplied as if independent.

WHY THE PROBABILITIES ARE HAIRCUT

Poisson underrates blowouts in hockey (empty-net goals turn 2-goal leads into
3) and normals underrate fat tails. Both errors make a "won't win by 3" or
"over a low total" leg look safer than it is. So every leg's MISS chance is
inflated by 30% before it is used: a modelled 92% leg is carried as 89.6%.
The ledger grades every leg; when enough have settled the calibration table
in `report` shows whether that haircut is too much or too little.

WHAT IT CANNOT DO

It does not know Kalshi's prices. Each ticket carries its FAIR payout --
what it should pay if the probabilities are right. Kalshi paying more than
that is a good bet; paying less, a bad one. Check before buying.

A 20-leg ticket of 90% legs wins 12% of the time. These are long shots built
from short legs, not locks.
"""
import argparse
import datetime as dt
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "stacks.json")
STATE = os.path.join(HERE, ".cache", "last_board.json")

MISS_INFLATE = 1.30          # see "why the probabilities are haircut"
# A 97% leg pays almost nothing -- ten of them return 1.3x -- while the posted
# winning combos run legs of roughly 85-92% (a 23-leg ticket paying 16x is
# ~89% a leg). So legs are kept in a band and the one nearest TARGET is
# preferred, not the safest one.
LEG_MIN, LEG_MAX = 0.82, 0.94
TARGET = 0.90
TIERS = (2, 3, 4, 6, 8, 10, 15, 20)
VARIANTS = 3                 # different tickets per size

# Standard deviation of (final margin - spread) and (final total - posted
# total), per sport. Margin figures are the ones the repo already uses
# (oddsdesk.SIGMA). Totals are set on the wide side of published estimates on
# purpose: a wider spread makes far-off alternate lines LESS likely, which errs
# toward caution.
SD_MARGIN = {"nfl": 13.5, "ncaaf": 16.5, "nba": 12.0, "ncaab": 11.0, "wnba": 11.0}
SD_TOTAL = {"nfl": 10.5, "ncaaf": 14.5, "nba": 18.0, "ncaab": 16.0, "wnba": 15.0}
POISSON = {"nhl"}            # plus every soccer league (passed in)

# alternate lines offered, as offsets from the posted number
ALT = {
    "nfl":   dict(over=(7, 10, 14), under=(7, 10, 14), fav=(7, 10, 14), dog=(3, 7, 10)),
    "ncaaf": dict(over=(10, 14, 17), under=(10, 14, 17), fav=(10, 14, 17), dog=(7, 10, 14)),
    "nba":   dict(over=(8, 12, 16), under=(8, 12, 16), fav=(8, 12, 16), dog=(4, 8, 12)),
    "ncaab": dict(over=(8, 12, 16), under=(8, 12, 16), fav=(8, 12, 16), dog=(4, 8, 12)),
    "wnba":  dict(over=(8, 12, 16), under=(8, 12, 16), fav=(8, 12, 16), dog=(4, 8, 12)),
}


# ------------------------------------------------------------------ maths
def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def nquant(p):
    """Inverse normal CDF by bisection; plenty for this use."""
    lo, hi = -8.0, 8.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if ncdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def pois(lam, kmax=15):
    out, p = [], math.exp(-lam)
    for k in range(kmax + 1):
        out.append(p)
        p *= lam / (k + 1)
    return out


def grid(lh, la, kmax=15):
    """{(home, away): probability} for independent Poisson scoring."""
    ph, pa = pois(lh, kmax), pois(la, kmax)
    return {(h, a): ph[h] * pa[a] for h in range(kmax + 1) for a in range(kmax + 1)}


def _pwin(g, ot):
    """P(home wins). In hockey a level score goes to OT/shootout, split by
    the scoring rates; in soccer a draw is not a win."""
    win = sum(p for (h, a), p in g.items() if h > a)
    if ot:
        tie = sum(p for (h, a), p in g.items() if h == a)
        win += tie * ot
    return win


def fit_poisson(p_home, total, p_draw=None, hockey=False, p_over=0.5):
    """Scoring rates (home, away) reproducing the book's numbers.

    Least squares on the win probability, the draw probability (soccer) and
    the posted total sitting at the median of the modelled total. Coarse grid
    over (mean total, home share), then a fine grid around the best cell.
    """
    t0 = total if total else (6.0 if hockey else 2.6)

    def err(mu, s):
        lh, la = mu * s, mu * (1 - s)
        g = grid(lh, la, 12)
        e = (_pwin(g, s if hockey else None) - p_home) ** 2
        if p_draw is not None:
            e += (sum(p for (h, a), p in g.items() if h == a) - p_draw) ** 2
        if total:
            over = sum(p for (h, a), p in g.items() if h + a > total)
            e += 0.5 * (over - p_over) ** 2
        return e

    span = 1.0 if hockey else 0.6
    best = min(((err(mu, s), mu, s)
                for mu in [t0 - span + k * span / 4 for k in range(9)] if mu > 0.3
                for s in [k / 50 for k in range(3, 48)]))
    _, m0, s0 = best
    best = min(((err(mu, s), mu, s)
                for mu in [m0 - span / 8 + k * span / 32 for k in range(9)] if mu > 0.3
                for s in [s0 - 0.02 + k * 0.004 for k in range(11)] if 0.02 < s < 0.98))
    _, mu, s = best
    return mu * s, mu * (1 - s)


# ------------------------------------------------------------ game models
class Game:
    """Score distribution for one game, plus a way to price any leg."""

    @staticmethod
    def SD_SHIFT(sport, p_over):
        return SD_TOTAL[sport] * nquant(min(max(p_over, 0.05), 0.95))

    def __init__(self, sport, home, away, p_home, total=None, spread=None,
                 p_draw=None, soccer=False, p_over=0.5):
        self.sport, self.home, self.away = sport, home, away
        self.soccer = soccer
        self.kind = "poisson" if (soccer or sport in POISSON) else "normal"
        if self.kind == "poisson":
            lh, la = fit_poisson(p_home, total, p_draw if soccer else None,
                                 hockey=not soccer, p_over=p_over)
            self.g = grid(lh, la)
            self.ot = None if soccer else lh / (lh + la)
            self.mu_total = lh + la
        else:
            sdm = SD_MARGIN[sport]
            # mean home margin: from the spread when posted, else from the
            # moneyline through the same normal
            if spread is not None:
                self.mu_m = spread
            else:
                self.mu_m = sdm * nquant(min(max(p_home, 0.01), 0.99))
            self.sd_m = sdm
            # a juiced total means the book's median is off the line
            self.mu_t = (total + self.SD_SHIFT(sport, p_over)) if total else None
            self.sd_t = SD_TOTAL[sport]
            self.mu_total = total

    # each leg is a predicate on the final (home, away) score
    def prob(self, preds):
        """Joint probability that every predicate holds."""
        if self.kind == "poisson":
            tot = 0.0
            for (h, a), p in self.g.items():
                if h == a and self.ot is not None:
                    # hockey: the OT/shootout winner gets one extra goal
                    for hh, aa, w in ((h + 1, a, self.ot), (h, a + 1, 1 - self.ot)):
                        if all(f(hh, aa) for f in preds):
                            tot += p * w
                    continue
                if all(f(h, a) for f in preds):
                    tot += p
            return tot
        # normals: margin and total treated as independent; integrate on a
        # grid fine enough that line placement on .5 is resolved
        if self.mu_t is None:
            return None
        tot = 0.0
        steps = 81
        for i in range(steps):
            zm = -4 + 8 * i / (steps - 1)
            m = self.mu_m + zm * self.sd_m
            wm = math.exp(-zm * zm / 2)
            for j in range(steps):
                zt = -4 + 8 * j / (steps - 1)
                t = self.mu_t + zt * self.sd_t
                wt = math.exp(-zt * zt / 2)
                h, a = (t + m) / 2, (t - m) / 2
                if all(f(h, a) for f in preds):
                    tot += wm * wt
        norm = (sum(math.exp(-(-4 + 8 * i / (steps - 1)) ** 2 / 2)
                    for i in range(steps))) ** 2
        return tot / norm


def haircut(p):
    return max(0.0, 1 - (1 - p) * MISS_INFLATE)


def half(x):
    """Nearest .5 line."""
    return math.floor(x) + 0.5


# ------------------------------------------------------------------- legs
def leg_specs(game, sport, fav_home):
    """Every candidate leg for a game as (group, label, spec). `group` keeps
    at most one total leg and one side leg per game on a ticket."""
    H, A = game.home, game.away
    fav, dog = (H, A) if fav_home else (A, H)
    out = []
    if game.kind == "poisson":
        unit = "goals"
        overs = (0.5, 1.5, 2.5) if game.soccer else (2.5, 3.5, 4.5)
        unders = (3.5, 4.5, 5.5) if game.soccer else (7.5, 8.5, 9.5)
        margins = (2.5, 3.5) if game.soccer else (2.5,)
        for L in overs:
            out.append(("total", f"Over {L} {unit}", dict(t="over", line=L)))
        for L in unders:
            out.append(("total", f"Under {L} {unit}", dict(t="under", line=L)))
        for team in (fav, dog):
            for L in margins:
                out.append(("side", f"No · {team} wins by over {L} {unit}",
                            dict(t="nomargin", team=team, line=L)))
        out.append(("side", f"{fav} to win", dict(t="win", team=fav)))
        if game.soccer:
            out.append(("btts", "Both teams to score", dict(t="btts")))
        return out
    alt = ALT[sport]
    T = game.mu_t
    spread = abs(game.mu_m)
    if T:
        for k in alt["over"]:
            L = half(T - k)
            if L > 0:
                out.append(("total", f"Over {L} points", dict(t="over", line=L)))
        for k in alt["under"]:
            L = half(T + k)
            out.append(("total", f"Under {L} points", dict(t="under", line=L)))
    for k in alt["fav"]:
        L = half(spread + k)
        out.append(("side", f"No · {fav} wins by over {L} points",
                    dict(t="nomargin", team=fav, line=L)))
    for k in alt["dog"]:
        L = half(k)
        out.append(("side", f"No · {dog} wins by over {L} points",
                    dict(t="nomargin", team=dog, line=L)))
    out.append(("side", f"{fav} to win", dict(t="win", team=fav)))
    return out


def predicate(spec, home, away):
    """spec -> f(home_score, away_score) -> bool."""
    t = spec["t"]
    if t == "over":
        return lambda h, a: h + a > spec["line"]
    if t == "under":
        return lambda h, a: h + a < spec["line"]
    if t == "btts":
        return lambda h, a: h >= 1 and a >= 1
    is_home = spec["team"] == home
    if t == "win":
        return (lambda h, a: h > a) if is_home else (lambda h, a: a > h)
    if t == "nomargin":
        L = spec["line"]
        return (lambda h, a: h - a < L) if is_home else (lambda h, a: a - h < L)
    raise ValueError(t)


# ----------------------------------------------------------------- inputs
def _ml_prob(price):
    try:
        v = int(str(price).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if -100 < v < 100:
        return None
    return 100 / (v + 100) if v > 0 else -v / (-v + 100)


def game_from_row(row, league, soccer):
    """Build a Game from a board row's market block, or None if unpriced."""
    m = row.get("mkt") or {}
    home, away = m.get("home"), m.get("away")
    if not home or not away:
        return None
    legs = {L["side"]: L for L in row.get("legs") or []}
    ph, pa = (_ml_prob((legs.get("home") or {}).get("price")),
              _ml_prob((legs.get("away") or {}).get("price")))
    pdr = _ml_prob((legs.get("draw") or {}).get("price"))
    if ph is None or pa is None:
        return None
    if soccer:
        if pdr is None:
            return None
        s = ph + pa + pdr
        ph, pa, pdr = ph / s, pa / s, pdr / s
    else:
        s = ph + pa
        ph, pa = ph / s, pa / s
    total = m.get("total")
    po, pu = _ml_prob(m.get("over")), _ml_prob(m.get("under"))
    p_over = po / (po + pu) if po and pu else 0.5
    spread = None
    if m.get("spread") is not None and m.get("fav") in ("home", "away") \
            and league in SD_MARGIN:
        mag = abs(float(m["spread"]))
        spread = mag if m["fav"] == "home" else -mag
    if league in SD_MARGIN and not total:
        return None                       # alt lines need a posted total
    if league not in SD_MARGIN and league not in POISSON and not soccer:
        return None                       # MLB, tennis, golf, UFC: not modelled
    return Game(league, home, away, ph, total=total, spread=spread,
                p_draw=pdr, soccer=soccer, p_over=p_over)


# ---------------------------------------------------------------- tickets
def candidates(board_slot, soccer_keys, labels=None):
    """All legs worth stacking, grouped by game, best first."""
    games = []
    for league, rows in (board_slot or {}).items():
        for row in rows:
            try:
                g = game_from_row(row, league, league in soccer_keys)
            except Exception as e:                       # one bad feed row
                print(f"stacks: {league} {row.get('label')}: {e}", file=sys.stderr)
                continue
            if not g:
                continue
            fav_home = g.prob([predicate(dict(t="win", team=g.home), g.home, g.away)]) >= \
                g.prob([predicate(dict(t="win", team=g.away), g.home, g.away)])
            legs = []
            for group, label, spec in leg_specs(g, league, fav_home):
                p = g.prob([predicate(spec, g.home, g.away)])
                if p is None:
                    continue
                q = haircut(p)
                if LEG_MIN <= q <= LEG_MAX:
                    legs.append(dict(group=group, label=label, spec=spec,
                                     p_model=round(p, 4), p=round(q, 4)))
            if not legs:
                continue
            legs.sort(key=lambda L: abs(L["p"] - TARGET))
            games.append(dict(gid=row["id"], league=league, lg=(labels or {}).get(league, league),
                              home=g.home, away=g.away, tip=row.get("tip"),
                              match=f"{g.away} at {g.home}", model=g, legs=legs))
    return games


def pick_for_game(game, n_legs):
    """1 or 2 legs from one game, from different groups, priced jointly."""
    chosen, groups = [], set()
    for L in game["legs"]:
        if L["group"] in groups:
            continue
        chosen.append(L)
        groups.add(L["group"])
        if len(chosen) == n_legs:
            break
    g = game["model"]
    raw = g.prob([predicate(L["spec"], g.home, g.away) for L in chosen])
    # the haircut applies per leg; carry it over to the joint figure
    joint = raw
    for L in chosen:
        joint *= L["p"] / L["p_model"] if L["p_model"] else 1
    return chosen, joint


def build_tickets(games, tiers=TIERS, variants=VARIANTS):
    """{size: [ticket, ...]}. One leg per game first; a second leg from the
    same game (priced jointly) only when there are fewer games than legs."""
    out = {}
    for n in tiers:
        made, used = [], {}
        for v in range(variants):
            # games not yet used in this size first, so the variants are
            # genuinely different tickets rather than one ticket three times
            order = sorted(games, key=lambda G: (used.get(G["gid"], 0),
                                                 abs(G["legs"][0]["p"] - TARGET)))
            per = {G["gid"]: 1 for G in order[:n]}
            extra = n - len(per)
            for G in order[:n]:
                if extra <= 0:
                    break
                if len({L["group"] for L in G["legs"]}) >= 2:
                    per[G["gid"]] = 2
                    extra -= 1
            if extra > 0:
                break                          # not enough legs on the slate
            legs, joint = [], 1.0
            for G in order[:n]:
                chosen, pj = pick_for_game(G, per[G["gid"]])
                joint *= pj
                legs.extend(dict(L, gid=G["gid"], league=G["league"], lg=G["lg"],
                                 match=G["match"], tip=G["tip"], home=G["home"],
                                 away=G["away"]) for L in chosen)
            for gid in per:
                used[gid] = used.get(gid, 0) + 1
            sig = tuple(sorted((L["gid"], L["label"]) for L in legs))
            if any(t["sig"] == sig for t in made):
                continue
            made.append(dict(sig=sig, n=len(legs), prob=round(joint, 4),
                             fair=round(1 / joint, 2) if joint > 0 else None,
                             legs=legs))
        for t in made:
            t.pop("sig")
        out[n] = made
    return out


def build(slots, soccer_keys, labels=None):
    res = {}
    for slot in ("today", "tomorrow"):
        games = candidates(slots.get(slot), soccer_keys, labels)
        res[slot] = dict(games=len(games), tickets=build_tickets(games))
    return res


# ---------------------------------------------------------------- ledger
def load():
    try:
        with open(LEDGER) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"legs": {}, "tickets": {}}


def save(d):
    with open(LEDGER, "w") as fh:
        json.dump(d, fh, indent=1, sort_keys=True)


def record(stacks, dates):
    """Log every leg and ticket of today's stacks. Idempotent per day."""
    book = load()
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=-4))).isoformat()[:16]
    for slot in ("today",):
        day = dates.get(slot)
        if not day:
            continue
        for n, tickets in (stacks.get(slot) or {}).get("tickets", {}).items():
            for i, t in enumerate(tickets):
                tkey = f"{day}:{n}:{i}"
                if tkey in book["tickets"]:
                    continue                    # first version of the day stands
                keys = []
                for L in t["legs"]:
                    lkey = f'{L["gid"]}|{L["label"]}'
                    keys.append(lkey)
                    book["legs"].setdefault(lkey, dict(
                        league=L["league"], match=L["match"], label=L["label"],
                        spec=L["spec"], home=L["home"], away=L["away"],
                        p=L["p"], p_model=L["p_model"], status="open",
                        logged=now, date=f"{day[:4]}-{day[4:6]}-{day[6:]}"))
                book["tickets"][tkey] = dict(n=int(n), prob=t["prob"], fair=t["fair"],
                                             legs=keys, status="open", logged=now)
    save(book)


def grade(final):
    """`final(league, comp_id, entry)` is ledger._final. Settles legs, then
    tickets whose legs are all settled."""
    book = load()
    for key, L in book["legs"].items():
        if L["status"] != "open":
            continue
        gid = key.split("|", 1)[0]
        lg, comp = gid.split(":", 1)
        res = final(lg, comp, L)
        if not res or res.get("live") or res.get("missing"):
            continue
        if res.get("void"):
            L["status"] = "void"
            continue
        sc = res.get("scores") or {}
        h, a = sc.get(L["home"]), sc.get(L["away"])
        if not isinstance(h, int) or not isinstance(a, int):
            continue
        ok = predicate(L["spec"], L["home"], L["away"])(h, a)
        L["status"] = "won" if ok else "lost"
        L["score"] = f"{L['away']} {a} - {L['home']} {h}"
    for t in book["tickets"].values():
        if t["status"] != "open":
            continue
        st = [book["legs"].get(k, {}).get("status", "open") for k in t["legs"]]
        if "lost" in st:
            t["status"] = "lost"
        elif all(s in ("won", "void") for s in st):
            t["status"] = "won"
    save(book)


def report():
    book = load()
    legs = [L for L in book["legs"].values() if L["status"] in ("won", "lost")]
    bands = {}
    for L in legs:
        b = min(int(L["p"] * 100) // 5 * 5, 95)
        x = bands.setdefault(b, [0, 0, 0.0])
        x[0] += 1
        x[1] += L["status"] == "won"
        x[2] += L["p"]
    tk = [t for t in book["tickets"].values() if t["status"] in ("won", "lost")]
    by_n = {}
    for t in tk:
        x = by_n.setdefault(t["n"], [0, 0, 0.0])
        x[0] += 1
        x[1] += t["status"] == "won"
        x[2] += t["prob"]
    return dict(
        legs=len(legs), legs_won=sum(1 for L in legs if L["status"] == "won"),
        calibration=[dict(band=b, n=v[0], said=round(100 * v[2] / v[0], 1),
                          actual=round(100 * v[1] / v[0], 1))
                     for b, v in sorted(bands.items())],
        tickets=[dict(n=n, played=v[0], won=v[1],
                      expected=round(v[2], 1))
                 for n, v in sorted(by_n.items())])


# -------------------------------------------------------------------- CLI
def show(res):
    for slot in ("today", "tomorrow"):
        r = res.get(slot) or {}
        print(f"\n{slot.upper()} -- {r.get('games', 0)} games with priced legs")
        for n, tickets in (r.get("tickets") or {}).items():
            for i, t in enumerate(tickets):
                print(f"\n  {n}-LEG #{i+1}   hits {100*t['prob']:.1f}%   "
                      f"fair payout {t['fair']:.2f}x  ($10 -> ${10*t['fair']:.2f})")
                for L in t["legs"]:
                    print(f"     {100*L['p']:5.1f}%  {L['label']:<44} {L['match']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="show", choices=["show", "report"])
    a = ap.parse_args()
    if a.cmd == "report":
        print(json.dumps(report(), indent=1))
        return
    try:
        with open(STATE) as fh:
            board = json.load(fh)
    except (OSError, ValueError):
        raise SystemExit("no board yet -- run python3 rebuild_board.py first")
    show(board.get("stacks") or {})
    print("\nOnly buy a ticket where Kalshi's payout beats the fair payout.")


if __name__ == "__main__":
    main()
