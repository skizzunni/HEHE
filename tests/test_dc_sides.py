import unittest

import ledger


class DcSides(unittest.TestCase):
    def test_by_side(self):
        B = {"a": dict(dc=True, status="won", myside="home", conf=70),
             "b": dict(dc=True, status="lost", myside="home", conf=80),
             "c": dict(dc=True, status="won", myside="away", conf=72),
             "d": dict(dc=True, status="won", myside="away", conf=72, record_excluded="unpriced"),
             "e": dict(dc=False, status="won", myside="away", conf=72),
             "f": dict(dc=True, status="open", myside="away", conf=72)}
        self.assertEqual(ledger.dc_sides(B), {"home": [1, 2, 75.0], "away": [1, 1, 72.0]})


if __name__ == "__main__":
    unittest.main()
