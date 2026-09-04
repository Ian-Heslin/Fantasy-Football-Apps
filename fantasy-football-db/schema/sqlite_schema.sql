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

-- NOTE: foreign_keys is a PER-CONNECTION setting that defaults to OFF and
-- is NOT stored in the database file. This line therefore applies only to
-- the connection that runs this schema (build_db.py's). Every other
-- connection has to turn it on for itself or the REFERENCES clauses below
-- are decorative -- see app/db.py's get_connection(), which does.
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

-- Daily Stat Pad (see app/daily_challenge.py): pick 5 distinct players +
-- seasons to maximize one stat category, a new category each day
-- (deterministic from the date -- not stored here, recomputed from
-- challenge_date so there's one less thing that could drift out of sync).
-- Leaderboard is naturally per-day since challenge_date is part of the key.
CREATE TABLE IF NOT EXISTS daily_challenge_entries (
    user_id         INTEGER NOT NULL REFERENCES users(user_id),
    challenge_date  TEXT NOT NULL,   -- 'YYYY-MM-DD'
    pick_num        INTEGER NOT NULL,   -- 1..5
    year            INTEGER,
    player          TEXT,
    stat_value      REAL,
    PRIMARY KEY (user_id, challenge_date, pick_num)
);

-- Group games: shared-screen, host-run live sessions (see app/group_games.py
-- and app/group_draft.py) -- one browser (the host's) drives the whole
-- session; participants are free-text names, not site accounts, since
-- everyone's in the same room and only the host needs to be logged in.
-- Two shapes: reveal-style trivia (group_items/group_answers) and a live
-- Fantasy Draft (group_draft_picks) -- a session is one or the other,
-- never both, selected by game_type.
CREATE TABLE IF NOT EXISTS group_sessions (
    session_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    host_user_id    INTEGER NOT NULL REFERENCES users(user_id),
    game_type       TEXT NOT NULL,   -- 'award_winners' | 'season_leaders' | 'nfl_top100' | 'fantasy_draft'
    category        TEXT,             -- the trivia category; NULL for fantasy_draft
    status          TEXT NOT NULL DEFAULT 'active',   -- 'active' | 'completed'
    turn_index      INTEGER NOT NULL DEFAULT 0,   -- fantasy_draft only: whose overall pick # is next
    created_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS group_participants (
    session_id      INTEGER NOT NULL REFERENCES group_sessions(session_id),
    participant_id  INTEGER NOT NULL,   -- 1..N within this session, not a user_id
    name            TEXT NOT NULL,
    PRIMARY KEY (session_id, participant_id)
);

-- reveal-style trivia sessions only -- snapshotted at session-creation
-- time, same reasoning as trivia_round_items.
CREATE TABLE IF NOT EXISTS group_items (
    session_id      INTEGER NOT NULL REFERENCES group_sessions(session_id),
    item_key        TEXT NOT NULL,
    sort_order      INTEGER NOT NULL,   -- explicit presentation order, not relying on insertion order
    prompt_label    TEXT NOT NULL,
    correct_answer  TEXT NOT NULL,
    revealed        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, item_key)
);

CREATE TABLE IF NOT EXISTS group_answers (
    session_id      INTEGER NOT NULL,
    item_key        TEXT NOT NULL,
    participant_id  INTEGER NOT NULL,
    is_correct      INTEGER,   -- NULL until the host marks it
    PRIMARY KEY (session_id, item_key, participant_id)
);

-- live Fantasy Draft sessions only -- same 9 slots as the solo version,
-- but with real draft-conflict enforcement across participants within
-- one session (see app/group_draft.py), unlike the solo game.
CREATE TABLE IF NOT EXISTS group_draft_picks (
    session_id      INTEGER NOT NULL REFERENCES group_sessions(session_id),
    participant_id  INTEGER NOT NULL,
    slot            TEXT NOT NULL,
    year            INTEGER,
    player          TEXT,
    points          REAL,
    pick_order      INTEGER,   -- overall pick number (1-based), for the draft-board display
    PRIMARY KEY (session_id, participant_id, slot)
);

-- 501 (see app/five_oh_one.py): pick a stat category, get a starting
-- value, then guess 5 distinct (player, year) pairs one at a time trying
-- to land the running total as close to 0 as possible. Rounds/picks
-- snapshotted the same way trivia_rounds/trivia_round_items are.
CREATE TABLE IF NOT EXISTS five_oh_one_games (
    game_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(user_id),
    category        TEXT NOT NULL,
    start_value     REAL NOT NULL,
    remaining       REAL NOT NULL,
    picks_made      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_501_games_user_cat ON five_oh_one_games(user_id, category);

CREATE TABLE IF NOT EXISTS five_oh_one_picks (
    game_id         INTEGER NOT NULL REFERENCES five_oh_one_games(game_id),
    pick_num        INTEGER NOT NULL,   -- 1..5
    player          TEXT NOT NULL,
    year            INTEGER NOT NULL,
    stat_value      REAL NOT NULL,
    remaining_after REAL NOT NULL,
    PRIMARY KEY (game_id, pick_num)
);

-- Imposter (see app/imposter.py): a random year+stat shows 10 names -- 9
-- from that season's real top 10, 1 from rank 11-20 -- and the player
-- clicks names one at a time trying to avoid the imposter. Names are
-- snapshotted at round-creation time (same reasoning as everywhere else
-- here): if the underlying nflverse data is later corrected, a round
-- already in progress or finished keeps showing exactly what it asked.
CREATE TABLE IF NOT EXISTS imposter_rounds (
    round_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(user_id),
    year            INTEGER NOT NULL,
    category        TEXT NOT NULL,
    imposter_name   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',   -- 'active' | 'won' | 'lost'
    correct_count   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS imposter_round_names (
    round_id        INTEGER NOT NULL REFERENCES imposter_rounds(round_id),
    name            TEXT NOT NULL,
    is_top10        INTEGER NOT NULL,
    clicked         INTEGER NOT NULL DEFAULT 0,
    display_order   INTEGER NOT NULL,
    PRIMARY KEY (round_id, name)
);

-- Per-user difficulty filter (see app/routes/game_settings.py): narrows
-- the year range and which stat categories can come up for Imposter's
-- random picker and the 501/Imposter category menus. NULL/empty means
-- "no restriction" -- everything's in play, the default for a new user.
CREATE TABLE IF NOT EXISTS game_settings (
    user_id             INTEGER PRIMARY KEY REFERENCES users(user_id),
    min_year            INTEGER,
    max_year            INTEGER,
    enabled_categories  TEXT   -- comma-separated stat_categories.py keys, NULL = all enabled
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

-- ============================================================================
-- POKEMON DRAFT LEAGUE
-- ============================================================================
-- A separate fantasy-style domain (draft real Pokemon on a point budget,
-- play weekly Bo3 matches, track kills/deaths, standings, playoffs) that
-- replaces a set of Excel workbooks. Reuses the `users` table/tier system
-- above (every self-signup account gets `games` tier, the minimum this
-- whole feature needs) rather than inventing separate accounts -- see
-- webapp/app/pokemon_draft/permissions.py for the season-scoped
-- "commissioner" role layered on top, which is NOT a site-wide tier.
-- All new tables are `pokemon_`-prefixed, matching this file's existing
-- per-feature namespacing (pickem_*, trivia_*, group_*).

-- Static reference data, seeded once (and re-run per new generation
-- release) by fantasy-football-db/scripts/load_pokemon_pokedex.py from
-- PokeAPI's bulk static dump -- never written to by the running app.
-- Modeled at PokeAPI's *form* level (pokemon_id), not species level:
-- Landorus-Therian and Landorus-Incarnate are separate rows here since a
-- draft picks a specific form, but species_id (shared across every form of
-- one dex entry) is carried as its own column because species-clause
-- enforcement checks THAT, not pokemon_id -- see pokemon_draft/draft.py.
CREATE TABLE IF NOT EXISTS pokemon (
    pokemon_id            INTEGER PRIMARY KEY,   -- PokeAPI `pokemon` resource id, NOT autoincrement,
                                                  -- so re-running the seed script upserts the same row
                                                  -- PokeAPI already assigns rather than minting new ids
    species_id            INTEGER NOT NULL,      -- PokeAPI `pokemon-species` id -- the species-clause key
    slug                   TEXT NOT NULL UNIQUE,  -- PokeAPI dash-case id, e.g. 'landorus-therian' --
                                                  -- also the join key against Smogon usage-stat rows
    display_name           TEXT NOT NULL,         -- e.g. 'Landorus (Therian)'
    national_dex_number    INTEGER NOT NULL,
    generation             INTEGER,               -- introduced generation (1-9)
    type1                   TEXT NOT NULL,
    type2                   TEXT,
    base_hp INTEGER, base_atk INTEGER, base_def INTEGER,
    base_spa INTEGER, base_spd INTEGER, base_spe INTEGER,
    sprite_url              TEXT,   -- hotlinked to PokeAPI/sprites' raw.githubusercontent.com URL --
                                    -- same external-URL pattern as app/team_colors.py's NFL logos,
                                    -- nothing copied onto the Pi's disk
    updated_at              TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pokemon_species ON pokemon(species_id);
CREATE INDEX IF NOT EXISTS idx_pokemon_gen     ON pokemon(generation);

-- A reusable ruleset "shape" a season is built on -- singles vs doubles,
-- which Smogon usage-stat file to pull, free-text rules. Distinct from a
-- season's own ruleset (point budget, roster cap, etc. below) -- a season
-- picks one format and can still override its numeric defaults.
CREATE TABLE IF NOT EXISTS pokemon_formats (
    format_id               TEXT PRIMARY KEY,   -- e.g. 'gen9ou', 'gen9vgc2024regh' -- matches the
                                                 -- Smogon stats URL's formatid segment directly
    display_name             TEXT NOT NULL,
    battle_style               TEXT NOT NULL,      -- 'singles' | 'doubles' -- drives replay slot
                                                    -- parsing (p1a/p2a only vs p1a/p1b/p2a/p2b)
    smogon_stats_prefix        TEXT,               -- kept separate from format_id in case they diverge
    rules_text                   TEXT,               -- free text: clauses, level, Bo3 rules -- shown
                                                    -- as-is on the season's Rules page
    default_roster_size          INTEGER NOT NULL DEFAULT 10,
    default_point_budget           INTEGER NOT NULL DEFAULT 100,
    default_species_clause           INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- One row per season. Only one may be 'active' at a time (unique partial
-- index below); re-checked in pokemon_draft/seasons.py before the UPDATE
-- too, for a friendly redirect+message instead of a raw IntegrityError.
CREATE TABLE IF NOT EXISTS pokemon_seasons (
    season_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name                       TEXT NOT NULL,
    format_id                   TEXT NOT NULL REFERENCES pokemon_formats(format_id),
    commissioner_user_id          INTEGER NOT NULL REFERENCES users(user_id),
                                                 -- season-scoped role layered on top of the site-wide
                                                 -- 'games' tier -- see pokemon_draft/permissions.py.
                                                 -- The commissioner can ALSO hold a coach seat (a
                                                 -- pokemon_season_coaches row with this same user_id) --
                                                 -- checked by joining against this column, no separate flag.
    status                        TEXT NOT NULL DEFAULT 'draft',
                                                 -- 'draft' | 'active' | 'complete' | 'archived'
    roster_size_cap                INTEGER NOT NULL,   -- copied from format default at creation,
                                                        -- editable until draft_locked_at is set
    point_budget                     INTEGER NOT NULL,
    species_clause_enabled             INTEGER NOT NULL DEFAULT 1,
    fa_transactions_allowed              INTEGER NOT NULL DEFAULT 0,  -- per-coach cap for the season
    roster_freeze_week                    INTEGER,   -- moves rejected at/after this schedule week;
                                                      -- NULL = no freeze configured yet
    playoff_bracket_size                    INTEGER NOT NULL DEFAULT 4,  -- 4 = QF->SF->F
    draft_locked_at                          TEXT,   -- set once the pool+costs are locked and
                                                      -- picking can start
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_pokemon_season
    ON pokemon_seasons(status) WHERE status = 'active';

-- One row per coach seat in a season.
CREATE TABLE IF NOT EXISTS pokemon_season_coaches (
    coach_id                INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id                 INTEGER NOT NULL REFERENCES pokemon_seasons(season_id),
    user_id                     INTEGER NOT NULL REFERENCES users(user_id),
    team_name                     TEXT NOT NULL,
    draft_order                     INTEGER,   -- 1..N snake seed, set at draft setup
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE (season_id, user_id)   -- one seat per account per season
);
CREATE INDEX IF NOT EXISTS idx_pk_season_coaches_season ON pokemon_season_coaches(season_id);

-- Which pokemon are legal in a season and what they cost -- layered on top
-- of the static `pokemon` table since legality/cost is season-specific
-- (the same Pokemon could be a 14-point staple one season and banned the
-- next). computed_cost (from usage stats) and cost_override (commissioner
-- hand-edit) are kept in SEPARATE columns so a later usage-stat re-fetch
-- can refresh computed_cost without clobbering a manual override --
-- effective_cost() in pokemon_draft/draft_pool.py is COALESCE(cost_override,
-- computed_cost).
CREATE TABLE IF NOT EXISTS pokemon_draft_pool (
    season_id       INTEGER NOT NULL REFERENCES pokemon_seasons(season_id),
    pokemon_id        INTEGER NOT NULL REFERENCES pokemon(pokemon_id),
    is_banned           INTEGER NOT NULL DEFAULT 0,
    usage_percent         REAL,
    computed_cost           INTEGER,
    cost_override             INTEGER,
    stats_fetched_at          TEXT,
    PRIMARY KEY (season_id, pokemon_id)
);
CREATE INDEX IF NOT EXISTS idx_draft_pool_season ON pokemon_draft_pool(season_id);

-- Configurable usage%->cost tiers (see pokemon_draft/points.py's
-- compute_cost()). Ordered by min_usage_percent descending; a Pokemon's
-- computed_cost is the point_cost of the first tier it clears. Seeded with
-- placeholder defaults per format at season setup, editable by the
-- commissioner before the draft board locks -- there's no historical
-- usage-based formula to seed real boundaries from, since the source
-- spreadsheets hand-assigned costs.
CREATE TABLE IF NOT EXISTS pokemon_cost_tiers (
    season_id          INTEGER NOT NULL REFERENCES pokemon_seasons(season_id),
    tier_rank            INTEGER NOT NULL,   -- 1 = most expensive tier
    min_usage_percent      REAL NOT NULL,
    point_cost               INTEGER NOT NULL,
    PRIMARY KEY (season_id, tier_rank)
);

-- One row per season -- a season only ever runs one draft.
CREATE TABLE IF NOT EXISTS pokemon_draft_sessions (
    season_id           INTEGER PRIMARY KEY REFERENCES pokemon_seasons(season_id),
    status                 TEXT NOT NULL DEFAULT 'not_started',
                                              -- 'not_started' | 'in_progress' | 'paused' | 'complete'
    turn_index               INTEGER NOT NULL DEFAULT 0,  -- overall pick # about to be made (0-based) --
                                                          -- snake order computed from this + coach
                                                          -- count + roster_size_cap, same round/
                                                          -- direction math as group_draft.whose_turn()
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS pokemon_draft_picks (
    season_id       INTEGER NOT NULL REFERENCES pokemon_seasons(season_id),
    coach_id          INTEGER NOT NULL REFERENCES pokemon_season_coaches(coach_id),
    pokemon_id          INTEGER NOT NULL REFERENCES pokemon(pokemon_id),
    pick_order            INTEGER NOT NULL,   -- overall 1-based pick number
    cost_paid                INTEGER NOT NULL,   -- snapshot of effective_cost at pick time -- stable
                                                -- even if cost_override changes later (same snapshot
                                                -- philosophy as fantasy_draft_entries.points)
    picked_at                  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (season_id, pokemon_id),   -- the exact-form draft-conflict rule; species clause
                                          -- (blocking a DIFFERENT form of an already-picked species)
                                          -- is an application-code check, not a DB constraint --
                                          -- see pokemon_draft/draft.py's make_pick()
    UNIQUE (season_id, pick_order)
);
CREATE INDEX IF NOT EXISTS idx_draft_picks_coach ON pokemon_draft_picks(season_id, coach_id);

-- Every roster change after the draft, append-only. Current roster is
-- computed LIVE via a window-function query (see pokemon_draft/roster.py's
-- current_roster()), never stored -- matches app/pickem.py's
-- compute-don't-cache philosophy and avoids the drift-bug class this
-- schema's own trade_values comment already documents once. A trade is
-- one 'trade_out' row + one 'trade_in' row sharing trade_group_id.
CREATE TABLE IF NOT EXISTS pokemon_roster_moves (
    move_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id              INTEGER NOT NULL REFERENCES pokemon_seasons(season_id),
    coach_id                 INTEGER NOT NULL REFERENCES pokemon_season_coaches(coach_id),
    pokemon_id                 INTEGER NOT NULL REFERENCES pokemon(pokemon_id),
    move_type                    TEXT NOT NULL,  -- 'draft' | 'fa_add' | 'drop' | 'trade_in' | 'trade_out'
    cost                           INTEGER,   -- points charged/refunded by this move (NULL for 'drop')
    trade_group_id                    TEXT REFERENCES pokemon_trade_offers(trade_id),
                                              -- set only for trade_in/trade_out rows
    counts_toward_fa_cap                INTEGER NOT NULL DEFAULT 0,   -- 1 only for standalone 'fa_add'
                                                                     -- rows -- drops (including ones
                                                                     -- bundled into a trade) are free,
                                                                     -- stored explicitly rather than
                                                                     -- inferred from move_type so the
                                                                     -- cap rule can change later
                                                                     -- without reinterpreting old rows
    week                                  INTEGER,   -- schedule week this move was made in -- used for
                                                     -- the roster-freeze cutoff and "roster as of week
                                                     -- N" reconstruction
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_roster_moves_season_coach ON pokemon_roster_moves(season_id, coach_id);
CREATE INDEX IF NOT EXISTS idx_roster_moves_pokemon ON pokemon_roster_moves(season_id, pokemon_id);

-- A pending/accepted/rejected trade between two coaches. Bundles both the
-- Pokemon changing hands AND any drops needed to stay under budget/roster
-- cap into ONE offer (pokemon_trade_offer_items.action) -- confirmed: a
-- trade is proposed and accepted as a single atomic transaction, never one
-- that completes first and leaves a coach over-budget to clean up
-- afterward. See pokemon_draft/roster.py's accept_trade().
CREATE TABLE IF NOT EXISTS pokemon_trade_offers (
    trade_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id                 INTEGER NOT NULL REFERENCES pokemon_seasons(season_id),
    proposing_coach_id           INTEGER NOT NULL REFERENCES pokemon_season_coaches(coach_id),
    receiving_coach_id             INTEGER NOT NULL REFERENCES pokemon_season_coaches(coach_id),
    status                           TEXT NOT NULL DEFAULT 'pending',
                                                  -- 'pending' | 'accepted' | 'rejected' | 'cancelled'
    created_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS pokemon_trade_offer_items (
    trade_id        INTEGER NOT NULL REFERENCES pokemon_trade_offers(trade_id),
    pokemon_id         INTEGER NOT NULL REFERENCES pokemon(pokemon_id),
    from_coach_id         INTEGER NOT NULL REFERENCES pokemon_season_coaches(coach_id),  -- current
                                                                                          -- owner
    action                  TEXT NOT NULL DEFAULT 'trade',  -- 'trade' (moves to the offer's OTHER
                                                            -- coach) | 'drop' (leaves from_coach_id's
                                                            -- roster entirely, no receiver -- bundled
                                                            -- in specifically to fix a budget/roster-cap
                                                            -- overage the trade would otherwise cause)
    PRIMARY KEY (trade_id, pokemon_id)
);

-- Regular-season and playoff matchups share one table (a playoff row sets
-- `round` instead of `week`) -- a match is a match either way;
-- pokemon_playoff_bracket below decides who fills a playoff row's
-- coach_id_home/away once earlier rounds resolve.
CREATE TABLE IF NOT EXISTS pokemon_schedule (
    schedule_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id           INTEGER NOT NULL REFERENCES pokemon_seasons(season_id),
    week                  INTEGER,   -- regular-season week #; NULL for playoff rows
    round                   TEXT,      -- 'QF' | 'SF' | 'F' for playoff rows; NULL otherwise --
                                      -- exactly one of (week, round) is set, enforced in application code
    coach_id_home              INTEGER REFERENCES pokemon_season_coaches(coach_id),
    coach_id_away                 INTEGER REFERENCES pokemon_season_coaches(coach_id),  -- NULL = bye
    bracket_slot                    TEXT,   -- e.g. 'QF1' -- links to pokemon_playoff_bracket.slot
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_schedule_season_week ON pokemon_schedule(season_id, week);

-- The Bo3 SERIES between two coaches for one schedule row -- tracks the
-- self-report -> confirm/dispute workflow and the series winner once
-- resolved. Individual games are pokemon_match_games below.
CREATE TABLE IF NOT EXISTS pokemon_matches (
    match_id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    schedule_id                  INTEGER NOT NULL REFERENCES pokemon_schedule(schedule_id),
    reported_by_user_id             INTEGER REFERENCES users(user_id),
    status                            TEXT NOT NULL DEFAULT 'unreported',
                                            -- 'unreported' | 'pending_confirmation' | 'confirmed' |
                                            -- 'disputed'
    winner_coach_id                     INTEGER REFERENCES pokemon_season_coaches(coach_id),
    dispute_reason                        TEXT,
    dispute_resolved_by                     INTEGER REFERENCES users(user_id),  -- the commissioner
    dispute_resolution_note                   TEXT,
    confirmed_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_matches_schedule ON pokemon_matches(schedule_id);

-- One row per game within a Bo3 series (1-3 rows -- a 2-0 series never
-- gets a 3rd row). entry_method covers both a hand-typed winner+K/D grid
-- ('manual') and a parsed Showdown replay link ('replay') with the same
-- downstream shape -- see pokemon_draft/matches.py and .../replay.py.
CREATE TABLE IF NOT EXISTS pokemon_match_games (
    game_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id               INTEGER NOT NULL REFERENCES pokemon_matches(match_id),
    game_num                  INTEGER NOT NULL,   -- 1, 2, or 3
    entry_method                 TEXT NOT NULL DEFAULT 'manual',   -- 'manual' | 'replay'
    replay_url                     TEXT,     -- set only when entry_method = 'replay'
    replay_battle_id                 TEXT,     -- parsed out of the URL, e.g. 'gen9randombattle-2675319655'
    winner_coach_id                    INTEGER REFERENCES pokemon_season_coaches(coach_id),
    parse_status                         TEXT,   -- 'pending' | 'parsed' | 'failed' -- NULL when manual
    parse_error                            TEXT,   -- human-readable reason when parse_status = 'failed'
    raw_log_uploadtime                       TEXT,   -- the replay JSON's own `uploadtime`, so a later
                                                     -- re-parse can tell if the source changed
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE (match_id, game_num)
);

-- Per-Pokemon K/D for one game. A Pokemon that never took the field gets
-- no row at all, not a zero row.
CREATE TABLE IF NOT EXISTS pokemon_match_stats (
    game_id        INTEGER NOT NULL REFERENCES pokemon_match_games(game_id),
    coach_id         INTEGER NOT NULL REFERENCES pokemon_season_coaches(coach_id),
    pokemon_id         INTEGER NOT NULL REFERENCES pokemon(pokemon_id),
    kills                INTEGER NOT NULL DEFAULT 0,
    deaths                 INTEGER NOT NULL DEFAULT 0,   -- 0 or 1 -- a Pokemon can only faint once/game
    PRIMARY KEY (game_id, coach_id, pokemon_id)
);
CREATE INDEX IF NOT EXISTS idx_match_stats_pokemon ON pokemon_match_stats(pokemon_id);

-- One row per bracket slot (QF1..QF4, SF1..SF2, F -- sized by
-- playoff_bracket_size). coach_id is filled at seeding time from
-- regular-season standings (via the fixed tiebreaker order) for round 1,
-- and from whichever playoff pokemon_schedule match feeds this slot for
-- later rounds -- advances_to_slot lets the bracket walk forward
-- automatically as each round's matches confirm.
CREATE TABLE IF NOT EXISTS pokemon_playoff_bracket (
    season_id             INTEGER NOT NULL REFERENCES pokemon_seasons(season_id),
    slot                    TEXT NOT NULL,   -- e.g. 'QF1', 'SF1', 'F'
    round                     TEXT NOT NULL,   -- 'QF' | 'SF' | 'F'
    seed                        INTEGER,          -- regular-season seed, first round only
    coach_id                      INTEGER REFERENCES pokemon_season_coaches(coach_id),
    advances_to_slot                TEXT,   -- NULL for the final
    PRIMARY KEY (season_id, slot)
);
