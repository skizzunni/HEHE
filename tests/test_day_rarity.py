import unittest
import ledger


class DayRarity(unittest.TestCase):
    def test_exact_tail(self):
        rows = [dict(conf=50, status="lost", league="nhl"), dict(conf=50, status="won", league="nhl")]
        r = ledger.day_rarity(rows)
        self.assertEqual(r["expected_losses"], 1.0)
        self.assertEqual(r["as_bad_pct"], 75.0)          # 1 or 2 losses of two coin flips
        self.assertEqual(r["lost_by_league"], {"nhl": 1})
        self.assertEqual(r["expected_by_league"], {"nhl": 1.0})
        self.assertEqual(r["as_good_pct"], 75.0)         # 0 or 1 losses of two coin flips

    def test_rare_day(self):
        rows = [dict(conf=90, status="lost", league="uel") for _ in range(3)]
        self.assertEqual(ledger.day_rarity(rows)["as_bad_pct"], 0.1)

    def test_no_losses_is_certain(self):
        r = ledger.day_rarity([dict(conf=80, status="won", league="mlb")])
        self.assertEqual((r["as_bad_pct"], r["lost_by_league"]), (100.0, {}))

    def test_empty(self):
        self.assertEqual(ledger.day_rarity([]), {})


class ReviewSweepLine(unittest.TestCase):
    def test_broken_sweep_says_how_unusual(self):
        import os, sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review
        text = daily_review.sweep_line(dict(won=17, lost=2, open=32, broke_on="arg San Lorenzo at 68%",
                                            expected_losses=5.3, as_bad_pct=98.5, lost_by_league={"arg": 1, "col": 1},
                                            expected_by_league={"arg": 0.6, "col": 0.4}, coin_flips=0))
        self.assertIn("Board sweep: 17-2, 32 open -- broken (first loss: arg San Lorenzo at 68%); 5.3 losses expected"
                      " from the settled picks' chances, so 2 or more by now had a 98.5% chance; 0 of the 2 were near coin flips"
                      " (called under 60%), 2 were real misses; losses by league:"
                      " arg 1 (0.6 expected), col 1 (0.4 expected).", text)
        self.assertEqual(daily_review.sweep_line(dict(won=5, lost=0, open=3, broke_on=None, expected_losses=0.9,
                                                      as_bad_pct=100.0)), "Board sweep: 5-0, 3 open -- still clean.")
        self.assertIsNone(daily_review.sweep_line({}))
        good = daily_review.sweep_line(dict(won=52, lost=8, open=51, broke_on="x", expected_losses=15.5, as_bad_pct=99.5,
                                            as_good_pct=2.1, coin_flips=0))
        self.assertIn("-- an unusually good day: only 2.1% of days go this well this far in", good)
        tiny = daily_review.sweep_line(dict(won=76, lost=10, open=25, broke_on="x", expected_losses=23, as_bad_pct=100.0,
                                            as_good_pct=0.04, coin_flips=0))
        self.assertIn("only under 0.1% of days go this well", tiny)
        self.assertEqual(daily_review.pct_text(12.5), "12.5%")
        a = dict(name="locks nfl prop", hit=50.0, said=79.7, n=10, flag=True, halves=[[4, 5, 79.0], [1, 5, 80.0]])
        self.assertEqual(daily_review.trailing_line(a, {}), "TRAILING locks nfl prop: 50.0% hit vs 79.7% stated on 10"
                         " (by half 4/5 then 1/5; short in one half only -- a slump, not yet a pattern)")
        a["halves"] = [[2, 5, 79.0], [3, 5, 80.0]]
        self.assertIn("short in both halves", daily_review.trailing_line(a, {}))
        y = dict(day="2026-11-06", sweep=dict(won=40, lost=9, broke_on="arg San Lorenzo at 68%", expected_losses=13.3, as_bad_pct=95.0))
        self.assertEqual(daily_review.yesterday_line(y), "Yesterday (2026-11-06): board 40-9, sweep broken by arg San Lorenzo at 68%;"
                         " 13.3 losses expected, 9 came in (95% chance of that many or more).")
        self.assertIn("-- an unusually good day: only 1.2% of days go this well.",
                      daily_review.yesterday_line(dict(day="2026-11-08", sweep=dict(won=91, lost=19, broke_on="x",
                                                                                      expected_losses=29.7, as_bad_pct=99.5, as_good_pct=1.2))))
        self.assertEqual(daily_review.yesterday_line(dict(day="2026-11-05", sweep=dict(won=30, lost=0))),
                         "Yesterday (2026-11-05): board 30-0, clean sweep.")


class LikeRecord(unittest.TestCase):
    def test_like_record_and_line(self):
        import os, sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review
        lost = dict(league="epl", conf=66, dc=False, status="lost")
        book = {"x": lost}
        for i in range(12):
            book[f"w{i}"] = dict(league="epl", conf=64 + i % 4, dc=False, status="won" if i < 9 else "lost")
        book["far"] = dict(league="epl", conf=80, dc=False, status="won")            # outside the band
        book["dc"] = dict(league="epl", conf=66, dc=True, status="won")              # other bet
        book["nfl"] = dict(league="nfl", conf=66, dc=False, status="won")            # other league
        self.assertEqual(daily_review.like_record(book, lost), dict(won=9, n=12, said=66))
        self.assertIsNone(daily_review.like_record({"x": lost}, lost))
        line = daily_review.loss_line(dict(league="epl", pick="Tottenham Hotspur", said=66, price="-240",
                                           score={"Leeds United": 1, "Tottenham Hotspur": 0}, why="margin 1",
                                           tags=["favourite lost"], like=dict(won=9, n=12, said=66)))
        self.assertTrue(line.endswith("[favourite lost]; picks like it: 9 of 12 (75% vs 66% stated)"), line)


class DrawLosses(unittest.TestCase):
    def test_counts_draws_among_straight_win_losses(self):
        three = {"first": {"prices": {"home": "-200", "draw": "+300", "away": "+500"}}}
        book = {"a": dict(three, status="lost", scores={"X": 1, "Y": 1}),
                "b": dict(three, status="lost", scores={"X": 0, "Y": 2}),
                "c": dict(three, status="won", scores={"X": 2, "Y": 0}),
                "d": dict(three, status="lost", dc=True, scores={"X": 0, "Y": 1}),          # double chance: left out
                "e": dict(status="lost", scores={"X": 1, "Y": 1})}                          # two-way sport: left out
        self.assertEqual(ledger.draw_losses(book), dict(n=3, lost=2, drawn=1))


class MovesHalves(unittest.TestCase):
    def test_split(self):
        book = {"a": dict(date="2026-11-01", status="won", first_price="-150", price="-250"),     # moved for
                "b": dict(date="2026-11-02", status="lost", first_price="-250", price="-150"),    # moved against
                "c": dict(date="2026-11-03", status="won", first_price="-200", price="-205"),     # flat
                "d": dict(date="2026-11-04", status="lost", first_price="-150", price="-250")}
        m = ledger.moves_halves(book)
        self.assertEqual([h[:2] for h in m["for"]], [[1, 1], [0, 1]])
        self.assertEqual([h[:2] for h in m["against"]], [[0, 0], [0, 1]])        # mid is 11-02, so b is second half
        self.assertEqual(ledger.moves_halves({}), {})


class BandRecords(unittest.TestCase):
    def test_keys_and_min(self):
        book = {f"a{i}": dict(league="ncaaf", conf=56 + i % 3, status="won" if i < 7 else "lost") for i in range(10)}
        book["dc"] = dict(league="ncaaf", conf=56, dc=True, status="won")
        self.assertEqual(ledger.band_records(book), {"ncaaf|0|55": [7, 10, 56.9]})


class CallCautions(unittest.TestCase):
    def test_short_in_both_halves_only(self):
        book = {}
        for d in range(1, 9):
            for i in range(6):
                book[f"a{d}{i}"] = dict(league="ncaaf", conf=75, date=f"2026-11-0{d}", status="won" if i < 3 else "lost")
                book[f"b{d}{i}"] = dict(league="nfl", conf=75, date=f"2026-11-0{d}",
                                        status="won" if (i < 2 if d < 5 else i < 6) else "lost")   # short then long
        self.assertEqual(ledger.call_cautions(book), [dict(league="ncaaf", band=70, won=24, n=48, said=75)])
        self.assertEqual(ledger.call_cautions({}), [])


class HiSweepLedger(unittest.TestCase):
    def test_hi_sweep(self):
        B = {"a": dict(date="2026-11-10", conf=75, status="won"), "b": dict(date="2026-11-10", conf=72, status="lost"),
             "c": dict(date="2026-11-11", conf=85, status="won"), "d": dict(date="2026-11-11", conf=55, status="lost"),
             "e": dict(date="2026-11-12", conf=90, status="open")}
        self.assertEqual(ledger.hi_sweep(B, "2026-11-12"), dict(cut=70, today=[0, 0, 1], swept=1, days=2, last="2026-11-11"))


class B2B(unittest.TestCase):
    def test_played_and_side(self):
        B = {"a": dict(date="2026-11-11", league="nhl", scores={"Tampa Bay Lightning": 8, "Buffalo Sabres": 3}),
             "b": dict(date="2026-11-11", league="nba", scores={"X": 1, "Y": 2}),
             "c": dict(date="2026-11-12", league="nhl", scores={"Z": 1, "W": 2})}
        P = ledger.played_on(B, "2026-11-11", "nhl")
        self.assertEqual(P, {"Tampa Bay Lightning", "Buffalo Sabres"})
        self.assertEqual(ledger.b2b_side("Tampa Bay Lightning", "Columbus Blue Jackets", "Tampa Bay Lightning", P), "mine")
        self.assertEqual(ledger.b2b_side("Columbus Blue Jackets", "Columbus Blue Jackets", "Tampa Bay Lightning", P), "theirs")
        self.assertIsNone(ledger.b2b_side("Tampa Bay Lightning", "Buffalo Sabres", "Tampa Bay Lightning", P))
        self.assertIsNone(ledger.b2b_side("Q", "A", "B", P))


if __name__ == "__main__":
    unittest.main()
