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

The session cookie is marked `Secure`, so over plain `http://localhost`
the browser will accept it and then never send it back -- you'd sign in
and land straight back on `/login`. For local development, opt out:

```bash
SESSION_INSECURE_COOKIE=1 uvicorn app.main:app --reload
```

Never set that on the Pi -- see `app/main.py`.

To stop starting this manually every time and instead have it run
persistently on your home network at a friendly hostname, see
`deploy/README.md`.

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
python3 -m pytest tests/ -q
```

They run against throwaway in-memory / `tmp_path` databases and never
touch a real `app.db`. Coverage is deliberately narrow -- the rules a
player would notice being wrong, not the route boilerplate:

- `test_pickem.py` -- scoring, the spread-sign convention, when a game
  locks, and the confidence permutation. A game's number and score must
  stop moving the moment it kicks off; several of these are regression
  tests for a bug where they didn't.
- `test_auth.py` -- signup validation, the login throttle, and the
  no-such-user timing path.
- `test_db.py` -- that `PRAGMA foreign_keys` and WAL are actually on for
  every connection, and that a failed paired open leaks nothing.
- `test_routes.py` -- end to end through the real ASGI app, real schema
  and real templates: the auth flow, tier boundaries, and cookie flags.

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

## Design system -- Solaris / Dynasty Desk

Full spec: `docs/solaris-design-spec.md`. Mid-century/solarpunk WPA travel-
poster look -- flat color blocks, bold black borders and rules, no
gradients, no drop shadows, no rounded corners. The whole page sits inside
a black picture-frame border (`.page-frame`/`.page-content` in
`base.html`). Jost (headlines/titles/numbers) + Work Sans (everything
else) via Google Fonts.

Colors are CSS custom properties: fixed neutrals in `style.css`'s `:root`,
plus three **dynamic accent slots** (`--yellow`/`--green`/`--sky`) that
every component consumes through `var(...)` rather than a hardcoded color,
so re-theming the three slots re-themes the whole page with no other
changes needed. That's exactly what **Team Colors** does:

- `/profile` (or the quick toggle+picker in the top bar, every page) lets
  a user pick a favorite NFL team and turn Team Colors on/off
  (`users.favorite_team`/`team_colors_enabled`).
- `app/team_colors.py` resolves the three slots (+ their contrast-safe
  text colors, since badges/icons render text *on* an accent fill and a
  team's colors can be dark where the defaults are always light) from
  whatever's currently logged in -- ported directly from the design
  spec's JS, including the "team has only two brand colors" fallback
  (white or black, whichever contrasts better) and the luminance-based
  text contrast rule.
- `app/auth.py`'s `load_current_user` (a global dependency, runs on every
  request) resolves this into `request.state.colors`; `base.html` writes
  it onto `:root` as an inline `<style>` block in `<head>`, after the main
  stylesheet so it overrides the defaults. Off (or logged out) just
  re-asserts the same defaults already in `style.css` -- harmless either
  way, one code path for both states.
- Turning the toggle off reverts to the defaults immediately even with a
  team still selected; turning it back on re-applies that same team --
  nothing destructive, per spec.

Only the Dashboard (`/`) was actually mocked up in the design spec; every
other page uses the same tokens/components (cards, badges, status dots,
tables, buttons, the toggle switch) for a consistent look, without
necessarily matching a layout the spec never drew.

## Pages

- **`/`** -- data freshness dashboard (reads `sync_log`) and quick counts.
  Fantasy-tier+ only; a `games`-tier user hitting `/` is redirected
  straight to `/games` instead, since this dashboard has nothing for them.

Games live under 4 tabs (`_macros.html`'s `game_tabs(active)` renders the
shared nav; each page passes which tab is active):

- **Leagues** (`/games`, `games_index.html`) -- admin-created,
  shared-standings games. **`/games/pickem`**, **`/games/pickem/picks`**,
  **`/games/pickem/standings`** -- NFL Pick'em: pick every game's winner
  (or who covers the spread -- a league-wide, admin-only setting) each
  week, with optional confidence points. When confidence is on, every
  pick gets a 1..N number automatically (N = that week's game count, most
  confident pick highest); changing one number reorders the rest to keep
  them unique (see `pickem.reorder_confidence`) instead of leaving that to
  manual free-entry. Team logos (nflverse's github-hosted `squared_logos`)
  render next to every team name. Real schedule/spreads/scores come from
  `scripts/load_pickem_schedule.py` (nflverse/nfldata's `games.csv`,
  re-run periodically during the season); picks lock at kickoff. Standings
  (season and week-by-week) are computed live from picks + settings every
  time they're viewed, not stored, so toggling straight-up/spread or
  confidence on/off recomputes everything immediately.
- **Solo** (`/games/solo`) -- individual play, shared leaderboard.
  **`/games/trivia`** -- Award Winners (9 categories: MVP, Super Bowl
  MVP, Coach of the Year, etc.), Season Leaders (all-time Sacks/Points),
  and NFL Top 100 guessing games. Award Winners/Season Leaders are
  one-time exported from a personal spreadsheet (see
  `scripts/load_trivia_data.py`); NFL Top 100 (guess where 10
  randomly-picked players ranked on the NFL's fan-voted annual Top 100
  Players list, one category per year, 2011-2026) is Wikipedia-sourced
  via Claude/Cowork in a browser (`scripts/load_nfl_top100.py` --
  this sandbox can't reach Wikipedia directly). NFL Top 100 has 5
  optional hint toggles, checked when starting a round: Team, Position,
  Side of the ball (Offense/Defense/Special Teams), Years in the league,
  and Season stats (yards/TDs/turnovers for offense; tackles/sacks/PBUs/
  turnovers forced/TDs for defense). All off is the hardest version --
  just the rank. Real per-season stats come from nflverse's
  `player_stats_season` (offense) and `player_stats_def_season` (defense,
  added for this), position/rookie-season from `player_bio` --
  `trivia._top100_enrichment()` loosely matches nfl_top_100's free-text
  names against them (disambiguating same-name players across NFL history
  by whether they were active in that list's year), and the chosen hints
  get baked into the prompt text at round-creation time, same as
  everything else here. Played async/individually, like Pick'em --
  anyone starts a round anytime (a random sample of that
  category's years/ranks), submits guesses, gets scored immediately
  (loose name matching -- case/punctuation/suffix-insensitive), and each
  category has a "best score" leaderboard. `trivia.build_pool()` builds
  the sampled question pool and is shared with Group's reveal engine
  below, so the two never present different questions for the same
  category. **Not** the original spreadsheet's live, shared, host-run
  "strikes" format -- that's Group mode's reveal engine now (see below).
  **`/games/fantasy-draft`** -- draft any player from any NFL season,
  1970-2025, at 9 roster slots (QB/WR/WR/RB/RB/TE/FLEX/FLEX/SUPERFLEX);
  your score is that player's real PPR fantasy total from that exact
  season. 1999 onward comes from `player_season_fantasy_points` --
  computed directly from play-by-play (`scripts/compute_fantasy_points.py`),
  so it live-updates as new weeks get loaded during the season and doesn't
  have the personal spreadsheet's gaps (Rob Gronkowski's 2011 season, e.g.,
  missing from that year's spreadsheet tab entirely, is present here).
  1970-1998 (before nflverse's play-by-play coverage starts) still comes
  from the spreadsheet's `fantasy_draft_stats`. Async/individual -- not a
  shared draft board, so two users can pick the same year+player with no
  conflict. A typed name that doesn't match gets a handful of
  close-spelling suggestions rather than just failing.
- **Daily** (`/games/daily`, `app/daily_challenge.py`) -- two games that
  reset/rotate daily or weekly. **Weekly Top Scorers** -- guess the 15
  highest real PPR scorers from the most recently loaded week (same
  `player_week_fantasy_points` data as Fantasy Draft). Re-running
  `load_nflverse.py` + `compute_fantasy_points.py` during the season moves
  "most recent week" forward automatically. **Daily Stat Pad** (inspired
  by statpadgame.com) -- pick 5 (year, player) pairs to maximize the
  day's stat category (passing yards, rushing TDs, receptions, etc., from
  `player_season_fantasy_points`); the category is auto-picked each day
  via `random.Random(date.isoformat()).choice(...)`, so it's the same
  category for everyone with nothing to persist about "today's pick."
  Shared daily leaderboard, ranked by total across the 5 picks.
- **Group** (`/games/group`, `app/group_games.py` + `app/group_draft.py`)
  -- shared-screen, host-run live sessions: one device (the host's) drives
  the whole thing, everyone else just needs to be in the room. Participants
  are free-text names typed in at session start, not site accounts -- no
  per-device real-time sync in this version (see "Not yet built"). Two
  engines: a **reveal engine** for Award Winners/Season Leaders/NFL Top
  100 (host reads each clue aloud, checks off who got it right, reveals
  the answer, moves to the next item; standings and session-complete are
  computed live; NFL Top 100 sessions get the same 5 hint toggles as
  Solo, checked once when starting the session), and a **live snake
  draft** for Fantasy Draft (host
  enters each pick on the current participant's behalf in standard snake
  turn order -- `group_draft.whose_turn()` -- same real PPR scoring and
  slot/position rules as Solo's Fantasy Draft, with duplicate
  year+player picks rejected).
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
  pickem.py            -- Pick'em scoring (winner/cover/score_pick), standings,
                         current_season/current_week, kickoff locking (is_locked,
                         Eastern-aware), and confidence assignment/reorder
                         (confidence_layout/reorder_confidence) -- pure functions
                         over DB rows, no FastAPI/route code
  trivia.py             -- Award Winners/Season Leaders/NFL Top 100 round sampling
                         (build_pool(), shared with Group's reveal engine),
                         scoring (normalize_name), and leaderboards -- pure functions
  fantasy_draft.py        -- Fantasy Draft slot/position rules, player lookup +
                         close-spelling suggestions, leaderboard -- pure functions
  daily_challenge.py      -- Daily Stat Pad: today's category (deterministic by
                         date), player/season lookup, pick validation + scoring,
                         daily leaderboard -- pure functions
  group_games.py          -- Group mode's reveal engine (Award Winners/Season
                         Leaders/NFL Top 100): session/item/participant state,
                         mark_and_reveal(), standings -- pure functions
  group_draft.py          -- Group mode's live Fantasy Draft: snake turn order
                         (whose_turn()), pick validation, standings -- pure
                         functions, reuses fantasy_draft.py's slot/position rules
  team_colors.py         -- Team Colors: the 32-team color/logo table + resolve()
                         (ported from docs/solaris-design-spec.md's JS) --
                         also pure functions, no FastAPI/route code
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
    pickem.py            -- /games/pickem routes (games-tier+) -- also serves
                           bare /games (games_index, the Leagues tab)
    trivia.py             -- /games/trivia routes (games-tier+, the Solo tab's
                           trivia games)
    fantasy_draft.py        -- /games/fantasy-draft routes (games-tier+, the Solo
                           tab's Fantasy Draft)
    games_hub.py           -- /games/solo, /games/daily routes (games-tier+)
    group.py             -- /games/group routes (games-tier+)
    home.py, rosters.py, predictions.py, arbitrage.py, teams.py, coaches.py
                           (fantasy-tier+, except home.py which is games-tier+ but
                           redirects games-tier users to /games)
  templates/             -- one Jinja2 template per page, extending base.html
  static/
    style.css             -- hand-written CSS, no framework
requirements.txt
```

## Not yet built

- Real-time, per-device sync for Group mode -- each participant on their
  own phone instead of everyone gathered around the host's one screen.
  Deliberately deferred as a separate, bigger future project; this
  version's Group mode is shared-screen/host-run only.
- `fantasy_draft_stats` (the source spreadsheet's per-year tables) has at
  least one confirmed gap -- Rob Gronkowski's 2011 season is missing from
  that year's tab entirely -- a real hole in the source data itself, not a
  load bug. **No longer surfaced in the app**: Fantasy Draft now prefers
  `player_season_fantasy_points` (computed from play-by-play) for any
  season 1999+, which doesn't have this gap; `fantasy_draft_stats` is only
  still used for 1970-1998. Likely similar spreadsheet gaps exist
  uncaught in that pre-1999 range, where there's no play-by-play to
  cross-check against.
- A dedicated "coach detail" view doesn't yet show `coach_tenure_segments`
  (continuous tenure spans) -- the per-season table on `/coaches/{name}`
  covers the same information less compactly.
- Bespoke Solaris layouts for league/roster detail, player detail, and a
  dedicated trade-signals board -- the design spec explicitly only mocked
  up the Dashboard; those pages use the same tokens/components for a
  consistent look, but haven't gotten a from-scratch layout pass.
- Password reset -- an admin can't currently reset another user's
  password through the UI (would need a direct DB update for now).
