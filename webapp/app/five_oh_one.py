"""501 -- inspired by the darts game of the same name: start from a
category-specific number, then guess 5 distinct (player, year) pairs one
at a time, each one's stat value subtracted from what's left, trying to
land exactly on (or as close as possible to) 0.

Every guessable value is a non-negative counting stat, so there's no way
to "come back up" after overshooting -- unlike real darts there's no bust
rule here; a game just runs its 5 picks and reports however close to 0 the
final remaining value landed, positive or negative. The skill is mixing a
couple of huge seasons with a couple of quiet ones to land the total close
to the target, which is why each category's start_501 (see
app/stat_categories.py) is picked to be a few multiples of a typical great
season -- not a verified constant, just a first guess at what makes a
5-pick game interesting, tunable by feel once people actually play it.

"Each player can only be used once" is enforced by name (not by
(player, year) pair like Fantasy Draft) -- the point is testing breadth of
knowledge across different players, so reusing the same person at a
different season isn't in the spirit of it even though the data would
allow it.
"""
from app.stat_categories import STAT_CATEGORIES, available_years, find_player_value, suggestions
from app.trivia import normalize_name

PICK_COUNT = 5


def start_game(conn, user_id, category):
    if category not in STAT_CATEGORIES:
        return None
    start_value = STAT_CATEGORIES[category]["start_501"]
    cur = conn.execute(
        "INSERT INTO five_oh_one_games (user_id, category, start_value, remaining) VALUES (?, ?, ?, ?)",
        (user_id, category, start_value, start_value),
    )
    conn.commit()
    return cur.lastrowid


def get_game(conn, game_id, user_id):
    return conn.execute(
        "SELECT * FROM five_oh_one_games WHERE game_id = ? AND user_id = ?", (game_id, user_id)
    ).fetchone()


def get_picks(conn, game_id):
    return conn.execute(
        "SELECT * FROM five_oh_one_picks WHERE game_id = ? ORDER BY pick_num", (game_id,)
    ).fetchall()


def make_pick(conn, duckdb_conn, game_id, year_raw, player_raw):
    """Returns an error message, or None on success."""
    game = conn.execute("SELECT * FROM five_oh_one_games WHERE game_id = ?", (game_id,)).fetchone()
    if game is None or game["completed_at"] is not None:
        return "This game is already finished."

    if not year_raw or not player_raw:
        return "Enter both a year and a player."
    try:
        year = int(year_raw)
    except ValueError:
        return f"'{year_raw}' isn't a year."

    category = game["category"]
    year_min, year_max = available_years(duckdb_conn, category)
    if year_min is None or not (year_min <= year <= year_max):
        return f"{STAT_CATEGORIES[category]['label']} only covers {year_min}-{year_max}."

    match = find_player_value(duckdb_conn, category, year, player_raw)
    if match is None:
        hint = suggestions(duckdb_conn, category, year, player_raw)
        return (
            f"No player named '{player_raw}' found in {year}."
            + (f" Did you mean: {', '.join(hint)}?" if hint else "")
        )
    player, value = match

    already_picked = {normalize_name(p["player"]) for p in get_picks(conn, game_id)}
    if normalize_name(player) in already_picked:
        return f"{player} has already been picked in this game -- pick 5 different players."

    pick_num = game["picks_made"] + 1
    remaining_after = game["remaining"] - value
    conn.execute(
        """INSERT INTO five_oh_one_picks (game_id, pick_num, player, year, stat_value, remaining_after)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (game_id, pick_num, player, year, value, remaining_after),
    )
    picks_made = pick_num
    completed = picks_made >= PICK_COUNT
    conn.execute(
        """UPDATE five_oh_one_games SET remaining = ?, picks_made = ?,
               completed_at = CASE WHEN ? THEN datetime('now') ELSE completed_at END
           WHERE game_id = ?""",
        (remaining_after, picks_made, completed, game_id),
    )
    conn.commit()
    return None


def leaderboard(conn, category=None):
    """Best (closest-to-zero) finished game per user, ranked by
    abs(remaining) ascending -- same "best score per user" shape as
    trivia.leaderboard."""
    where = "completed_at IS NOT NULL"
    params = []
    if category is not None:
        where += " AND category = ?"
        params.append(category)

    rows = conn.execute(
        f"""SELECT g.user_id, u.username, g.category, g.remaining, g.start_value
            FROM five_oh_one_games g JOIN users u ON u.user_id = g.user_id
            WHERE {where}""",
        params,
    ).fetchall()

    best = {}
    for r in rows:
        key = r["user_id"]
        distance = abs(r["remaining"])
        if key not in best or distance < best[key]["distance"]:
            best[key] = {
                "user_id": r["user_id"], "username": r["username"], "category": r["category"],
                "remaining": r["remaining"], "distance": distance,
            }
    results = sorted(best.values(), key=lambda r: r["distance"])
    for i, r in enumerate(results, start=1):
        r["rank"] = i
    return results
