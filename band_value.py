"""What a favourite at a given chance has returned per $1 at its real price.

From tools/fav_band_study.py (data/fav_band_study.json): 6,976 favourites in
the two-way leagues (MLB, NBA, NCAAB, NCAAF, NFL, NHL, WNBA), 2025-08-23 to
2026-10-21, at DraftKings' closing moneyline. Losses fall as the favourite
gets stronger -- the favourite-longshot bias:

    50-60%   -6.2% (95% -9.2 to -3.2)      60-70%   -3.8% (-7.3 to -0.5)
    70-80%   -1.6% (-5.0 to +2.1)          80-90%   -1.9% (-4.6 to +0.8)
    90%+     +0.5% (-1.0 to +1.9)

No band is proven profitable. A band whose whole interval is below zero is a
SKIP: it is shown, never hidden, but marked as a bet that has reliably lost.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "data", "fav_band_study.json")
TWO_WAY = {"mlb", "nba", "ncaab", "ncaaf", "nfl", "nhl", "wnba"}

try:
    with open(PATH) as _fh:
        _B = json.load(_fh)["bands"]
except (OSError, ValueError, KeyError):
    _B = {}


def band(p):
    for k, v in _B.items():
        lo, hi = (int(x) / 100 for x in k.split("-"))
        if lo <= p < hi or (hi >= 1 and p >= lo):
            return k, v.get("all")
    return None, None


def value(league, p):
    """dict(band, roi, roi95, n, skip) for a straight-win favourite, or None
    outside the study (soccer three-way, underdogs, unknown league)."""
    if league not in TWO_WAY or p is None or p < 0.5:
        return None
    k, s = band(p)
    if not s:
        return None
    return dict(band=k, roi=s["roi"], roi95=s["roi95"], n=s["n"], skip=s["roi95"][1] < 0)
