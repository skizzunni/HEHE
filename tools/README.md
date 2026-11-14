# tools/

Every script here, with the first paragraph of its own description.
`tests/test_tools_index.py` fails when a script is added without a row.

| Script | What it does |
|---|---|
| `autotune.py` | Re-decide the calls' selection rule and bench from the record (autotune.py). |
| `backtest.py` | Backtest stacks.py on real closing lines and real final scores. |
| `band_roi_study.py` | Favourite / underdog return by price band at the close, season by season, on tools/nba_history.py output (any league). Answers: where, if anywhere, is the underdog under-priced? python tools/band_roi_study.py... |
| `clv.py` | Closing line value: the primary scoreboard. |
| `daily_review.py` | The daily review: what lost, why, and what to change for tomorrow. |
| `devig_study.py` | Ledger study for the de-vig change (README, accuracy plan item 3). |
| `edge_lab.py` | The edge lab: can anything pick winners better than the closing favourite? |
| `fav_band_study.py` | Are mid-priced favourites under-priced? A pre-stated test. |
| `independent_backtest.py` | Chronological, reproducible private research on recorded soccer closing odds. |
| `independent_site_backtest.py` | Independent fixed-coverage comparison on archived exchange quotes. |
| `injury_study.py` | Board picks against the injury report as it stood at tip-off (injuries.before on the archived review/injuries snapshots): did picks whose own side had more players Out do worse than those whose opponent did? python... |
| `kalshi_backtest.py` | Does Kalshi ever sell a leg cheaper than the sportsbooks say it is worth? |
| `ladder_lab.py` | Ladder lab: at the same FanDuel price, do far overs beat far unders? |
| `ladder_study.py` | Ladder leg-ranking study, walk-forward on every saved Locks card: the top K by stated chance against the top K by each kind's record so far (shrunk to its stated chance with 10 pseudo-legs). Rerun as cards come in. |
| `ladder_watch.py` | Ladder watcher: one line per ladder leg whose result changed, and one when the ticket settles. Run it in a loop next to a checkout that the board bot keeps up to date; the last state is kept in a file so a restart... |
| `lottery_backtest.py` | Replay the lottery on past games: would the tickets have hit? |
| `ladder_count_study.py` | Fixed ladder leg counts by date halves on every saved Locks card: cash rate, average payout and the odds of the straight wins $1 -> target takes. Rejected a fixed 2-leg ladder 2026-11-13. python tools/ladder_count_study.py [max_legs] |
| `ladder_ticket.py` | Today's ladder ticket as plain lines from ladder.report() for the 8 AM message: legs, prices, chances, what each needs, Locks records, top-4 and no-props comparisons, wins to target. python tools/ladder_ticket.py |
| `move_study.py` | Board picks whose price moved against them (first log to close), walk-forward by date halves: hit vs stated and flat-$1 return at 2/3/5-point moves. Rejected 2026-11-13. python tools/move_study.py [ledger.json] [league|all ...] |
| `nba_history.py` | NBA history for schedule studies: every regular-season game of the given seasons from ESPN (date, teams, final score) and its closing moneyline (DraftKings where posted, else the first book with both sides), cached. |
| `nba_rest_study.py` | Rest / back-to-back study on tools/nba_history.py output: home win rate against the no-vig closing price, and flat-stake ROI for each side, by rest spot and season. python tools/nba_rest_study.py NBA_HISTORY.json |
| `nfl_rest_study.py` | NFL rest edges against the closing moneyline and spread: each side's days since its previous game (short week <= 5, off a bye >= 13), the rest-advantaged side's win rate vs its no-vig price and a flat $1 at the... |
| `nhl_lab.py` | NHL lab: how many one-goal games does the empty net turn into two? |
| `paired.py` | Paired comparison of two choosers on the same decisions. |
| `priced_record_audit.py` | Compare identical ledger windows; never fetch or invent historical quotes. |
| `probe.py` | Feed probe, run on GitHub's runners. Round 34: college touchdown scorers on FanDuel games that have NOT started (round 31 only reached live games, whose TD markets FanDuel had already pulled). |
| `regrade.py` | Nightly independent re-grade of the pick ledger. |
| `resample.py` | ROI with an interval that matches it, counted by games. |
| `review_pick_quality.py` | Reproduce the priced calibration check; do not enable a losing calibrator. |
| `shadow.py` | Forward shadow test of call tickets (calls.shadow_tickets). |
| `soccer_band_study.py` | Soccer favourites by band at their real closing price (straight win). |
| `soccer_lab.py` | Soccer lab: how often does the closing favourite actually win? |
| `spread_study.py` | Underdog / favourite against the closing point spread, by size of spread and season, on tools/nba_history.py output with spreads (football). Pushes are dropped; returns are a flat $1 at the closing spread price. |
| `tag_preseason.py` | Which ledger games were exhibitions: ESPN season type 1. |
| `td_lab.py` | Touchdown lab: how accurate are anytime-TD chances, and can anything beat them? |
| `ticket_backtest.py` | Whole-ticket backtest on the pick ledger's own games. |
| `totals_lab.py` | Totals lab: do far unders and far overs hit equally often? |
| `draw_league_study.py` | Straight-win soccer picks in high-draw leagues, walk-forward on the board ledger (draw rates fitted on one half, picks scored on the other). Rejected 2026-11-13. python tools/draw_league_study.py [ledger.json] [cut] |
| `totals_study.py` | Overs and unders against the closing total, season by season, on tools/nba_history.py output (any league). Pushes dropped; returns are a flat $1 at the closing over / under price. python tools/totals_study.py... |
| `ufc_bands.py` | How UFC favourites have done by their de-vigged chance band, at real DraftKings prices since 2021 (ufc_history.json): writes ufc_bands.json, a small summary the board shows beside each UFC pick. |
| `ufc_enrich.py` | Add ESPN's detailed data to each fight in ufc_history.json: DraftKings odds (moneyline, open, total-rounds line and its prices), both fighters' fight stats, and fighter bio (age at the fight, height, reach, stance;... |
| `ufc_history.py` | Collect every UFC fight ESPN lists (calendar per year, then each event's scoreboard): date, both fighters (ESPN athlete id + name), winner, round, clock, scheduled rounds and the result text. Saved to... |
| `ufc_lab.py` | UFC lab: is the de-vigged favourite's price the best chance we can state? |
| `ufc_study_rating.py` | UFC study: walk-forward Elo rating vs DraftKings prices (ufc_history.json from tools/ufc_history.py + ufc_enrich.py). Run: python tools/ufc_study_rating.py |
| `ufc_study_stats.py` | UFC study: market price + rolling fight stats (strike differential, takedowns, win rate, reach, age), fit on the first half of fights, tested on the second at real prices. Run: python tools/ufc_study_stats.py |
| `weather_lab.py` | Weather lab: does kickoff weather beat the closing total? |
| `whole_ticket.py` | Whole-ticket backtest: does the optimizer cash more tickets than the baseline at the same payout target? Individual hit rates do not count here. |
| `check.sh` | Everything a change must pass before it is committed. Exits non-zero on the first failure, so `tools/check.sh && git commit ...` cannot commit past a failing test (2026-11-05: a pipe into `tail` hid a failing unit test). |
| `watch_ladder.sh` | Live ladder tracking in one command, safe to re-run after a restart: tools/watch_ladder.sh [WORKDIR] [DAY LEAGUE]. WORKDIR defaults to ~/.cache/hehe-ladder-watch (a restart can wipe /tmp); DAY "auto" is the board day (ET, 3 AM rollover). Keeps state in WORKDIR.state.json and prints DONE when everything has settled. |
