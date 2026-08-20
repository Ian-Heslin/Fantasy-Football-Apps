# Fantasy Football web app

A small FastAPI app that reads `fantasy-football-db/data/app.db` directly
and renders it as plain server-side HTML (Jinja2 templates, no build step,
no JS framework) -- see `docs/local-webapp-and-database-architecture.md`
for why the data lives in two databases and why this app only needs the
SQLite one.

## Setup

```bash
cd fantasy-football-db
pip install -r scripts/requirements.txt
python3 scripts/build_db.py   # creates app.db if it doesn't exist yet
# (see fantasy-football-db/README.md for the full data-population setup --
# load_sleeper.py, load_nflverse.py, load_coaching_and_offense.py,
# build_arbitrage_signals.py, build_bounceback_model.py, build_breakout_model.py)

cd ../webapp
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000.

## Pages (v1)

- **`/`** -- data freshness dashboard (reads `sync_log`) and quick counts.
- **`/rosters`** -- your Sleeper leagues; click through to a roster valued
  against current dynasty trade values (1QB or superflex, matching the
  league's format) with the buy-low/sell-high arbitrage signal shown
  alongside each player. Empty until `scripts/load_sleeper.py` has been run
  somewhere with real network access to Sleeper's API.
- **`/predictions`** -- the breakout (v11) and bounce-back (v7) model
  outputs, filterable by season and position. Defaults to the most recent
  season for each model, which is the forward-looking (not-yet-resolved)
  set of predictions.

Nothing here queries `analytics.duckdb` directly -- every table the app
reads (`players`, `trade_values`, `leagues`/`rosters`/`roster_players`,
`arbitrage_signals`, `model_predictions`) already lives in `app.db`, kept
current by the scripts in `fantasy-football-db/scripts/`. If a future page
needs the big historical DuckDB tables (`team_offense_season`,
`coach_table`, `play_by_play`, etc.), add a `duckdb.connect(..., read_only=True)`
helper alongside `app/db.py`'s SQLite one rather than trying to `ATTACH`
across the two from inside the app.

## Layout

```
app/
  main.py        -- FastAPI app + all routes
  db.py           -- SQLite connection helper (path resolution, row_factory)
  templates/       -- Jinja2 templates (base.html + one per page)
  static/
    style.css       -- hand-written CSS, no framework
requirements.txt
```

## Not yet built

- Arbitrage-signals board (a dedicated page browsing every player's
  buy-low/sell-high signal, not just yours) -- deferred out of v1 scope.
  The signal itself is already shown inline on the roster page.
- Team/coach/offense-quality reference pages (`team_offense_season`,
  `coach_table`, `vegas_odds`) -- deferred out of v1 scope; would need a
  DuckDB connection alongside the SQLite one (see above).
- Trading/roster editing, auth, or anything beyond read-only display -- this
  is a single-user local tool reading data the scripts already produced.
