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
python3 scripts/load_nflverse.py  # loads 1999-2025 play-by-play (defaults to
                                   # the full range; pass --start/--end for a
                                   # smaller window)
python3 scripts/load_coaching_and_offense.py  # loads coach_table/team_offense_
                                   # season/vegas_odds/team_primary_qb/
                                   # player_offense_rank/coach_tenure_segments
                                   # from data/coaching_and_offense/ (a separate
                                   # Cowork session's v13-v18 research export)
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
  actual results, 2001-2025 (799 rows)
- `team_primary_qb` (DuckDB) -- ID-based primary starting QB per
  team-season (830 rows)
- `player_offense_rank` (DuckDB) -- per-player-season fantasy performance
  joined to their team's offense-quality rank/percentile (10,079 rows)

These five tables replaced a thinner, `load_nflverse.py`-derived version of
`team_offense_season`/`vegas_odds`/`coach_table` (PPG/YPG/EPA only, HC-only
coaches, no Super Bowl odds) once this richer, PFR-sourced export arrived --
`load_nflverse.py` now only handles `play_by_play`.

Loaded by `load_sleeper.py` (run separately, needs real internet -- this
can't be tested from inside the cloud sandbox this was built in, since that
sandbox's network specifically blocks `api.sleeper.app`, but it should work
fine from a normal machine):
- `leagues`, `rosters`, `roster_players` -- your 5 Sleeper leagues

**Still not populated -- no reachable source found:**
- `adp_history` (DuckDB) -- the methodology doc's sources (footballguys.com
  2022-2026, FantasyPros 2012-2021) are ordinary websites, not GitHub-hosted,
  and this sandbox's egress policy blocks them the same way it blocks
  `api.sleeper.app`. A few GitHub-hosted ADP mirrors exist (e.g.
  `bendominguez0111/fantasy-csv-data`) but only carry a single current-season
  snapshot, not the 15-year time series the model needs -- not worth loading
  in place of the real thing.
- `model_feature_pool` (DuckDB) -- this is the breakout/bounce-back model's
  own output, not raw data; it gets populated once that model is built.
- `arbitrage_signals`, `model_predictions` (SQLite) -- populated by a
  signal-computation script, not written yet. See `pipeline/` below --
  `build_comparison_model.py`/`trade_signals.py` already implement a
  lightweight version of this signal against Sleeper rosters; porting that
  logic to write into `app.db`'s `arbitrage_signals` table is the natural
  next step.

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
  load_nflverse.py                 -- loads play_by_play
  load_coaching_and_offense.py      -- loads coach/offense/vegas-odds tables
                                       from data/coaching_and_offense/
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
  build_comparison_model.py, trade_signals.py -- the lightweight buy-low/sell-high
                            signal (dynasty vs. redraft ECR percentile gap) --
                            not yet wired into app.db's arbitrage_signals table
  yahoo_pull_example.py    -- Yahoo starter script (yfpy), awaiting API approval
  fantasypros_pull_example.py -- FantasyPros v2 API starter script, needs
                            FANTASYPROS_API_KEY env var, never run against live data
  data/                    -- cached output from the session that produced this
                            (Sleeper league/roster snapshots, crosswalk, signals) --
                            stale the moment real leagues/rosters change; re-run
                            the scripts above rather than trusting these as current
```
