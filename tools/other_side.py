"""The other-side card: NFL underdogs getting 7.5 to 14 points (information only).

User, 2026-11-25: "u need to see what other side brings ... favorites be losing
us hella slips bc u always just pick them". The one other-side spot the record
leans on in football: NFL underdogs getting 7.5-14 covered 53.3% (2023, n 30),
60.8% (2024, n 51) and 51.6% this season (n 31) -- 56.3% on 112 games, under
the bar for a rule (README). So it is a card, labelled a modest lean, never a
lock, and saved as a gradable ticket so its own record builds day by day.

  python3 tools/other_side.py [today|YYYY-MM-DD] [--save work/slate_<mon><dd>/ticket_other.json]

The spread price is not in ESPN's scoreboard row; legs carry -110 (the usual
spread price) for the record's flat return and say so -- check your book.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
LO, HI = 7.5, 14.0
# covered / games: earlier seasons, this season to 2026-11-23 (ESPN line on
# each game), then each card shown since -- the record counts itself forward
SEASONS = {2023: (16, 30), 2024: (31, 51), 2026: (16, 31)}
FORWARD = [("2026-11-26", "PHI +8.5 at DAL", True)]       # PHI won 39-38


def note(seasons=SEASONS, forward=FORWARD):
    s = dict(seasons)
    w, n = s[2026]
    s[2026] = (w + sum(1 for f in forward if f[2]), n + len(forward))
    cw, cn = sum(v[0] for v in s.values()), sum(v[1] for v in s.values())
    pct = lambda a, b: f"{int(1000 * a / b + 0.5) / 10:.1f}%"      # half up: 63/112 is 56.3%
    return (f"NFL underdogs getting 7.5-14 points: {pct(cw, cn)} covered on {cn} games over three seasons "
            f"({', '.join(pct(*s[y]) for y in sorted(s)[:-1])}, then {pct(*s[2026])} this season, "
            f"{sum(1 for f in forward if f[2])}/{len(forward)} on cards shown here) -- a modest lean, not a strong pick.")


NOTE = note()


def dogs(rows):
    """[(row, dog abbr, points)] for NFL games whose favourite lays 7.5-14."""
    out = []
    for r in rows:
        if r.get("lg") != "nfl":
            continue
        m = re.match(r"^\s*([A-Z]{2,4})\s+-(\d+(?:\.\d+)?)\s*$", str(r.get("line") or ""))
        if not m:
            continue
        fav, pts = m.group(1), float(m.group(2))
        if not LO <= pts <= HI or fav not in (r.get("home"), r.get("away")):
            continue
        out.append((r, r["away"] if fav == r["home"] else r["home"], pts))
    return out


def legs(found):
    return [dict(label=f"{dog} +{pts:g} ({r['game']}; spread price assumed -110 -- check your book)",
                 id=str(r.get("id")), lg="nfl", kind="spread", team=dog, line=pts, price=-110)
            for r, dog, pts in found]


def text(found):
    if not found:
        return "Other side: no NFL underdog getting 7.5-14 today."
    return "\n".join(["Other side (information only): " + NOTE] +
                     [f"  {dog} +{pts:g} -- {r['game']}" for r, dog, pts in found])


def main(argv):
    import build_ticket
    import slate_sheet
    args = argv[1:]
    save = None
    if "--save" in args:
        i = args.index("--save")
        save = args[i + 1]
        del args[i:i + 2]
    day = build_ticket.resolve_day(args[0] if args else None)
    found = dogs(slate_sheet.main(day))
    print(text(found))
    if save and found:
        if os.path.exists(save):
            print(f"not saved: {save} already exists")
        else:
            os.makedirs(os.path.dirname(save) or ".", exist_ok=True)
            json.dump(legs(found), open(save, "w"), indent=1)
            print(f"saved: {save}")


if __name__ == "__main__":
    main(sys.argv)
