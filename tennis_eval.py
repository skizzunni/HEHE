#!/usr/bin/env python3
"""Walk-forward evaluation harness for tennis rating systems.

Every model sees a match ONLY after being scored on it, so no variant can peek.
Predictions before BURN_IN are discarded (ratings are still converging) but the
matches are still learned from.

    python3 tennis_eval.py                 # score every registered model
    python3 tennis_eval.py --holdout 08    # score on August only
"""
import argparse, json, math, os, datetime as dt
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "matches_2026.json")
BURN_IN = "2026-04-01"     # predictions before this are not scored

LEVEL_K = {"slam": 40.0, "masters": 34.0, "tour": 30.0,
           "challenger": 20.0, "qual": 14.0}
LEVEL_SEED = {"slam": 1620.0, "masters": 1590.0, "tour": 1540.0,
              "challenger": 1440.0, "qual": 1420.0}


def load():
    with open(DATA) as f:
        ms = json.load(f)
    ms.sort(key=lambda m: (m["date"], m["id"]))
    return ms


# --------------------------------------------------------------- models

class Model(object):
    name = "base"
    def predict(self, m):
        """P(winner listed first wins). Return None to abstain."""
        raise NotImplementedError
    def update(self, m):
        pass


class WinCount(Model):
    """'Who has won more matches this year' -- the baseline Elo could not beat."""
    name = "win-count"
    def __init__(self):
        self.w = Counter(); self.l = Counter()
    def predict(self, m):
        a, b = m["winner"], m["loser"]
        wa, wb = self.w[a], self.w[b]
        if wa == wb:
            return 0.5
        return 0.5 + 0.5 * (1 if wa > wb else -1) * min(abs(wa - wb) / 20.0, 0.45)
    def update(self, m):
        self.w[m["winner"]] += 1; self.l[m["loser"]] += 1


class PlainElo(Model):
    """Everyone starts 1500, K=32, no level or surface awareness."""
    name = "plain-elo"
    K = 32.0
    def __init__(self):
        self.r = defaultdict(lambda: 1500.0)
    def predict(self, m):
        return 1.0 / (1 + 10 ** ((self.r[m["loser"]] - self.r[m["winner"]]) / 400.0))
    def update(self, m):
        p = self.predict(m)
        self.r[m["winner"]] += self.K * (1 - p)
        self.r[m["loser"]] -= self.K * (1 - p)


class LevelElo(PlainElo):
    """Seed by the level a player debuts at, and scale K by match importance.

    This targets the exact failure the tennis.py docstring documents: a
    Challenger win counting as much as a Slam win, and everyone cold-starting
    equal so volume at a low level outranks quality at a high one.
    """
    name = "level-elo"
    def __init__(self):
        self.r = {}
    def _get(self, p, m):
        if p not in self.r:
            self.r[p] = LEVEL_SEED.get(m["level"], 1500.0)
        return self.r[p]
    def predict(self, m):
        ra, rb = self._get(m["winner"], m), self._get(m["loser"], m)
        return 1.0 / (1 + 10 ** ((rb - ra) / 400.0))
    def update(self, m):
        p = self.predict(m)
        k = LEVEL_K.get(m["level"], 30.0)
        self.r[m["winner"]] += k * (1 - p)
        self.r[m["loser"]] -= k * (1 - p)


class SurfaceElo(LevelElo):
    """Level-seeded Elo plus a surface-specific rating, blended."""
    name = "surface-elo"
    BLEND = 0.42
    def __init__(self):
        LevelElo.__init__(self)
        self.s = {}
        self.n = Counter()
    def _sget(self, p, surf, m):
        key = (p, surf)
        if key not in self.s:
            self.s[key] = self._get(p, m)
        return self.s[key]
    def _eff(self, p, m):
        base = self._get(p, m)
        surf = self._sget(p, m["surface"], m)
        n = self.n[(p, m["surface"])]
        w = self.BLEND * min(n / 12.0, 1.0)     # trust surface only once it has data
        return (1 - w) * base + w * surf
    def predict(self, m):
        ra, rb = self._eff(m["winner"], m), self._eff(m["loser"], m)
        return 1.0 / (1 + 10 ** ((rb - ra) / 400.0))
    def update(self, m):
        p = self.predict(m)
        k = LEVEL_K.get(m["level"], 30.0)
        for who, sign in ((m["winner"], 1), (m["loser"], -1)):
            self.r[who] = self._get(who, m) + sign * k * (1 - p)
            key = (who, m["surface"])
            self.s[key] = self._sget(who, m["surface"], m) + sign * k * (1 - p)
            self.n[key] += 1


MODELS = [WinCount, PlainElo, LevelElo, SurfaceElo]


# --------------------------------------------------------------- scoring

def evaluate(models, matches, holdout_month=None):
    stats = {m.name: {"n": 0, "hit": 0, "brier": 0.0, "ll": 0.0,
                      "buckets": defaultdict(lambda: [0, 0])} for m in models}
    for mt in matches:
        scored = mt["date"] >= BURN_IN
        if holdout_month:
            scored = scored and mt["date"][5:7] == holdout_month
        for mdl in models:
            if scored:
                # the listed "winner" actually won, so the label is always 1
                p = mdl.predict(mt)
                if p is not None:
                    p = min(max(p, 1e-6), 1 - 1e-6)
                    s = stats[mdl.name]
                    s["n"] += 1
                    s["hit"] += 1 if p > 0.5 else (0 if p < 0.5 else 0.5)
                    s["brier"] += (1 - p) ** 2
                    s["ll"] += -math.log(p)
                    conf = p if p >= 0.5 else 1 - p
                    b = min(int(conf * 20) * 5, 95)
                    s["buckets"][b][0] += 1 if p > 0.5 else 0
                    s["buckets"][b][1] += 1
            mdl.update(mt)
    return stats


def report(stats, label):
    print("\n=== %s ===" % label)
    print("%-14s %7s %9s %9s %9s" % ("model", "n", "accuracy", "brier", "logloss"))
    print("-" * 52)
    rows = []
    for name, s in stats.items():
        if not s["n"]:
            continue
        rows.append((s["hit"] / s["n"], name, s))
    rows.sort(key=lambda r: -r[0])
    for acc, name, s in rows:
        print("%-14s %7d %8.1f%% %9.4f %9.4f"
              % (name, s["n"], 100 * acc, s["brier"] / s["n"], s["ll"] / s["n"]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", default=None, help="month e.g. 08")
    a = ap.parse_args()
    ms = load()
    print("%d matches, %s to %s" % (len(ms), ms[0]["date"], ms[-1]["date"]))
    mods = [c() for c in MODELS]
    st = evaluate(mods, ms, a.holdout)
    rows = report(st, "holdout %s" % (a.holdout or "all from " + BURN_IN))
    if rows:
        best = rows[0]
        print("\ncalibration -- %s" % best[1])
        print("  %-10s %7s %9s %9s" % ("conf", "n", "predicted", "actual"))
        for b in sorted(best[2]["buckets"]):
            hit, n = best[2]["buckets"][b]
            if n >= 25:
                print("  %2d-%2d%%     %7d %8.1f%% %8.1f%%"
                      % (b, b + 5, n, b + 2.5, 100.0 * hit / n))


if __name__ == "__main__":
    main()
