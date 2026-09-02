-- ============================================================================
-- app.db  (SQLite)  --  OPERATIONAL / CURRENT-STATE DATA
-- ============================================================================
-- Holds the data the web page reads and writes directly: who's on which
-- roster right now, current trade values, current buy-low/sell-high signals,
-- and current model predictions. Small, fast-changing, and the natural home
-- for anything a web framework needs to query with plain SQL.
--
-- Bulk historical/analytical data (25 years of play-by-play, full ADP and
-- ECR archives, coaching history) lives instead in analytics.duckdb -- see
-- schema/duckdb_schema.sql. DuckDB can ATTACH this SQLite file directly and
-- join across both without duplicating anything (see scripts/build_db.py).
-- ============================================================================

PRAGMA foreign_keys = ON;

-- Canonical player crosswalk (sleeper_id / espn_id / yahoo_id / mfl_id / fantasypros_id
-- all resolved to one row), sourced from dynastyprocess/data's db_playerids.csv.
CREATE TABLE IF NOT EXISTS players (
    player_id       TEXT PRIMARY KEY,      -- fantasypros_id when available, else 'sleeper:<id>'
    sleeper_id      TEXT,
    espn_id         TEXT,
    yahoo_id        TEXT,
    mfl_id          TEXT,
    fantasypros_id  TEXT,
    gsis_id         TEXT,                  -- nflverse's player id (play_by_play, player_stats_season,
                                            -- player_offense_rank, model_predictions all key on this)
    name            TEXT NOT NULL,
    position        TEXT,
    team            TEXT,
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_players_sleeper ON players(sleeper_id);
CREATE INDEX IF NOT EXISTS idx_players_gsis    ON players(gsis_id);
CREATE INDEX IF NOT EXISTS idx_players_fp      ON players(fantasypros_id);
CREATE INDEX IF NOT EXISTS idx_players_name    ON players(name);

-- Leagues Ian is in. Platform-agnostic (platform defaults to 'sleeper' but this
-- doesn't assume Sleeper forever, in case Yahoo/ESPN leagues get added later).
CREATE TABLE IF NOT EXISTS leagues (
    league_id       TEXT PRIMARY KEY,
    platform        TEXT NOT NULL DEFAULT 'sleeper',
    name            TEXT,
    season          INTEGER,
    format          TEXT,               -- '1QB' or 'SF' (superflex)
    status          TEXT,               -- 'pre_draft' | 'in_season' | 'complete'
    my_roster_id    TEXT,
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Every roster in every league (not just Ian's -- so trade partners' rosters
-- are visible for trade-value comparisons too).
CREATE TABLE IF NOT EXISTS rosters (
    league_id       TEXT NOT NULL REFERENCES leagues(league_id),
    roster_id       TEXT NOT NULL,
    owner_id        TEXT,               -- platform user id
    owner_name      TEXT,
    is_mine         INTEGER DEFAULT 0,
    updated_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (league_id, roster_id)
);

-- Roster <-> player membership, snapshotted by date rather than overwritten in
-- place, so "who did I own on this date" history isn't lost on each refresh.
CREATE TABLE IF NOT EXISTS roster_players (
    league_id       TEXT NOT NULL,
    roster_id       TEXT NOT NULL,
    player_id       TEXT NOT NULL,
    as_of_date      TEXT NOT NULL,
    PRIMARY KEY (league_id, roster_id, player_id, as_of_date)
);
CREATE INDEX IF NOT EXISTS idx_roster_players_date ON roster_players(as_of_date);

-- Dynasty trade values (dynastyprocess/data's values.csv), one row per
-- player-or-pick per snapshot date. Re-running the loader with a new date
-- adds a new snapshot rather than overwriting, so value trends over time.
-- NOTE: player_id and pick_label are NOT NULL (empty string, not NULL, for
-- whichever one doesn't apply to a given row) specifically so the PRIMARY
-- KEY actually dedupes on re-run -- SQLite (like standard SQL) treats every
-- NULL as distinct from every other NULL in a uniqueness check, so a
-- nullable column in a PK silently defeats ON CONFLICT and every re-run
-- just appends duplicate rows instead of updating them in place. (Learned
-- the hard way: the originally-delivered app.db had exactly this bug --
-- every row duplicated 2x from an earlier double-run, invisible until
-- someone went looking for it.)
CREATE TABLE IF NOT EXISTS trade_values (
    player_id       TEXT NOT NULL DEFAULT '',  -- '' when is_pick = 1
    value_date      TEXT NOT NULL,
    value_1qb       REAL,
    value_2qb       REAL,
    ecr_1qb         REAL,
    ecr_2qb         REAL,
    ecr_pos         REAL,
    is_pick         INTEGER DEFAULT 0,
    pick_label      TEXT NOT NULL DEFAULT '',  -- e.g. '2027 1st', '' when is_pick = 0
    source          TEXT DEFAULT 'dynastyprocess',
    PRIMARY KEY (value_date, source, player_id, pick_label)
);
CREATE INDEX IF NOT EXISTS idx_trade_values_date ON trade_values(value_date);

-- Buy-low / sell-high signal: dynasty ECR percentile vs. redraft ECR
-- percentile gap, per the methodology in the project's pipeline doc.
CREATE TABLE IF NOT EXISTS arbitrage_signals (
    player_id           TEXT NOT NULL,
    format               TEXT NOT NULL,     -- '1qb' or 'sf'
    as_of_date           TEXT NOT NULL,
    dynasty_percentile   REAL,
    redraft_percentile   REAL,
    gap                  REAL,
    signal               TEXT,              -- 'BUY_LOW' | 'SELL_HIGH' | 'FAIR'
    PRIMARY KEY (player_id, format, as_of_date)
);

-- Output of the breakout / bounce-back statistical models (see the project's
-- breakout-falloff-methodology doc, currently at v18). One row per player per
-- model version per season being predicted.
CREATE TABLE IF NOT EXISTS model_predictions (
    player_id               TEXT NOT NULL,
    model_name              TEXT NOT NULL,   -- 'breakout' | 'bounceback'
    model_version           TEXT NOT NULL,   -- e.g. 'v12', 'v7'
    season                  INTEGER NOT NULL, -- season being predicted FOR
    predicted_probability   REAL,
    actual_outcome          INTEGER,          -- 1 / 0 / NULL if not yet resolved
    scored_at               TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (player_id, model_name, model_version, season)
);

-- Final season-by-season standings, one row per team per season -- see
-- both load_espn.py's and load_sleeper.py's --history flag (ESPN keeps one
-- league_id across years; Sleeper mints a new one each season and chains
-- them via previous_league_id, but load_sleeper.py stores history under
-- the CURRENT season's league_id either way, since that's the id this
-- league is keyed by everywhere else in app.db). final_rank is a best-effort
-- ranking by (wins desc, points_for desc) computed from the regular-season
-- record, NOT pulled from the platform's own playoff bracket result -- a
-- team that lost in the championship game could still rank #1 here if its
-- regular-season record was better. Good enough for "how has this team
-- done over the years" context, not a substitute for real playoff history.
CREATE TABLE IF NOT EXISTS league_season_standings (
    league_id       TEXT NOT NULL,
    season          INTEGER NOT NULL,
    roster_id       TEXT NOT NULL,
    owner_name      TEXT,
    wins            INTEGER,
    losses          INTEGER,
    ties            INTEGER,
    points_for      REAL,
    points_against  REAL,
    final_rank      INTEGER,
    PRIMARY KEY (league_id, season, roster_id)
);
CREATE INDEX IF NOT EXISTS idx_league_standings_league ON league_season_standings(league_id, season);

-- Site accounts. tier is a strict hierarchy (see app/auth.py's TIER_RANK):
-- 'games' (default on signup -- Games section + leaderboards only),
-- 'fantasy' (also gets rosters/arbitrage/predictions/teams/coaches),
-- 'admin' (also gets user management). New accounts always start at
-- 'games' -- promoting someone to 'fantasy' or 'admin' is an admin-only
-- action (see /admin/users). The very first admin has to be promoted by
-- hand (scripts/promote_user.py) since there's no admin yet to do it
-- through the UI.
--
-- sleeper_owner_id/espn_owner_id link this account to "my team" in
-- rosters.owner_id for that platform -- set via /profile, matched against
-- whatever owner_ids already showed up in rosters from load_sleeper.py/
-- load_espn.py. NULL until the user links an account; roster pages fall
-- back to the league's own my_roster_id (Ian's) until then.
-- favorite_team (an id from app/team_colors.py's TEAMS, e.g. 'kc') +
-- team_colors_enabled drive the Solaris design system's Team Colors
-- feature (see app/team_colors.py) -- re-themes the site's three dynamic
-- accent tokens to the user's chosen NFL team's brand colors when
-- enabled. Off by default; a favorite team can be set without turning
-- colors on (the toggle is independent of the picker, per spec).
CREATE TABLE IF NOT EXISTS users (
    user_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    username            TEXT NOT NULL UNIQUE,
    password_hash       TEXT NOT NULL,
    tier                TEXT NOT NULL DEFAULT 'games',
    sleeper_owner_id    TEXT,
    espn_owner_id       TEXT,
    favorite_team       TEXT,
    team_colors_enabled INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT DEFAULT (datetime('now'))
);

-- NFL Pick'em -- see fantasy-football-db/scripts/load_pickem_schedule.py
-- (pulls the real schedule/spreads/scores from nflverse/nfldata) and
-- webapp/app/routes/pickem.py.
CREATE TABLE IF NOT EXISTS pickem_settings (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    pick_mode           TEXT NOT NULL DEFAULT 'straight_up',  -- 'straight_up' | 'spread'
    confidence_enabled  INTEGER NOT NULL DEFAULT 0
);

-- One row per real NFL game. spread_line follows nfldata's convention:
-- POSITIVE means the home team is favored (e.g. 6.5 = home favored by
-- 6.5) -- verified empirically against ~2,900 real games (2015-2025):
-- spread_line correlates +0.44 with actual home-team margin, not
-- negatively, which is the opposite of the sign convention a couple of
-- other pick'em implementations assume. Don't flip this without
-- re-checking. is_final flips to 1 (and scores get filled in) as the
-- season progresses -- see load_pickem_schedule.py, meant to be re-run
-- periodically during the season.
CREATE TABLE IF NOT EXISTS pickem_games (
    game_id         TEXT PRIMARY KEY,
    season          INTEGER NOT NULL,
    week            INTEGER NOT NULL,
    home_team       TEXT NOT NULL,
    away_team       TEXT NOT NULL,
    kickoff_at      TEXT,
    spread_line     REAL,
    home_score      INTEGER,
    away_score      INTEGER,
    is_final        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pickem_games_week ON pickem_games(season, week);

-- One row per user per game they've picked. Points aren't stored here --
-- standings are computed live from picks + pickem_settings each time
-- they're viewed (see pickem.py's score_pick()), so toggling
-- straight-up/spread or confidence on/off recomputes every standings page
-- immediately instead of needing a re-scoring pass.
CREATE TABLE IF NOT EXISTS pickem_picks (
    user_id         INTEGER NOT NULL REFERENCES users(user_id),
    game_id         TEXT NOT NULL REFERENCES pickem_games(game_id),
    picked_team     TEXT NOT NULL,
    confidence      INTEGER,
    submitted_at    TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, game_id)
);

-- Trivia games -- async, played anytime like Pick'em (not the original
-- spreadsheet's live shared-session/strikes format -- see
-- webapp/app/trivia.py's module docstring). One shared shape covers both
-- Award Winners and Season Leaders (guess-a-name-for-a-clue, scored
-- right/wrong); Fantasy Draft is structurally different (draft slots, not
-- a clue-per-question) and gets its own table below.
--
-- A round snapshots its questions/answers at creation time (item_key,
-- prompt_label, correct_answer) rather than joining live against
-- analytics.duckdb's trivia_award_winners/trivia_season_leaders on every
-- view -- so a past round's history stays exactly as played even if the
-- reference data is ever corrected or reloaded.
CREATE TABLE IF NOT EXISTS trivia_rounds (
    round_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(user_id),
    game_type       TEXT NOT NULL,   -- 'award_winners' | 'season_leaders'
    category        TEXT NOT NULL,   -- e.g. 'MVP', 'Official Sacks Leaders'
    started_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT,
    score           INTEGER,         -- correct count, filled in on submit
    total           INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trivia_rounds_user ON trivia_rounds(user_id, game_type, category);

CREATE TABLE IF NOT EXISTS trivia_round_items (
    round_id        INTEGER NOT NULL REFERENCES trivia_rounds(round_id),
    item_key        TEXT NOT NULL,    -- the year (Award Winners) or rank (Season Leaders), as text
    prompt_label    TEXT NOT NULL,    -- what's shown as the clue
    correct_answer  TEXT NOT NULL,    -- pipe-separated if the item has real tied/co-winners
    guess           TEXT,
    is_correct      INTEGER,
    PRIMARY KEY (round_id, item_key)
);

-- Fantasy Draft (all-time redraft): each user builds one roster by
-- picking a (year, player) for every slot -- independent per user, not a
-- shared draft board, so two users can pick the same year+player without
-- conflict (matches the async-individual-play model everything else
-- here uses; a real shared draft with pick conflicts would need a very
-- different table). points is a snapshot of that player-year's PPR total
-- at pick time, from fantasy_draft_stats -- stable even if that table is
-- ever reloaded/corrected.
CREATE TABLE IF NOT EXISTS fantasy_draft_entries (
    user_id     INTEGER NOT NULL REFERENCES users(user_id),
    slot        TEXT NOT NULL,   -- 'QB','WR1','WR2','RB1','RB2','TE','FLEX1','FLEX2','SUPERFLEX'
    year        INTEGER,
    player      TEXT,
    points      REAL,
    PRIMARY KEY (user_id, slot)
);

-- Freshness tracking, so the web page can show "last updated" per source
-- instead of silently serving stale data.
CREATE TABLE IF NOT EXISTS sync_log (
    table_name      TEXT PRIMARY KEY,
    source          TEXT,
    last_synced_at  TEXT,
    row_count       INTEGER,
    notes           TEXT
);
