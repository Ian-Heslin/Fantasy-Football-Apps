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

Loaded by `build_db.py` right now:
- `players` -- ~6,500 players, full cross-platform ID crosswalk
- `trade_values` -- current dynasty values (1QB and superflex), snapshotted
  by date
- `fp_ecr_history` (DuckDB) -- the current FantasyPros ECR snapshot across
  ~30 ranking pages

Loaded by `load_sleeper.py` (run separately, needs real internet -- this
can't be tested from inside the cloud sandbox this was built in, since that
sandbox's network specifically blocks `api.sleeper.app`, but it should work
fine from a normal machine):
- `leagues`, `rosters`, `roster_players` -- your 5 Sleeper leagues

Schema exists but **not yet populated** (per the project's methodology doc,
rebuilding these fully is a multi-session undertaking -- re-pulling 25 years
of nflverse play-by-play and re-deriving the breakout/fall-off model's
features from scratch):
- `play_by_play`, `team_offense_season`, `coach_table`, `vegas_odds`,
  `adp_history`, `model_feature_pool` (DuckDB)
- `arbitrage_signals`, `model_predictions` (SQLite -- these get populated by
  a signal-computation script, not written yet)

Worth flagging so the web page doesn't silently show stale numbers: check
`sync_log` in `app.db` for when each table was last refreshed.

## Repo layout

```
schema/
  sqlite_schema.sql    -- app.db table definitions
  duckdb_schema.sql     -- analytics.duckdb table definitions
scripts/
  build_db.py           -- creates both DBs, loads dynastyprocess data
  load_sleeper.py        -- loads your leagues/rosters from Sleeper
  requirements.txt
data/
  app.db                -- committed
  analytics.duckdb       -- gitignored, regenerate locally
  _dynastyprocess_data/  -- gitignored, a working clone build_db.py manages
```
