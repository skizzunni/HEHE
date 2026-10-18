"""Sanity checks on every board build, before it is published.

A bad value seldom crashes anything -- a chance of 1.3, a price that reads
"None", a pick with no team -- it just misleads quietly. Every rebuild walks
the whole payload; anything found goes to the Results tab's Checks box.
Checked live 2026-10-18: 24 sections, 0 issues.
"""
import re

NAME_KEYS = ("label", "pick", "mp", "match")
TEXT_SKIP = ("why", "diagnosis", "where", "basis", "note")
BAD_TEXT = re.compile(r"\bNone\b|\bnan\b|\bNaN\b|undefined")


def _price_ok(v, path):
    try:
        if ".kalshi." in path:
            return 0 < float(v) < 1                      # Kalshi trades in dollars
        return abs(float(str(v).replace("+", ""))) >= 100   # American odds
    except (TypeError, ValueError):
        return False


def check(payload, limit=20):
    """[(path, problem, value)] for the first `limit` problems found."""
    out = []

    def bad(path, what, v):
        if len(out) < limit:
            out.append((path, what, str(v)[:60]))

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                p = f"{path}.{k}"
                if k in ("p", "prob") and isinstance(v, (int, float)) and not 0 <= v <= 1:
                    bad(p, "chance outside 0-1", v)
                elif k == "mc" and isinstance(v, (int, float)) and not 0 <= v <= 100:
                    bad(p, "confidence outside 0-100", v)
                elif k == "price" and v is not None and not _price_ok(v, p):
                    bad(p, "price does not parse", v)
                elif k in NAME_KEYS and (v is None or str(v).strip() in ("", "None", "nan", "undefined")):
                    bad(p, "missing name", v)
                elif isinstance(v, str) and k not in TEXT_SKIP and BAD_TEXT.search(v):
                    bad(p, "None/nan in text", v)
                walk(v, p)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
    walk(payload, "D")
    return out
