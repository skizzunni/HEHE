"""Record and grade BOTH sides of every two-sided FanDuel prop (over and under).

User, 2026-11-25: "u need to see what other side brings ... favorites be losing
us hella slips bc u always just pick them". The prop record (props.json) only
ever held the side a ticket took -- the over or the milestone -- so whether the
under is the better bet at FanDuel's price had never been measured. FanDuel's
main lines are priced on both sides ("Player Over" / "Player Under"); this
logs both, at the first price seen, into data/both_sides.json, grades them
from ESPN box scores with the same grader as props.json (props_ledger.grade),
and reports win rate and return by side and price band, split by date half --
the evidence a rule needs before it changes a ticket.

  python3 tools/both_sides.py record [today|YYYY-MM-DD]   log today's lines
  python3 tools/both_sides.py grade                       settle finished games
  python3 tools/both_sides.py report                      over vs under
  python3 tools/both_sides.py markets                     the same by league and market
"""
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [HERE, ROOT]
BOOK = os.path.join(ROOT, "data", "both_sides.json")
BANDS = ((-10**6, -300), (-300, -150), (-150, 100), (100, 200), (200, 10**6))


def load(path=BOOK):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(book, path=BOOK):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(book, f, indent=0, sort_keys=True)


def entries(games, day):
    """[record] for the two-sided props of `games` ([{id, match, props}])."""
    import props_ledger as PL
    out = []
    for g in games:
        lg = g["id"].split(":", 1)[0]
        for p in g.get("props") or []:
            if not p.get("two_sided") or not PL.gradable(lg, p.get("market") or ""):
                continue
            L = dict(gid=g["id"], aid=p.get("aid"), name=p["name"], market=p["market"], line=p["line"])
            out.append((PL.prop_key(L), dict(league=lg, gid=g["id"], aid=p.get("aid"), name=p["name"],
                                              market=p["market"], line=p["line"], price=p["price"],
                                              imp=p.get("imp"), p=p.get("p"), label=p["label"],
                                              side="under" if str(p["line"]).startswith("u") else "over",
                                              date=day, status="open")))
    return out


def not_started(rows, now=None):
    """Rows whose start is still ahead: a started game's FanDuel prices are
    in-play, not the pre-game price a bettor takes in the morning."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    for r in rows:
        try:
            t = dt.datetime.fromisoformat(str(r.get("start")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if t > now:
            out.append(r)
    return out


def record(day, games=None, path=BOOK):
    """Add today's lines (first price seen wins); returns how many were new."""
    if games is None:
        import build_ticket
        import slate_sheet
        games = build_ticket._fd_props(not_started(slate_sheet.main(day)))
    book = load(path)
    new = 0
    for k, e in entries(games, str(day)):
        if k not in book:
            book[k] = e
            new += 1
    save(book, path)
    return new


def grade(path=BOOK):
    """Settle open lines with props_ledger's own grader, pointed at this file."""
    import props_ledger as PL
    keep = PL.LEDGER
    PL.LEDGER = path
    try:
        PL.grade()
    finally:
        PL.LEDGER = keep


def _ret(e):
    o = int(e["price"])
    return (100 / -o if o < 0 else o / 100) if e["status"] == "won" else -1.0


def report(book=None):
    book = load() if book is None else book
    done = [e for e in book.values() if e.get("status") in ("won", "lost")]
    if not done:
        return "both sides: nothing graded yet (record daily, then grade)"
    dates = sorted({e["date"] for e in done})
    mid = dates[len(dates) // 2]
    one_day = len(dates) < 2
    # 2026-11-26: with one day graded every line fell in the "second" half --
    # a split needs two dates; until then the report says so and shows totals
    lines = [f"both sides: {len(done)} graded lines, {dates[0]} to {dates[-1]} "
             + ("(one day so far -- no date halves yet)" if one_day else f"(halves split at {mid})")]
    for side in ("over", "under"):
        for lo, hi in BANDS:
            cells = []
            for name, f in ((("all", lambda d: True),) if one_day else
                            (("first", lambda d: d < mid), ("second", lambda d: d >= mid))):
                s = [e for e in done if e["side"] == side and lo < int(e["price"]) <= hi and f(e["date"])]
                if s:
                    w = sum(e["status"] == "won" for e in s)
                    cells.append(f"{name} {w}/{len(s)} = {100 * w / len(s):.0f}%, "
                                 f"return {100 * sum(map(_ret, s)) / len(s):+.1f}%")
            if cells:
                lines.append(f"  {side} {lo if lo > -10**6 else ''}..{hi if hi < 10**6 else ''}: " + "; ".join(cells))
    return "\n".join(lines)


def by_market(book=None, min_n=10):
    """Under minus over, win rate and flat return, per league and market with
    min_n graded lines a side: where the other side does better, if anywhere."""
    book = load() if book is None else book
    done = [e for e in book.values() if e.get("status") in ("won", "lost")]
    groups = {}
    for e in done:
        groups.setdefault((e.get("league"), e.get("market")), {}).setdefault(e["side"], []).append(e)
    out = []
    for (lg, mk), sides in sorted(groups.items(), key=lambda kv: str(kv[0])):
        o, u = sides.get("over", []), sides.get("under", [])
        if len(o) < min_n or len(u) < min_n:
            continue
        r = lambda s: (sum(e["status"] == "won" for e in s), len(s), 100 * sum(map(_ret, s)) / len(s))
        (ow, on, oret), (uw, un, uret) = r(o), r(u)
        out.append(f"  {lg} {mk}: over {ow}/{on} ({oret:+.1f}%), under {uw}/{un} ({uret:+.1f}%)")
    return "\n".join(["both sides by market (10+ graded a side):"] + out) if out else \
        "both sides by market: no market has 10 graded lines a side yet"


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "report"
    if cmd == "record":
        arg = argv[2] if len(argv) > 2 else "today"
        import build_ticket
        day = build_ticket.resolve_day(arg)
        print(f"both sides: {record(day)} new lines logged for {day}")
    elif cmd == "grade":
        grade()
        print(report())
        print(by_market())
    elif cmd == "markets":
        print(by_market())
    else:
        print(report())


if __name__ == "__main__":
    main(sys.argv)
