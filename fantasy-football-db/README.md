# Fantasy Football database layer

Two local, file-based databases replace the Excel workbook this project was
using before, and give the future web page something to query directly.

- **`data/app.db`** (SQLite) -- operational, current-state data: the player
  crosswalk, your Sleeper leagues/rosters, current dynasty trade values,
  buy-low/sell-high signals, and model predictions. Small, fast, and
  **committed to this repo** so roster/value history persists across
  machines and sessions instead of living only in one place.
- **`data/analytics.duckdb`** (DuckDB) -- the large historical/analytical
  data behind the breakout/fall-off models: nflverse play-by-play, the full
  FantasyPros ECR archive, ADP history, coaching staff data, Vegas odds.
  Not committed (gitignored) -- it's regenerated from source and can get
  large once play-by-play is loaded.

Both are plain files, no server to run, no account to create.

## Setup

```bash
pip install -r scripts/requirements.txt
python3 scripts/build_db.py       # creates both DBs, loads the player
                                   # crosswalk + trade values + ECR archive
                                   # from dynastyprocess/data (public, no auth)
python3 scripts/load_sleeper.py   # pulls your leagues/rosters from Sleeper's
                                   # public API (edit LEAGUE_IDS in the script
                                   # if your leagues change)
python3 scripts/load_espn.py      # pulls your leagues/rosters from ESPN's
                                   # public (unofficial) API -- both of Ian's
                                   # ESPN leagues are public, no login cookies
                                   # needed; edit LEAGUE_IDS/SEASON in the
                                   # script if they change
python3 scripts/load_nflverse.py  # loads 1999-2025 play-by-play (defaults to
                                   # the full range; pass --start/--end for a
                                   # smaller window)
python3 scripts/load_coaching_and_offense.py  # loads coach_table/team_offense_
                                   # season/vegas_odds/team_primary_qb/
                                   # player_offense_rank/coach_tenure_segments
                                   # from data/coaching_and_offense/ (a separate
                                   # Cowork session's v13-v18 research export)
python3 scripts/backfill_vegas_actual_wins.py  # fills in actual_wins/losses/
                                   # ties/over_under_result for any season
                                   # vegas_odds doesn't have a final result
                                   # for yet, from nflverse/nfldata's
                                   # standings.csv
python3 scripts/build_arbitrage_signals.py  # computes the buy-low/sell-high
                                   # signal (dynasty vs. redraft ECR percentile
                                   # gap) from fp_ecr_history into app.db
python3 scripts/load_player_stats.py  # loads season-level fantasy stats +
                                   # draft/birth data (player_stats_season,
                                   # player_bio) -- feeds the models below
python3 scripts/build_bounceback_model.py  # the v7 bounce-back model:
                                   # does a player who fell off Star+ tier
                                   # return to Star+ next season?
python3 scripts/build_breakout_model.py  # the v11 breakout model (4
                                   # per-position logistic regressions):
                                   # does a below-Star player break out?
```

Re-run either script any time to refresh -- both are safe to run repeatedly
(schema creation is idempotent, and data loads upsert rather than duplicate).

## Why two databases instead of one

The operational data (a few thousand rows: players, rosters, current
values) and the analytical data (millions of rows: 25 years of play-by-play,
the full ECR archive) have very different access patterns. SQLite is the
easier target for a web app -- every framework talks to it natively, and it's
plenty fast at this size. DuckDB is built for the big columnar historical
queries the models actually need, and reads CSV/Parquet directly without an
import step.

They're not isolated from each other, though: DuckDB can `ATTACH` the SQLite
file directly and query across both in one statement, e.g.:

```sql
ATTACH 'data/app.db' AS app (TYPE SQLITE);

-- join current roster value (SQLite) against career team-offense quality
-- history (DuckDB) in a single query
SELECT app.players.name, app.trade_values.value_2qb, team_offense_season.epa_per_play
FROM app.roster_players
JOIN app.players       USING (player_id)
JOIN app.trade_values   USING (player_id)
JOIN team_offense_season -- DuckDB's own table
  ON team_offense_season.team = app.players.team
WHERE app.roster_players.roster_id = '9';
```

(The `ATTACH` step needs a one-time internet connection the first time it
runs, to download DuckDB's `sqlite_scanner` extension -- after that it's
cached locally and works offline.)

## What's loaded today vs. what's still a placeholder

Loaded by `build_db.py`:
- `players` -- ~6,500 players, full cross-platform ID crosswalk
- `trade_values` -- current dynasty values (1QB and superflex), snapshotted
  by date
- `fp_ecr_history` (DuckDB) -- the current FantasyPros ECR snapshot across
  ~30 ranking pages

Loaded by `load_nflverse.py` (reachable from this sandbox even though
`api.sleeper.app` and ordinary websites aren't -- it pulls exclusively from
GitHub release assets and raw files):
- `play_by_play` (DuckDB) -- full 1999-2025 nflverse play-by-play,
  ~1.28M rows

Loaded by `load_coaching_and_offense.py`, from `data/coaching_and_offense/`
(the CSV/script trail behind a separate Cowork session's v13-v18
coaching-effects and offense-quality research -- see
`docs/breakout-falloff-methodology.md`):
- `team_offense_season` (DuckDB) -- PPG/YPG/EPA-per-play plus rank and
  percentile within season, 2001-2025 (830 team-seasons)
- `coach_table` (DuckDB) -- HC/OC/DC/position coaches scraped from
  Pro-Football-Reference staff pages, 2001-2025 (5,962 rows)
- `coach_tenure_segments` (DuckDB) -- continuous coach/team tenure ranges,
  every role merged into one span (592 rows)
- `vegas_odds` (DuckDB) -- preseason win-total lines, Super Bowl odds, and
  actual results, 2001-2025 (799 rows). The 2025 season's `actual_wins`/
  `actual_losses`/`actual_ties`/`over_under_result` were still NULL as
  delivered (that research predated the season finishing) --
  `scripts/backfill_vegas_actual_wins.py` fills them in from nflverse/
  nfldata's `standings.csv` without touching the PFR-sourced historical
  rows. Safe to re-run each time a season wraps up.
- `team_primary_qb` (DuckDB) -- ID-based primary starting QB per
  team-season (830 rows)
- `player_offense_rank` (DuckDB) -- per-player-season fantasy performance
  joined to their team's offense-quality rank/percentile (10,079 rows)

These five tables replaced a thinner, `load_nflverse.py`-derived version of
`team_offense_season`/`vegas_odds`/`coach_table` (PPG/YPG/EPA only, HC-only
coaches, no Super Bowl odds) once this richer, PFR-sourced export arrived --
`load_nflverse.py` now only handles `play_by_play`.

Loaded by `build_arbitrage_signals.py` (ported from `pipeline/
build_comparison_model.py`, a prior Cowork session's prototype that computed
the same signal but wrote to a standalone JSON file instead of `app.db`):
- `arbitrage_signals` (SQLite) -- dynasty-vs-redraft ECR percentile gap, per
  player per format (905 player-format rows as of the 2026-08-14 ECR
  snapshot: 52 `BUY_LOW`, 65 `SELL_HIGH`, 788 `FAIR`). **Known limitation**:
  computed from a preseason snapshot, before any 2026 games -- almost every
  signal that fires right now is a rookie/prospect (real dynasty-vs-redraft
  uncertainty) or an aging/deep-bench veteran, not yet a genuine
  performance-vs-price gap. Re-run every few weeks in-season as redraft
  rankings start moving on actual results.

Loaded by `load_player_stats.py`:
- `player_stats_season` (DuckDB) -- season-level fantasy stats (PPR points,
  games, carries/targets/attempts/sacks, rushing/receiving/passing EPA),
  1999-2024. nflverse's `player_stats` release currently lags `play_by_play`
  by about a season -- `build_breakout_model.py` derives the same counting
  stats from `play_by_play` for whichever season(s) aren't here yet (2025,
  as of this writing) rather than lose a season of candidates to the gap.
- `player_bio` (DuckDB) -- birth date, draft year/round/pick, rookie season,
  keyed on `gsis_id` (nflverse's player id -- the same id `play_by_play`,
  `player_stats_season`, and `player_offense_rank` all use).

Loaded by `build_bounceback_model.py` and `build_breakout_model.py` (a
rebuild of the two models in `docs/breakout-falloff-methodology.md`, using
`player_offense_rank`'s tier/PPG data -- 2001-2025, fixed cutoffs recovered
from `data/final_workbooks/Fantasy_Football_PPG_Tiers_2001-2025.xlsx`'s
"Tier Cutoffs" sheet -- plus `player_stats_season`/`player_bio` above):
- `model_predictions` (SQLite) -- `bounceback` v7 (547 fall-off events,
  2001-2025) and `breakout` v11 (4,905 candidate-seasons across QB/RB/WR/TE,
  2001-2025), each with a predicted probability and the actual outcome where
  known. Coefficients and walk-forward backtest AUCs closely track the
  original doc's own numbers (same signs throughout, similar magnitudes) --
  see each script's docstring for the handful of known, documented
  deviations (no confirmed-injury fall-off cases, no ADP feature).
- `model_feature_pool` (DuckDB) -- the exact feature values behind every
  `model_predictions` row, as JSON, for both models.

**v11, not the doc's final v12**, for the breakout model: v12 adds `log_adp`,
built from footballguys.com/FantasyPros scrapes -- ordinary websites this
sandbox's egress policy blocks, the same wall as `api.sleeper.app`. v11 (no
ADP) is the doc's own documented fallback for exactly this situation ("kept
as the baseline/full-coverage view since ~30% of candidates have no ADP
match"). If ADP ever becomes reachable, `log_adp` can be added the same way.

Loaded by `load_sleeper.py` and `load_espn.py` (run separately, needs real
internet -- this can't be tested from inside the cloud sandbox this was
built in, since that sandbox's network specifically blocks `api.sleeper.app`
and `lm-api-reads.fantasy.espn.com`, but both work fine from a normal
machine):
- `leagues`, `rosters`, `roster_players` -- your 5 Sleeper leagues + 2 ESPN
  leagues, `platform` column on `leagues` distinguishing them. Both loaders
  write `sleeper:<id>`/`espn:<id>`-prefixed player ids into `roster_players`
  and then repoint any that resolve to a `players.fantasypros_id` at their
  canonical `player_id` (via `players.sleeper_id`/`players.espn_id`), so
  trade values/arbitrage signals join against both platforms' rosters the
  same way.

**Still not populated -- no reachable source found:**
- `adp_history` (DuckDB) -- the methodology doc's sources (footballguys.com
  2022-2026, FantasyPros 2012-2021) are ordinary websites, not GitHub-hosted,
  and this sandbox's egress policy blocks them the same way it blocks
  `api.sleeper.app`. A few GitHub-hosted ADP mirrors exist (e.g.
  `bendominguez0111/fantasy-csv-data`) but only carry a single current-season
  snapshot, not the 15-year time series the model needs -- not worth loading
  in place of the real thing.

Worth flagging so the web page doesn't silently show stale numbers: check
`sync_log` in `app.db` for when each table was last refreshed.

## Repo layout

```
docs/
  breakout-falloff-methodology.md          -- the statistical model spec (v18)
  sleeper-and-trade-value-pipeline.md       -- Sleeper/trade-value pipeline spec
  local-webapp-and-database-architecture.md -- this two-database architecture
schema/
  sqlite_schema.sql    -- app.db table definitions
  duckdb_schema.sql     -- analytics.duckdb table definitions
scripts/
  build_db.py                     -- creates both DBs, loads dynastyprocess data
  load_sleeper.py                  -- loads your leagues/rosters from Sleeper
  load_espn.py                     -- loads your leagues/rosters from ESPN
  load_nflverse.py                 -- loads play_by_play
  load_coaching_and_offense.py      -- loads coach/offense/vegas-odds tables
                                       from data/coaching_and_offense/
  backfill_vegas_actual_wins.py      -- fills in actual results for any
                                       season vegas_odds doesn't have one
                                       for yet, from nflverse/nfldata
  build_arbitrage_signals.py         -- computes the buy-low/sell-high signal
                                       into app.db's arbitrage_signals table
  load_player_stats.py                -- loads player_stats_season + player_bio
  build_bounceback_model.py            -- rebuilds the v7 bounce-back model
  build_breakout_model.py              -- rebuilds the v11 breakout model
  requirements.txt
data/
  app.db                -- committed
  analytics.duckdb       -- gitignored, regenerate locally (~800MB with full
                            play-by-play history loaded)
  final_workbooks/       -- committed: the 10 Excel deliverables produced
                            across the project to date (human-readable
                            reference, not read by any script)
  coaching_and_offense/   -- committed: CSV/JSON/script trail behind the
                            v13-v18 coaching-effects and offense-quality
                            research -- source data for
                            load_coaching_and_offense.py
  _dynastyprocess_data/  -- gitignored, a working clone build_db.py manages
  _nflverse_data/        -- gitignored: cached play-by-play CSV.gz downloads
                            (~450MB for the full 1999-2025 range) so
                            re-running load_nflverse.py doesn't re-download
                            what it already has
pipeline/
  HANDOFF.md              -- Sleeper/ESPN/Yahoo/FantasyPros API research: what's
                            reachable, auth status, known data-integrity gotchas
  build_crosswalk.py, value_rosters.py       -- Sleeper -> crosswalk -> valued roster
  build_comparison_model.py, trade_signals.py -- the original lightweight buy-low/
                            sell-high signal prototype (dynasty vs. redraft ECR
                            percentile gap) -- ported into
                            scripts/build_arbitrage_signals.py, which writes to
                            app.db instead of a standalone JSON file
  yahoo_pull_example.py    -- Yahoo starter script (yfpy), awaiting API approval
  fantasypros_pull_example.py -- FantasyPros v2 API starter script, needs
                            FANTASYPROS_API_KEY env var, never run against live data
  data/                    -- cached output from the session that produced this
                            (Sleeper league/roster snapshots, crosswalk, signals) --
                            stale the moment real leagues/rosters change; re-run
                            the scripts above rather than trusting these as current
```
