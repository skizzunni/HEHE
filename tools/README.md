# tools/

Every script here, with the first paragraph of its own description.
`tests/test_tools_index.py` fails when a script is added without a row.

| Script | What it does |
|---|---|
| `autotune.py` | Re-decide the calls' selection rule and bench from the record (autotune.py). |
| `backtest.py` | Backtest stacks.py on real closing lines and real final scores. |
| `band_roi_study.py` | Favourite / underdog return by price band at the close, season by season, on tools/nba_history.py output (any league). Answers: where, if anywhere, is the underdog under-priced? python tools/band_roi_study.py... |
| `blind_model.py` | Price-blind team numbers from results only (no odds), walk-forward tested against the ledger's no-vig price. Information only: it lost to the market in every league (README 2026-11-23). |
| `slate_sheet.py` | A day's NBA/NHL/NFL games with our price-blind number printed first, then the DraftKings line, no-vig chance and the gap (research first, lines second). Information only. |
| `nba_minutes.py` | Each NBA player's minutes over his last 5 games (ESPN rosters + game logs), for the daily card's low-minutes prop caution. Information only. |
| `nba_injury_report.py` | The newest official NBA injury report PDF (walks back in 15-minute steps), parsed into team / player / status rows plus teams NOT YET SUBMITTED. `python3 tools/nba_injury_report.py OKC IND`. |
| `key_absences.py` | For each NBA game, players among a team's top 6 by minutes over its last 10 games who are Out / Doubtful / Questionable on the official report -- the ticket's "no favourite missing key players" check. |
| `build_ticket.py` | The user's daily ticket by game: board winners at 75%+ with no key player out and no price-blind disagreement, plus the card's ~87% props (not on the injury report; blowout games flagged), every leg left off listed with its reason. `--save` writes a grade_picks file. `--ncaab` (opt-in) adds college favourites at 90%+ no-vig from DraftKings on ESPN. |
| `nhl_goalies.py` | The day's NHL starting goalies from DailyFaceoff with each one's status (Confirmed / Likely / Unconfirmed) and when it was posted, ET. |
| `pregame_brief.py` | One pre-game brief for a day: slate_sheet (our number first, then the line), the official NBA injury report, NHL goalies; each section fails on its own. |
| `recheck_ticket.py` | Re-checks a saved ticket (build_ticket.py --save) against the latest official NBA injury report: props on players now Out / Doubtful / Questionable, and NBA winners whose team now has a top-minutes player out (caution). Run before tip-off. |
| `grade_preview.py` | Runs the board's own grader (ledger.grade) with saving switched off and prints what it would settle -- result, score and loss diagnosis -- so the record can be read while the board workflow is off. Writes nothing. |
| `grade_picks.py` | Grades a saved JSON list of researched picks (spread / ml / over / under) from ESPN final scores: each pick won / lost / push / open, the record and flat $1 return. |
| `prereg_nhl_dog.py` | Pre-registered forward test (2026-11-23): NHL underdog +1.5 when the favourite closes -200 or shorter, graded from ESPN closing lines on games from 2026-11-24; decides at 150 games. Information only. |
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
| `td_two_plus_study.py` | Checks the 2+ touchdown estimate on every graded player-game: rebuilds each 2+ chance from the saved anytime chance and counts touchdowns from ESPN box scores, by date half. Read only. python tools/td_two_plus_study.py |
| `daily_card.py` | Today's card from the published board for the daily message: yesterday's board record and three tickets (ladder, 10-leg, 2x every-game), the 10-leg (ten_leg.py) in start order with PREVIEW flagged until the 8 AM card is set, its other sizes and the same lines to 2x (what it adds and leaves out), NFL touchdown scorers for every player (anytime / 2+ / first TD), then the likeliest NBA and NHL props one per player (at most 3 per game), NBA team points, every game's winner pick (toss-ups marked). python tools/daily_card.py [today\|tomorrow] |
| `ladder_ticket.py` | Today's ladder ticket as plain lines from ladder.report() for the 8 AM message: legs, prices, chances, what each needs, Locks records, top-4 and no-props comparisons, wins to target. python tools/ladder_ticket.py |
| `line_moves.py` | How a league's board picks moved since a saved snapshot: chance drops of 3+ points (money to the other side), side changes, scratched or new games. python tools/line_moves.py LEAGUE --save SNAP.json / --compare SNAP.json |
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
| `ufc_card_research.py` | A UFC card fight by fight from ESPN: records, KO and submission wins-losses, last-5 significant strikes and accuracy, takedowns, knockdowns, days since the last fight, latest headline. Information only. python tools/ufc_card_research.py [YYYYMMDD] |
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
