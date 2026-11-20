"""Today's ladder ticket as plain lines, straight from ladder.report(), for the
8 AM message: run, stake, each leg (price, chance, game, start ET, what it
needs in plain words, the record of Locks like it), the 2x-5x pick against the
plain top 4 and the no-props option, and wins still needed. Every number comes
from the report; nothing is computed that the board does not already state.

    python tools/ladder_ticket.py
"""
import math
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


SOCCER = None


def _is_soccer(league):
    """True for a soccer league code (the board's D.paths: soccer/...)."""
    global SOCCER
    if SOCCER is None:
        try:
            import dashboard                        # the board's league list (D.paths comes from it)
            SOCCER = {k for k, pth, _ in dashboard.LEAGUES if str(pth).startswith("soccer/")}
        except Exception:
            SOCCER = set()
    return league in SOCCER


def needs(label, league=None):
    """What a leg needs, in plain words -- the same wording as the board's
    needLine (board.html), so the 8 AM message and the page agree."""
    lab = str(label or "")
    unit = "goals" if re.search(r"goal", lab, re.I) else "runs" if re.search(r"\brun", lab, re.I) else "points"
    m = re.match(r"^(.+?):\s*(\d+(?:\.\d+)?)\+\s+(.+)$", lab)                     # "Franz Wagner: 6+ Assists"
    if m:
        return f"{m.group(1)}: {m.group(2)} or more {m.group(3).lower()}"
    m = re.match(r"^(.+?)\s+(under|over)\s+([\d.]+)\s+\w+", lab, re.I)              # a team total
    if m and m.group(1).lower() not in ("over", "under"):
        x = float(m.group(3))
        return f"{m.group(1)} must score " + (f"{math.floor(x)} or fewer" if m.group(2).lower() == "under"
                                               else f"{math.ceil(x)} or more") + f" {unit}"
    m = re.match(r"^(Over|Under)\s+([\d.]+)", lab, re.I)
    if m:
        x = float(m.group(2))
        return "Both teams together: " + (f"{math.floor(x)} or fewer" if m.group(1).lower() == "under"
                                          else f"{math.ceil(x)} or more") + f" {unit}"
    m = re.match(r"^(.+?)\s+([+-])([\d.]+)$", lab)                                   # a spread
    if m:
        x = float(m.group(3))
        return (f"{m.group(1)} must win by {math.ceil(x)} or more" if m.group(2) == "-"
                else f"{m.group(1)} must win, or lose by {math.floor(x)} or fewer")
    m = re.match(r"^(.+?)\s+to win$", lab, re.I)
    if m:
        return f"{m.group(1)} must win outright" + (" (a draw loses)" if league and _is_soccer(league) else "")
    m = re.match(r"^(.+?)\s+or draw$", lab, re.I)
    if m:
        return f"{m.group(1)} must win or draw"
    return lab


def lines(R):
    """The ticket as a list of strings; [] when there is no ticket today."""
    T = (R or {}).get("today") or {}
    if not T.get("legs"):
        return []
    out = []
    E = (R or {}).get("ended")
    H = [h for h in (R or {}).get("history") or [] if h.get("status") == "lost"]
    if E:            # today's ticket opens a new run: say so, and how the last one ended
        last = H[-1] if H else {}
        out.append(f"New run: run {R.get('runs', 0) + 1} starts at $1. Run {R.get('runs')} lasted {last.get('days', '?')} day(s), "
                   f"peak ${E.get('peak', 0):.2f}, lost on {', '.join(E.get('lost_on') or []) or '?'}; best ever ${R.get('best', 0):.2f}.")
    out += [f"Run {R.get('runs', 0) + 1 if E else R.get('runs')}, stake ${T['stake']:.2f} (the whole bank) on {len(T['legs'])} legs at "
           f"{T['pays']:.2f}x -> ${T['stake'] * T['pays']:.2f}; {round(100 * T['prob'])}% est. all win."]
    for i, L in enumerate(T["legs"], 1):
        rec = L.get("kind_rec") or {}
        pr = L.get("prop_rec") or {}
        outs = "; ".join(f"{t} without {', '.join(p)}" for t, p in (L.get("outs") or {}).items())
        out.append(f"{i}. {L['label']} {L['price']} ({round(100 * L['p'])}%) -- {L.get('match')}, {L.get('lg')} "
                   f"{L.get('tip')} ET. Needs: {needs(L['label'], L.get('league'))}."
                   + (f" Locks like it: {rec['won']} of {rec['n']}." if rec.get("n") else "")
                   + (f" Every {str(L.get('league') or '').upper()} {L.get('market')} line at a similar chance: "
                      f"{pr['won']} of {pr['n']} ({round(100 * pr['won'] / pr['n'])}% vs {pr['said']}% stated)." if pr.get("n") else "")
                   + (f" Out: {outs}." if outs else ""))
    v = T.get("vs_top4") or {}
    if v:
        out.append(f"Plain top 4 instead: {round(100 * v['prob'])}% at {v['pays']:.2f}x.")
    npr = T.get("no_props")
    if npr and any(L.get("kind") == "prop" for L in T["legs"]):
        out.append(f"Without props: {npr['n']} legs at {npr['pays']:.2f}x, {round(100 * npr['prob'])}% "
                   f"({', '.join(npr.get('labels') or [])}).")
    tl = type_line(R)
    if tl:
        out.append(tl)
    if R.get("wins_needed"):
        out.append(f"{R['wins_needed']} straight wins at this price reach the target"
                   + (f", about 1 in {round(1 / R['chance_to_target']):,}." if R.get("chance_to_target") else "."))
    return out


TYPE_NAMES = {"total": "totals", "prop": "props", "team total": "team totals", "spread": "spreads", "win": "winners"}


def type_line(R):
    """Every ladder leg so far by bet type -- where tickets actually break.
    A type 10+ points under its stated rate on 10+ legs is named, but not
    cut: that takes the date-halves test (README, 2026-11-19)."""
    B = (R or {}).get("legs_by_type") or {}
    rows = sorted(((k, v) for k, v in B.items() if v.get("n")), key=lambda kv: -kv[1]["n"])
    if not rows:
        return None
    parts = [f"{TYPE_NAMES.get(k, k)} {v['won']}/{v['n']}" + (f" ({round(100 * v['won'] / v['n'])}% vs {round(v['said'])}% stated)"
             if v.get("said") is not None else "") for k, v in rows]
    weak = [TYPE_NAMES.get(k, k) for k, v in rows
            if v["n"] >= 10 and v.get("said") is not None and 100 * v["won"] / v["n"] < v["said"] - 10]
    tk = (R or {}).get("tickets") or {}
    return ("Ladder legs so far: " + "; ".join(parts) + "."
            + (f" Tickets cashed {tk['won']} of {tk['n']}." if tk.get("n") else "")
            + (f" Weak spot: {', '.join(weak)} -- too few legs to cut them yet." if weak else ""))


def alt_line(T, record=None):
    """The ladder's 2x from the board's safest every-game lines instead
    (ten_leg.to_target), beside its replayed record against the ladder --
    the alternative the user may choose (2026-11-19). T: to_target's ticket."""
    if not T:
        return None
    rec = ""
    if record and record.get("days"):
        rec = (f" Replayed on the same {record['days']} days: it cashed {record['alt']}, the ladder {record['ladder']}.")
        a, b = record.get("only_alt"), record.get("only_ladder")
        if a is not None and b is not None and a + b:
            from daily_review import sign_p
            rec += (f" Only it cashed on {a} days, only the ladder on {b}; a fair coin splits that unevenly "
                    f"{round(100 * sign_p(a, b))}% of the time.")
    return (f"Alternative (your call, not used): the {T['n']} safest every-game lines to {T['pays']:.2f}x, "
            f"{round(100 * T['chance'])}% stated all win.{rec}")


def alt_record():
    """{days, alt, ladder}: the every-game ticket to 2x and the ladder on the
    days both were graded."""
    import ladder
    import locks
    import ten_leg
    lad = {e["day"]: e["result"] == "won" for r in ladder.replay() for e in r["days"] if e["result"] in ("won", "lost")}
    alt = ten_leg.to_target_days(locks.SAFE_LEDGER)
    days = set(lad) & set(alt)
    return dict(days=len(days), alt=sum(alt[d] for d in days), ladder=sum(lad[d] for d in days),
                only_alt=sum(alt[d] and not lad[d] for d in days), only_ladder=sum(lad[d] and not alt[d] for d in days))


if __name__ == "__main__":
    import ladder
    out = lines(ladder.report())
    print("\n".join(out) or "No ladder ticket today yet.")
    try:                                     # the every-game alternative, from today's frozen 8 AM pool
        import datetime as dt
        import ledger
        import locks
        import ten_leg
        from zoneinfo import ZoneInfo
        day = dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        pool = locks.frozen_pool(day, locks.SAFE_LEDGER)
        if pool and out:
            a = alt_line(ten_leg.to_target(locks.every_game(pool.get("legs"), ledger.load()), 2.0), alt_record())
            if a:
                print(a)
    except Exception:
        pass
