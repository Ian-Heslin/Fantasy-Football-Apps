# Fantasy Football web app

A small FastAPI app that reads `fantasy-football-db/data/app.db` (and, for
the team/coach pages, `analytics.duckdb`) directly and renders it as plain
server-side HTML (Jinja2 templates, no build step, no JS framework) -- see
`docs/local-webapp-and-database-architecture.md` for why the data lives in
two databases.

## Setup

```bash
cd fantasy-football-db
pip install -r scripts/requirements.txt
python3 scripts/build_db.py   # creates both DBs if they don't exist yet
# (see fantasy-football-db/README.md for the full data-population setup --
# load_sleeper.py, load_nflverse.py, load_coaching_and_offense.py,
# build_arbitrage_signals.py, build_bounceback_model.py, build_breakout_model.py)

cd ../webapp
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000.

To stop starting this manually every time and instead have it run
persistently on your home network at a friendly hostname, see
`deploy/README.md`.

## Pages

- **`/`** -- data freshness dashboard (reads `sync_log`) and quick counts.
- **`/rosters`** -- your Sleeper and ESPN leagues; click through to any
  team's roster (a picker lets you view league-mates' rosters too, not just
  yours) valued against current dynasty trade values (1QB or superflex,
  matching the league's format) with the buy-low/sell-high arbitrage signal
  shown alongside each player. **`/rosters/{league}/trades`** suggests
  fair-value 1-for-1 trades against a chosen opponent, weighted toward
  moving a Sell High player for a Buy Low one. Empty until
  `scripts/load_sleeper.py`/`scripts/load_espn.py` have been run somewhere
  with real network access to those platforms' APIs.
- **`/arbitrage`** -- every player's buy-low/sell-high signal (dynasty vs.
  redraft ECR percentile gap), not just yours. Filterable by format
  (1QB/superflex), signal, and position.
- **`/predictions`** -- the breakout (v11) and bounce-back (v7) model
  outputs, filterable by season and position. Defaults to the most recent
  season for each model, which is the forward-looking (not-yet-resolved)
  set of predictions.
- **`/teams`**, **`/teams/{team}`** -- team offense quality by season
  (PPG/YPG/EPA-per-play, ranked league-wide) alongside that team-season's
  head coach, primary QB, and Vegas win total/actual wins.
- **`/coaches`**, **`/coaches/{coach_name}`** -- coaches ranked by average
  team offensive EPA/play percentile across their HC/OC seasons, with a
  minimum-seasons filter (defaults to 3+) to keep one-season small-sample
  noise from dominating the list -- see
  `docs/breakout-falloff-methodology.md`'s v13-v18 coaching-effects research
  for why this ranking alone doesn't prove a coaching effect.

`/`, `/rosters`, `/arbitrage`, and `/predictions` read `app.db` only
(`app/db.py`'s `get_connection()`). `/teams` and `/coaches` read
`analytics.duckdb` instead (`get_duckdb_connection()`, opened read-only) --
that's where `team_offense_season`/`coach_table`/`vegas_odds` live. Nothing
in the app tries to `ATTACH` across the two databases from inside a
request; each route just picks whichever connection it needs.

## Layout

```
app/
  main.py            -- creates the FastAPI app, mounts static files, includes routers
  db.py               -- SQLite + DuckDB connection helpers (path resolution, row_factory,
                         duckdb_rows() to give DuckDB's tuples the same dict-style
                         template access as sqlite3.Row)
  common.py            -- shared constants (POSITIONS, SIGNAL_LABELS) and the
                         db_missing_response() helper every route uses
  templating.py         -- the single shared Jinja2Templates instance
  routes/
    home.py, rosters.py, predictions.py, arbitrage.py, teams.py, coaches.py
  templates/             -- one Jinja2 template per page, extending base.html
  static/
    style.css             -- hand-written CSS, no framework
requirements.txt
```

## Not yet built

- Trading/roster editing, auth, or anything beyond read-only display -- this
  is a single-user local tool reading data the scripts already produced.
- A dedicated "coach detail" view doesn't yet show `coach_tenure_segments`
  (continuous tenure spans) -- the per-season table on `/coaches/{name}`
  covers the same information less compactly.
