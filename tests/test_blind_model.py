import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import blind_model as bm  # noqa: E402


def g(date, home, away, hs, as_, gid=None):
    return dict(id=gid or f'{date}{home}{away}', date=date, home=home, away=away,
                hs=hs, as_=as_, neutral=False)


class FitTest(unittest.TestCase):
    def setUp(self):
        self.games = []
        for i in range(10):
            d = f'2026-11-{i + 1:02d}'
            self.games.append(g(d, 'AAA', 'BBB', 110, 100))
            self.games.append(g(d, 'BBB', 'AAA', 100, 110, gid=f'r{i}'))

    def test_stronger_team_is_favoured_either_venue(self):
        m = bm.fit(self.games, '2026-11-20', 1, 999)
        mar, tot, ph = bm.predict(m, 'AAA', 'BBB')
        self.assertGreater(mar, 5)
        self.assertGreater(ph, 0.5)
        mar2, _, ph2 = bm.predict(m, 'BBB', 'AAA')
        self.assertLess(mar2, -5)
        self.assertAlmostEqual(tot, 210, delta=15)

    def test_only_earlier_games_are_used(self):
        m = bm.fit(self.games, '2026-11-03', 1, 999)
        self.assertEqual(m['games'], 4)
        self.assertIsNone(bm.fit(self.games, '2026-11-01', 1, 999))

    def test_unknown_team_gives_none(self):
        m = bm.fit(self.games, '2026-11-20', 1, 999)
        self.assertIsNone(bm.predict(m, 'AAA', 'ZZZ'))


class MarketTest(unittest.TestCase):
    def test_market_home_no_vig(self):
        L = {'nba:1': {'first': {'prices': {'home': '-150', 'away': '+130'}}}}
        p = bm.market_home(L, 'nba', '1')
        self.assertAlmostEqual(p, 0.6 / (0.6 + 100 / 230), places=4)
        self.assertIsNone(bm.market_home(L, 'nba', '2'))

    def test_compare_counts_disagreements(self):
        rows = [(0.7, 0.6, 1), (0.6, 0.4, 1), (0.4, 0.6, 1)]
        c = bm.compare(rows)
        self.assertEqual(c['n'], 3)
        self.assertEqual(c['disagree'], 2)
        self.assertAlmostEqual(c['blind_right_when_disagree'], 0.5)


if __name__ == '__main__':
    unittest.main()
