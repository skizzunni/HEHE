# Picks system — post-mortem and rebuild

## What actually went wrong

Not the picks. The bet structure.

**Table tennis / MMA, 12 legs, +21074 — LOST.** Nine of twelve legs hit. A 75%
per-leg hit rate is genuinely good. It still lost, because a 12-leg parlay pays
nothing for 11/12. At a sustained 75% accuracy, the chance of running all twelve
is 3.2%.

**Golf R3 2-balls, 14 legs, +152121 — LOST.** Dead after four legs; nine legs
never got graded. Round-3 two-balls are near coinflips priced around -145, and
they are *correlated* — R3 pairings are set by leaderboard position, so a whole
card of "underdog beats favorite" is one repeated bet on the same idea.

**MLB, 10-leg (+20316) and 12-leg (+62536) — both still live, both effectively
gone.** Two legs in (Red Sox, Cubs), they need 8 and 10 more straight. At a
strong 58% per leg that is 1.28% and 0.43%.

## The math (run `python3 parlay_math.py`)

The price of each parlay tells you the accuracy it demands:

| Slip | Legs | Price | Per-leg accuracy to break even |
|---|---|---|---|
| Table tennis / MMA | 12 | +21074 | 64.00% |
| Golf 2-balls | 14 | +152121 | 59.25% |
| MLB | 10 | +20316 | 58.75% |
| MLB | 12 | +62536 | 58.47% |

Nobody picks 64% on table tennis moneylines. Nobody picks 59% on golf 2-balls.

And a picker who *is* genuinely skilled still loses on these, because the book's
hold compounds with every leg while the edge only multiplies. At a real 55%
edge against a 4.5% hold:

| Legs | Expected return per $1 |
|---|---|
| 1 | $0.957 |
| 4 | $0.839 |
| 8 | $0.703 |
| 12 | $0.590 |
| 14 | $0.540 |

A 55% picker is +EV on singles and burns 41 cents on the dollar by twelve legs.
Same $10, three ways: ten $1 singles returns $10.50; a 3-leg returns $8.76; a
12-leg returns $5.90.

## The fix

1. **Cap at 2–3 legs.** This is the single change that matters. Everything else
   is a rounding error next to leg count.
2. **Only bet where the model disagrees with the market.** `mlb_model.py`
   computes a win probability and compares it to the posted price. No edge, no
   bet — "no +EV plays today" is a valid output.
3. **Never correlate legs.** Golf 2-balls off one leaderboard, or ten home
   favorites, are one bet wearing a costume.
4. **Fractional Kelly staking** (quarter-Kelly), not flat $5 lottery tickets.
5. **Log every bet with the closing line.** Beating the close is the only
   real evidence a model works; win/loss over a weekend is noise.

## Files

- `parlay_math.py` — slip autopsy and parlay EV math. No network needed.
- `ncaaf_team_props.py` — opponent-adjusted SRS over all 1,633 FBS+FCS games of
  2025, priced against the Thu 9/3/26 board and against DraftKings' live
  numbers. Shrinkage and home-field are picked on a holdout (fit wk 1–10,
  scored wk 11+), which puts the honest margin RMSE at 15.9 rather than the
  flattering in-sample 12.7. Needs `site.api.espn.com`.
- `mlb_model.py` — Pythagorean team strength + log5 + starting-pitcher
  adjustment + home field, priced against market moneylines with EV and Kelly
  sizing. Needs `statsapi.mlb.com`.

```
python3 parlay_math.py
python3 mlb_model.py --date 2026-08-29 --odds TOR=-155 ATL=-190
python3 ncaaf_team_props.py
```

## Environment note

Egress varies by sandbox. `ncaaf_team_props.py` reaches ESPN fine and caches
the season to `.cfb2025.json`, but the sandbox the MLB work was written in
blocked all outbound sports data
(`statsapi.mlb.com`, `mlb.com`, `espn.com`, Yahoo, Baseball-Reference — every
one refused by the egress proxy). `mlb_model.py` reports that and exits rather
than guessing. Run it somewhere with normal network access and it produces real
numbers.
