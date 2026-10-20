# Implementation brief: high-rated legs with useful whole-ticket payouts

Read independent_review.md and independent_results.json before changing
forecast weights. The user wants individually reliable legs that combine
into a worthwhile payout, evaluated as completed tickets. Zero losing picks
or zero future software defects cannot be promised; acceptance is explicit
tests plus honest forward evidence.

## Objective and selection contract

Build a payout frontier: for each requested minimum decimal payout (2x, 3x,
5x), find the highest supported cash-probability ticket within a user-chosen
minimum leg strength and maximum leg count. Do not start with 11 legs or a
$10,000 target. Always distinguish total return from profit.

High-rated means calibrated on later, comparable events, with sample count,
dates and uncertainty shown. An arbitrary 85% model number is not proof.
All legs must have the exact same-book market, line, period, price and
settlement rules, source timestamp, verified availability and participation.
Allow at most one leg/event. Use an actual combined quote where available;
otherwise label product payouts estimates. Probability products also need
whole-ticket calibration and day/event dependence checks.

Within the October 19 archived candidate pools, using at most 11 distinct
events and the largest payout per event, these are optimistic unboosted
payout ceilings: minimum estimated leg chance 90% -> 1.424x (6 events);
85% -> 2.226x (8 events); 80% -> 3.688x (9 events). These are limited to the
archived pool and assume its estimates/eligibility; they are not global
market limits or true probability guarantees. Requiring 90% legs and a 3x
payout could not be met from that pool. Say unavailable; never invent an
edge or silently lower the leg standard.

## Work already prepared in this branch

1. Lottery refinement considers replacement/removal throughout a completed
   payout-target ticket, accepting only nondecreasing estimated cash chance
   AND expected cash return. Preserve one/event, target, boost rules and
   prior-ticket exclusions. Versioned replay preserves old recommendations.
   Oct19 archived +25%/+50% boost examples improve estimated cash chance
   26.86%/48.64% without lowering estimated return. Absolute cash chances
   remain tiny; these are optimizer facts, not a profitable forecast proof.
2. Suggested value parlays use the published final probability, require
   qualified legs, prevent duplicate events, and reject legs below a 2%
   estimated-return buffer. That buffer is not a proven profitable rule.
   It removes eight internally negative-EV suggestions in the captured
   tomorrow view. It must not be counted as generating extra winners.
3. Independent chronological scripts and all results, including rejected
   experiments, are retained. No unsuccessful forecast adjustment was deployed.

## Required next implementation

Keep multiple non-dominated alternatives per game, then optimize the whole
ticket for the contract above. Report search bounds/approximation explicitly;
compare the solver with exhaustive enumeration on small pools. Do not drop
a shorter, likelier line before evaluating whether the full ticket still
meets the payout. Same-game alternatives may compete but never coexist.

Capture pregame features before testing them: confirmed lineups/starters,
player role/opportunities, absences, goalkeeper/QB status, and timestamped
same-market prices. Fit adjustments to market residuals; keep the market
baseline unless a candidate earns promotion on later dates. Preserve all
candidate exclusions and first-publication versions permanently.

## Acceptance evidence

- Split full dates/events into fit, selection and untouched reporting
  intervals. Deploy exactly the tested policy/version.
- Same coverage, odds window, quote time, book and ticket objective for both
  choosers. Count new-right/old-wrong AND the reverse.
- Primary: whole-ticket cash rate at the same payout target, actual/simulated
  cash return after fees/voids, and event/day uncertainty. Secondary: individual
  hit rate, calibration/Brier/log loss, coverage and drawdown.
- Individual accuracy alone is insufficient: independently tested calibration
  produced 207 vs205 individual winners, but doubles fell from48 to45 cashes
  per104 dates; triples stayed33. Reject that promotion for this objective.
- Tests: probability identities, identical forecast inputs everywhere,
  integer pushes, confirmed participants, duplicate events, no future quotes,
  exact-target feasibility, valid promotions, old archive replay and tiny
  probability numerical stability. Keep all 61 unit checks passing; all39
  protected mutations were caught using the environment's Playwright adapter.
- Never label a ticket safe because each leg is a favorite. If no supported
  ticket meets both payout and cash-probability requirements, show that result.

There is no demonstrated profitable new forecasting rule in this research.
Publish any later claim only with its frozen out-of-sample results. The
prepared branch is a reviewable implementation and experiment handoff,
not a deployed promise of wins.
