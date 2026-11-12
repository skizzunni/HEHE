import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import daily_review  # noqa: E402


def row(day, side, won, conf=70):
    return dict(dc=True, date=day, myside=side, conf=conf, status="won" if won else "lost")


class DcSide(unittest.TestCase):
    def test_split_and_halves(self):
        L = {}
        for i in range(20):
            L[f"h{i}"] = row("2026-10-01" if i < 10 else "2026-10-20", "home", i % 4 != 0)
        for i in range(10):
            L[f"a{i}"] = row("2026-10-01" if i < 5 else "2026-10-20", "away", i < 3)
        L["x"] = dict(row("2026-10-02", "home", False), record_excluded="unpriced")
        L["s"] = dict(row("2026-10-02", "home", False), dc=False)
        out = daily_review.dc_side_line(L, min_n=30)
        self.assertIn("home 75% vs 70% stated on 20", out)
        self.assertIn("away 30% vs 70% stated on 10 (halves 60%, 0%) SHORT", out)
        self.assertNotIn("home 75% vs 70% stated on 20 (halves 70%, 80%) SHORT", out)

    def test_straight_wins_and_draws(self):
        L = {f"h{i}": row("2026-10-01", "home", True) for i in range(30)}
        for k in L.values():
            k["league"] = "epl"
        L["s1"] = dict(row("2026-10-02", "home", False), dc=False, league="epl", scores={"A": 1, "B": 1})
        L["s2"] = dict(row("2026-10-02", "home", False), dc=False, league="epl", scores={"A": 0, "B": 2})
        L["s3"] = dict(row("2026-10-02", "home", True), dc=False, league="epl")
        L["n"] = dict(row("2026-10-02", "home", False), dc=False, league="nba", scores={"A": 9, "B": 9})
        out = daily_review.dc_side_line(L, min_n=30)
        self.assertIn("Straight wins: 33% vs 70% stated on 3; 1 of 2 losses were draws.", out)

    def test_too_few(self):
        self.assertIsNone(daily_review.dc_side_line({"a": row("2026-10-01", "home", True)}))


class DcBands(unittest.TestCase):
    def test_band_short_in_both_halves(self):
        L = {}
        for i in range(40):
            L[f"a{i}"] = row("2026-10-01" if i < 20 else "2026-10-20", "home", i % 2 == 0, conf=82)
        for i in range(40):
            L[f"b{i}"] = row("2026-10-01" if i < 20 else "2026-10-20", "home", True, conf=72)
        out = daily_review.dc_side_line(L)
        self.assertIn("Short in both halves: 80-100% (50%, then 50%).", out)
        self.assertNotIn("70-75%", out)


class NhlB2b(unittest.TestCase):
    def test_line(self):
        import datetime as dt
        T = lambda i, n: dict(id=i, name=n)
        def fn(day, finished=False):
            if day == dt.date(2026, 11, 9):
                return [dict(home=T("1", "Oilers"), away=T("2", "Rangers"))]
            return [dict(home=T("3", "Kings"), away=T("2", "Rangers")),        # Rangers tired, away
                    dict(home=T("1", "Oilers"), away=T("4", "Wild")),          # Oilers tired, home
                    dict(home=T("5", "Jets"), away=T("6", "Devils"))]          # both rested
        L = {"a": dict(league="nhl", date="2026-11-10", pick="Rangers"), "b": dict(league="nhl", date="2026-11-10", pick="Wild")}
        out = daily_review.nhl_b2b_line(dt.date(2026, 11, 10), games_fn=fn, ledger=L)
        self.assertIn("Rangers (away, played yesterday) v Kings (rested) -- the board has the tired side", out)
        self.assertIn("Oilers (home, played yesterday) v Wild (rested) -- the board has the rested side", out)
        self.assertNotIn("Jets", out)
        self.assertIsNone(daily_review.nhl_b2b_line(dt.date(2026, 11, 10), games_fn=lambda d, finished=False: [], ledger={}))


class PreregLine(unittest.TestCase):
    def test_history_attached(self):
        from unittest import mock
        import locks
        st = dict(name="college + NFL spreads getting 7-13.5 points", won=73, n=90, said=81.0, need=100, verdict="waiting")
        with mock.patch.object(locks, "prereg_status", lambda: st):
            out = daily_review.prereg_line()
        self.assertTrue(out.startswith("Pre-registered test, college + NFL spreads getting 7-13.5 points: 73/90 (81% vs 81% stated); waiting for 100 legs."))
        self.assertIn("dogs getting 7.5-14 covered 53% then 61% in the NFL", out)


class DrawRate(unittest.TestCase):
    def test_line(self):
        L = {"dc": dict(dc=True, league="epl"), "dc2": dict(dc=True, league="mls")}
        for i in range(20):
            L[f"e{i}"] = dict(league="epl", status="won", scores={"A": 1, "B": 1 if i < 5 else 0})
            L[f"m{i}"] = dict(league="mls", status="won", scores={"A": 2, "B": 2 if i < 10 else 0})
        L["n"] = dict(league="nba", status="won", scores={"A": 100, "B": 100})
        out = daily_review.draw_rate_line(L)
        self.assertEqual(out, "Soccer draws on the board: 38% of 40 games; most in MLS 50% of 20, EPL 25% of 20"
                              " -- where a straight win most often loses to a draw.")
        self.assertIsNone(daily_review.draw_rate_line({}))


class LockTypes(unittest.TestCase):
    def test_line(self):
        legs = []
        for i in range(20):
            d = "2026-10-01" if i < 10 else "2026-10-20"
            legs.append(dict(date=d, label=f"Over {i}.5", p=0.8, status="won" if i % 10 else "lost"))
            legs.append(dict(date=d, label=f"P{i}: 2+ Assists", kind="prop", p=0.85, status="won" if i % 2 else "lost"))
        out = daily_review.locks_type_line(legs)
        self.assertIn("total 90% then 90% (vs 80%, 80%)", out)
        self.assertIn("prop 50% then 50% (vs 85%, 85%)", out)
        self.assertTrue(out.endswith("Short in both halves: prop."))
        self.assertIsNone(daily_review.locks_type_line(legs[:10]))


class RosterCheck(unittest.TestCase):
    def test_check(self):
        teams = {"sports": [{"leagues": [{"teams": [{"team": {"displayName": "Milwaukee Bucks", "id": "15"}},
                                                    {"team": {"displayName": "Los Angeles Lakers", "id": "13"}}]}]}]}
        rosters = {"15": {"athletes": [{"displayName": "Jaime Jaquez Jr."}]},
                   "13": {"athletes": [{"position": "G", "items": [{"displayName": "Luka Doncic"}]}]}}
        def fetch(url):
            if url.endswith("limit=500"):
                return teams
            return rosters[url.split("/teams/")[1].split("/")[0]]
        leg = dict(kind="prop", league="nba", name="Jaime Jaquez Jr.", home="Milwaukee Bucks", away="Los Angeles Lakers", match="LAL @ MIL")
        self.assertEqual(daily_review.roster_check([leg], fetch), [])
        self.assertEqual(daily_review.roster_check([dict(leg, name="Bam Adebayo")], fetch), ["Bam Adebayo (LAL @ MIL)"])
        self.assertEqual(daily_review.roster_check([dict(leg, home="Unknown Team")], fetch), [])      # unreadable: no alarm
        def boom(url):
            raise OSError("down")
        self.assertEqual(daily_review.roster_check([leg], boom), [])


class WithTeams(unittest.TestCase):
    def test_fill(self):
        book = {"legs": {"k": dict(gid="nba:1", label="J: 2+ Assists", home="Milwaukee Bucks", away="Los Angeles Lakers")}}
        out = daily_review.with_teams([dict(gid="nba:1", label="J: 2+ Assists"), dict(gid="nba:2", label="X")], book)
        self.assertEqual((out[0]["home"], out[0]["away"]), ("Milwaukee Bucks", "Los Angeles Lakers"))
        self.assertIsNone(out[1]["home"])


class InjuryCheck(unittest.TestCase):
    def test_check(self):
        teams = {"nba": {"Milwaukee Bucks": [["Jaime Jaquez Jr.", "Questionable"]], "New York Knicks": [["X", "Out"]]}}
        legs = [dict(kind="prop", league="nba", name="Jaime Jaquez Jr.", home="Milwaukee Bucks", away="Los Angeles Lakers", match="LAL @ MIL"),
                dict(kind="prop", league="nba", name="Mikal Bridges", home="New York Knicks", away="Cleveland Cavaliers", match="CLE @ NY"),
                dict(kind="game", league="nba", label="Over 200.5", home="Milwaukee Bucks", away="Los Angeles Lakers")]
        self.assertEqual(daily_review.injury_check(legs, teams), ["Jaime Jaquez Jr.: Questionable (LAL @ MIL)"])
        self.assertEqual(daily_review.injury_check(legs, {}), [])


class InjuryContext(unittest.TestCase):
    def test_line(self):
        teams = {"nba": {"New York Knicks": [["Josh Hart", "Out"], ["Y", "Day-To-Day"]],
                         "Cleveland Cavaliers": [["Sam Merrill", "Out"]]}}
        legs = [dict(league="nba", home="New York Knicks", away="Cleveland Cavaliers", match="CLE @ NY"),
                dict(league="nba", home="New York Knicks", away="Cleveland Cavaliers", match="CLE @ NY"),
                dict(league="ncaab", home="Cal", away="USC", match="USC @ CAL")]
        self.assertEqual(daily_review.injury_context(legs, teams),
                         "Ladder games, players out or doubtful: CLE @ NY: Cleveland Cavaliers without Sam Merrill;"
                         " New York Knicks without Josh Hart.")
        self.assertIsNone(daily_review.injury_context(legs[2:], teams))


class InjuryStudyLine(unittest.TestCase):
    def test_line(self):
        from unittest import mock
        import injury_study
        R = [dict(date="2026-11-0%d" % (1 + i % 8), mine=i % 2, theirs=(i + 1) % 2, won=i % 3 != 0, conf=65) for i in range(40)]
        with mock.patch.object(injury_study, "rows", lambda led, days: R):
            out = daily_review.injury_study_line({})
        self.assertTrue(out.startswith("Injuries at tip-off (40 games, 8 days, early read): my side more out: 1st "))
        with mock.patch.object(injury_study, "rows", lambda led, days: R[:5]):
            self.assertIsNone(daily_review.injury_study_line({}))


class Lessons(unittest.TestCase):
    def test_flags_group_short_in_both_halves(self):
        L = {}
        for i in range(60):
            d = "2026-10-01" if i < 30 else "2026-10-20"
            L[f"a{i}"] = dict(league="nhl", status="won" if i % 2 else "lost", date=d, conf=65)      # 50% vs 65%
            L[f"b{i}"] = dict(league="nba", status="won" if i % 5 else "lost", date=d, conf=75)      # 80% vs 75%
        out = daily_review.lessons_line(L)
        self.assertIn("NHL win 60-70%: 50% then 50% vs 65%, 65% stated (30+30)", out)
        self.assertNotIn("NBA", out)
        good = {k: v for k, v in L.items() if k.startswith("b")}
        good.update({k + "x": v for k, v in good.items()})            # 120 picks, all ahead
        self.assertTrue(daily_review.lessons_line(good).startswith("Lessons from losses: no league"))
        self.assertIsNone(daily_review.lessons_line(dict(list(L.items())[:10])))


class TeamLine(unittest.TestCase):
    def test_line(self):
        L = {}
        for i in range(14):
            L[f"k{i}"] = dict(league="nba", pick="New York Knicks", status="won" if i < 6 else "lost", conf=71)
        for i in range(12):
            L[f"c{i}"] = dict(league="nba", pick="Boston Celtics", status="won", conf=70)
        out = daily_review.team_line(L)
        self.assertTrue(out.startswith("Teams backed most, furthest behind (10+ picks): NBA New York Knicks 6/14 vs 71% stated ("))
        self.assertNotIn("Celtics", out)
        self.assertIsNone(daily_review.team_line({k: v for k, v in L.items() if k.startswith("c")}))


class HiSweep(unittest.TestCase):
    def test_line(self):
        L = {"a": dict(date="2026-11-10", conf=75, status="won"), "b": dict(date="2026-11-10", conf=72, status="lost"),
             "c": dict(date="2026-11-11", conf=85, status="won"), "d": dict(date="2026-11-11", conf=71, status="won"),
             "e": dict(date="2026-11-11", conf=55, status="lost"),
             "f": dict(date="2026-11-12", conf=90, status="won"), "g": dict(date="2026-11-12", conf=74, status="open")}
        out = daily_review.hi_sweep_line(L, "2026-11-12")
        self.assertEqual(out, "High-chance sweep: 70%+ today 1-0, 1 open; swept 1 of 2 past days (last 2026-11-11)"
                              " | 80%+ today 1-0; swept 1 of 1 past days (last 2026-11-11).")


class ReportCache(unittest.TestCase):
    def test_once_per_review_only(self):
        from unittest import mock
        import ladder
        calls = []
        fake = lambda book=None: calls.append(book) or {"n": len(calls)}
        with mock.patch.object(ladder, "report", fake):
            daily_review._CACHE = {}
            try:
                self.assertEqual(daily_review._report(), {"n": 1})
                self.assertEqual(daily_review._report(), {"n": 1})          # cached inside a review
                self.assertEqual(daily_review._report({"x": 1}), {"n": 2})  # an explicit book is never cached
            finally:
                daily_review._CACHE = None
            self.assertEqual(daily_review._report(), {"n": 3})              # outside a review: fresh each time
            self.assertEqual(daily_review._report(), {"n": 4})


class B2BLine(unittest.TestCase):
    def test_line(self):
        B = {"y": dict(date="2026-11-11", league="nhl", status="won", conf=60, pick="A", scores={"A": 3, "B": 2}),
             "t1": dict(date="2026-11-12", league="nhl", status="lost", conf=55, pick="A", scores={"A": 1, "C": 4})}
        self.assertEqual(daily_review.b2b_line(B), "Back-to-backs, board record so far: NHL on the tired side 0/1 vs 55%.")
        self.assertIsNone(daily_review.b2b_line({}))


class LockLeagues(unittest.TestCase):
    def test_line(self):
        legs = []
        for i in range(40):
            d = "2026-10-01" if i < 20 else "2026-10-20"
            legs.append(dict(date=d, league="nhl", p=0.85, status="won" if i % 10 else "lost"))     # 90%
            legs.append(dict(date=d, league="nfl", p=0.85, status="won" if i % 2 else "lost"))      # 50%
        out = daily_review.locks_league_line(legs)
        self.assertIn("NHL 90% then 90% (vs 85%, 85%)", out)
        self.assertTrue(out.endswith("Short in both halves: NFL."))


class HalvesBy(unittest.TestCase):
    def test_split_and_filters(self):
        legs = [dict(date="2026-10-0%d" % (1 + i % 9), league="nba" if i < 30 else "nhl", p=0.8,
                     status="won" if i % 4 else "lost") for i in range(40)]
        legs.append(dict(date="2026-10-01", league="nba", p=0.8, status="open"))          # ungraded: ignored
        H = dict(daily_review._halves_by(legs, lambda x: x["league"]))
        self.assertEqual(set(H), {"nba", "nhl"})
        self.assertEqual(sum(n for _, _, n in H["nba"]), 30)
        self.assertAlmostEqual(H["nba"][0][1], 80.0)
        self.assertEqual(dict(daily_review._halves_by(legs, lambda x: x["league"], min_half=8)).keys(), {"nba"})
        self.assertIsNone(daily_review._halves_by(legs[:39], lambda x: x["league"]))
        self.assertEqual(daily_review._halves_by(legs, lambda x: None), [])


class TrailingPool(unittest.TestCase):
    def test_locks_prop_gets_pool(self):
        P = {f"p{i}": dict(league="nfl", status="won" if i % 4 else "lost", p=0.76) for i in range(200)}
        a = dict(name="locks nfl prop", hit=50.0, said=79.7, n=10)
        out = daily_review.trailing_line(a, P)
        self.assertIn("all 200 saved NFL prop lines 150/200 (75% vs 76% stated) -- the pool is on par", out)
        P2 = {f"p{i}": dict(league="nfl", status="won" if i % 2 else "lost", p=0.76) for i in range(200)}
        self.assertIn("the pool is short too", daily_review.trailing_line(a, P2))
        self.assertNotIn("saved", daily_review.trailing_line(dict(name="calls nba", hit=50, said=70, n=40), P))


class PoolCtx(unittest.TestCase):
    def test_card_caution_gets_pool(self):
        F = {("nba", "over"): dict(league="nba", t="over", won=515, n=625, said=81.7, since="2026-11-02")}
        self.assertEqual(daily_review.pool_ctx(dict(league="nba", t="over", where="Locks"), F),
                         " (all saved lines since 2026-11-02: 515/625, 82% vs 82% -- pool on par)")
        F2 = {("nba", "over"): dict(league="nba", t="over", won=450, n=625, said=81.7, since="2026-11-02")}
        self.assertIn("pool short too", daily_review.pool_ctx(dict(league="nba", t="over", where="Safe Locks"), F2))
        self.assertEqual(daily_review.pool_ctx(dict(league="nba", t="over", where="all saved lines"), F), "")
        self.assertEqual(daily_review.pool_ctx(dict(league="nhl", t="over", where="Locks"), F), "")


if __name__ == "__main__":
    unittest.main()
