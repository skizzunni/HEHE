# Pick-quality repair after the Oct 20 audit

Reviewed source: `4d1ac5d`, with 1,404 priced graded outcomes. This is a later
snapshot than the previous 1,392-row comparison, not a revision of that comparison.

## What the fresh tests support

The existing Platt calibrator stays disabled. Re-running its chronological study
on priced picks dated Oct 15–20 gives 111 fitted forecasts: raw log loss 0.5687,
calibrated 0.6055; Brier 0.1888 versus 0.2012. The per-game bootstrap log-loss
difference is +0.03679 (95% +0.00752 to +0.06739). Calibration made this sample
worse. This interval does not account for within-day dependence. The legacy study
splits by game date, not a complete replay of information available at a
particular morning timestamp. No replacement
forecaster or profitable strategy is promoted. `tools/review_pick_quality.py`
reproduces the check; aggregate outputs are in `pick_quality_recheck.json`.

## Actual decision defects repaired

- The legacy ticket helper defaults to treating every call as unstarted unless
  its caller supplies a check. Production supplied none. It also admits settled
  calls and ignores unconfirmed lineup gates. That helper is retained only for
  old research compatibility; the published live recommendation path replaces it.
- Calls retain their original morning price while their chance can move under
  the existing move rule. Those fields are not an executable current quote.
  Current recommendations use a separately timestamped observation of the exact
  original outcome, with a chance refreshed from the current inputs. The original
  call identities, first prices, `conf_first`, and wins/losses remain on record.
- The league-level news check could clear one game's news using another game's
  newer quote. Current recommendations require that game's price AND probability
  inputs to postdate its own observed news. Missing/stale/future-dated quotes,
  unconfirmed required gates, already-started games and settled calls are excluded
  from current tickets. This does not remove their outcomes from the record.
- A failed NBA/WNBA fetch returned `{}`, which counted as a checked injury report.
  It now needs a verified matching game header. The summary cache preserves that
  header; an empty or mismatched response cannot imply a healthy roster.
- Picking the strongest individual legs first can add an unnecessary leg. The
  live chooser exhaustively compares compatible 2–3-leg combinations at 2x, 3x,
  and 5x total-return targets, maximizing estimated ticket cash chance, including
  the existing per-added-leg probability adjustment. The leg standard stays at
  75%; unavailable targets stay unavailable. Prices must come from one sportsbook.
- The pool reconsiders ALL currently priced games at the declared leg standard,
  beyond the five frozen calls. Later candidates can improve a live ticket while
  the original calls and their outcomes remain intact. Tennis restrictions remain.

In a deliberately synthetic regression example, the strongest-first prefix adds
92% at -2000 to 84% at -250 and 82% at -200. That prefix pays 2.205x with an
estimated 61.11% cash chance after the existing adjustment; the latter two alone
pay 2.10x with estimated 67.64% cash chance. Both meet the same 2x target. These
are illustrative inputs, not real bets or a measured improvement in realized wins.

## Honest evaluation going forward

Forward shadow snapshots now freeze the complete eligible quote/probability pool,
not only game IDs. Strongest-first and the optimizer use the SAME payout targets
and constraints. Later quote updates cannot change an archived payout. Grading
uses the archived market/side and actual winner, even if the board subsequently
changes its selection. Void tickets are excluded from this forecast comparison;
its ROI is therefore conditional on nonvoid tickets, not a full bankroll ledger.
Old snapshots remain untouched. No automated promotion is made from this study.

The existing whole-day closing-line comparison is now explicitly a hindsight
closing diagnostic: different games close at different times, so its candidate
pool is not simultaneously available in the morning. It excludes unpriced cached
rows and cannot mark a strategy proven or eligible for promotion. The regenerated
study has 1,049 legs over 50 dates. At the 75% leg standard and 2x target, there
were only four common-ticket dates and zero difference in cashes; it does not
establish a winning forecasting or betting strategy.

The UI labels payouts as estimated same-book products, not accepted combo quotes.
Negative modeled-return tickets are labeled payout comparisons, not value
recommendations. Required gate status is shown per leg. Browser-side expiry
checks remove stale/started combinations even if a phone keeps an old page open.

## Validation

The first 10 targeted regressions failed before implementation. The expanded
suite covers fresh quote/chance pairing, post-news quotes per game, injured-report
fetch failure and cache provenance, original-call preservation, frozen forward
snapshots, exact-market settlement, same-book constraints, start/settlement
checks, unchanged leg standards, later slate candidates, and the target-selection
counterexample. Full-suite and browser results are recorded in the README.

These repairs make the chooser use current, qualified inputs and choose better
combinations under its estimates. Future ticket cash rates and profits require
forward evidence. The tests do not establish a profitable new forecasting model.
