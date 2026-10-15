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

  `hit` is the rate the leg's own sport and confidence band has MEASURED,
  pulled halfway toward the book's de-vigged probability (see MARKET_WEIGHT),
  not the model's raw confidence. The joint probability multiplies those, which
  assumes independent games -- true across different games, not within one.
  `ev` is the expected return per $1 at the posted prices. When no combination
  is positive the best one is still shown and labelled negative: on a vigged
  market that is the usual state, and a parlay never turns a -EV leg into a
  +EV ticket.
"""
import argparse
import itertools
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, ".cache", "last_board.json")

# The board's band rates are not the whole truth. On 904 graded favourites the
# ledger hit 69.0% against 68.9% implied by the price -- the book was right,
# the bands were optimistic. So each leg's probability is pulled halfway to the
# book's de-vigged number. Two-way margin measured at ~4.5%, half per side.
MARKET_WEIGHT = 0.5
HALF_VIG = 1.0225

MAX_POOL = 12          # best legs considered; 12 choose 3 = 220 tickets
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


def eligible(rows):
    """Legs fit to parlay, best expected return first."""
    out = []
    for lgk, r in rows:
        o = dec(r.get("p"))
        hit = r.get("hit")
        if o is None or not hit or r.get("d") or r.get("hd"):
            continue
        if r.get("tk") in BAD_TIERS:
            continue
        fair = min(1 / o / HALF_VIG, 0.99)
        p = (1 - MARKET_WEIGHT) * hit + MARKET_WEIGHT * fair
        out.append(dict(lgk=lgk, pick=r["mp"], league=r.get("lg", lgk),
                        tip=r.get("t"), price=r["p"], dec=o, hit=p,
                        implied=1 / o, ev=p * o - 1, dk=r.get("dk")))
    out.sort(key=lambda L: (-L["ev"], -L["hit"]))
    return out[:MAX_POOL]


def tickets(legs, n):
    out = []
    for combo in itertools.combinations(legs, n):
        p = 1.0
        o = 1.0
        for L in combo:
            p *= L["hit"]
            o *= L["dec"]
        out.append(dict(legs=[dict(lgk=L["lgk"], pick=L["pick"], league=L["league"],
                                   tip=L["tip"], price=L["price"],
                                   hit=round(L["hit"], 4), dk=L["dk"])
                              for L in combo],
                        n=n, prob=round(p, 4), price=american(o),
                        ret5=round(5 * o, 2), ev=round(100 * (p * o - 1), 1),
                        dk="+".join(L["dk"] for L in combo if L["dk"])
                           if all(L["dk"] for L in combo) else None))
    return out


def build(slot_leagues, top=3):
    """{2: [...], 3: [...], "pool": n} for one day's board slot."""
    rows = [(k, r) for k, v in (slot_leagues or {}).items()
            for r in v.get("rows") or []]
    legs = eligible(rows)
    res = {"pool": len(legs)}
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
