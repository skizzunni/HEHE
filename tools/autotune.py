"""Re-decide the calls' selection rule and bench from the record (autotune.py).

    python3 tools/autotune.py        # writes review/autotune.json
"""
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import autotune                                           # noqa: E402


def main():
    with open(os.path.join(ROOT, "ledger.json")) as fh:
        book = json.load(fh)
    today = dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    out = autotune.run(book, today)
    ev = out["evidence"]
    print(f'autotune: rule {out["rule"]} ({"CHANGED" if ev.get("changed") else "kept"}), '
          f'benched {out["benched"] or "none"}', file=sys.stderr)


if __name__ == "__main__":
    main()
