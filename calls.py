"""Which games count as a CALL, and which are only a lean.

Every game still gets a side on the board, but only games whose favourite is
strong enough are recorded as calls and counted in the record. On 1,068 past
priced games (ledger.json, 2026-10-16) the market's favourite hit:

    chance >= 50%   67.9%   (every game)
    chance >= 55%   72.7%
    chance >= 60%   76.5%   (635 games)
    chance >= 65%   81.8%   (456 games)
    chance >= 70%   88.0%

Every pick is recorded and counted. The cutoff only labels each one "strong"
or "close" on the board, so it is clear which picks carry the record.
tools/daily_review.py refits the cutoff per league every day -- the lowest
one whose own record reaches TARGET with enough games behind it -- and writes
review/call_min.json; DEFAULT applies where a league has too few games.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "review", "call_min.json")
DEFAULT = 0.60
TARGET = 0.75

try:
    with open(PATH) as _fh:
        _J = json.load(_fh)
    _MIN = {k: float(v) for k, v in (_J.get("cutoffs") or {}).items() if v is not None}
    # leagues whose record was fitted and no cutoff qualified: no strong
    # calls there until one does (2026-10-18; before, a fallback cut applied)
    _NONE = set(_J.get("unqualified") or [])
except (OSError, ValueError, TypeError):
    _MIN, _NONE = {}, set()


# Soccer picks follow the de-vigged price, which tools/soccer_lab.py found
# honest on 1,115 unseen matches -- so a strong soccer call is one the market
# itself puts at TARGET or better (mostly "X or draw").
SOCCER_MIN = TARGET


def _soccer(league):
    try:
        import ledger
        return league in ledger.SOCCER
    except Exception:
        return False


def call_min(league):
    """The cutoff for a strong call, or None where the league's own record
    has been tested and none qualified."""
    if league in _MIN:
        return _MIN[league]
    if league in _NONE and not _soccer(league):
        return None
    return SOCCER_MIN if _soccer(league) else DEFAULT


def is_call(league, conf):
    """conf is the pick's chance as a fraction (0.63) or a percent (63.0)."""
    if conf is None or call_min(league) is None:
        return False
    c = conf / 100 if conf > 1 else conf
    return c >= call_min(league)
