"""The whole-ticket optimizer against brute force, and its contract."""
import itertools
import math
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tickets as T  # noqa: E402


def leg(g, p, dec, lg="nfl", t="under", label=None):
    return dict(gid=g, p=p, dec=dec, league=lg, spec=dict(t=t), label=label or f"{g}:{p}:{dec}")


def brute(legs, target, min_p, max_legs, boost=0.0, kind_cap=T.KIND_CAP):
    """Every combination of at most one line per game: the true optimum."""
    need = T.needed_price(target, boost)
    by = {}
    for L in legs:
        if L["p"] >= min_p:
            by.setdefault(L["gid"], []).append(L)
    best = None
    games = list(by)
    for n in range(1, max_legs + 1):
        for gs in itertools.combinations(games, n):
            for pick in itertools.product(*(by[g] for g in gs)):
                ks = {}
                for L in pick:
                    ks[T.kind(L)] = ks.get(T.kind(L), 0) + 1
                if max(ks.values()) > kind_cap:
                    continue
                d = math.prod(L["dec"] for L in pick)
                if d < need - 1e-12:
                    continue
                p = math.prod(L["p"] for L in pick)
                if best is None or p > best[0] + 1e-12 or (abs(p - best[0]) <= 1e-12 and d > best[1]):
                    best = (p, d)
    return best


class Optimizer(unittest.TestCase):
    def test_matches_brute_force_on_random_small_pools(self):
        rng = random.Random(7)
        for case in range(300):
            legs = []
            for g in range(rng.randint(2, 7)):
                for _ in range(rng.randint(1, 4)):
                    p = rng.uniform(0.55, 0.97)
                    dec = max(1.01, (1 / p) * rng.uniform(0.85, 1.02))   # priced near the chance
                    legs.append(leg(f"g{g}", round(p, 4), round(dec, 4),
                                    t=rng.choice(["under", "over", "win"])))
            target, min_p = rng.choice([1.5, 2, 3, 5]), rng.choice([0.6, 0.7, 0.8])
            K, boost = rng.randint(1, 5), rng.choice([0, 0.25, 0.5])
            want = brute(legs, target, min_p, K, boost)
            got = T.optimize(legs, target, min_p, max_legs=K, boost=boost)
            self.assertTrue(got["exact"])
            if want is None:
                self.assertIsNone(got["legs"], case)
            else:
                self.assertIsNotNone(got["legs"], case)
                self.assertAlmostEqual(got["prob"], want[0], places=10, msg=case)

    def test_matches_brute_force_on_larger_pools(self):
        rng = random.Random(21)
        for case in range(40):
            legs = []
            for g in range(9):
                for _ in range(3):
                    p = rng.uniform(0.7, 0.97)
                    legs.append(leg(f"g{g}", round(p, 4), round(max(1.01, (1 / p) * rng.uniform(0.88, 1.0)), 4),
                                    lg=rng.choice(["nfl", "ncaaf"]), t=rng.choice(["under", "over", "win"])))
            target = rng.choice([2, 3])
            want = brute(legs, target, 0.75, 5)
            got = T.optimize(legs, target, 0.75, max_legs=5)
            self.assertTrue(got["exact"])
            self.assertEqual(got["legs"] is None, want is None, case)
            if want:
                self.assertAlmostEqual(got["prob"], want[0], places=10, msg=case)

    def test_contract(self):
        legs = [leg("a", 0.92, 1.10), leg("a", 0.85, 1.30, t="over"), leg("b", 0.90, 1.25),
                leg("c", 0.88, 1.35, t="win"), leg("d", 0.70, 1.45, t="win")]
        r = T.optimize(legs, 2.0, 0.80)
        self.assertIsNotNone(r["legs"])
        self.assertGreaterEqual(r["dec"], 2.0 - 1e-12)                     # payout reached
        self.assertTrue(all(L["p"] >= 0.80 for L in r["legs"]))              # standard kept
        self.assertEqual(len({L["gid"] for L in r["legs"]}), len(r["legs"]))  # one per game
        self.assertLessEqual(len(r["legs"]), T.MAX_LEGS)
        # the 0.70 leg is never used to reach the target at an 0.80 standard
        self.assertNotIn("d", {L["gid"] for L in r["legs"]})

    def test_standard_is_never_lowered(self):
        """A below-standard leg that would give a likelier ticket is still not used."""
        legs = [leg("a", 0.85, 1.5), leg("b", 0.85, 1.5, t="win"), leg("d", 0.79, 2.1, t="over")]
        r = T.optimize(legs, 2.0, 0.80)
        self.assertEqual(sorted(L["gid"] for L in r["legs"]), ["a", "b"])
        self.assertAlmostEqual(r["prob"], 0.7225)

    def test_alternative_line_beats_adding_a_leg(self):
        """A game's likeliest line pays too little; its longer line finishes
        the ticket with fewer legs and a higher chance."""
        legs = [leg("a", 0.95, 1.40), leg("a", 0.86, 1.62, t="over"),
                leg("b", 0.95, 1.40, t="win"), leg("c", 0.90, 1.12, t="side")]
        r = T.optimize(legs, 2.2, 0.80)
        self.assertEqual(sorted(L["label"] for L in r["legs"]),
                         sorted([legs[1]["label"], legs[2]["label"]]))
        self.assertAlmostEqual(r["prob"], 0.86 * 0.95)

    def test_unavailable_is_said_not_weakened(self):
        legs = [leg(f"g{i}", 0.91, 1.08, t=["under", "over", "win"][i % 3], lg=f"l{i}") for i in range(6)]
        r = T.optimize(legs, 3.0, 0.90)
        self.assertIsNone(r["legs"])
        c = T.ceiling(legs, 0.90)
        self.assertLess(c["total"], 3.0)
        row = [x for x in T.frontier(legs, targets=(3.0,), standards=(0.90,))][0]
        self.assertIsNone(row["legs"])
        self.assertAlmostEqual(row["ceiling"], round(1.08 ** 6, 3))

    def test_boost_lowers_the_price_needed(self):
        self.assertAlmostEqual(T.needed_price(5.0, 0.0), 5.0)
        self.assertAlmostEqual(T.needed_price(5.0, 1.0), 3.0)                 # +100% on winnings
        self.assertAlmostEqual(T.total_return(3.0, 1.0), 5.0)

    def test_kind_cap(self):
        legs = [leg(f"g{i}", 0.95, 1.35) for i in range(6)]                   # six NFL unders
        r = T.optimize(legs, 3.0, 0.80)
        self.assertIsNone(r["legs"])                                           # 1.35^3 < 3, cap 3
        r = T.optimize(legs, 2.4, 0.80)
        self.assertEqual(len(r["legs"]), 3)

    def test_budget_reports_approximation(self):
        rng = random.Random(1)
        legs = [leg(f"g{g}", round(rng.uniform(0.8, 0.95), 4), round(rng.uniform(1.15, 1.6), 4),
                    lg=f"l{g}") for g in range(40)]
        r = T.optimize(legs, 3.0, 0.8, max_legs=6, budget=3)
        self.assertFalse(r["exact"])


class WagerAndRecord(unittest.TestCase):
    NOW = None

    def live(self, i, p, price, kind="game", **kw):
        import datetime as dt
        now = dt.datetime(2026, 10, 20, 12, 10, tzinfo=dt.timezone.utc)       # 8:10 AM ET
        self.NOW = now
        L = dict(gid=f"nfl:{i}", label=f"leg{i}", p=p, price=price, fd=f"m:{i}", where="Alternate Total",
                 spec=dict(t="under", line=44.5), kind=kind, league="nfl", home="H", away="A",
                 quoted=(now - dt.timedelta(minutes=5)).isoformat(), start=(now + dt.timedelta(hours=3)).isoformat())
        L.update(kw)
        return L

    def test_verify_reasons(self):
        import datetime as dt
        good = self.live(1, 0.8, "-300")
        self.assertEqual(T.verify(dict(good, dec=1.33), self.NOW), (True, []))
        stale = dict(good, dec=1.33, quoted=(self.NOW - dt.timedelta(hours=2)).isoformat())
        self.assertIn("quote older than 30 min", T.verify(stale, self.NOW)[1])
        started = dict(good, dec=1.33, start=(self.NOW - dt.timedelta(minutes=1)).isoformat())
        self.assertIn("game has started", T.verify(started, self.NOW)[1])
        prop = dict(good, dec=1.33, kind="prop", plays=False, play="lineup not out")
        self.assertIn("player not confirmed to play (lineup not out)", T.verify(prop, self.NOW)[1])
        self.assertIn("no FanDuel selection id", T.verify(dict(good, dec=1.33, fd=None), self.NOW)[1])

    def test_freeze_grade_replay(self):
        import datetime as dt
        import tempfile
        import props_ledger
        pool = [self.live(i, 0.80 + 0.01 * (i % 3), "-250") for i in range(8)]
        front = T.build_frontier(pool, targets=(2.0,), standards=(0.80,), now=self.NOW)
        self.assertTrue(front["rows"][0]["legs"])
        path = os.path.join(tempfile.mkdtemp(), "f.json")
        real = props_ledger.LEDGER
        props_ledger.LEDGER = os.path.join(os.path.dirname(path), "p.json")
        try:
            T.record(front, pool, "2026-10-20", set_card=False, path=path, now=self.NOW)
            T.record(front, pool, "2026-10-20", set_card=False, path=path, now=self.NOW)
            self.assertEqual(len(T.load(path)["days"]["2026-10-20"]["versions"]), 1)   # unchanged: one version
            late = self.NOW + dt.timedelta(hours=14)
            T.record(front, pool, "2026-10-20", set_card=True, path=path, now=late)
            self.assertNotIn("tickets", T.load(path)["days"]["2026-10-20"])        # 10 PM: no card
            T.record(front, pool, "2026-10-20", set_card=True, path=path, now=self.NOW)
            self.assertTrue(T.replay("2026-10-20", path))
            frozen = [L["label"] for L in T.load(path)["days"]["2026-10-20"]["tickets"][0]["legs"]]
            T.record(dict(front, rows=[dict(front["rows"][0], legs=[])]), pool, "2026-10-20", set_card=True,
                     path=path, now=self.NOW)
            self.assertEqual([L["label"] for L in T.load(path)["days"]["2026-10-20"]["tickets"][0]["legs"]], frozen)
            # settle: every leg's game ends 20-17 (under 44.5 wins), one game 24-20 on an integer line pushes
            b = T.load(path)
            legs = b["days"]["2026-10-20"]["tickets"][0]["legs"]
            legs[0]["spec"] = dict(t="under", line=44)
            T.save(b, path)
            final = lambda lg, c, L: dict(scores={"H": 24, "A": 20}) if L is legs[0] or L["label"] == legs[0]["label"] \
                else dict(scores={"H": 20, "A": 17})
            T.grade(final, path)
            t = T.load(path)["days"]["2026-10-20"]["tickets"][0]
            self.assertEqual(t["legs"][0]["status"], "void")                    # the push leaves the slip
            self.assertEqual(t["status"], "won")
            rep = T.report(path)[0]
            self.assertEqual((rep["made"], rep["cashed"], rep["settled"]), (1, 1, 1))
        finally:
            props_ledger.LEDGER = real


class PregameArchive(unittest.TestCase):
    def test_only_before_start_and_only_changes(self):
        import datetime as dt
        import tempfile
        import participation
        import pregame
        now = dt.datetime(2026, 10, 20, 1, 0, tzinfo=dt.timezone.utc)
        rows = {"nhl": [dict(id="nhl:9", mkt=dict(start="2026-10-20T23:00Z"),
                             comp=dict(competitors=[dict(team=dict(abbreviation="MTL"), probables=[
                                 dict(athlete=dict(displayName="Jacob Fowler"), name="probableStartingGoalie")])])),
                        dict(id="nhl:8", mkt=dict(start="2026-10-19T23:00Z"), comp={})]}
        real = participation._summary
        participation._summary = lambda lg, eid: dict(rosters=[], injuries=[dict(team=dict(abbreviation="MTL"),
            injuries=[dict(athlete=dict(displayName="X Y", position=dict(abbreviation="C")), status="Out")])])
        try:
            snap = pregame.snapshot(rows, now)
        finally:
            participation._summary = real
        self.assertEqual(list(snap), ["nhl:9"])                                    # started game skipped
        self.assertEqual(snap["nhl:9"]["probables"], {"MTL": [["Jacob Fowler", "probableStartingGoalie"]]})
        self.assertEqual(snap["nhl:9"]["injuries"], [["MTL", "X Y", "Out", "C"]])
        p = os.path.join(tempfile.mkdtemp(), "f.json")
        pregame.archive(snap, "2026-10-20", p)
        pregame.archive(snap, "2026-10-20", p)
        self.assertEqual(len(T.load(p)["days"]["2026-10-20"]["inputs"]["nhl:9"]), 1)
        snap["nhl:9"]["injuries"] = []
        pregame.archive(snap, "2026-10-20", p)
        self.assertEqual(len(T.load(p)["days"]["2026-10-20"]["inputs"]["nhl:9"]), 2)


class Evidence(unittest.TestCase):
    def test_band_verdicts_never_adjust(self):
        rows = [(0.91, i % 10 != 0, "2026-10-01", f"g{i}") for i in range(100)]      # 90% hit at 91%
        r = [x for x in T._band_rows(rows) if x["band"] == "90-95%"][0]
        self.assertEqual((r["n"], r["games"], r["won"]), (100, 100, 90))
        self.assertEqual(r["verdict"], "supported")
        thin = [x for x in T._band_rows(rows[:10]) if x["band"] == "90-95%"][0]
        self.assertEqual(thin["verdict"], "thin")
        bad = [(0.91, i % 2 == 0, "2026-10-01", f"g{i}") for i in range(100)]          # 50% at 91%
        self.assertEqual([x for x in T._band_rows(bad) if x["band"] == "90-95%"][0]["verdict"], "contradicted")

    def test_clustered_legs_widen_the_range(self):
        """Ten lines of one game are one trial, not ten."""
        one = [(0.91, True, "d", "g") for _ in range(10)] + [(0.91, i % 3 != 0, "d", f"h{i}") for i in range(40)]
        r = [x for x in T._band_rows(one) if x["band"] == "90-95%"][0]
        self.assertEqual(r["games"], 41)
        w = T.wilson(r["won"], r["n"])
        self.assertGreater(r["ci95"][1] - r["ci95"][0], w[1] - w[0])           # wider than counting legs


if __name__ == "__main__":
    unittest.main()
