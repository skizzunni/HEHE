import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ufc_model as M                                            # noqa: E402


def fight(date, a, b, a_won, result="U-Dec"):
    return dict(date=date, a=dict(id=a, name=a, won=a_won), b=dict(id=b, name=b, won=not a_won), result=result)


class UFCModel(unittest.TestCase):
    def test_walk_forward_uses_only_earlier_fights(self):
        book = {"1": fight("2024-01-01", "x", "y", True, "KO/TKO"), "2": fight("2024-02-01", "x", "z", True),
                "3": fight("2024-03-01", "y", "z", True)}
        R, log = M.run(book)
        self.assertEqual(log[0][3], 0.5)                          # first fight: nobody rated yet
        self.assertGreater(log[1][3], 0.5)                        # x favoured after beating y
        self.assertGreater(R["x"], R["y"])
        s = M.score(log, since="2024-01-01", min_fights=0)
        self.assertEqual((s["n"], s["right"]), (3, 2))            # the 0.5 first fight counts as a pick of a

    def test_draws_skipped_and_methods(self):
        book = {"1": dict(date="2024-01-01", a=dict(id="x", name="x", won=False), b=dict(id="y", name="y", won=False))}
        self.assertEqual(M.run(book)[1], [])
        self.assertEqual([M.method(dict(result=r)) for r in ("KO/TKO", "Sub", "S-Dec", "U-Dec", None)],
                         ["KO", "Sub", "S-Dec", "U-Dec", None])

    def test_finish_rates(self):
        book = {"1": fight("2024-01-01", "x", "y", True, "Sub"), "2": fight("2024-02-01", "x", "z", True, "U-Dec")}
        self.assertEqual(M.finish_rates(book)["x"], [1, 2])


    def test_card_record(self):
        picks = {("A", "B"): dict(pick="A", conf=0.7), ("C", "D"): dict(pick="C", conf=0.55),
                 ("E", "F"): dict(pick="E", conf=0.8)}
        winners = {frozenset(("A", "B")): "A", frozenset(("C", "D")): "D"}           # E-F not finished
        r = M.card_record("20261107", picks=picks, winners=winners)
        self.assertEqual((r["won"], r["lost"], r["close"]), (1, 1, [0, 1]))
        self.assertEqual(r["losses"], ["C (55%) lost to D"])
        self.assertIsNone(M.card_record("x", picks={}, winners={}))


    def test_next_card_line(self):
        import datetime as dt
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review
        fake = lambda day: ({("A", "B"): dict(pick="A", conf=0.55), ("C", "D"): dict(pick="D", conf=0.8)}
                            if day == "20261114" else {})
        line = daily_review.ufc_next_line(dt.date(2026, 11, 8), picks_fn=fake)
        self.assertEqual(line, "Next UFC card 2026-11-14 (2 fights priced, 1 close): D 80%; A 55% (close).")
        self.assertIsNone(daily_review.ufc_next_line(dt.date(2026, 11, 8), picks_fn=lambda d: {}))


if __name__ == "__main__":
    unittest.main()


class UFCBands(unittest.TestCase):
    def test_bands_pick_the_price_favourite(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import ufc_bands
        book = {"1": dict(a=dict(id="x", won=True), b=dict(id="y", won=False), odds=dict(ml={"x": -300, "y": 240})),   # fav x ~73%, won
                "2": dict(a=dict(id="p", won=True), b=dict(id="q", won=False), odds=dict(ml={"p": 150, "q": -180})),   # fav q ~62%, lost
                "3": dict(a=dict(id="m", won=False), b=dict(id="n", won=False), odds=dict(ml={"m": -200, "n": 170})),  # draw: skipped
                "4": dict(a=dict(id="s", won=True), b=dict(id="t", won=False), odds=dict(ml={"s": -150}))}             # one price: skipped
        out = ufc_bands.bands(book)
        self.assertEqual(out["70-80"], dict(won=1, n=1, roi=33.3))
        self.assertEqual(out["60-70"], dict(won=0, n=1, roi=-100.0))
        self.assertNotIn("50-60", out)


class UFCReviewLines(unittest.TestCase):
    def test_ufc_line_finds_the_latest_card(self):
        import datetime as dt
        from unittest import mock
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review
        rec = dict(won=9, lost=5, losses=["Degli (69%) lost to Raposo"], close=[1, 2])
        with mock.patch.object(M, "card_record", lambda day: rec if day == "20261107" else None):
            line = daily_review.ufc_line(dt.date(2026, 11, 8))
        self.assertEqual(line, "UFC 2026-11-07: picks (the price favourite) 9-5; close fights (under 60%) 1 of 2;"
                               " lost: Degli (69%) lost to Raposo.")
        with mock.patch.object(M, "card_record", lambda day: None):
            self.assertIsNone(daily_review.ufc_line(dt.date(2026, 11, 8)))

    def test_prop_fair_line(self):
        from unittest import mock
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
        import daily_review
        import props_ledger
        B = [dict(band="90%+", halves=[[250, 296, 93.4, 85.4], [283, 339, 93.2, 85.1]])]
        with mock.patch.object(props_ledger, "fair_bands", lambda *a, **k: B):
            self.assertEqual(daily_review.prop_fair_line(),
                             "Props by the book's fair chance (won, by half; fair / our stated): 90%+ 84%, 83% (93% / 85%).")
