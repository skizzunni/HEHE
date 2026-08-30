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
- `mlb_model.py` — Pythagorean team strength + log5 + starting-pitcher
  adjustment + home field, priced against market moneylines with EV and Kelly
  sizing. Needs `statsapi.mlb.com`.

```
python3 parlay_math.py
python3 mlb_model.py --date 2026-08-29 --odds TOR=-155 ATL=-190
```

## Environment note

The sandbox this was written in blocks all outbound sports data
(`statsapi.mlb.com`, `mlb.com`, `espn.com`, Yahoo, Baseball-Reference — every
one refused by the egress proxy). `mlb_model.py` reports that and exits rather
than guessing. Run it somewhere with normal network access and it produces real
numbers.

---

# v3 — stress test, audit, and multi-sport (2026-08-30)

## The correction that matters

An earlier pass in this session reported **61.6% accuracy** for the MLB model.
That number was wrong. It came from a backtest that used end-of-season stats to
predict August games — the model could see the future. Rebuilt with strictly
point-in-time inputs (no stat used for a game includes that game or any later
one), on a held-out window it never touched during fitting:

| Method | Accuracy (757 games) |
|---|---|
| **model v3** | **57.5%** (Brier 0.2449) |
| better W-L record | 55.6% |
| better run differential | 54.6% |
| always pick home | 53.4% |

**McNemar test, model vs. better-record baseline: chi² = 1.03, p = 0.31.**

The ~2-point edge is *not statistically significant* at this sample size. One
standard error is 1.8 points. The model has found a little signal; it has not
proven an edge.

## Bugs found and fixed

1. **Park factors were a no-op.** The venue constant multiplied both teams' run
   expectation, so it cancelled exactly in the win-probability ratio. It was
   reported as a model feature and contributed nothing. Removed — park belongs
   in a totals model.
2. **Probability sharpening made things worse.** An exponent k=1.18 was fitted
   on contaminated in-sample data and pushed probabilities away from 50%.
   Out-of-sample it *degraded* Brier (0.2449 → 0.2455). Shrinking (k=0.50)
   was also worse (0.2456). Raw output wins; the curve is left alone.
3. **Silent team-name mismatch.** The standings endpoint returns `"Rays"`; the
   schedule endpoint returns `"Tampa Bay Rays"`. Keying on name matched nothing
   and printed an empty slate instead of erroring. Now keyed on team **id**.
4. **`slate.py` crashed on soccer** — ESPN emits literal `null` entries inside
   the odds array.
5. **`slate.py` showed only the main event** for UFC/golf/tennis. Those feeds
   put every fight or matchup in `competitions[]`; it read only `[0]`.
6. **`"OFF"` prices** (suspended markets) hit `int()` and were mislabelled
   "price unreadable". Now reported as "market off".
7. **Soccer was priced as a two-way market.** It is three-way; the draw is now
   included in the de-vig.

Not a bug, for the record: the hardcoded starters in `devig.py` were checked
against the MLB API and are **correct**. The apparent mismatches were a
doubleheader (it took game 2), pitchers not yet announced, and an accent in
"Cristopher Sánchez".

## Calibration — read this before betting anything

| Model says | n | Actually wins |
|---|---|---|
| 50–55% | 315 | 55.9% |
| 55–60% | 258 | 58.1% |
| 60–65% | 128 | 59.4% |
| 65–70% | 56 | **58.9%** |

The model is **overconfident at the top**. Its most confident picks do not
outperform its middling ones. Output is clamped at 66% because that is the
edge of what the data supports; treating a 65% pick as better than a 58% one
is not supported by the backtest.

## Files

- `slate.py` — any sport, any date, de-vigged market prices. 16 leagues.
  `python3 slate.py mlb` / `slate.py ufc` / `slate.py epl --date 20260912` / `slate.py --all`
- `model_v3.py` — the validated MLB model. `--backtest` reproduces the table above.
- `mlb_model.py` — earlier model, different functional form, **never validated**.
  Its constants were not retuned to v3's, because those were fitted for a
  different structure and porting them would create a new bug.
