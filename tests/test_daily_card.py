import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import daily_card                                                      # noqa: E402
import td_scorers                                                      # noqa: E402
import ten_leg                                                         # noqa: E402


class TenLeg(unittest.TestCase):
    def test_american_first_and_open_only(self):
        G = [dict(gid=f"g{i}", label=f"L{i}", price="-400", p=0.9 - i / 100, league="nba", status="open") for i in range(8)]
        G += [dict(gid="s1", label="Soccer", price="-900", p=0.95, league="epl", status="open"),
              dict(gid="s2", label="Soccer2", price="-900", p=0.94, league="ita", status="open"),
              dict(gid="s3", label="Soccer3", price="-900", p=0.93, league="esp", status="open"),
              dict(gid="x", label="Started", price="-900", p=0.99, league="nba", status="won")]
        T = ten_leg.build(G)
        self.assertEqual(T["n"], 10)
        self.assertEqual([g["label"] for g in T["legs"]][:8], [f"L{i}" for i in range(8)])   # every American game first
        self.assertEqual([g["label"] for g in T["legs"]][8:], ["Soccer", "Soccer2"])          # then the likeliest others
        self.assertFalse(T["us_only"])
        self.assertAlmostEqual(T["pays"], round(1.25 ** 8 * (1 + 100 / 900) ** 2, 2), places=2)
        self.assertNotIn("Started", [g["label"] for g in T["legs"]])
        self.assertIsNone(ten_leg.build([]))


class ToTarget(unittest.TestCase):
    def test_adds_safest_until_2x(self):
        G = [dict(gid=f"g{i}", label=f"L{i}", price="-400", p=0.9 - i / 100, league="nba", status="open") for i in range(6)]
        T = ten_leg.to_target(G, 2.0)
        self.assertEqual(T["n"], 4)                       # 1.25 ** 4 = 2.44, three legs only 1.95
        self.assertEqual([g["label"] for g in T["legs"]], ["L0", "L1", "L2", "L3"])
        self.assertIsNone(ten_leg.to_target(G[:2], 2.0))

    def test_days_graded_as_at_8am(self):
        import unittest.mock as m
        import locks
        rows = {"2026-11-01": ["won", "void", "won"],      # a void leg does not lose the ticket
                "2026-11-02": ["won", "lost", "won"],
                "2026-11-03": ["won", "open", "won"]}      # not fully graded: left out
        pools = {"pools": {d: {"legs": [d]} for d in rows}}

        def eg(legs, led=None):
            d = legs[0]
            return [dict(gid=f"{d}{i}", label=f"L{i}", price="-300", p=0.9 - i / 100, league="nba", status=s)
                    for i, s in enumerate(rows[d])]
        with m.patch.object(locks, "load", lambda path=None: pools), m.patch.object(locks, "every_game", eg):
            out = ten_leg.to_target_days(None, {})
        self.assertEqual(out, {"2026-11-01": True, "2026-11-02": False})

    def test_ten_leg_record_as_at_8am(self):
        import unittest.mock as m
        import locks
        rows = {"2026-11-01": ["won"] * 9 + ["void"],         # a void leg does not lose it
                "2026-11-02": ["won"] * 9 + ["lost"],
                "2026-11-03": ["won"] * 9 + ["open"],         # not fully graded: left out
                "2026-11-04": ["won"] * 5}                     # fewer than ten games: left out
        pools = {"pools": {d: {"legs": [d]} for d in rows}}

        def eg(legs, led=None):
            d = legs[0]
            return [dict(gid=f"{d}{i}", label=f"L{i}", price="-2000", p=0.93, league="nba", status=s)
                    for i, s in enumerate(rows[d])]
        with m.patch.object(locks, "load", lambda path=None: pools), m.patch.object(locks, "every_game", eg):
            r = ten_leg.record(None, led={})
        self.assertEqual((r["days"], r["cashed"]), (2, 1))

    def test_review_line(self):
        import daily_review
        lad = {f"2026-11-{d:02d}": d % 3 == 0 for d in range(5, 13)}
        alt = {f"2026-11-{d:02d}": d % 2 == 0 for d in range(5, 14)}
        out = daily_review.ladder_alt_line(lad, alt)
        self.assertTrue(out.startswith("Ladder vs every-game ticket to 2x, same 8 days (the last 14 saved cards only; older days drop off): ladder "), out)
        self.assertIsNone(daily_review.ladder_alt_line({"2026-11-05": True}, {"2026-11-05": True}))

    def test_sign_p(self):
        import daily_review
        self.assertAlmostEqual(daily_review.sign_p(8, 3), 0.2266, places=3)
        self.assertEqual(daily_review.sign_p(0, 0), 1.0)
        self.assertEqual(daily_review.sign_p(2, 2), 1.0)


class Sizes(unittest.TestCase):
    def test_sizes_skips_empty(self):
        import unittest.mock as m
        recs = {6: dict(days=13, cashed=12, pays=1.34), 8: dict(days=0)}
        with m.patch.object(ten_leg, "record", lambda path=None, led=None, n=10: recs.get(n, dict(days=0))):
            self.assertEqual(ten_leg.sizes(led={}, ns=(6, 8)), [dict(n=6, days=13, cashed=12, pays=1.34)])


class YesterdayLines(unittest.TestCase):
    def test_from_tickets_text(self):
        book = {"a": dict(date="2026-11-20", status="won", price="-150"), "b": dict(date="2026-11-20", status="lost", price="-150"),
                "c": dict(date="2026-11-20", status="won", price="-150", record_excluded=True),
                "e": dict(date="2026-11-20", status="won"),                     # unpriced: off the record
                "d": dict(date="2026-11-19", status="won", price="-150")}
        out = daily_card.yesterday_lines("2026-11-21", lambda d: "; tickets: ladder lost, 10-leg cashed" if d == "2026-11-20" else "", book)
        self.assertEqual(out, ["Yesterday (2026-11-20): board 1-1; ladder lost, 10-leg cashed."])
        self.assertEqual(daily_card.yesterday_lines("2026-11-21", lambda d: "", {}), [])


class TicketsText(unittest.TestCase):
    def test_three_tickets(self):
        import daily_review
        self.assertEqual(daily_review.tickets_text("2026-11-20", {"2026-11-20": "lost"}, {"2026-11-20": True}, {"2026-11-20": False}),
                         "; tickets: ladder lost, 10-leg cashed, 2x every-game lost")
        self.assertEqual(daily_review.tickets_text("2026-11-20", {"2026-11-20": "open"}, {}, {}), "")


class SoccerSideLine(unittest.TestCase):
    def test_kinds_and_draws(self):
        import daily_review
        led = {}
        for i in range(80):
            lost = i % 4 == 0
            led[f"k{i}"] = dict(league="epl", conf=70, date=f"2026-11-{1 + i % 20:02d}", dc=i % 2 == 1,
                                status="lost" if lost else "won", diagnosis="margin 0 · drawn" if lost and i % 8 == 0 else "")
        out = daily_review.soccer_side_line(led)
        self.assertTrue(out.startswith("Soccer picks by kind, by half: to win "), out)
        self.assertIn("lost to draws", out)
        self.assertIn("; win or draw ", out)
        self.assertIsNone(daily_review.soccer_side_line({}))


class SoccerWeekdayLine(unittest.TestCase):
    def test_weekdays(self):
        import daily_review
        led = {f"k{i}": dict(league="epl", status="lost" if i % 14 in (0, 7) else "won", conf=70,
                             date=f"2026-11-{2 + i % 14:02d}") for i in range(140)}      # Nov 2 and 9 are Mondays
        led["nba"] = dict(league="nba", status="lost", conf=90, date="2026-11-02")
        out = daily_review.soccer_weekday_line(led)
        self.assertTrue(out.startswith("Soccer board picks by weekday, by half: Mon "), out)
        self.assertIn("short in both halves: Mon", out)
        self.assertIsNone(daily_review.soccer_weekday_line({}))


class BoardBandLine(unittest.TestCase):
    def test_bands(self):
        import daily_review
        led = {f"k{i}": dict(status="won" if i % 4 else "lost", conf=75 if i % 2 else 95, date=f"2026-11-{1 + i % 20:02d}")
               for i in range(80)}
        out = daily_review.board_band_line(led)
        self.assertTrue(out.startswith("Board picks by stated chance, by half: 70-80% "), out)
        self.assertIn("; 90%+ ", out)
        self.assertNotIn("50-60%", out)
        self.assertIsNone(daily_review.board_band_line({}))


class BoardLeagueLine(unittest.TestCase):
    def test_weakest_first(self):
        import daily_review
        led = {}
        for i in range(100):
            d = f"2026-11-{1 + i % 20:02d}"
            led[f"a{i}"] = dict(league="nba", status="won", conf=60, date=d)
            led[f"b{i}"] = dict(league="nhl", status="won" if i % 2 else "lost", conf=70, date=d)
        out = daily_review.board_league_line(led)
        self.assertTrue(out.startswith("Board picks by league, weakest first, by half: NHL "), out)
        self.assertIn("short in both halves: NHL.", out)
        self.assertIsNone(daily_review.board_league_line({}))


class ValueEdgeLine(unittest.TestCase):
    def test_by_edge(self):
        import daily_review
        finds = {f"v{i}": dict(status="won" if i % 2 else "lost", fair=0.5, ev=0.01 if i % 3 else 0.05,
                               start=f"2026-11-{1 + i // 4:02d}T19:00Z") for i in range(60)}
        out = daily_review.value_edge_line(finds)
        self.assertTrue(out.startswith("Value bets by stated edge, by half: under 2% "), out)
        self.assertIn("; 2-4% none then none; 4%+ ", out)
        self.assertIsNone(daily_review.value_edge_line({}))


class ValueLeagueLine(unittest.TestCase):
    def test_by_league_and_half(self):
        import daily_review
        finds = {f"v{i}": dict(status="won" if i % 2 else "lost", fair=0.5, start=f"2026-11-{1 + i // 4:02d}",
                               league="nba" if i % 3 else "nhl") for i in range(60)}
        out = daily_review.value_league_line(finds)
        self.assertTrue(out.startswith("Value bets by league, by half: all 15/30 (z +0.0) then 15/30 (z +0.0); NBA "), out)
        self.assertIsNone(daily_review.value_league_line({}))


class DcBandLine(unittest.TestCase):
    def test_bands(self):
        import daily_review
        led = {f"k{i}": dict(dc=True, status="won" if i % 4 else "lost", date=f"2026-11-{1 + i % 28:02d}",
                             conf=65 if i < 40 else 85) for i in range(80)}
        out = daily_review.dc_band_line(led)
        self.assertTrue(out.startswith("Win-or-draw picks by stated chance, by half: under 70% 14/20"), out)
        self.assertIn("80%+ ", out)
        self.assertNotIn("70-80%", out)                      # too few picks in that band
        self.assertIsNone(daily_review.dc_band_line({}))


class LocksLeagueTypeLine(unittest.TestCase):
    def test_short_pairs_named(self):
        import daily_review
        legs = []
        for i in range(48):
            d = f"2026-11-{1 + i % 24:02d}"
            legs.append(dict(league="nba", label="Over 220.5 points", spec={"t": "over"}, kind="game", p=0.8, date=d,
                             status="won" if i % 2 else "lost"))
            legs.append(dict(league="nhl", label="Under 6.5 goals", spec={"t": "under"}, kind="game", p=0.6, date=d,
                             status="won"))
        out = daily_review.locks_league_type_line(legs)
        self.assertTrue(out.startswith("Locks by league and bet type, short in both halves: NBA total 50% then 50%"), out)
        self.assertNotIn("NHL", out)
        self.assertIsNone(daily_review.locks_league_type_line(legs[:10]))


class DcMoveLine(unittest.TestCase):
    def test_moved_against_only(self):
        import daily_review
        led = {f"k{i}": dict(dc=True, status="won" if i % 2 else "lost", date=f"2026-11-{i + 1:02d}", conf=75,
                             first_price="-300", price="-200" if i < 20 else "-300") for i in range(24)}
        out = daily_review.dc_move_line(led)
        self.assertTrue(out.startswith("Win-or-draw picks whose price moved 3+ points against, by half: 5/10 vs 7.5"), out)
        self.assertIsNone(daily_review.dc_move_line({k: v for k, v in list(led.items())[:10]}))


class LadderMissesLine(unittest.TestCase):
    def test_single_leg_and_close(self):
        import daily_review
        R = {"history": [dict(status="lost", lost_on=["Over 223.5 points (223, missed by 0.5)"]),
                         dict(status="lost", lost_on=["Boston Celtics to win"]),
                         dict(status="lost", lost_on=["A to win", "B to win"]),
                         dict(status="live", lost_on=[])]}
        self.assertEqual(daily_review.ladder_misses_line(R),
                         "Ladder runs lost: 2 of 3 died on a single leg, 1 of those by 2 or less (0.5); 1 on two or more.")
        self.assertIsNone(daily_review.ladder_misses_line({"history": []}))


class LadderTypeLine(unittest.TestCase):
    def test_review_reuses_ticket_wording(self):
        import daily_review
        R = dict(legs_by_type={"win": dict(won=7, n=12, said=76.0)}, tickets=dict(won=6, n=16))
        self.assertEqual(daily_review.ladder_type_line(R),
                         "Ladder legs so far: winners 7/12 (58% vs 76% stated). Tickets cashed 6 of 16. "
                         "Weak spot: winners -- too few legs to cut them yet.")
        self.assertIsNone(daily_review.ladder_type_line({}))


class TdSlim(unittest.TestCase):
    def test_keeps_every_player_drops_extra_fields(self):
        g = dict(match="A @ B", players=[{"name": "X"}],
                 everyone=[dict(name=f"P{i}", p=0.3, p2=0.05, pfirst=0.08, price="+200", fd="x", where="y", imp=0.33)
                           for i in range(33)])
        out = td_scorers.slim([g])
        self.assertEqual(len(out[0]["everyone"]), 33)
        self.assertEqual(set(out[0]["everyone"][0]), {"name", "p", "p2", "pfirst", "price"})
        self.assertEqual(td_scorers.slim([dict(match="C @ D")])[0]["everyone"], [])
        self.assertEqual(td_scorers.slim(None), None)


class TwoPlusStudy(unittest.TestCase):
    def test_from_p_and_halves(self):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import td_two_plus_study as s
        self.assertAlmostEqual(s.two_plus_from_p(1 - 2.718281828 ** -0.6), td_scorers.two_plus(0.6), places=4)
        book = {f"k{i}": dict(date=f"2026-11-{1 + i // 5:02d}", p=0.45, status="won") for i in range(20)}
        tds = {f"k{i}": (2 if i % 10 == 0 else 1) for i in range(20)}
        H = s.study(book, tds)
        self.assertEqual([h["n"] for h in H], [10, 10])
        self.assertEqual([h["two_plus"] for h in H], [1, 1])
        self.assertEqual(s.study({}, {}), [])


class TdModel(unittest.TestCase):
    def test_two_plus_and_first(self):
        self.assertAlmostEqual(td_scorers.two_plus(0.6), 0.1219, places=4)
        self.assertAlmostEqual(td_scorers.first_td(0.6, 5.0), 0.6 / 5 * (1 - 2.718281828 ** -5), places=4)
        self.assertEqual(td_scorers.first_td(0.6, 0), 0.0)
        self.assertLess(td_scorers.two_plus(0.6), 1 - 2.718281828 ** -0.6)    # 2+ below anytime


class Card(unittest.TestCase):
    D = {"td": {"today": [{"lg": "NFL", "match": "BUF @ KC", "tip": "8:20 PM", "everyone": [
            dict(name="A", p=0.45, p2=0.12, pfirst=0.11, price="-110")]}]},
         "props": {"today": {"games": [{"id": "nba:1", "match": "X @ Y", "props": [
            dict(name="P1", label="P1: 10+ Points", price="-900", p=0.88, imp=0.9),
            dict(name="P1", label="P1: 5+ Points", price="-3000", p=0.88, imp=0.97),
            dict(name="P2", label="P2: 4+ Rebounds", price="-500", p=0.8, imp=0.83)]}]}},
         "markets": {"today": [{"lg": "NBA", "match": "X at Y", "m": [
            dict(g="Team total", l="Y over 110.5", p=0.52), dict(g="Team total", l="Y under 110.5", p=0.48),
            dict(g="Team total", l="Y over 100.5", p=0.8)]}]},
         "slots": {"today": {"nba": {"rows": [dict(mp="Y", mc=70)]}}},
         "every_game": {"today": [dict(gid="g", label="Y over 100.5 points", price="-400", p=0.8, league="nba", match="X @ Y", status="open")]}}

    def test_nfl_scorers_compact(self):
        E = [dict(name=f"P{i}", p=0.5 - i / 50, p2=0.1 + (i == 7) * 0.2, pfirst=0.12 - i / 100, price="+100") for i in range(10)]
        D = dict(self.D, td={"today": [{"lg": "NFL", "match": "BUF @ KC", "tip": "8:20 PM", "everyone": E}]})
        out = daily_card.scorer_lines(D)
        self.assertTrue(out[0].startswith("NFL touchdown scorers -- every player is on the page"))
        self.assertEqual(out[1], "  BUF @ KC 8:20 PM (10 players listed):")
        self.assertEqual(out[2].count(";"), 5)                                # top 6 anytime
        self.assertTrue(out[3].startswith("    2+ TDs: P7 30%"), out[3])      # sorted by its own chance
        self.assertTrue(out[4].startswith("    First TD: P0 12%; P1 11%; P2 10%"), out[4])

    def test_nfl_day_still_lists_nba_props(self):
        out = daily_card.scorer_lines(self.D)
        self.assertIn("NBA and NHL player props, one per player (his best-paying line at 80%+):", out)
        self.assertTrue(any("P1: 10+ Points" in l for l in out))
        self.assertLess(out.index("  NBA:"), len(out))
        D = dict(self.D, props={})
        self.assertFalse(any("player props" in l for l in daily_card.scorer_lines(D)))   # none posted: no empty heading

    def test_no_nfl_falls_back_to_props_one_per_player(self):
        D = dict(self.D, td={"today": []})
        out = daily_card.scorer_lines(D)
        self.assertEqual(out[0], "No NFL today -- player props instead, one per player (his best-paying line at 80%+):")
        self.assertEqual(sum("P1:" in l for l in out), 1)              # one prop per player
        self.assertTrue(any("P1: 10+ Points" in l for l in out))       # his longest price still 80%+
        self.assertTrue(any("P2: 4+ Rebounds" in l for l in out))

    def test_spread_games_caps_one_match(self):
        P = [dict(name=f"A{i}", match="G1") for i in range(5)] + [dict(name="B", match="G2")]
        self.assertEqual([p["name"] for p in daily_card.spread_games(P, 15)], ["A0", "A1", "A2", "B"])
        self.assertEqual(len(daily_card.spread_games(P, 2)), 2)

    def test_best_per_player_floor(self):
        P = [dict(name="A", p=0.88, imp=0.99), dict(name="A", p=0.82, imp=0.85), dict(name="A", p=0.6, imp=0.6),
             dict(name="B", p=0.7, imp=0.7)]
        self.assertEqual(daily_card.best_per_player(P), [dict(name="A", p=0.82, imp=0.85)])

    def test_ten_leg_sizes_line(self):
        D = dict(self.D, ten_leg={"sizes": [dict(n=6, days=13, cashed=12, pays=1.34), dict(n=10, days=13, cashed=11, pays=1.64)]})
        out = daily_card.ten_leg_lines(D)
        self.assertEqual(out[1], "  Other sizes, replayed: 6 legs cashed 12/13 at 1.34x; 10 legs cashed 11/13 at 1.64x"
                                 " -- fewer legs win more often, pay less.")
        self.assertFalse(any("Other sizes" in l for l in daily_card.ten_leg_lines(self.D)))

    def test_ten_leg_in_start_order(self):
        legs = [dict(label=f"L{t}", p=0.93, price="-2000", league="nba", match="M", tip=t) for t in ("10:00 PM", "7:00 PM", "", "7:30 PM")]
        D = dict(self.D, ten_leg={"today": dict(legs=legs, n=4, chance=0.7, pays=1.2)})
        out = [l for l in daily_card.ten_leg_lines(D) if l.startswith("  ") and ". L" in l]
        self.assertEqual([l.split(". ")[1].split(" ")[0] for l in out], ["L7:00", "L7:30", "L10:00", "L"])

    def test_ten_leg_preview_flagged(self):
        D = dict(self.D, ten_leg={"preview": True, "today": dict(legs=self.D["every_game"]["today"], n=10, chance=0.4, pays=1.6)})
        self.assertIn("PREVIEW: the board has not rebuilt on the 8 AM card yet", daily_card.ten_leg_lines(D)[0])
        D["ten_leg"]["preview"] = False
        self.assertNotIn("PREVIEW", daily_card.ten_leg_lines(D)[0])

    def test_ten_leg_alt2x_line(self):
        D = dict(self.D, ten_leg={"alt2x": dict(n=14, chance=0.3034, pays=2.0, cashed=8, days=13)})
        self.assertIn("  The same lines to 2.00x: 14 legs, 30% stated all win; replayed, cashed 8 of the last 13 days.",
                      daily_card.ten_leg_lines(D))
        eg = [dict(gid=f"g{i}", label=f"L{i}", price="-150", p=0.9 - i / 100, league="nba", match=f"M{i}", status="open")
              for i in range(3)]
        D = dict(self.D, every_game={"today": eg}, ten_leg={"today": dict(legs=eg[:1], n=1, chance=0.9, pays=1.67),
                                                           "alt2x": dict(n=2, chance=0.8, pays=2.0)})
        self.assertIn("    It adds: L1 -150 89% (M1)", daily_card.ten_leg_lines(D))
        low = dict(gid="g9", label="L9", price="-150", p=0.5, league="nba", match="M9", status="open")
        D2 = dict(D, every_game={"today": eg + [low]}, ten_leg=dict(D["ten_leg"], today=dict(legs=[low], n=1, chance=0.5, pays=1.67)))
        self.assertIn("    It leaves out: L9 (M9)", daily_card.ten_leg_lines(D2))
        D = dict(self.D, ten_leg={"alt2x": dict(n=None, chance=None, pays=None)})
        self.assertFalse(any("same lines" in l for l in daily_card.ten_leg_lines(D)))

    def test_team_points_under_lean_and_even(self):
        D = {"markets": {"today": [{"lg": "NBA", "match": "X at Y", "m": [
            dict(g="Team total", l="Y over 110.5", p=0.46), dict(g="Team total", l="Y under 110.5", p=0.54),
            dict(g="Team total", l="Y over 104.5", p=0.71), dict(g="Team total", l="Y under 104.5", p=0.29),
            dict(g="Team total", l="X over 101.5", p=0.5), dict(g="Team total", l="X under 101.5", p=0.5)]},
            {"lg": "NHL", "match": "A at B", "m": [dict(g="Team total", l="B over 2.5", p=0.6)]}]}}
        self.assertEqual(daily_card.team_points_lines(D),
                         ["NBA team points (main team total, the side the price leans):",
                          "  X at Y: Y under 110.5 54%; X over 101.5 50%"])       # NHL left out
        self.assertEqual(daily_card.team_points_lines({}), [])

    def test_team_points_and_winners_and_ten_leg(self):
        self.assertEqual(daily_card.team_points_lines(self.D)[1], "  X at Y: Y over 110.5 52%")
        self.assertEqual(daily_card.winner_lines(self.D)[1], "  NBA (1): Y 70%")
        D = dict(self.D, slots={"today": {"nhl": {"rows": [dict(mp="A", mc=71), dict(mp="B", mc=54), dict(mp="C", mc=50)]}}})
        self.assertEqual(daily_card.winner_lines(D)[1], "  NHL (3): A 71%; B 54% (toss-up); C 50% (toss-up)")
        D = dict(self.D, slots={"today": {"soccer": {"rows": [dict(mp="Flamengo", mc=75), dict(mp="Santos or draw", mc=73)]}}})
        self.assertEqual(daily_card.winner_lines(D)[1:], ["  SOCCER (1): Flamengo 75%", "  SOCCER win or draw (1): Santos 73%"])
        self.assertTrue(daily_card.ten_leg_lines(self.D)[0].startswith("Daily 1-leg: all win 80%, pays 1.25x"))
        self.assertTrue(daily_card.ten_leg_lines(self.D)[0].endswith("(only 1 games priced so far; it fills to 10 at the 8 AM card)"))
        self.assertEqual(daily_card.ten_leg_lines(self.D)[2], "     Needs: Y must score 101 or more points")
        D = dict(self.D, every_game={"today": [dict(gid="g", label="Over 200.5 points", price="-2000", p=0.93,
                                                   league="nba", match="A @ B", status="open")]})
        self.assertEqual(daily_card.ten_leg_lines(D)[2], "     Needs: Both teams together: 201 or more points")


class ReviewLine(unittest.TestCase):
    def test_ten_leg_line(self):
        import daily_review
        self.assertEqual(daily_review.ten_leg_line(dict(days=13, cashed=11, stated=0.409, pays=1.64)),
                         "Daily 10-leg, replayed on every 8 AM card: cashed 11 of 13 days (85%) vs 41% stated, at about 1.64x.")
        self.assertIsNone(daily_review.ten_leg_line(dict(days=0)))

    def test_ticket_size_line(self):
        import daily_review
        recs = {10: dict(days=13, cashed=11, stated=0.41, pays=1.64), 6: dict(days=13, cashed=12, stated=0.6, pays=1.34),
                15: dict(days=0)}
        self.assertEqual(daily_review.ticket_size_line(recs),
                         "Ticket size, replayed on every 8 AM card: 6 legs 12/13 at 1.34x; 10 legs 11/13 at 1.64x.")
        self.assertIsNone(daily_review.ticket_size_line({8: dict(days=0)}))


class TdCalibration(unittest.TestCase):
    def test_line(self):
        import daily_review
        B = {f"k{i}": dict(status="won" if i % 4 == 0 else "lost", p=0.25, date=f"2026-11-{1 + i // 4:02d}") for i in range(40)}
        B["k0"]["tds"] = 2
        B["k4"]["tds"] = 1
        out = daily_review.td_calibration_line(B)
        self.assertTrue(out.startswith("Anytime touchdown chances, by half: 5/20 scored vs 5.0 stated (z +0.0) to 2026-11-05"), out)
        self.assertTrue(out.endswith("2+ touchdowns graded so far: 1 of 2 players."), out)
        self.assertIsNone(daily_review.td_calibration_line({}))


class EveryGameBands(unittest.TestCase):
    def test_line(self):
        import daily_review
        rows = [(f"2026-11-{1 + i // 5:02d}", dict(p=0.93 if i % 2 else 0.88, status="won" if i % 7 else "lost")) for i in range(30)]
        out = daily_review.every_game_band_line(rows)
        self.assertTrue(out.startswith("Every game's safest line by chance, halves split 2026-11-04: 92%+ "), out)
        self.assertIn("under 85% none then none", out)
        self.assertIsNone(daily_review.every_game_band_line([]))


class ValueBands(unittest.TestCase):
    def test_line(self):
        import daily_review
        F = {f"v{i}": dict(status="won" if i % 2 else "lost", fair=0.5, start=f"2026-11-{1 + i // 4:02d}T00:00Z", kind="value")
             for i in range(40)}
        F["parlay"] = dict(status="won", fair=0.5, start="2026-11-01T00:00Z", kind="parlay")
        out = daily_review.value_band_line(F)
        self.assertIn("45-60% 10/20 (z +0.0) then 10/20 (z +0.0)", out)
        self.assertIn("0-30% none then none", out)
        self.assertIsNone(daily_review.value_band_line({}))



class FrozenPool(unittest.TestCase):
    def test_either_date_form_finds_the_pool(self):
        import json
        import tempfile
        import locks
        self.assertEqual(locks.iso_day("20261118"), "2026-11-18")
        self.assertEqual(locks.iso_day("2026-11-18"), "2026-11-18")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "safe.json")
            with open(p, "w") as fh:
                json.dump({"pools": {"2026-11-18": {"legs": [{"gid": "g"}]}}}, fh)
            self.assertEqual(locks.frozen_pool("20261118", p), {"legs": [{"gid": "g"}]})   # the board's form
            self.assertEqual(locks.frozen_pool("2026-11-18", p), {"legs": [{"gid": "g"}]})
            self.assertIsNone(locks.frozen_pool("20261119", p))


if __name__ == "__main__":
    unittest.main()
