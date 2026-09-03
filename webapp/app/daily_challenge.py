"""Daily Stat Pad -- inspired by statpadgame.com: pick 5 distinct players,
each paired with a season, to maximize the total for one stat category.
A new category is picked automatically each day (deterministic from the
date, so everyone sees the same one), and the leaderboard resets daily.

Scoped to 1999+ only -- player_season_fantasy_points (computed from
play_by_play, see scripts/compute_fantasy_points.py) is the only source
with the raw per-category season totals this needs; the personal-
spreadsheet export (fantasy_draft_stats, 1970-1998) only has fant_pt/
ppr_pt, not the category breakdowns.

Design call (the real statpadgame.com's exact ruleset wasn't verifiable
-- this sandbox can't reach ordinary websites): 5 picks must be 5 DISTINCT
players (no picking the same player twice at different seasons) -- keeps
this about broad roster knowledge rather than "who do I know the whole
career arc of."
"""
import difflib
import random

from app.trivia import normalize_name

CATEGORIES = {
    "Passing Yards": "passing_yards",
    "Passing TDs": "passing_tds",
    "Rushing Yards": "rushing_yards",
    "Rushing TDs": "rushing_tds",
    "Receptions": "receptions",
    "Receiving Yards": "receiving_yards",
    "Receiving TDs": "receiving_tds",
    "PPR Fantasy Points": "ppr_pt",
}

PICK_COUNT = 5
MIN_YEAR = 1999  # player_season_fantasy_points' coverage start


def todays_category(date):
    """Deterministic from the date -- same for every player that day, and
    reproducible later (no need to store which category a given day used)."""
    return random.Random(date.isoformat()).choice(list(CATEGORIES))


def _season_pool(duckdb_conn, year):
    return duckdb_conn.execute(
        "SELECT player_id, player, team, position FROM player_season_fantasy_points WHERE season = ?",
        (year,),
    ).fetchall()


def find_player(duckdb_conn, year, name_guess):
    """Best (player_id, player, team, position) match for a typed guess
    within that season, or None."""
    target = normalize_name(name_guess)
    for row in _season_pool(duckdb_conn, year):
        if normalize_name(row[1]) == target:
            return row
    return None


def suggestions(duckdb_conn, year, name_guess, limit=5):
    pool = _season_pool(duckdb_conn, year)
    normalized_to_real = {normalize_name(row[1]): row[1] for row in pool}
    close = difflib.get_close_matches(normalize_name(name_guess), normalized_to_real.keys(), n=limit, cutoff=0.6)
    return [normalized_to_real[n] for n in close]


def category_value(duckdb_conn, year, player_id, category):
    column = CATEGORIES[category]
    row = duckdb_conn.execute(
        f"SELECT {column} FROM player_season_fantasy_points WHERE season = ? AND player_id = ?",
        (year, player_id),
    ).fetchone()
    return row[0] if row else None


def next_pick_num(conn, user_id, challenge_date):
    """The first pick slot (1..PICK_COUNT) not yet saved today, or None
    once all PICK_COUNT are in -- what row-by-row submission shows next."""
    done = set(get_picks(conn, user_id, challenge_date).keys())
    for i in range(1, PICK_COUNT + 1):
        if i not in done:
            return i
    return None


def save_one_pick(conn, duckdb_conn, user_id, challenge_date, category, pick_num, year_raw, player_raw):
    """Validates and saves a single pick slot (submitted row by row rather
    than all PICK_COUNT at once) -- returns an error message, or None on
    success."""
    if not year_raw or not player_raw:
        return "Enter both a year and a player."
    try:
        year = int(year_raw)
    except ValueError:
        return f"'{year_raw}' isn't a year."
    if year < MIN_YEAR:
        return f"Daily Stat Pad only covers {MIN_YEAR}-present."

    match = find_player(duckdb_conn, year, player_raw)
    if match is None:
        hint = suggestions(duckdb_conn, year, player_raw)
        return (
            f"No player named '{player_raw}' found in {year}."
            + (f" Did you mean: {', '.join(hint)}?" if hint else "")
        )

    player_id, player, team, position = match
    already_picked = {r["player"] for r in get_picks(conn, user_id, challenge_date).values()}
    if player in already_picked:
        return f"{player} is already one of today's picks -- pick 5 different players."

    value = category_value(duckdb_conn, year, player_id, category)
    conn.execute(
        """INSERT INTO daily_challenge_entries (user_id, challenge_date, pick_num, year, player, stat_value)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, challenge_date, pick_num) DO UPDATE SET
               year=excluded.year, player=excluded.player, stat_value=excluded.stat_value""",
        (user_id, challenge_date, pick_num, year, player, value),
    )
    conn.commit()
    return None


def get_picks(conn, user_id, challenge_date):
    rows = conn.execute(
        "SELECT * FROM daily_challenge_entries WHERE user_id = ? AND challenge_date = ? ORDER BY pick_num",
        (user_id, challenge_date),
    ).fetchall()
    return {r["pick_num"]: r for r in rows}


def leaderboard(conn, challenge_date):
    rows = conn.execute(
        """SELECT u.user_id, u.username, sum(e.stat_value) AS total, count(e.pick_num) AS picks_made
           FROM users u JOIN daily_challenge_entries e ON e.user_id = u.user_id
           WHERE e.challenge_date = ?
           GROUP BY u.user_id, u.username""",
        (challenge_date,),
    ).fetchall()
    results = [
        {"user_id": r["user_id"], "username": r["username"], "total": r["total"] or 0, "picks_made": r["picks_made"]}
        for r in rows
    ]
    results.sort(key=lambda r: r["total"], reverse=True)
    for i, r in enumerate(results, start=1):
        r["rank"] = i
    return results
