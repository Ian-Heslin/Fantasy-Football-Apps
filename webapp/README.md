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

Then open http://127.0.0.1:8000 -- you'll land on `/signup` since every
page now requires an account (see Accounts & tiers below). Sign up, then
promote yourself to admin:

```bash
python3 fantasy-football-db/scripts/promote_user.py <your-username> admin
```

To stop starting this manually every time and instead have it run
persistently on your home network at a friendly hostname, see
`deploy/README.md`.

## Accounts & tiers

Every page requires a logged-in account except `/login` and `/signup`.
Three tiers, strictly nested (`app/auth.py`'s `TIER_RANK`):

- **`games`** -- what self-signup grants automatically. Games section
  (`/games`, Pick'em) and leaderboards only.
- **`fantasy`** -- also gets `/rosters`, `/arbitrage`, `/predictions`,
  `/teams`, `/coaches`. Granted by an admin (`/admin/users`), not
  self-service -- new accounts always start at `games`.
- **`admin`** -- also gets `/admin/users` (change anyone's tier). The very
  first admin has to be promoted by hand (`scripts/promote_user.py`, above)
  since there's no admin yet to do it through the UI.

A page declares its own minimum tier at the router level --
`APIRouter(dependencies=[Depends(require_tier("fantasy"))])` -- rather than
per-route, so a new route file just needs that one line, not a check in
every function. `request.state.user` (a dict, or `None`) is populated for
every request by a global app dependency (`load_current_user`), so any
route or template can read `request.state.user['tier']` without an extra
DB lookup.

**"My team" is per-account, not hardcoded to one person**: `/profile` lets
a user link their account to whichever Sleeper/ESPN owner_id is theirs
(picked from whatever's already showed up in `rosters` -- no live lookup).
`/rosters/{league}` and the trade finder then default to *that* linked
roster instead of the league's own `my_roster_id` (which really just means
"whoever ran `load_sleeper.py`/`load_espn.py` set MY_USER_ID/MY_TEAM_ID to
-- the site owner). Unlinked accounts (including the site owner's, until
they link one too) fall back to that `my_roster_id`/`is_mine` behavior
unchanged.

## Pages

- **`/`** -- data freshness dashboard (reads `sync_log`) and quick counts.
  Fantasy-tier+ only; a `games`-tier user hitting `/` is redirected
  straight to `/games` instead, since this dashboard has nothing for them.
- **`/games`**, **`/games/pickem`**, **`/games/pickem/picks`**,
  **`/games/pickem/standings`** -- NFL Pick'em: pick every game's winner
  (or who covers the spread -- a league-wide, admin-only setting) each
  week, with optional confidence points. Real schedule/spreads/scores come
  from `scripts/load_pickem_schedule.py` (nflverse/nfldata's `games.csv`,
  re-run periodically during the season); picks lock at kickoff. Standings
  (season and week-by-week) are computed live from picks + settings every
  time they're viewed, not stored, so toggling straight-up/spread or
  confidence on/off recomputes everything immediately. A "Daily Trivia"
  card sits alongside Pick'em on `/games` as a placeholder -- not built yet.
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
  main.py            -- creates the FastAPI app, mounts static files, includes routers,
                         wires up SessionMiddleware + load_current_user + the
                         NotAuthenticated/Forbidden exception handlers
  auth.py              -- accounts, sessions, tiers: hash/verify_password, load_current_user,
                         require_tier() (the router-level dependency every protected
                         router uses)
  pickem.py            -- Pick'em scoring (winner/cover/score_pick), standings, and
                         current_season/current_week -- pure functions over DB rows,
                         no FastAPI/route code
  db.py               -- SQLite + DuckDB connection helpers (path resolution, row_factory,
                         duckdb_rows() to give DuckDB's tuples the same dict-style
                         template access as sqlite3.Row)
  common.py            -- shared constants (POSITIONS, SIGNAL_LABELS) and the
                         db_missing_response() helper every route uses
  templating.py         -- the single shared Jinja2Templates instance
  routes/
    auth.py              -- signup/login/logout (no tier requirement -- these are the
                           pages you need to reach without being logged in yet)
    admin.py             -- /admin/users, tier changes (admin-only)
    profile.py           -- link your account to your Sleeper/ESPN team (games-tier+)
    pickem.py            -- /games routes (games-tier+)
    home.py, rosters.py, predictions.py, arbitrage.py, teams.py, coaches.py
                           (fantasy-tier+, except home.py which is games-tier+ but
                           redirects games-tier users to /games)
  templates/             -- one Jinja2 template per page, extending base.html
  static/
    style.css             -- hand-written CSS, no framework
requirements.txt
```

## Not yet built

- The Daily Trivia game -- a placeholder card on `/games`, rules still
  being specced out.
- A dedicated "coach detail" view doesn't yet show `coach_tenure_segments`
  (continuous tenure spans) -- the per-season table on `/coaches/{name}`
  covers the same information less compactly.
- Password reset -- an admin can't currently reset another user's
  password through the UI (would need a direct DB update for now).
