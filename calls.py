"""Which games count as a CALL, and which are only a lean.

Every game still gets a side on the board, but only games whose favourite is
strong enough are recorded as calls and counted in the record. On 1,068 past
priced games (ledger.json, 2026-10-16) the market's favourite hit:

    chance >= 50%   67.9%   (every game)
    chance >= 55%   72.7%
    chance >= 60%   76.5%   (635 games)
    chance >= 65%   81.8%   (456 games)
    chance >= 70%   88.0%

So a pick below the cutoff is shown as a lean and left out of the record.
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
        _MIN = {k: float(v) for k, v in (json.load(_fh).get("cutoffs") or {}).items()}
except (OSError, ValueError, TypeError):
    _MIN = {}


def call_min(league):
    return _MIN.get(league, DEFAULT)


def is_call(league, conf):
    """conf is the pick's chance as a fraction (0.63) or a percent (63.0)."""
    if conf is None:
        return False
    c = conf / 100 if conf > 1 else conf
    return c >= call_min(league)
