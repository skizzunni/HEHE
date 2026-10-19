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
review/call_min.json. A league with no qualifying record gets no strong
calls (soccer qualifies as one group).
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "review", "call_min.json")
TARGET = 0.75

try:
    with open(PATH) as _fh:
        _J = json.load(_fh)
    _MIN = {k: float(v) for k, v in (_J.get("cutoffs") or {}).items() if v is not None}
except (OSError, ValueError, TypeError):
    _MIN = {}


def _group(league):
    """Soccer leagues qualify together (tools/daily_review.call_group)."""
    try:
        import ledger
        return "soccer" if league in ledger.SOCCER else league
    except Exception:
        return league


def call_min(league):
    """The cutoff for a strong call, or None: only a league (or the soccer
    group) whose own record qualified gets strong calls. No defaults and no
    exceptions -- until 2026-10-19 soccer got 75% without a test and leagues
    with no record (NBA, college basketball) got 60%."""
    return _MIN.get(_group(league))


def is_call(league, conf):
    """conf is the pick's chance as a fraction (0.63) or a percent (63.0)."""
    if conf is None or call_min(league) is None:
        return False
    c = conf / 100 if conf > 1 else conf
    return c >= call_min(league)
