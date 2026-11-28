"""Saved ticket legs against FanDuel's own price, forward (research, information only).

2026-11-28: the README rows "Every ticket leg against FanDuel's own price,
forward" and "NHL 1+ Shots on Goal in the safest band, forward" came from a
hand parse of graded ticket output -- and the first draft miscounted the legs
(226 for 205). This grades every saved ticket in work/slate_*/ with
tools/grade_picks.py, counts each leg once per day (a leg on both tickets is
one result), and prints won / settled against the chance FanDuel's price
implies, with z, by league and price band.

Bands follow the safest ticket's cuts: NBA props -2500 or shorter, NHL props
-1500 or shorter, NFL props -1000 or shorter; moneylines are left out.

`--scoring` also splits the NBA and NFL legs by whether the game finished
under or over its ESPN pickcenter total (README row 2026-11-28: the NBA legs'
shortfall came from games that went under their total -- known only after).

  python3 tools/forward_check.py [--since 2026-11-24] [--root work] [--scoring]
"""
import glob
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
CUTS = {"nba": -2500, "nhl": -1500, "nfl": -1000}
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
                                      "oct", "nov", "dec"), 1)}


def implied(price):
    """FanDuel's implied chance from an American price (with the margin in)."""
    p = int(price)
    return -p / (-p + 100) if p < 0 else 100 / (p + 100)


def legs(graded):
    """{(day, league, label): (price, won, event id)} from [(day, picks, results)] --
    props only, settled only, each label once per day."""
    out = {}
    for day, picks, results in graded:
        for p, r in zip(picks, results):
            if p.get("kind") != "prop" or r not in ("won", "lost") or p.get("lg") not in CUTS:
                continue
            out[(day, p["lg"], p.get("label", "").split(" -- ")[0])] = (int(p["price"]), r == "won", p.get("id"))
    return out


def table(found):
    """[(league, band, won, n, priced, z)] by league and band."""
    rows = []
    for lg, cut in CUTS.items():
        for heavy in (True, False):
            t = [(pr, w) for (d, l, _), (pr, w, *_) in found.items() if l == lg and (pr <= cut) == heavy]
            if not t:
                continue
            won = sum(w for _, w in t)
            imp = [implied(pr) for pr, _ in t]
            ex, v = sum(imp), sum(i * (1 - i) for i in imp)
            rows.append((lg, f"{cut} or shorter" if heavy else f"longer than {cut}", won, len(t), ex,
                         (won - ex) / math.sqrt(v) if v else 0.0))
    return rows


def _z(t):
    """(won, n, priced, z) for [(price, won)]."""
    won = sum(w for _, w in t)
    imp = [implied(pr) for pr, _ in t]
    ex, v = sum(imp), sum(i * (1 - i) for i in imp)
    return won, len(t), ex, (won - ex) / math.sqrt(v) if v else 0.0


def by_scoring(found, scoring):
    """[(league, 'under' | 'over', games, won, n, priced, z)] -- legs split by
    whether their game finished under its total. scoring(lg, event id) ->
    (final points, total) or None."""
    cache, rows = {}, []
    for lg in ("nba", "nfl"):
        tagged = []
        for (d, l, _), (pr, w, eid) in found.items():
            if l != lg or not eid:
                continue
            if (lg, eid) not in cache:
                try:
                    cache[(lg, eid)] = scoring(lg, eid)
                except Exception:
                    cache[(lg, eid)] = None
            sc = cache[(lg, eid)]
            if sc:
                tagged.append((sc[0] < sc[1], pr, w, eid))
        for under in (True, False):
            t = [(pr, w) for u, pr, w, _ in tagged if u == under]
            if t:
                games = len({e for u, _, _, e in tagged if u == under})
                rows.append((lg, "under" if under else "over", games) + _z(t))
    return rows


def day_of(folder):
    """'slate_nov27' -> '11-27' (sortable within a season); None if unreadable."""
    b = os.path.basename(folder).replace("slate_", "")
    try:
        return f"{MONTHS[b[:3]]:02d}-{int(b[3:]):02d}"
    except (KeyError, ValueError):
        return None


def main(argv):
    import grade_picks
    root = argv[argv.index("--root") + 1] if "--root" in argv else os.path.join(os.path.dirname(HERE), "work")
    since = (argv[argv.index("--since") + 1] if "--since" in argv else "2026-11-24")[5:]
    graded = []
    for folder in sorted(glob.glob(os.path.join(root, "slate_*"))):
        day = day_of(folder)
        if not day or day < since:
            continue
        for name in ("ticket_safe.json", "ticket.json"):
            path = os.path.join(folder, name)
            if os.path.exists(path):
                picks, results, _ = grade_picks.main(path)
                graded.append((day, picks, results))
    found = legs(graded)
    print(f"{len(found)} settled prop legs, each once per day, from {len(graded)} saved tickets")
    for lg, band, won, n, ex, z in table(found):
        print(f"  {lg} {band}: {won}/{n} against {ex:.1f} priced (z {z:+.2f})")
    if "--scoring" in argv:
        import both_sides
        print("by how the game scored against its ESPN total (known only after the game):")
        for lg, side, games, won, n, ex, z in by_scoring(found, both_sides.scoring):
            print(f"  {lg} games that went {side} ({games}): {won}/{n} against {ex:.1f} priced (z {z:+.2f})")


if __name__ == "__main__":
    main(sys.argv)
