# Fantasy Football Apps -- standing context

Personal project for Ian Heslin: a two-database data layer plus a FastAPI
web app, deployed persistently on a Raspberry Pi and reachable at
`https://solarisfantasyfootball.com`. This file is what a fresh session
should read first -- it's the durable memory across sessions; the
`README.md` in each subdirectory has the full detail behind everything
summarized here.

## Repo layout

- `fantasy-football-db/` -- the data layer (SQLite `app.db` + DuckDB
  `analytics.duckdb`), load scripts, and ad-hoc research. See its
  `README.md` for setup, what's loaded vs. still a placeholder, and the
  full repo layout.
- `webapp/` -- the FastAPI + Jinja2 web app. See its `README.md` for
  pages, accounts/tiers, the design system, and deploy notes.

## The one hard rule: never lose Pick'em history

`app.db` holds live, continuously-written user data (accounts, Pick'em
picks, trivia rounds, Fantasy Draft rosters) with no other source of
truth. It is **gitignored, not git-tracked** -- committing it was a real
data-loss risk (a future commit changing its tracked content would have
either hard-failed every future `git pull` on the Pi, or silently
overwritten real user data), fixed by untracking it and building an
independent hourly backup system instead (`scripts/backup_app_db.py` +
`app-db-backup.timer` on the Pi, see `webapp/deploy/README.md`'s Backups
section). Never suggest re-tracking `app.db` in git. Backups currently
live on the same SD card as the original -- known gap, accepted until a
NAS is set up.

## Two-database architecture

SQLite (`app.db`) is small/operational: users, leagues/rosters, trade
values, arbitrage signals, Pick'em/trivia/Fantasy-Draft game state.
DuckDB (`analytics.duckdb`) is the big historical/analytical store: full
play-by-play back to 1999, draft data, coaching/offense research, trivia
reference data. Routes pick whichever connection they need
(`app/db.py`'s `get_connection()`/`get_duckdb_connection()`); nothing
`ATTACH`es across them from inside a request. Full rationale in
`fantasy-football-db/docs/local-webapp-and-database-architecture.md`.

## Deployment

Raspberry Pi (Debian 13 trixie, aarch64, already running Homebridge),
system user `fantasyapp` owns `/opt/fantasy-football-apps` (repo +
venv), systemd units for the app and the Cloudflare named tunnel (real
domain, not a rate-limited quick tunnel), plus the hourly backup timer.
SSH to the Pi as `hestia` (sudo), git operations against the repo need
`sudo -u fantasyapp` (it owns the files) with its own SSH key (not
`hestia`'s -- sudo doesn't inherit another user's agent/keys). Full
walkthrough, including the DNS/tunnel setup and known gotchas (sudo +
shell redirects don't inherit privileges; write to `/tmp` then `sudo
mv`), in `webapp/deploy/README.md`.

## Accounts & tiers

Self-signup, three tiers strictly nested (`games < fantasy < admin`),
`games` is the signup default. First admin via
`fantasy-football-db/scripts/promote_user.py <username> admin`; after
that, `/admin/users` in the UI. Session cookie only stores `user_id` --
tier is read fresh from the DB every request, so a promotion takes effect
immediately, no re-login needed.

## Games built so far (all async/individual play, not live/shared sessions)

- **Pick'em** (`/games/pickem`) -- real schedule/spreads/scores, optional
  confidence points (auto-assigned N..1, reorders automatically when one
  pick's number changes -- see `app/pickem.py`'s `reorder_confidence`),
  team logos.
- **Award Winners / Season Leaders / Weekly Top Scorers / NFL Top 100
  trivia** (`/games/trivia`) -- guess-a-name-for-a-clue games, one-time
  spreadsheet export (Award Winners/Season Leaders), live play-by-play-
  computed data (Weekly Top Scorers), and Wikipedia-via-Cowork data (NFL
  Top 100). Loose name matching (case/punctuation/suffix-insensitive),
  real co-winner years handled correctly.
- **Fantasy Draft** (`/games/fantasy-draft`) -- draft any player from any
  season 1970-2025 at 9 roster slots, scored by real PPR points. 1999+
  comes from `player_season_fantasy_points` (computed from play_by_play,
  live-updating -- re-run `load_nflverse.py` then
  `scripts/compute_fantasy_points.py` to pick up new weeks during the
  season); 1970-1998 still comes from the one-time spreadsheet export.

**Explicitly not built yet**, by the user's own choice or a real
blocker -- don't reintroduce without checking first:
- A live, shared, host-run "strikes" version of the trivia games (the
  original spreadsheet's format) -- async/individual was the deliberate
  simpler-first choice.
- Timeline (order personal in-joke events chronologically) -- no real
  dates for the events yet, explicitly deferred.
- "Daily Trivia" -- a placeholder card on `/games`, a different game,
  rules not specced.

**Resolved via Cowork** (Wikipedia-sourced data fetched in a browser,
since this sandbox can't reach Wikipedia directly): `nfl_top_100` (the
NFL's annual Top 100 Players list) and `team_executives_season`
(owner/GM/HC per team-season, 1898-2026) are both loaded from committed
CSVs (`load_nfl_top100.py`, `load_team_executives.py`). GM-level draft-
reach attribution now exists alongside the HC-level analysis in
`analyze_draft_reaches.py` (`draft_reach_by_gm.csv`). The NFL Top 100
game itself is built (`/games/trivia`, game_type `nfl_top100`).

## Data source conventions (matters when adding new data)

From the dev sandbox: `github.com`/`raw.githubusercontent.com` and
GitHub release assets are reachable; ordinary websites are not
(Wikipedia, ESPN, Pro-Football-Reference, `api.sleeper.app`,
`lm-api-reads.fantasy.espn.com` all confirmed blocked). Prefer
nflverse/nfldata's GitHub-hosted CSVs over anything else. If a source is
genuinely only reachable as an ordinary website, write the script anyway
(same shape as everything else here) but expect to hand it to the user
to run locally or via Claude in Chrome -- don't guess at a page's exact
structure without a way to verify it; say so plainly in the script's
docstring and in chat.

## Design system

"Solaris -- Dynasty Desk": Jost + Work Sans, oklch-based dynamic accent
tokens resolved server-side per request, Team Colors (a user's favorite
team's brand colors can replace the default accents). Full spec in
`webapp/docs/solaris-design-spec.md`, mechanism in `webapp/README.md`.

## Working conventions

- Test against a disposable seeded user/data in the local dev DB before
  trusting a change -- clean it up afterward, never leave test data in
  a committed DB or leak it into `app.db` on the Pi.
- The sandbox's `app.db`/`analytics.duckdb` are separate from the Pi's
  real ones -- schema changes need `apply_schema`/manual `ALTER`/re-run
  of the relevant load script on both independently.
- This branch (`claude/hello-world-doc-lq2m27`) gets pushed to from both
  this kind of session and the Pi directly -- expect the occasional
  divergent-branch push rejection; `git pull --no-rebase` (not rebase,
  not force) to reconcile, per the project's established safe pattern.
- Commit messages should explain *why*, not just what changed -- this
  project spans many sessions and the git history is a real part of its
  documentation.
