"""What parlay size actually cashes, given a measured hit rate.

    python3 parlay_opt.py                  # the table
    python3 parlay_opt.py --legs 24        # what one specific structure costs

WHY THIS EXISTS

The model has been the focus of every upgrade in this repo, and the model is
not what has been losing. A 24-leg parlay at a genuine 85% per leg wins 2% of
the time. At a genuine 65% per leg it wins 0.01% of the time -- once every
9,000 tickets. No achievable model accuracy rescues that structure, because the
failure is multiplicative and the edge is not.

The numbers below use HIT RATES MEASURED ON HELD-OUT DATA, not model
confidence. Those are different things and conflating them is how a 24-leg
ticket gets built.

    tennis, both ranked, model said 80-90%   ->  84.6% actual (n=91, August)
    tennis, model said 60-70%                ->  70.6% actual (n=218)
    MLB, model's side                        ->  57.5% actual (n=757)

VIG IS THE POINT

A book prices each leg at roughly its true probability plus a margin. Stacking
N legs stacks the margin N times: it compounds against you at exactly the rate
your win probability compounds down. That is why the expected value column
falls off a cliff long before the payout gets interesting.
"""
import argparse

# per-leg margin a book keeps on a two-way market, from the de-vig work in this
# repo: measured 4,090 real MLB sides, two-way overround averaged ~4.4%
VIG = 0.044


def parlay(p, n, vig=VIG):
    """(win probability, fair decimal, offered decimal, EV per $1)."""
    win = p ** n
    fair = 1.0 / win
    # the book's price on each leg is shaded by the margin, and that compounds
    offered = (1.0 / (p * (1 + vig))) ** n
    return win, fair, offered, win * offered - 1.0


def american(dec):
    return f"+{round((dec-1)*100):,}" if dec >= 2 else f"-{round(100/(dec-1))}"


def table(rates):
    for label, p in rates:
        print(f"\n{label}  (per-leg hit rate {p:.1%})")
        print(f"  {'legs':>4} {'wins':>9} {'payout':>12} {'$5 returns':>12} "
              f"{'EV/$1':>8} {'1+ win in 30 tickets':>21}")
        for n in (1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 24):
            win, fair, off, ev = parlay(p, n)
            once = 1 - (1 - win) ** 30
            print(f"  {n:>4} {win:>8.2%} {american(off):>12} "
                  f"{'$'+format(5*off, ',.2f'):>12} {ev:>+8.1%} {once:>20.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legs", type=int)
    ap.add_argument("--rate", type=float, default=0.846)
    a = ap.parse_args()
    if a.legs:
        win, fair, off, ev = parlay(a.rate, a.legs)
        print(f"{a.legs} legs at a measured {a.rate:.1%} each")
        print(f"  wins            {win:.4%}   (1 in {1/win:,.0f})")
        print(f"  fair price      {american(fair)}")
        print(f"  book price      {american(off)}")
        print(f"  expected value  {ev:+.1%} per $1")
        print(f"  to cash once you would expect to buy {1/win:,.0f} tickets")
        return
    table([("MY BEST BUCKET   tennis 80-90%, both players ranked", 0.846),
           ("SOLID            tennis 60-70% band", 0.706),
           ("MLB              the model's side, any game", 0.575)])
    print("\nEV is negative at every size, which is what a vigged market means. "
          "It gets\nmonotonically worse with legs: the margin compounds at the "
          "same rate the win\nprobability decays. Fewer legs is not a preference, "
          "it is arithmetic.")


if __name__ == "__main__":
    main()
