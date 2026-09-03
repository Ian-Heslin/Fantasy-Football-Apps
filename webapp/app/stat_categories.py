"""Shared registry of "guessable" season stat categories, used by both the
501 game (app/five_oh_one.py) and Imposter (app/imposter.py) so a stat
category means the same thing -- same source table/column, same available
years -- in both places instead of each game reinventing its own mapping.

Three source tables, all in analytics.duckdb:
  player_stats_season       nflverse's official offense counting stats
                             (passing/rushing/receiving yards & TDs,
                             interceptions thrown), 1999-2024.
  player_stats_def_season   the same release's defense-specific file
                             (tackles, sacks, passes defended, forced
                             fumbles/interceptions, defensive TDs),
                             1999-2024. See scripts/load_player_stats.py.
  player_season_fantasy_points  this project's own computed PPR fantasy
                             points (from play_by_play), 1999-2025 --
                             reused here rather than nflverse's
                             fantasy_points_ppr so this always matches what
                             Fantasy Draft/Daily Stat Pad show elsewhere in
                             the app.

start_501 values are a first-pass estimate, not a verified constant -- the
right starting point depends on how many "big" and "small" seasons exist
for a category, and is meant to be tuned by feel once people actually play
a few rounds (see the 501 game's module docstring).
"""
import difflib

from app.trivia import normalize_name

STAT_CATEGORIES = {
    "passing_yards": {
        "label": "Passing Yards", "side": "offense", "table": "player_stats_season",
        "column": "passing_yards", "name_column": "player_display_name", "start_501": 6000,
    },
    "passing_tds": {
        "label": "Passing TDs", "side": "offense", "table": "player_stats_season",
        "column": "passing_tds", "name_column": "player_display_name", "start_501": 50,
    },
    "interceptions_thrown": {
        "label": "Interceptions Thrown", "side": "offense", "table": "player_stats_season",
        "column": "interceptions", "name_column": "player_display_name", "start_501": 100,
    },
    "rushing_yards": {
        "label": "Rushing Yards", "side": "offense", "table": "player_stats_season",
        "column": "rushing_yards", "name_column": "player_display_name", "start_501": 2500,
    },
    "rushing_tds": {
        "label": "Rushing TDs", "side": "offense", "table": "player_stats_season",
        "column": "rushing_tds", "name_column": "player_display_name", "start_501": 30,
    },
    "receptions": {
        "label": "Receptions", "side": "offense", "table": "player_stats_season",
        "column": "receptions", "name_column": "player_display_name", "start_501": 170,
    },
    "receiving_yards": {
        "label": "Receiving Yards", "side": "offense", "table": "player_stats_season",
        "column": "receiving_yards", "name_column": "player_display_name", "start_501": 2200,
    },
    "receiving_tds": {
        "label": "Receiving TDs", "side": "offense", "table": "player_stats_season",
        "column": "receiving_tds", "name_column": "player_display_name", "start_501": 25,
    },
    "fantasy_points": {
        "label": "Fantasy Points (PPR)", "side": "offense", "table": "player_season_fantasy_points",
        "column": "ppr_pt", "name_column": "player", "start_501": 1000,
    },
    "tackles": {
        "label": "Tackles", "side": "defense", "table": "player_stats_def_season",
        "column": "def_tackles", "name_column": "player_display_name", "start_501": 150,
    },
    "sacks": {
        "label": "Sacks", "side": "defense", "table": "player_stats_def_season",
        "column": "def_sacks", "name_column": "player_display_name", "start_501": 25,
    },
    "interceptions_caught": {
        "label": "Interceptions Caught", "side": "defense", "table": "player_stats_def_season",
        "column": "def_interceptions", "name_column": "player_display_name", "start_501": 40,
    },
    "passes_defended": {
        "label": "Passes Defended", "side": "defense", "table": "player_stats_def_season",
        "column": "def_pass_defended", "name_column": "player_display_name", "start_501": 35,
    },
    "forced_fumbles": {
        "label": "Forced Fumbles", "side": "defense", "table": "player_stats_def_season",
        "column": "def_fumbles_forced", "name_column": "player_display_name", "start_501": 12,
    },
    "defensive_tds": {
        "label": "Defensive TDs", "side": "defense", "table": "player_stats_def_season",
        "column": "def_tds", "name_column": "player_display_name", "start_501": 6,
    },
}

# A single-game outlier (e.g. 2 interceptions caught in one late-season
# start) shouldn't be able to out-rank a full season's production just
# because nflverse's season tables have no games-played floor built in.
MIN_GAMES = 4


def available_years(duckdb_conn, key):
    table = STAT_CATEGORIES[key]["table"]
    row = duckdb_conn.execute(f"SELECT min(season), max(season) FROM {table}").fetchone()
    return (row[0], row[1]) if row and row[0] is not None else (None, None)


def _season_pool(duckdb_conn, key, year):
    cat = STAT_CATEGORIES[key]
    return duckdb_conn.execute(
        f"""SELECT {cat['name_column']}, {cat['column']} FROM {cat['table']}
            WHERE season = ? AND games >= ? AND {cat['column']} IS NOT NULL""",
        (year, MIN_GAMES),
    ).fetchall()


def find_player_value(duckdb_conn, key, year, name_guess):
    """(real_name, stat_value) for the closest name match in that season, or
    None if nothing matches."""
    target = normalize_name(name_guess)
    for name, value in _season_pool(duckdb_conn, key, year):
        if normalize_name(name) == target:
            return name, value
    return None


def suggestions(duckdb_conn, key, year, name_guess, limit=5):
    pool = _season_pool(duckdb_conn, key, year)
    normalized_to_real = {normalize_name(name): name for name, _ in pool}
    close = difflib.get_close_matches(normalize_name(name_guess), normalized_to_real.keys(), n=limit, cutoff=0.6)
    return [normalized_to_real[n] for n in close]


def top_n(duckdb_conn, key, year, n=20):
    """That category's top n (name, stat_value) for one season, highest
    first -- the ranking Imposter's top-10/11-20 split is built from."""
    pool = sorted(_season_pool(duckdb_conn, key, year), key=lambda row: row[1], reverse=True)
    return pool[:n]
