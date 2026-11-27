import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import grade_preview as GP  # noqa: E402


class PreviewTest(unittest.TestCase):
    def test_nothing_is_saved(self):
        import ledger
        calls = []
        real = ledger.save
        try:
            ledger.save = lambda d: calls.append(d)

            def fake_grade():
                ledger.save({"x": 1})          # the grader saves at its end
                return [("nba:1", dict(status="lost", pick="Raptors", conf=79, price="-449", matchup="MIL @ TOR",
                                       scores={"TOR": 111, "MIL": 116}, diagnosis="upset · close game"))]
            out = GP.preview(fake_grade)
            self.assertEqual(calls, [])          # patched out during the preview
        finally:
            ledger.save = real
        self.assertEqual(GP.line(*out[0]),
                         "LOST nba Raptors at 79% (-449), MIL @ TOR TOR 111 - MIL 116 -- upset · close game")
        self.assertEqual(GP.summary(out + [("nhl:2", dict(status="won")), ("x:3", dict(status="void"))]),
                         "Would settle 3: 1 won, 1 lost, 1 void (preview only, nothing saved)")


class ReviewLineTest(unittest.TestCase):
    def test_preview_losses_line(self):
        import daily_review
        S = [("nba:1", dict(status="lost", pick="Raptors", conf=79, price="-449", matchup="MIL @ TOR",
                            scores={"TOR": 111, "MIL": 116}, diagnosis="upset")),
             ("nba:2", dict(status="won", pick="Lakers", conf=85, price="-800"))]
        line = daily_review.preview_losses_line(lambda: S)
        self.assertTrue(line.startswith("Not yet graded by the board, from ESPN: Would settle 2: 1 won, 1 lost"))
        self.assertIn("\n- LOST nba Raptors at 79% (-449)", line)
        self.assertIn("; by day played: ? 1-1", line)
        self.assertIsNone(daily_review.preview_losses_line(lambda: []))

    def test_line_carries_the_day_played(self):
        import grade_preview as GP
        e = dict(status="lost", pick="Thunder", conf=63, price="-191", matchup="OKC @ IND", played="2026-11-23")
        self.assertTrue(GP.line("nba:1", e).startswith("LOST Nov 23 nba Thunder at 63% (-191)"))

    def test_by_day_newest_first(self):
        import grade_preview as GP
        S = [("a", dict(status="won", played="2026-11-23")), ("b", dict(status="lost", played="2026-11-24")),
             ("c", dict(status="won", played="2026-11-24")), ("d", dict(status="void", date="2026-11-16"))]
        self.assertEqual(GP.by_day(S), "2026-11-24 1-1, 2026-11-23 1-0, 2026-11-16 0-0")


class UserTicketsLineTest(unittest.TestCase):
    def test_slate_day_orders_by_name_not_mtime(self):
        import datetime as dt
        import daily_review as R
        today = dt.date(2026, 11, 25)
        self.assertEqual(R.slate_day("work/slate_nov24", today), dt.date(2026, 11, 24))
        self.assertEqual(R.slate_day("work/slate_dec30/", today), dt.date(2025, 12, 30))   # last year
        self.assertEqual(R.slate_day("work/slate_nov26", today), dt.date(2026, 11, 26))    # tomorrow's
        self.assertEqual(R.slate_day("work/slate_feb29", dt.date(2028, 3, 1)), dt.date(2028, 2, 29))
        self.assertEqual(R.slate_day("work/slate_x", today), dt.date.min)
        order = sorted(["work/slate_nov3", "work/slate_nov24", "work/slate_oct30"], key=lambda p: R.slate_day(p, today))
        self.assertEqual(order[-1], "work/slate_nov24")

    def test_line(self):
        import json
        import tempfile
        import daily_review
        root = tempfile.mkdtemp()
        d = os.path.join(root, "work", "slate_nov24")
        os.makedirs(d)
        for name in ("ticket.json", "ticket25.json"):
            json.dump([{}], open(os.path.join(d, name), "w"))
        res = {"ticket.json": dict(won=13, lost=0, push=0, open=0), "ticket25.json": dict(won=24, lost=0, push=0, open=1)}
        g = lambda f: ([{}] * (13 if f.endswith("ticket.json") else 25), [], res[os.path.basename(f)])
        line = daily_review.user_tickets_line(root, g)
        self.assertEqual(line, "Your tickets: nov24 13-leg ticket 13-0 (all won); nov24 25-leg ticket 24-0 (1 open).")
        self.assertIsNone(daily_review.user_tickets_line(tempfile.mkdtemp(), g))
        json.dump([{}], open(os.path.join(d, "ticket_ladder.json"), "w"))
        res["ticket_ladder.json"] = dict(won=6, lost=0, push=0, open=0)
        g2 = lambda f: ([{}] * 6, [], res[os.path.basename(f)]) if f.endswith("ladder.json") else g(f)
        self.assertIn("6-leg ladder stand-in 6-0 (all won)", daily_review.user_tickets_line(root, g2))
        json.dump([{}], open(os.path.join(d, "ticket_2x.json"), "w"))
        res["ticket_2x.json"] = dict(won=5, lost=1, push=0, open=0)
        g3 = lambda f: ([{}] * 6, [], res[os.path.basename(f)]) if f.endswith("2x.json") else g2(f)
        self.assertIn("6-leg 2x combo 5-1 (lost)", daily_review.user_tickets_line(root, g3))
        json.dump([{}], open(os.path.join(d, "ticket_other.json"), "w"))
        res["ticket_other.json"] = dict(won=1, lost=0, push=0, open=0)
        g4 = lambda f: ([{}], [], res[os.path.basename(f)]) if f.endswith("other.json") else g3(f)
        self.assertIn("1-leg other-side card 1-0 (all won)", daily_review.user_tickets_line(root, g4))


class HeavyPropsLineTest(unittest.TestCase):
    def test_line(self):
        import daily_review
        props = {f"k{i}": dict(price="-3000", p=0.87, status="won" if i % 10 else "lost", date=f"2026-11-{1 + i // 10:02d}")
                 for i in range(60)}
        props["light"] = dict(price="-1000", p=0.85, status="lost", date="2026-11-01")
        line = daily_review.heavy_props_line(props)
        self.assertTrue(line.startswith("Props priced -2500 or shorter, by half: 27/30 (90.0% vs 87.0% stated"))
        self.assertIsNone(daily_review.heavy_props_line({}))

class LostLegsClauseTest(unittest.TestCase):
    def test_counts_once_and_flags_repeats(self):
        """2026-11-27: Loveland lost on both Nov 26 tickets (two different props)."""
        import daily_review
        a = dict(lg="nfl", market="Receptions", player="Colston Loveland", label="Colston Loveland: 3+ Receptions")
        b = dict(lg="nfl", market="Receiving Yards", player="Colston Loveland", label="Colston Loveland: 25+ Receiving Yards")
        ml = dict(lg="nfl", kind="ml", label="DAL moneyline -434 (78%)")
        lost = {("slate_nov26", a["label"]): (a, {"safest ticket"}),
                ("slate_nov26", b["label"]): (b, {"ticket"}),
                ("slate_nov26", ml["label"]): (ml, {"ticket", "2x combo"})}
        out = daily_review.lost_legs_clause(lost)
        self.assertIn("nfl Receiving Yards 1, nfl Receptions 1, nfl moneyline 1", out)
        self.assertIn("Colston Loveland (nov26)", out)
        self.assertIn("DAL moneyline -434 (nov26)", out)
        one = daily_review.lost_legs_clause({("slate_nov26", a["label"]): (a, {"safest ticket"})})
        self.assertNotIn("more than one ticket", one)


if __name__ == "__main__":
    unittest.main()
