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
-- breakout/bounce-back models are ultimately built from. One row per
-- player per ranking page per scrape date -- PRIMARY KEY enforces that and
-- lets the loader upsert instead of blindly re-appending the same snapshot
-- every time build_db.py is re-run (this table had exactly that bug: no
-- key at all, so re-running it doubled/tripled the table with zero
-- warning -- caught by comparing row counts before and after a rerun).
CREATE TABLE IF NOT EXISTS fp_ecr_history (
    fp_id           VARCHAR NOT NULL,
    page            VARCHAR NOT NULL,  -- e.g. 'dynasty-overall', 'ppr-cheatsheets'
    player_name     VARCHAR,
    position        VARCHAR,
    rank            INTEGER,
    ecr             DOUBLE,
    rank_delta      DOUBLE,
    scrape_date     DATE NOT NULL,
    PRIMARY KEY (fp_id, page, scrape_date)
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

-- nflverse play-by-play, 1999-2025 (~1.28M rows). nflverse's real schema is
-- 300+ columns, so rather than hand-maintaining a column list here, this
-- table's schema is inferred straight from the source CSVs -- see
-- scripts/load_nflverse.py. Intentionally left uncreated by build_db.py.

-- nflverse's season-level player fantasy stats (fantasy_points_ppr, games,
-- carries/targets/attempts/sacks for touches and dropbacks, rushing_epa/
-- receiving_epa/passing_epa for epa-per-touch) -- the raw ingredient the
-- breakout/fall-off model's per-position feature engineering needs on top
-- of player_offense_rank (which has PPG/tier but not touches/EPA). Same
-- inferred-schema pattern as play_by_play; see scripts/load_player_stats.py.
-- NOTE: as of this writing nflverse's player_stats release lags play_by_play
-- by about a season -- scripts/build_breakout_model.py falls back to
-- deriving the same counting stats from play_by_play for whichever season(s)
-- aren't in this table yet.

-- nflverse player biographical/draft data (birth_date for age, draft_year/
-- round/pick, rookie_season) -- keyed on gsis_id, the same id play_by_play/
-- player_stats_season/player_offense_rank use. See scripts/load_player_stats.py.

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

-- ============================================================================
-- Draft reach analysis (see scripts/load_draft_grades.py, load_draft_picks.py,
-- load_team_executives.py, analyze_draft_reaches.py)
-- ============================================================================

-- Pre-draft evaluation, one row per combine invitee. NOT a multi-analyst
-- "consensus big board" -- no clean historical version of that was
-- reachable/found (see the project chat log) -- this is NFL.com's own
-- prospect grade + Next Gen Stats' draft grade, from
-- github.com/array-carpenter/nfl-draft-data. 2021 has no rows at all (no
-- combine grading that cycle). Matched to draft_picks by name -- no
-- shared ID between the two sources, so the loader's join is fuzzy
-- (normalized name + position) and worth spot-checking.
CREATE TABLE IF NOT EXISTS draft_prospect_grades (
    year                INTEGER NOT NULL,
    player_name         VARCHAR NOT NULL,
    college             VARCHAR,
    position            VARCHAR,
    nfl_grade           DOUBLE,     -- NFL.com prospect grade, ~5.0-8.0 scale
    ngs_draft_grade     DOUBLE,     -- Next Gen Stats draft grade, 0-100 scale
    draft_projection    VARCHAR     -- e.g. "Round 2" -- sparse, don't rely on it alone
);
CREATE INDEX IF NOT EXISTS idx_draft_grades_year ON draft_prospect_grades(year);

-- Actual draft results + career outcomes, from nflverse-data's richer
-- draft_picks release (not nfldata's thinner mirror -- this one has
-- approximate value and Pro Bowl/All-Pro counts, needed to test whether
-- reaches actually underperform).
CREATE TABLE IF NOT EXISTS draft_picks (
    season              INTEGER NOT NULL,
    round               INTEGER,
    pick                INTEGER NOT NULL,
    team                VARCHAR NOT NULL,
    gsis_id             VARCHAR,
    pfr_player_id       VARCHAR,
    player_name         VARCHAR NOT NULL,
    position            VARCHAR,
    college             VARCHAR,
    age                 DOUBLE,
    games               INTEGER,
    allpro              INTEGER,
    probowls            INTEGER,
    seasons_started     INTEGER,
    w_av                DOUBLE,     -- PFR's weighted career Approximate Value (source column
                                    -- named car_av upstream, but is 100% empty there -- confirmed
                                    -- across all ~13k rows -- w_av is what's actually populated)
    PRIMARY KEY (season, pick)
);
CREATE INDEX IF NOT EXISTS idx_draft_picks_season_team ON draft_picks(season, team);

-- Owner + GM per team-season, scraped from Wikipedia's per-team-season
-- articles (e.g. "2023 Arizona Cardinals season") -- see
-- load_team_executives.py's docstring for why this can't be verified from
-- inside this sandbox (Wikipedia is blocked here) and needs spot-checking
-- against a few real pages after running it. HC attribution for the same
-- team-season comes from the existing coach_table -- not duplicated here.
CREATE TABLE IF NOT EXISTS team_executives_season (
    season              INTEGER NOT NULL,
    team                VARCHAR NOT NULL,
    owner               VARCHAR,
    general_manager     VARCHAR,
    source_url          VARCHAR,
    PRIMARY KEY (season, team)
);

-- Trivia game reference/answer data, one-time exported from a personal
-- spreadsheet of games played with friends (see
-- scripts/load_trivia_data.py) -- not re-fetchable from a live source, so
-- the exported CSVs under data/trivia/ are committed directly.

-- Award-winner-by-year guessing game. No PRIMARY KEY on (category, year):
-- several categories have real co-winner years (e.g. 1977 Super Bowl
-- co-MVPs Randy White + Harvey Martin, 1997 MVP co-winners Sanders +
-- Favre) -- confirmed by the source data, not a load bug -- so a guess
-- matching ANY row for that category+year counts as correct.
CREATE TABLE IF NOT EXISTS trivia_award_winners (
    category    VARCHAR NOT NULL,   -- 'MVP', 'Super Bowl MVP', 'Coach of the Year', etc. (9 total)
    year        INTEGER NOT NULL,
    position    VARCHAR,            -- position/'Coach' -- a hint, not used for scoring
    player      VARCHAR NOT NULL,
    team        VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_trivia_award_winners_cat_year ON trivia_award_winners(category, year);

-- All-time-leaderboard-by-rank guessing game (Career Sacks, Career Points
-- so far). team_clue is the team abbreviation shown as a hint (PFR-style
-- codes as-is, e.g. "2TM" for players who spent that career split across
-- multiple teams -- a genuine, intentionally vague clue in the source
-- game, not a code needing normalization here).
CREATE TABLE IF NOT EXISTS trivia_season_leaders (
    category        VARCHAR NOT NULL,   -- 'Points Leaders' | 'Official Sacks Leaders'
    rank            INTEGER NOT NULL,
    player          VARCHAR NOT NULL,
    stat_value      DOUBLE,
    years_active    VARCHAR,
    team_clue       VARCHAR,
    PRIMARY KEY (category, rank)
);

-- Season-level fantasy stats for the "draft any player from any year"
-- redraft game, 1970-2023 -- much further back than player_stats_season
-- (nflverse only goes to 1999), Pro-Football-Reference-sourced. Not
-- deduped across the whole player history -- (year, player, position) is
-- the natural key since the game only ever looks up one specific
-- season's total for one specific player.
CREATE TABLE IF NOT EXISTS fantasy_draft_stats (
    year        INTEGER NOT NULL,
    player      VARCHAR NOT NULL,
    team        VARCHAR,
    position    VARCHAR NOT NULL,
    games       INTEGER,
    fant_pt     DOUBLE,   -- standard scoring
    ppr_pt      DOUBLE,
    PRIMARY KEY (year, player, position)
);
CREATE INDEX IF NOT EXISTS idx_fantasy_draft_stats_year_pos ON fantasy_draft_stats(year, position);

-- Fantasy points computed directly from play_by_play (1999-2025, wherever
-- nflverse's play-by-play covers), via scripts/compute_fantasy_points.py --
-- standard PPR scoring, validated against player_offense_rank's
-- independently-sourced season totals (exact match on 3 of 4 spot-checked
-- seasons; a QB-only case was off by 0.36%, cause not chased down further).
-- Re-running load_nflverse.py then this script picks up newly-played weeks
-- automatically, unlike fantasy_draft_stats (the spreadsheet export,
-- frozen at 1970-2023) -- this is the live-updating source Fantasy Draft
-- prefers for any season it covers (see app/fantasy_draft.py), which also
-- fixes fantasy_draft_stats' one known gap (Rob Gronkowski's 2011 season).
CREATE TABLE IF NOT EXISTS player_week_fantasy_points (
    season      INTEGER NOT NULL,
    week        INTEGER NOT NULL,
    player_id   VARCHAR NOT NULL,   -- nflverse gsis_id
    player      VARCHAR NOT NULL,
    position    VARCHAR,
    team        VARCHAR,
    passing_yards DOUBLE, passing_tds DOUBLE, interceptions DOUBLE,
    rushing_yards DOUBLE, rushing_tds DOUBLE,
    receptions DOUBLE, receiving_yards DOUBLE, receiving_tds DOUBLE,
    fumbles_lost DOUBLE, two_point_conversions DOUBLE,
    fant_pt     DOUBLE,   -- standard scoring
    ppr_pt      DOUBLE,
    PRIMARY KEY (season, week, player_id)
);
CREATE INDEX IF NOT EXISTS idx_pwfp_season_week ON player_week_fantasy_points(season, week);

-- Season totals, aggregated from player_week_fantasy_points by the same
-- script -- what app/fantasy_draft.py actually queries (same shape as
-- fantasy_draft_stats, so the two are interchangeable at read time).
CREATE TABLE IF NOT EXISTS player_season_fantasy_points (
    season      INTEGER NOT NULL,
    player_id   VARCHAR NOT NULL,
    player      VARCHAR NOT NULL,
    position    VARCHAR,
    team        VARCHAR,     -- most common team that season (mode across weeks)
    games       INTEGER,
    fant_pt     DOUBLE,
    ppr_pt      DOUBLE,
    PRIMARY KEY (season, player_id)
);
CREATE INDEX IF NOT EXISTS idx_psfp_season_pos ON player_season_fantasy_points(season, position);

-- "Guess the rank" version of the NFL Network's fan-voted annual Top 100
-- list -- a real, separate game from Award Winners (see
-- load_nfl_top100.py's docstring for why this needs a Wikipedia scraper
-- like team_executives_season, and is unverified from this sandbox).
CREATE TABLE IF NOT EXISTS nfl_top_100 (
    year        INTEGER NOT NULL,
    rank        INTEGER NOT NULL,   -- 1 = best
    player      VARCHAR NOT NULL,
    team        VARCHAR,
    source_url  VARCHAR,
    PRIMARY KEY (year, rank)
);
