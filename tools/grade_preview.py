#!/usr/bin/env python3
"""Grade the board's open picks from ESPN without writing anything.

2026-11-24: every GitHub workflow was switched off, so the board's grader
stopped and the record (and the hourly "why it lost" log) froze with 41 picks
open. This runs the board's own grader (ledger.grade) with saving switched
off and prints what it would settle -- the same result, score and loss
diagnosis the board would log -- so the record can be read while the board
is down. Nothing is written; the board grades for real once it runs again.

    python3 tools/grade_preview.py            # every open pick whose game is final
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def preview(grade_fn=None):
    """[(key, entry)] the grader would settle, with ledger.save switched off."""
    import ledger
    with mock.patch.object(ledger, "save", lambda d: None):
        return (grade_fn or ledger.grade)()


def line(key, e):
    lg = key.split(":", 1)[0]
    sc = e.get("scores")
    score = (" " + " - ".join(f"{k} {v}" for k, v in sc.items())) if isinstance(sc, dict) else (f" {sc}" if sc else "")
    s = f"{e.get('status', '?').upper():4} {lg} {e.get('pick')} at {e.get('conf')}% ({e.get('price')}), {e.get('matchup') or ''}{score}"
    if e.get("status") == "lost" and e.get("diagnosis"):
        s += f" -- {e['diagnosis']}"
    return s


def summary(settled):
    w = sum(e.get("status") == "won" for _, e in settled)
    l = sum(e.get("status") == "lost" for _, e in settled)
    v = sum(e.get("status") == "void" for _, e in settled)
    return f"Would settle {len(settled)}: {w} won, {l} lost" + (f", {v} void" if v else "") + " (preview only, nothing saved)"


if __name__ == "__main__":
    S = sorted(preview(), key=lambda kv: (kv[1].get("status") != "lost", kv[1].get("played") or "", kv[0]))
    for k, e in S:
        print(line(k, e))
    print(summary(S))
