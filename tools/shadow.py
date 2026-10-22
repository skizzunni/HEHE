"""Forward shadow test of call tickets (calls.shadow_tickets).

Every day, once its calls are complete, calls.json archives -- before any
game starts, never revised -- the tickets each strategy would build:
likeliest-first (published) and the payout-target optimizer at 2x and 3x.
This grades them from the ledger and reports cashes, the chance claimed and
the ROI per strategy, with N and dates. A strategy is promoted only when the
day-bootstrap 95% interval of its cash difference against the published one
lies above zero on these forward days.

    python3 tools/shadow.py
"""
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "review", "shadow.json")


def grade(days, book):
    """{strategy: [(day, cashed or None if open/void, payout)]}"""
    import call_tickets as CT
    out = {}
    for day, rec in sorted(days.items()):
        sh = rec.get("shadow")
        if not sh or sh.get("skipped"):
            continue
        version = sh.get("version", 1)
        frozen = {c["id"]: c for c in sh.get("pool") or []}
        price = {c["id"]: CT.dec(c.get("price")) for c in (list(frozen.values()) if version == 2 else rec.get("calls") or [])}
        if version == 2:
            tickets = sh.get("strategies") or {}
        else:
            tickets = dict(sh)
            tickets.pop("t", None)
            strongest = tickets.pop("strongest", []) or []
            for ids in strongest:
                tickets[f"strongest_{len(ids)}leg"] = ids
        for name, ids in tickets.items():
            if not ids or any(not price.get(i) for i in ids):
                continue
            st = []
            for i in ids:
                e = book.get(i) or {}
                if version == 2:
                    # Grade the archived market/side, even if the board later
                    # switched side or changed moneyline to double chance.
                    if e.get("status") in ("void", "push"):
                        st.append("void")
                    elif e.get("status") in ("won", "lost") and e.get("winner"):
                        import ledger
                        snap = dict(frozen[i], pick=frozen[i]["pick"].removesuffix(" or draw"))
                        st.append(ledger._settle(snap, e["winner"]))
                    elif e.get("pick") == frozen[i]["pick"].removesuffix(" or draw") and bool(e.get("dc")) == bool(frozen[i].get("dc")):
                        st.append(e.get("status"))
                    else:
                        st.append(None)
                else:
                    st.append(e.get("status"))
            # Forecast cash calibration excludes void tickets, regardless of
            # whether another leg lost. It is not a full bankroll ledger.
            res = (all(s == "won" for s in st) if all(s in ("won", "lost") for s in st) else None)
            out.setdefault(name, []).append((day, res, math.prod(price[i] for i in ids)))
    return out


def report(graded):
    rep = {}
    for name, rows in graded.items():
        done = [r for r in rows if r[1] is not None]
        rep[name] = dict(n=len(done), cashed=sum(r[1] for r in done),
                         roi=round(100 * sum((r[2] - 1) if r[1] else -1 for r in done) / len(done), 1) if done else None,
                         dates=[done[0][0], done[-1][0]] if done else None)
    return rep


def no_ticket_days(days):
    """Days whose calls were complete but no ticket could be archived."""
    return {d: rec.get("shadow_watch") for d, rec in sorted(days.items())
            if rec.get("shadow_watch") and not rec.get("shadow")}


def main():
    import calls
    import ledger
    days = calls.load_daily()["days"]
    rep = report(grade(days, ledger.load()))
    rep["no_ticket_days"] = no_ticket_days(days)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(rep, fh, indent=1, sort_keys=True)
    print(json.dumps(rep))


if __name__ == "__main__":
    main()
