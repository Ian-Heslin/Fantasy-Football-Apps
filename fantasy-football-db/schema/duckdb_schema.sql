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

-- Team-season offensive performance: scoring/yardage/EPA quality, 2000-2025,
-- the "how good was this team's offense" fact table the coaching-effects and
-- QB-elevation analyses join against (methodology doc v15-v18). Sourced from
-- a Claude Cowork session's real v13-v18 coaching/offense research (see
-- scripts/load_coaching_and_offense.py and data/coaching_and_offense/) --
-- this superseded an earlier, thinner version of this table (ppg/ypg/
-- epa_per_play only, derived from nflverse play_by_play by
-- scripts/load_nflverse.py) once the richer export arrived.
CREATE TABLE IF NOT EXISTS team_offense_season (
    season                  INTEGER NOT NULL,
    team                    VARCHAR NOT NULL,
    games                   INTEGER,
    total_points            DOUBLE,
    ppg                     DOUBLE,
    plays                   INTEGER,
    total_epa               DOUBLE,
    mean_epa                DOUBLE,
    total_yards             DOUBLE,
    yards_per_game          DOUBLE,
    epa_per_play             DOUBLE,
    epa_rank                 INTEGER,     -- 1 = best offense that season
    epa_per_play_pctile      DOUBLE,      -- 0-1, 1 = best
    ppg_rank                  INTEGER,
    ppg_pctile                DOUBLE,
    ypg_rank                  INTEGER,
    yards_per_game_pctile     DOUBLE,
    PRIMARY KEY (season, team)
);

-- Coaching staff, normalized (season, team, role) -> coach name. Covers HC,
-- OC, DC, and primary position coaches, scraped from Pro-Football-Reference
-- staff pages (methodology doc v13). No PRIMARY KEY -- a handful of
-- (season, team, role) combos legitimately have more than one row (a
-- mid-season coaching change, or two names scraped for the same staff
-- slot) so the triple isn't guaranteed unique. See coach_tenure_segments
-- below for pre-merged continuous tenure ranges per coach/team.
CREATE TABLE IF NOT EXISTS coach_table (
    season      INTEGER NOT NULL,
    team        VARCHAR NOT NULL,
    role        VARCHAR NOT NULL,     -- 'HC' | 'OC' | 'DC' | 'QB' | 'RB' | 'WR' | 'TE' | 'OL'
    coach_name  VARCHAR NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coach_season_team ON coach_table(season, team);
CREATE INDEX IF NOT EXISTS idx_coach_name ON coach_table(coach_name);

-- Continuous coaching tenure segments per coach/team (every role merged into
-- one span, not broken out by HC/OC/DC) -- avoids re-deriving "which years
-- did this guy coach this team" for the QB-elevation and alumni-effect
-- analyses. Column names "start"/"end" (quoted -- reserved words in SQL)
-- match the source CSV header exactly.
CREATE TABLE IF NOT EXISTS coach_tenure_segments (
    coach       VARCHAR NOT NULL,
    team        VARCHAR NOT NULL,
    "start"     INTEGER NOT NULL,
    "end"       INTEGER NOT NULL,
    n_seasons   INTEGER NOT NULL
);

-- Preseason Vegas win-total lines and Super Bowl odds by team-season
-- (Pro-Football-Reference / sportsoddshistory.com, see methodology doc).
CREATE TABLE IF NOT EXISTS vegas_odds (
    season              INTEGER NOT NULL,
    team                VARCHAR NOT NULL,
    team_name_raw       VARCHAR,
    sb_odds_moneyline   INTEGER,
    sb_implied_prob     DOUBLE,
    win_total_line      DOUBLE,
    actual_wins         DOUBLE,
    actual_losses       DOUBLE,
    actual_ties         DOUBLE,
    over_under_result   VARCHAR,     -- 'over' / 'under' / 'push'
    PRIMARY KEY (season, team)
);

-- ID-based primary starting QB per team-season (more robust than a
-- name-based join -- see methodology doc v16 bugfix note on the
-- alphabetical-attribution bug).
CREATE TABLE IF NOT EXISTS team_primary_qb (
    season          INTEGER NOT NULL,
    team            VARCHAR NOT NULL,
    primary_qb_id   VARCHAR,
    primary_qb_name VARCHAR,
    starts          INTEGER,
    PRIMARY KEY (season, team)
);

-- Per-player-season fantasy performance plus the offense-quality rank/
-- percentile of the team they played for that season -- the table the
-- "does a better offense actually produce more superstar seasons" tests
-- (methodology doc v18) run on.
CREATE TABLE IF NOT EXISTS player_offense_rank (
    season              INTEGER NOT NULL,
    player_id           VARCHAR NOT NULL,
    display_name        VARCHAR,
    position            VARCHAR,
    fantasy_points_ppr  DOUBLE,
    pos_rank            INTEGER,
    top12               BOOLEAN,
    top24               BOOLEAN,
    games_played        DOUBLE,
    ppg                 DOUBLE,
    games_confidence    VARCHAR,
    tier                VARCHAR,
    tier_base           VARCHAR,
    tier_score          INTEGER,
    team                VARCHAR,
    off_epa             DOUBLE,
    off_rank            INTEGER,
    off_pctile          DOUBLE,
    PRIMARY KEY (season, player_id)
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
