"""Which ledger games were exhibitions: ESPN season type 1.

    python3 tools/tag_preseason.py            # writes data/preseason_games.json

The board stopped picking preseason games on 2026-10-15 (anysport.is_preseason),
but the ones picked before then are still in the history the calibration
table and the strong-call cutoffs fit on: 52 NBA preseason picks won 46.2%
against a 59.9% book price (-27.3% per $1), while the 14 regular-season NBA
picks since have won 78.6%. Those games are a population the board no longer
picks, so the fits skip them (preseason.is_preseason). The public record
keeps them: they were published, and they count.

Season type comes from ESPN's own summary for each game, not from a date
guess. Only leagues with an exhibition season are checked.
"""
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import preseason                                          # noqa: E402

PATHS = {"nba": "basketball/nba", "nhl": "hockey/nhl", "nfl": "football/nfl", "wnba": "basketball/wnba",
         "mlb": "baseball/mlb", "ncaab": "basketball/mens-college-basketball"}


def season_type(league, gid):
    url = (f"https://site.api.espn.com/apis/site/v2/sports/{PATHS[league]}/summary?event={gid}")
    for _ in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}),
                                        timeout=20) as r:
                return ((json.load(r).get("header") or {}).get("season") or {}).get("type")
        except Exception:
            continue
    return None


def main():
    with open(os.path.join(ROOT, "ledger.json")) as fh:
        book = json.load(fh)
    known = preseason.load()
    todo = sorted({k for k, e in book.items() if isinstance(e, dict) and e.get("league") in PATHS
                   and k not in known["checked"]})
    with ThreadPoolExecutor(max_workers=8) as ex:
        types = list(ex.map(lambda k: season_type(k.split(":", 1)[0], k.split(":", 1)[1]), todo))
    for k, t in zip(todo, types):
        if t is None:
            continue                       # not answered: tried again next run
        known["checked"].append(k)
        if t == 1:
            known["preseason"].append(k)
    known["checked"].sort()
    known["preseason"] = sorted(set(known["preseason"]))
    known["entries"] = sorted({preseason.signature(book[k]) for k in known["preseason"] if k in book}
                              | set(known["entries"]))
    preseason.save(known)
    print(f"checked {len(todo)} games, {sum(t == 1 for t in types)} preseason; "
          f"{len(known['preseason'])} preseason in all", file=sys.stderr)


if __name__ == "__main__":
    main()
