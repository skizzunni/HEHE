"""Exhibition games in the ledger, tagged by tools/tag_preseason.py from
ESPN's season type. Fits (calibration, strong-call cutoffs) skip them; the
public record keeps them."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "data", "preseason_games.json")
_CACHE = None


def load(path=None):
    try:
        with open(path or PATH) as fh:
            d = json.load(fh)
        return dict(checked=list(d.get("checked") or []), preseason=list(d.get("preseason") or []),
                    entries=list(d.get("entries") or []))
    except (OSError, ValueError):
        return dict(checked=[], preseason=[], entries=[])


def save(d, path=None):
    with open(path or PATH, "w") as fh:
        json.dump(d, fh, indent=0, sort_keys=True)


def signature(e):
    """A ledger entry's game, without its id (entries do not carry one)."""
    return f'{e.get("league")}|{(e.get("date") or e.get("logged") or "")[:10]}|{e.get("matchup")}'


def _sets():
    global _CACHE
    if _CACHE is None:
        d = load()
        _CACHE = (set(d["preseason"]), set(d["entries"]))
    return _CACHE


def is_preseason(game_id):
    return game_id in _sets()[0]


def is_preseason_entry(e):
    return signature(e) in _sets()[1]
