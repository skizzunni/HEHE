"""The one place the live board gets its selection policy from.

Every number that changes which side is picked lives in files the daily
review writes after testing them on games they were not fitted on:

    review/anchor_weights.json   the model's share against the same-time price
    review/call_min.json         which leagues have earned strong calls

Nothing here is hand-set. Until 2026-10-19 the board carried its own numbers
that won over those files wherever a league had no fit of its own -- NFL and
WNBA at 0.30, MLB 0.20, tennis 0.05 -- so the tested market-only policy was
overridden: the Atlanta Falcons were picked at 50.7% over a 51.7% Chicago
market favourite (and lost) on a weight no test had chosen. A league with no
tested weight now takes the file's default, which the review sets from the
leagues it could test (0 = the market alone).

version() fingerprints the policy so every archived pick says which one made it.
"""
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
WEIGHTS = os.path.join(HERE, "review", "anchor_weights.json")
CALLS = os.path.join(HERE, "review", "call_min.json")
# with no tested policy at all, the market alone: the baseline every change
# has to beat on later games before it is used
FALLBACK_W = 0.0


def _load(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


_W = _load(WEIGHTS)


def model_weight(league):
    """The model's share (0..1) in the log-odds blend with the same-time price."""
    w = (_W.get("weights") or {}).get(league)
    if w is None:
        w = _W.get("default")
    try:
        return float(w) if w is not None else FALLBACK_W
    except (TypeError, ValueError):
        return FALLBACK_W


def version():
    """Short fingerprint of the policy files the board is running on."""
    h = hashlib.sha1()
    for p in (WEIGHTS, CALLS):
        try:
            with open(p, "rb") as fh:
                h.update(fh.read())
        except OSError:
            h.update(b"-")
    sha = (os.environ.get("GITHUB_SHA") or "")[:7]
    return (sha + ":" if sha else "") + h.hexdigest()[:8]
