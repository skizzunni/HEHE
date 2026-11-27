import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import pregame_brief as P  # noqa: E402


class BriefTest(unittest.TestCase):
    def test_sections_in_order_and_failure_isolated(self):
        def boom(day):
            raise RuntimeError("feed down")
        out = P.brief("2026-11-24", sections=(("Numbers", lambda d: "blind first"), ("Injuries", boom),
                                              ("Goalies", lambda d: "goalies " + d)))
        self.assertLess(out.index("## Numbers"), out.index("## Injuries"))
        self.assertIn("blind first", out)
        self.assertIn("unavailable (RuntimeError)", out)
        self.assertIn("goalies 2026-11-24", out)


    def test_save_names_file_by_time(self):
        import datetime as dt
        import tempfile
        d = tempfile.mkdtemp()
        p = P.save("hello", os.path.join(d, "x"), now=dt.datetime(2026, 11, 23, 18, 40, tzinfo=P.ET))
        self.assertTrue(p.endswith("brief_1840.txt"))
        self.assertEqual(open(p).read(), "hello\n")


class TicketSectionTest(unittest.TestCase):
    def test_path_and_missing(self):
        import tempfile
        self.assertTrue(P.ticket_path("2026-11-24", "/r").endswith(os.path.join("work", "slate_nov24", "ticket.json")))
        self.assertTrue(P.ticket_path("2026-12-05", "/r").endswith(os.path.join("work", "slate_dec05", "ticket.json")))
        self.assertIn(("Your saved ticket, re-checked", P._ticket), P.SECTIONS)


    def test_ticket_section_runs_the_final_recheck(self):
        import tempfile
        from unittest import mock
        import recheck_ticket
        root = tempfile.mkdtemp()
        path = P.ticket_path("2026-11-25", root)
        os.makedirs(os.path.dirname(path))
        open(path, "w").write("[]")
        seen = {}
        with mock.patch.object(P, "ticket_path", lambda d, root=None: path), \
                mock.patch.object(recheck_ticket, "main", lambda p, d, final=False: seen.update(final=final) or "ok"):
            self.assertEqual(P._ticket("2026-11-25"), "ok")
        self.assertTrue(seen["final"])


    def test_both_tickets_rechecked_safest_first(self):
        import tempfile
        from unittest import mock
        import recheck_ticket
        root = tempfile.mkdtemp()
        path = P.ticket_path("2026-11-26", root)
        os.makedirs(os.path.dirname(path))
        open(path, "w").write("[]")
        open(os.path.join(os.path.dirname(path), "ticket_safe.json"), "w").write("[]")
        with mock.patch.object(P, "ticket_path", lambda d, root=None: path), \
                mock.patch.object(recheck_ticket, "main", lambda p, d, final=False: os.path.basename(p)):
            self.assertEqual(P._ticket("2026-11-26"),
                             "[ticket_safe.json]\nticket_safe.json\n\n[ticket.json]\nticket.json")

    def test_weather_section_listed(self):
        self.assertIn(("NFL kickoff weather", P._weather), P.SECTIONS)
        self.assertIn(("Other side (NFL underdogs getting 7.5-14)", P._other), P.SECTIONS)


class SharedPlayersTest(unittest.TestCase):
    def test_players_on_both_tickets(self):
        import json
        import tempfile
        d = tempfile.mkdtemp()
        a, b = os.path.join(d, "ticket_safe.json"), os.path.join(d, "ticket.json")
        json.dump([{"player": "Colston Loveland"}, {"player": "Sam LaPorta"}], open(a, "w"))
        json.dump([{"player": "Colston Loveland"}, {"team": "DAL"}], open(b, "w"))
        self.assertEqual(P.shared_players([a, b]), ["Colston Loveland"])
        self.assertEqual(P.shared_players([a]), [])

class SharedTextTest(unittest.TestCase):
    def test_counts_names(self):
        import pregame_brief as PB
        self.assertTrue(PB.shared_text(["A", "B"]).startswith("On both tickets, 2 players (one bad game"))
        self.assertTrue(PB.shared_text(["A"]).startswith("On both tickets, 1 player (one bad game"))
        self.assertTrue(PB.shared_text(["A", "B"]).endswith(": A, B"))


if __name__ == "__main__":
    unittest.main()
