"""band_value: each favourite's historical return at its real price, from
data/fav_band_study.json; a band whose whole interval is below zero is a skip."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import band_value as B                                    # noqa: E402


class BandValue(unittest.TestCase):
    def test_bands_from_the_study(self):
        v = B.value("nba", 0.55)
        self.assertEqual((v["band"], v["skip"]), ("50-60", True))
        self.assertLess(v["roi95"][1], 0)
        self.assertFalse(B.value("nhl", 0.95)["skip"])
        self.assertEqual(B.value("nhl", 0.95)["band"], "90-100")
        self.assertEqual(B.value("ncaaf", 0.999)["band"], "90-100")

    def test_losses_fall_as_favourites_strengthen(self):
        roi = [B.value("mlb", p)["roi"] for p in (0.55, 0.65, 0.95)]
        self.assertEqual(roi, sorted(roi))

    def test_soccer_straight_bands(self):
        v = B.value("epl", 0.65)
        self.assertEqual(v["band"], "60-70")
        self.assertFalse(v["skip"])                       # no soccer band is reliably losing
        self.assertEqual(B.value("epl", 0.85)["band"], "80-100")

    def test_outside_the_study(self):
        self.assertIsNone(B.value("epl", 0.35))         # a soccer underdog
        self.assertIsNone(B.value("nba", 0.45))         # an underdog
        self.assertIsNone(B.value("nba", None))


if __name__ == "__main__":
    unittest.main()
