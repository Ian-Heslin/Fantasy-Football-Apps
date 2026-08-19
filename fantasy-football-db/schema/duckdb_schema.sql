-- ============================================================================
-- analytics.duckdb  (DuckDB)  --  HISTORICAL / BULK ANALYTICAL DATA
-- ============================================================================
-- Holds the large, slow-changing datasets behind the breakout/fall-off models
-- and the coaching-quality research: 25 years of nflverse play-by-play, the
-- full FantasyPros ECR archive (~1.5M rows), 15 years of ADP, coaching staff
-- history, and Vegas odds. DuckDB is embedded (no server) but built for this
-- kind of columnar, millions-of-rows analytical workload -- SQLite would work
-- but would be noticeably slower for these queries.
--
-- DuckDB can ATTACH the SQLite app.db directly (see scripts/build_db.py for
-- the ATTACH example) so a query can join current roster/trade-value data
-- (SQLite) against historical performance data (DuckDB) in one statement,
-- without copying anything between the two files.
-- ============================================================================

-- Full FantasyPros ECR history (dynastyprocess/data's db_fpecr.csv.gz).
-- Long time series across many ranking pages (dynasty-overall, dynasty-
-- superflex, ppr-cheatsheets, etc.) -- this is what the arbitrage-signal and
-- breakout/bounce-back models are ultimately built from.
CREATE TABLE IF NOT EXISTS fp_ecr_history (
    fp_id           VARCHAR,
    page            VARCHAR,      -- e.g. 'dynasty-overall', 'ppr-cheatsheets'
    player_name     VARCHAR,
    position        VARCHAR,
    rank            INTEGER,
    ecr             DOUBLE,
    rank_delta      DOUBLE,
    scrape_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_ecr_fpid ON fp_ecr_history(fp_id);
CREATE INDEX IF NOT EXISTS idx_ecr_date ON fp_ecr_history(scrape_date);

-- Average Draft Position, 2012-2026 (footballguys.com 2022-2026 +
-- FantasyPros 2012-2021, per the methodology doc's v12 section).
CREATE TABLE IF NOT EXISTS adp_history (
    player_name_norm    VARCHAR,   -- normalized: lowercased, Jr./Sr./II/III stripped
    position             VARCHAR,
    season                INTEGER,
    adp                   DOUBLE,
    source                VARCHAR   -- 'footballguys' | 'fantasypros'
);
CREATE INDEX IF NOT EXISTS idx_adp_name_season ON adp_history(player_name_norm, season);

-- nflverse play-by-play. Loaded per season as needed -- nflverse's real
-- schema is 300+ columns, so rather than hand-maintaining a column list here,
-- load it straight from the nflverse Parquet release with:
--   CREATE TABLE play_by_play AS SELECT * FROM read_parquet('play_by_play_2025.parquet');
-- (DuckDB infers the schema from the file.) This table is intentionally left
-- uncreated by build_db.py -- populate it only for the season(s) a given
-- analysis actually needs, since the full 2001-2025 history is multiple GB.

-- Team-season offensive performance, derived from play_by_play (see the
-- methodology doc's v15 section: PPG / YPG / EPA-per-play, each ranked
-- within its season).
CREATE TABLE IF NOT EXISTS team_offense_season (
    season          INTEGER,
    team            VARCHAR,
    ppg             DOUBLE,
    ypg             DOUBLE,
    epa_per_play    DOUBLE,
    rank_ppg        INTEGER,
    rank_ypg        INTEGER,
    rank_epa        INTEGER,
    PRIMARY KEY (season, team)
);

-- Coaching staff, normalized (season, team, role) -> coach name. Covers HC,
-- OC, DC, and primary position coaches, 2001-2025 (see methodology doc v13).
CREATE TABLE IF NOT EXISTS coach_table (
    season      INTEGER,
    team        VARCHAR,
    role        VARCHAR,      -- 'HC' | 'OC' | 'DC' | 'QB' | 'RB' | 'WR' | 'TE' | 'OL'
    coach_name  VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_coach_season_team ON coach_table(season, team);
CREATE INDEX IF NOT EXISTS idx_coach_name ON coach_table(coach_name);

-- Preseason Vegas win-total lines and Super Bowl odds by team-season
-- (Pro-Football-Reference / sportsoddshistory.com, see methodology doc).
CREATE TABLE IF NOT EXISTS vegas_odds (
    season          INTEGER,
    team            VARCHAR,
    win_total_line  DOUBLE,
    sb_odds         VARCHAR,     -- American moneyline, kept as text (e.g. '+2500')
    actual_wins     INTEGER,
    PRIMARY KEY (season, team)
);

-- Feature pool for the breakout / bounce-back models: one row per
-- player-season candidate event, with the version-specific feature set
-- stored as JSON since the feature list has changed release to release
-- (v6 through v18, see the methodology doc) rather than forcing every
-- version's columns into one rigid schema.
CREATE TABLE IF NOT EXISTS model_feature_pool (
    player_id       VARCHAR,
    season          INTEGER,
    event_type      VARCHAR,     -- 'breakout_candidate' | 'falloff'
    model_version   VARCHAR,     -- e.g. 'v12', 'v7'
    features        JSON,
    outcome         INTEGER      -- 1 / 0 / NULL if unresolved
);
CREATE INDEX IF NOT EXISTS idx_feature_pool_player ON model_feature_pool(player_id, season);
