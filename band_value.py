"""What a favourite at a given chance has returned per $1 at its real price.

From tools/fav_band_study.py (data/fav_band_study.json): 6,976 favourites in
the two-way leagues (MLB, NBA, NCAAB, NCAAF, NFL, NHL, WNBA), 2025-08-23 to
2026-10-21, at DraftKings' closing moneyline. Losses fall as the favourite
gets stronger -- the favourite-longshot bias:

    50-60%   -6.2% (95% -9.2 to -3.2)      60-70%   -3.8% (-7.3 to -0.5)
    70-80%   -1.6% (-5.0 to +2.1)          80-90%   -1.9% (-4.6 to +0.8)
    90%+     +0.5% (-1.0 to +1.9)

Soccer straight wins (tools/soccer_band_study.py, data/soccer_band_study.json:
2,240 league matches 2025-08-15 to 2026-10-19 at DraftKings' 3-way close):
40-50% -4.9%, 50-60% -6.2%, 60-70% -0.2%, 70-80% -2.0%, 80%+ +7.1% (30
matches); no soccer band's whole interval is below zero, so none is a skip.

No band is proven profitable. A band whose whole interval is below zero is a
SKIP: it is shown, never hidden, but marked as a bet that has reliably lost.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "data", "fav_band_study.json")
TWO_WAY = {"mlb", "nba", "ncaab", "ncaaf", "nfl", "nhl", "wnba"}

SOCCER_PATH = os.path.join(HERE, "data", "soccer_band_study.json")


def _bands(path):
    try:
        with open(path) as fh:
            return json.load(fh)["bands"]
    except (OSError, ValueError, KeyError):
        return {}


_B = _bands(PATH)
_S = _bands(SOCCER_PATH)


def band(p, table=None):
    for k, v in (table if table is not None else _B).items():
        lo, hi = (int(x) / 100 for x in k.split("-"))
        if lo <= p < hi or (hi >= 1 and p >= lo):
            return k, v.get("all")
    return None, None


def value(league, p):
    """dict(band, roi, roi95, n, skip) for a straight-win favourite, or None
    outside the study (soccer three-way, underdogs, unknown league)."""
    if p is None:
        return None
    try:
        import ledger
        soccer = league in ledger.SOCCER
    except Exception:
        soccer = False
    if soccer:
        if p < 0.4:
            return None
        k, s = band(p, _S)
    elif league not in TWO_WAY or p < 0.5:
        return None
    else:
        k, s = band(p)
    if not s:
        return None
    return dict(band=k, roi=s["roi"], roi95=s["roi95"], n=s["n"], skip=s["roi95"][1] < 0)
