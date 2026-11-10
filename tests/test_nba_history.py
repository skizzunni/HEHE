import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import nba_history as h                                            # noqa: E402

G = dict(id="1", home=dict(id="10", name="Home"), away=dict(id="20", name="Away"))


def side(team, ml, close=None):
    s = {"team": {"$ref": f"http://x/seasons/2024/teams/{team}?lang=en"}, "moneyLine": ml}
    if close is not None:
        s["close"] = {"moneyLine": {"american": close}}
    return s


def book(pid, name, away, home):
    return {"provider": {"id": pid, "name": name}, "awayTeamOdds": away, "homeTeamOdds": home}


class OddsFor(unittest.TestCase):
    def run_with(self, items):
        with mock.patch.object(h, "get", lambda url: {"items": items}):
            return h.odds_for(G)

    def test_matched_by_team_id_not_position(self):
        # the feed lists the home team under awayTeamOdds: ids must still win
        o = self.run_with([book("40", "DraftKings", side("10", -200, "-210"), side("20", 170, "+175"))])
        self.assertEqual(o, dict(book="DraftKings", home=-210.0, away=175.0))

    def test_inconsistent_close_skipped_draftkings_preferred(self):
        bad = book("40", "DraftKings", side("20", 330, "+330"), side("10", -190, "-190"))     # sums to 0.89
        good = book("47", "MGM", side("20", 220, "+222"), side("10", -270, "-278"))
        other = book("58", "ESPN BET", side("20", 210), side("10", -260))
        self.assertEqual(self.run_with([other, bad, good])["book"], "ESPN BET")
        self.assertEqual(self.run_with([bad, good])["book"], "MGM")
        live = book("46", "Caesars - Live Odds", side("20", 500), side("10", -800))
        self.assertIsNone(self.run_with([live, bad]))

    def test_total_kept_with_its_book(self):
        b = book("40", "DraftKings", side("20", 175, "+175"), side("10", -210, "-210"))
        b.update(overUnder=221.5, overOdds=-110.0, underOdds=-110.0)
        self.assertEqual(self.run_with([b]), dict(book="DraftKings", home=-210.0, away=175.0, total=221.5, over=-110.0, under=-110.0))

    def test_spread_from_home_side(self):
        away = side("20", 400, "+400"); home = side("10", -550, "-550")
        away["close"]["pointSpread"] = {"american": "+10.5"}; away["close"]["spread"] = {"american": "-110"}
        home["close"]["pointSpread"] = {"american": "-10.5"}; home["close"]["spread"] = {"american": "-110"}
        o = self.run_with([book("40", "DraftKings", away, home)])
        self.assertEqual((o["home_spread"], o["home_spread_price"], o["away_spread_price"]), (-10.5, -110.0, -110.0))
        home["close"]["pointSpread"] = {"american": "-9.5"}                 # sides disagree: no spread kept
        self.assertNotIn("home_spread", self.run_with([book("40", "DraftKings", away, home)]))

    def test_imp(self):
        self.assertAlmostEqual(h._imp(100), 0.5)
        self.assertAlmostEqual(h._imp(-300), 0.75)


if __name__ == "__main__":
    unittest.main()
