# Independent backtests and implemented selection fixes

Source snapshot: `43681fe751e8f99245ba679b4f79f7ecf7043a30`.
Live snapshot: October 19, 2026, 9:02 p.m. Eastern. These results are frozen;
later games and deployments are not silently added to them.

The requested goal is higher accuracy and better returns. I ran the
experiments independently, rather than treating existing repository claims
as new evidence. No tested forecasting replacement earned promotion to live.
The patch therefore retains the existing forecast baseline and fixes
selection waste and recommendations that contradict their own return estimates.

## 1. External chronological experiment

Dataset: 14,044 usable soccer matches across England's top two divisions,
Germany, Italy, Spain and France, 2020–21 through 2025–26. Train: 9,437
matches in the first four seasons. Validation: 2,304 in 2024–25. Final test:
2,303 in 2025–26. Model selection was frozen before evaluating the final
test. The experiment protocol is described by the script, not chosen from
the final results.

Four alternatives were evaluated on validation: proportional odds removal,
power odds removal, regularized probability calibration, and a market-offset
model with rolling Elo built only from earlier match dates. Calibration won
validation log loss and was frozen for the final comparison.

For the primary selection comparison, both policies choose three of the same
eligible market-favorite selections per date, within the -400 to -120 price
window, using the same Bet365 recorded closing quote. Dates with fewer than
three eligible games are excluded from both policies. Final sample: 312 picks
over 104 dates.

| Final test | Baseline market | Selected calibration |
|---|---:|---:|
| Correct selections | 205/312 | 207/312 |
| Hit rate | 65.71% | 66.35% |
| Equal-unit ROI at the recorded Bet365 price | -5.11% | -4.01% |
| ROI at best recorded named-book price | -3.59% | -2.47% |
| All-game log loss, 2,303 games | .992894 | .992422 |

The paired day bootstrap gives an extra-win interval of **-2 to +6**, and
extra profit of 3.44 units with interval **-2.42 to +9.88 units**. This does
not establish a reliable improvement. The candidate remains unprofitable
in this test and is NOT applied to live probabilities.

### Whole-ticket results for the requested parlay objective

I also replayed complete same-book tickets from those frozen lists, risking
one unit per ticket. Payout multiplies the recorded Bet365 closing prices;
it is an estimated historical parlay quote, not an accepted betting slip.
Both policies use the same 104 dates.

| Ticket | Market baseline: cash rate / ROI | Calibrated: cash rate / ROI |
|---|---:|---:|
| Top single | 70/104 = 67.31% / -8.38% | 71/104 = 68.27% / -7.05% |
| Top two together | 48/104 = 46.15% / -9.51% | 45/104 = 43.27% / -15.34% |
| Top three together | 33/104 = 31.73% / -4.70% | 33/104 = 31.73% / -4.79% |

Mean total payout was about 2.01x for doubles and 3.14x for triples. Two
extra winning individual selections did not improve the three-leg cash rate
and made doubles worse. The whole-ticket comparison is diagnostic; no new
tuning was done after seeing it. The candidate is not promoted.

The requested chooser should maximize whole-ticket cash probability at a
declared minimum payout and minimum validated leg strength, presenting
separate 2x/3x/5x frontiers. It must preserve same-book quotes, one event per
leg, participation and settlement rules. A fixed 11-leg quota or $10,000
target is a different objective. When no supported ticket clears both the
cash-probability floor and payout target, report that explicitly.

The best-price calculation uses named Bet365, Betway, William Hill and
Betfair sportsbook columns, excluding Max columns and Pinnacle. The data
provider warns Pinnacle quotes became stale after July 2025. Better recorded
prices improve cash return for the identical selected outcomes, but this
comparison assumes access and fills and is not an executable profit claim.

This is a closing-time study, not an 8 a.m. ticket replay. It covers soccer
outright markets, not the site's unpriced double-chance records, props or
FanDuel executions. The private source CSVs are not redistributed here.

Reproduce in a research environment with numpy, pandas and scipy:

```
python3 tools/independent_backtest.py --data-dir /path/to/private/csvs --out /tmp/experiment --stage validation
python3 tools/independent_backtest.py --data-dir /path/to/private/csvs --out /tmp/experiment --stage final
```

The first command saves the chosen model and coefficients before the second
loads the final season. Input filenames are `E0_2021.csv`, etc.; supported
leagues and season identifiers are explicit in the script. Training includes
2021, 2122, 2223, 2324; validation 2425; final 2526. The frozen model artifact
includes source SHA-256 hashes. No fitting is done on the final season.

## 2. Independent test of the site's own archive

18,735 alternate-leg rows represent only **237 games across 38 dates**.
The archive's `p` and `q` fields are score-model probabilities, not exchange
midpoints; treating q as a market probability would misstate the comparison.

I compared midpoint ranking, score-model ranking, model/price-value ranking
and midpoint minus spread at fixed coverage. Methods were selected on
September 26–October 7; final test starts October 8. Each ticket has one
leg/event and the same permitted price window. Fees are included. The final
samples are small; reported returns below are from equal cash risk on each
individual leg, not compounded parlay returns.

| Final test | Market-ranked baseline | Validation-selected candidate |
|---|---:|---:|
| Regular, 3/day | 16/21; -7.01% ROI | 14/21; -17.60% ROI |
| Regular, 11/day | 36/44; +0.33% ROI | 36/44; +0.40% ROI |
| Safe, 3/day | 20/21; -0.37% ROI | 21/21; +4.85% ROI |
| Safe, 11/day | 42/44; -0.17% ROI | 41/44; -2.05% ROI |

The apparently good Safe 3/day result spans seven dates. Its extra-win
interval includes zero; it does not justify a broad score-model promotion.
The archive also joins hourly pre-start exchange quotes with sportsbook
closing features, so it cannot prove availability for a morning decision.
All four studies and intervals are retained, including the losing tests.

```
python3 tools/independent_site_backtest.py --archive data/backtest_kalshi_legs.json --out /tmp/site-results.json
```

## 3. Implemented ticket refinement

The existing Lottery builder improves only its finishing leg. The patch
adds a bounded coordinate refinement of the completed payout-target ticket:
it considers every one-leg replacement and redundant-leg removal. An update
is accepted only if:

- The payout target is still met, with the selected profit boost.
- No event appears twice or reuses an event reserved by a prior ticket.
- Estimated cash probability never decreases.
- Estimated expected cash return never decreases.
- At least one of those two quantities strictly improves.

The refinement does not fit outcomes or invent probabilities. It is a local
Pareto improvement, not a global optimum and not proof the probabilities are
correct. On the October 19 archived decision pool:

| Ticket | Old estimated cash chance | New | Relative gain | Old/new modeled EV |
|---|---:|---:|---:|---:|
| FanDuel +25% boost | .0069945% | .0088734% | +26.86% | -11.65% / -10.80% |
| FanDuel +50% boost | .0069945% | .0103970% | +48.64% | +6.01% / +6.20% |

The resulting boosted payouts are approximately $10,053 and $10,215 per
$1, respectively. These are modeled point estimates using archived quotes
and assumed eligible promotions. They are not realized returns or evidence
of positive true EV. Unboosted and +100% tickets were unchanged in this pool.
Only one archived date has the necessary complete Lottery candidate pool,
so this is an optimizer comparison, not a future win-rate backtest.

Old archives keep the old optimizer when replayed. New candidate pools save
an optimizer version; past tickets and their results are never rewritten.

## 4. Implemented recommendation gate

The current fetched page suggested eight tomorrow parlays whose own EV
estimates were -4.6% to -8.1%. The patch requires qualified selections,
uses the SAME final probability as the published Card, excludes duplicate
events, and requires each proposed leg to clear a 2% estimated-return buffer.
It returns no suggested betting ticket when none qualify. The explicit
Lottery and Locks sections retain their separate stated objectives.

The 2% is a screening buffer, not a statistically validated profit threshold.
It is not presented as an accuracy improvement, and suppressing bad-price
recommendations is not counted as generating more winners. A displayed
positive estimate still requires prospective validation and an available quote.

## Verification and deployment

All 61 standard-library unit tests pass, including 100 randomized Pareto
invariant cases, duplicate-event exclusion, canonical probability use and
legacy replay checks. The saved October 19 Lottery archive still replays
exactly. The existing Chrome CLI UI harness timed out in this execution
environment. Its fixtures and assertions passed through a Playwright adapter;
all 39 protected mutations were caught and the restored suite passed through
that adapter. A separate render with rebuilt live data verifies the updated
Card, absence of negative-return suggested tickets and no JS errors.

The patch is reviewable, not deployed. No bankroll, staking or live-bot
settings are changed. It makes no claim of a proven profitable forecasting
replacement. The next material prediction experiment needs archived pregame
lineups/roles and contemporaneous executable quotes, compared with the
market on new dates at fixed coverage; those inputs cannot be reconstructed
honestly from final box scores.

## Sources

- [Football-Data archive and data-quality notices](https://www.football-data.co.uk/data.php)
- [Source column definitions: C denotes closing quotes](https://www.football-data.co.uk/notes.txt)
- [Probability calibration documentation](https://scikit-learn.org/stable/modules/calibration.html)
- [Chronological validation documentation](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html)
- [Research on calibration versus accuracy in sports betting](https://arxiv.org/abs/2303.06021)
