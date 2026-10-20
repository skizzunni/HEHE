"""Suggested 2- and 3-leg parlays from the current board.

    python3 parlays.py                # from the last rebuild (.cache/last_board.json)
    python3 parlays.py --slot tomorrow

HOW LEGS ARE CHOSEN -- every rule here is one the ledger paid for

  * Priced legs only. A leg without a line cannot be priced into a parlay.
  * No underdogs. Across 1,144 priced, graded picks the model's underdog
    calls hit 34.2% against 39.0% implied: -15.1% a bet. Favourites broke
    even. A parlay multiplies whatever a leg returns, so a -15% leg is poison.
  * No "no signal" legs (MLB below its floor, coin-flip tiers).
  * One leg per game, so legs are not correlated by construction.
  * Two or three legs, never more. With a book margin of ~4.5% a leg, every
    extra leg compounds the tax; a 12-leg ticket at a real 75% a leg cashes
    3% of the time. See parlay_math.py.

WHAT THE NUMBERS MEAN

  `hit` is the published Card probability, used without another hidden blend.
  Every leg must be qualified and clear a 2% estimated-return buffer at its
  quoted price. That buffer is a screening rule, not evidence of a profitable
  strategy. When nothing qualifies, no suggested betting ticket is generated.
  Joint probabilities use an independence approximation across distinct games;
  one event never appears twice in a suggested ticket.
"""
import argparse
import itertools
import json
import os


HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, ".cache", "last_board.json")

MAX_POOL = 12
MIN_EV = 0.02  # screening buffer on estimated return, not a confidence bound
# Legs shorter than -500 add almost nothing to the payout while still able to
# sink the ticket; a -1450 / -2400 pair priced at -881 is risk without reward.
MIN_DEC = 1.2          # best legs considered; 12 choose 3 = 220 tickets
BAD_TIERS = {"nosig", "coin"}


def dec(american):
    try:
        v = int(str(american).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if v == 0 or -100 < v < 100:
        return None
    return 1 + (v / 100 if v > 0 else 100 / -v)


def american(d):
    if d >= 2:
        return f"+{round((d - 1) * 100)}"
    return f"-{round(100 / (d - 1))}"


def eligible(rows, min_ev=MIN_EV):
    """Legs fit to parlay, best expected return first."""
    out = []
    for lgk, r in rows:
        o = dec(r.get("p"))
        hit = r.get("hit")
        if o is None or o < MIN_DEC or not hit or r.get("d") or r.get("hd") or r.get("nc"):
            continue
        if r.get("tk") in BAD_TIERS:
            continue
        # Use the same final probability as the published Card. Re-blending
        # it with this bet's price makes the recommendation a different model.
        p = hit
        if p * o - 1 < min_ev:
            continue
        out.append(dict(lgk=lgk, pick=r["mp"], league=r.get("lg", lgk),
                        tip=r.get("t"), price=r["p"], dec=o, hit=p,
                        gid=r.get("id") or (lgk, r["mp"]),
                        implied=1 / o, ev=p * o - 1, dk=r.get("dk"), fd=r.get("fd")))
    out.sort(key=lambda L: (-L["ev"], -L["hit"]))
    return out[:MAX_POOL]


def tickets(legs, n):
    out = []
    for combo in itertools.combinations(legs, n):
        if len({L.get("gid", (L["lgk"], L["pick"])) for L in combo}) != n:
            continue
        p = 1.0
        o = 1.0
        for L in combo:
            p *= L["hit"]
            o *= L["dec"]
        out.append(dict(legs=[dict(lgk=L["lgk"], pick=L["pick"], league=L["league"],
                                   tip=L["tip"], price=L["price"],
                                   hit=round(L["hit"], 4), dk=L["dk"], fd=L.get("fd"))
                              for L in combo],
                        n=n, prob=round(p, 4), price=american(o),
                        ret5=round(5 * o, 2), ev=round(100 * (p * o - 1), 1),
                        dk="+".join(L["dk"] for L in combo if L["dk"])
                           if all(L["dk"] for L in combo) else None))
    return out


def build(slot_leagues, top=3):
    """{2: [...], 3: [...], "pool": n} for one day's board slot."""
    # a stale price (freshness.py: older than 15 minutes, or untimed) is
    # never a leg
    rows = [(k, r) for k, v in (slot_leagues or {}).items()
            for r in v.get("rows") or [] if not r.get("st")]
    legs = eligible(rows)
    res = {"pool": len(legs), "min_ev": MIN_EV,
           "reason": "No qualified priced picks clear the estimated-return buffer." if not legs else None}
    for n in (2, 3):
        t = tickets(legs, n)
        # best expected value first; among near-ties, the likelier ticket
        t.sort(key=lambda x: (-x["ev"], -x["prob"]))
        best = t[:top]
        safest = max(t, key=lambda x: (x["prob"], x["ev"]), default=None)
        if safest and safest not in best:
            best.append(dict(safest, safest=True))
        res[n] = best
    return res


def build_all(board):
    return {s: build(board["slots"].get(s)) for s in ("today", "tomorrow")}


def show(res, slot):
    print(f"{slot.upper()} -- {res['pool']} eligible legs "
          f"(priced, favourite, with a measured rate)")
    for n in (2, 3):
        print(f"\n  {n}-LEG")
        if not res[n]:
            print("    not enough eligible legs")
        for t in res[n]:
            tag = " (likeliest)" if t.get("safest") else ""
            print(f"    {t['price']:>6}  hits {100*t['prob']:.1f}%  "
                  f"EV {t['ev']:+.1f}%  $5 -> ${t['ret5']:.2f}{tag}")
            for L in t["legs"]:
                print(f"           {L['pick']:<28} {L['price']:>6}  "
                      f"{L['league']:<8} {100*L['hit']:.1f}%")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", choices=["today", "tomorrow"])
    a = ap.parse_args()
    try:
        with open(STATE) as fh:
            board = json.load(fh)
    except (OSError, ValueError):
        raise SystemExit("no board yet -- run python3 rebuild_board.py first")
    res = build_all(board)
    for s in ([a.slot] if a.slot else ["today", "tomorrow"]):
        show(res[s], s)
    print("No parlay is a sure thing. A 3-leg ticket of 75% legs loses 58% "
          "of the time.")


if __name__ == "__main__":
    main()
