"""Lock legs: where Kalshi pays more for the same bet, fee included."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import locks                                              # noqa: E402
import venues                                             # noqa: E402
from test_venues import KB, ROW                           # noqa: E402

ROWS = {"nhl": [dict(ROW, id="nhl:1")]}


def leg(price, team="Toronto Maple Leafs", **kw):
    return dict(dict(kind="game", gid="nhl:1", league="nhl", label=team, price=price, p=0.6,
                     spec=dict(t="win", team=team)), **kw)


class KalshiAlt(unittest.TestCase):
    def test_marked_only_where_kalshi_pays_more(self):
        card = {"locks": [leg("-200"), leg("-140"), leg("-300", kind="prop"), leg("-200", status="won")]}
        self.assertEqual(locks.kalshi_alt(card, ROWS, KB), 1)
        a = card["locks"][0]["alt"]
        # 60c + 1.68c fee pays 1.621 against FanDuel -200's 1.50
        self.assertAlmostEqual(a["dec"], round(venues.kalshi_dec(0.60), 4))
        self.assertAlmostEqual(a["gain"], round(venues.kalshi_dec(0.60) / 1.5 - 1, 4))
        self.assertNotIn("alt", card["locks"][1])                  # FanDuel -140 (1.714) already pays more
        self.assertNotIn("alt", card["locks"][2])                  # props are FanDuel's own
        self.assertNotIn("alt", card["locks"][3])                  # settled

    def test_a_price_far_from_the_chance_is_not_shown(self):
        card = {"locks": [leg("-200", p=0.92)]}                     # 60c is no price for a 92% leg
        self.assertEqual(locks.kalshi_alt(card, ROWS, KB), 0)

    def test_no_feed_no_change(self):
        card = {"locks": [leg("-200")]}
        self.assertEqual(locks.kalshi_alt(card, ROWS, {}), 0)
        self.assertNotIn("alt", card["locks"][0])


if __name__ == "__main__":
    unittest.main()
