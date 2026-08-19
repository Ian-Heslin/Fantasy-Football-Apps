# Local web app + database architecture

Ian is building a locally-run web page (repo: his personal GitHub "Fantasy
Football Apps") to replace the Excel workbook this project had been writing
to, and to surface everything from the Sleeper pipeline and the
breakout/fall-off model in one place.

## Decision: SQLite + DuckDB, not one database
- **`app.db` (SQLite)** -- operational/current-state data the web page reads
  directly: player crosswalk, leagues/rosters, current trade values,
  buy-low/sell-high signals, model predictions. Small (~1-2MB), fits every
  web framework natively, and is **committed to the repo** on purpose so
  roster/value snapshot history persists across machines/sessions.
- **`analytics.duckdb` (DuckDB)** -- the large historical data behind the
  models: nflverse play-by-play, full FantasyPros ECR archive, ADP history,
  coaching data, Vegas odds. Embedded, no server, but built for
  millions-of-rows columnar queries. Gitignored -- regenerated from source.
- DuckDB can `ATTACH` the SQLite file directly (`ATTACH 'app.db' AS app
  (TYPE SQLITE)`) and join across both in one query without duplicating data.
  This needs one-time internet access to download DuckDB's `sqlite_scanner`
  extension (blocked in this cloud sandbox's network specifically -- 403 from
  extensions.duckdb.org -- but should work on Ian's own machine).

## What was delivered (as a zip via SendUserFile, not pushed to GitHub --
no repo access/auth available from this session)
- `schema/sqlite_schema.sql`, `schema/duckdb_schema.sql` -- full table
  definitions for both databases, including tables that exist but aren't
  populated yet (play_by_play, team_offense_season, coach_table, vegas_odds,
  adp_history, model_feature_pool, arbitrage_signals, model_predictions).
- `scripts/build_db.py` -- creates both DBs from the schema files, clones
  dynastyprocess/data, loads the player crosswalk (db_playerids.csv, 6,568
  players after de-duping/cleaning "NA" string values) and current dynasty
  trade values (values.csv, snapshotted by date, including draft picks) into
  SQLite, and the full current FantasyPros ECR snapshot (db_fpecr_latest.csv,
  5,849 rows across ~30 ranking pages) into DuckDB. Tested end-to-end in this
  session, runs clean.
- `scripts/load_sleeper.py` -- pulls Ian's 5 known Sleeper leagues (IDs
  hardcoded from the pipeline doc) via the public Sleeper API using plain
  `requests`, loads leagues/rosters/roster_players into SQLite, then remaps
  roster player IDs from raw `sleeper:<id>` to the canonical
  crosswalk/fantasypros ID so rosters join cleanly against trade_values.
  **Not run/tested this session** -- api.sleeper.app is blocked from this
  sandbox's network (same restriction noted in the pipeline doc), confirmed
  again here (ProxyError). Should work fine run from a normal machine; syntax
  was verified and logic follows the same join pattern already validated in
  earlier Sleeper pulls.
- `README.md` -- setup instructions, the two-database rationale, an ATTACH
  query example, and an honest "loaded now vs. still a schema-only
  placeholder" list.

## Still open / next steps
- `load_sleeper.py` needs a real run (on Ian's machine or wherever the app
  ends up hosted) to confirm it against live data -- not yet verified beyond
  syntax check.
- No script yet computes `arbitrage_signals` (the buy-low/sell-high gap logic
  from the pipeline doc) into the new schema -- that logic currently only
  exists as the older session-local `build_comparison_model.py`/
  `trade_signals.py` described in the pipeline doc. Porting that into a
  script that writes to `arbitrage_signals` in app.db is a natural next step.
- No script populates DuckDB's historical tables (play_by_play,
  team_offense_season, coach_table, vegas_odds, adp_history) -- per the
  methodology doc, a full rebuild of those is a multi-session undertaking.
  Schema is ready for it whenever that's tackled. **This export's
  `database/` folder adds a starting schema + loader for exactly the
  coach_table and team_offense_season pieces**, built from this session's
  actual output files, so that gap is now partly closed -- see
  `database/README.md` in this zip.
- The actual web page/app (Flask, FastAPI, Node, whatever Ian picks) hasn't
  been started -- this session only built the data layer underneath it, per
  Ian's explicit request to start with "a schema and start script."
- Files were handed to Ian as a zip via SendUserFile, not committed to his
  GitHub repo directly -- this session has no GitHub auth/repo access. He'll
  need to unzip into his "Fantasy Football Apps" repo and commit it himself
  (or share repo access with a future session if he wants that automated).
