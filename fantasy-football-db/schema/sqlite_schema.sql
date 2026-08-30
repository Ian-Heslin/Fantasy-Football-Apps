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

-- Final season-by-season standings, one row per team per season, for
-- leagues whose platform exposes real season history (currently ESPN --
-- see scripts/load_espn.py's --history flag). final_rank is a best-effort
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

-- Freshness tracking, so the web page can show "last updated" per source
-- instead of silently serving stale data.
CREATE TABLE IF NOT EXISTS sync_log (
    table_name      TEXT PRIMARY KEY,
    source          TEXT,
    last_synced_at  TEXT,
    row_count       INTEGER,
    notes           TEXT
);
