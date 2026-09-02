"""Award Winners / Season Leaders trivia -- guess-a-name-for-a-clue
games, played async/individually (like Pick'em): anyone starts a round
anytime, answers on their own, gets scored immediately, and every round
counts toward a per-category leaderboard (best score per user).

This is a deliberately simpler design than the original spreadsheet
version, which was a live, shared, host-run session with per-contestant
"strikes" tracked by hand as the group played together in one sitting.
That's a real, different feature (see the project's task notes) -- this
module is the async individual-play version only.

Reference/answer data (trivia_award_winners, trivia_season_leaders,
nfl_top_100) lives in analytics.duckdb (see scripts/load_trivia_data.py,
scripts/load_nfl_top100.py); rounds themselves
(trivia_rounds/trivia_round_items) are operational data in app.db, and
snapshot their questions/answers at creation time rather than joining
live against the reference tables on every view -- so a round's history
stays exactly as played even if the reference data is later corrected.
"""
import random
import re

AWARD_CATEGORIES = [
    "MVP", "Super Bowl MVP", "Coach of the Year", "Offensive Player of the Year",
    "Defensive Player of the Year", "Offensive Rookie of the Year",
    "Defensive Rookie of the Year", "Comeback Player of the Year",
    "Walter Payton Man of the Year",
]

SEASON_CATEGORIES = ["Points Leaders", "Official Sacks Leaders"]

ROUND_SIZE = 10

# Weekly Top Scorers: a "guess the rank" round like Season Leaders, but
# scoped to one real week instead of all-time -- built on
# player_week_fantasy_points (see scripts/compute_fantasy_points.py),
# which is why it can point at "whatever week is most recently loaded"
# instead of a fixed category list. Every one of the top N scorers that
# week is a question (not a random sample of a larger pool) -- the whole
# premise is "guess who these were", not sampling down further.
WEEKLY_ROUND_SIZE = 15

# NFL Top 100: "guess the rank" like Season Leaders, but the category is a
# real year (2011-2026, whatever nfl_top_100 covers) instead of a fixed
# name -- see available_top100_years(). A round samples ROUND_SIZE of
# that year's 100 ranked players, same as Award Winners/Season Leaders.


def available_top100_years(duckdb_conn):
    rows = duckdb_conn.execute("SELECT DISTINCT year FROM nfl_top_100 ORDER BY year DESC").fetchall()
    return [r[0] for r in rows]


def normalize_name(name):
    """Loose match for a typed guess against a real player name -- casual
    trivia among friends shouldn't fail on a missing period or "Jr.""."""
    name = name.lower()
    name = re.sub(r"[.']", "", name)
    name = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", name)
    name = re.sub(r"[^a-z ]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _award_prompt(year, position):
    return f"{year} ({position})" if position and position != "Coach" else str(year)


def _season_prompt(category, rank, stat_value, years_active, team_clue):
    stat_label = "career sacks" if "Sacks" in category else "career points"
    value = f"{stat_value:g}" if stat_value is not None else "?"
    return f"#{rank} all-time — {team_clue or '?'} — {value} {stat_label} ({years_active or '?'})"


WEEKLY_CATEGORY_RE = re.compile(r"^(\d{4}) Week (\d+)$")


def weekly_category(season, week):
    return f"{season} Week {week}"


def parse_weekly_category(category):
    m = WEEKLY_CATEGORY_RE.match(category)
    if not m:
        raise ValueError(f"not a weekly-leaders category: {category!r}")
    return int(m.group(1)), int(m.group(2))


def latest_week(duckdb_conn):
    """(season, week) of the most recently loaded week -- re-running
    scripts/load_nflverse.py + compute_fantasy_points.py during the season
    moves this forward automatically."""
    row = duckdb_conn.execute(
        """SELECT season, max(week) FROM player_week_fantasy_points
           WHERE season = (SELECT max(season) FROM player_week_fantasy_points)
           GROUP BY season"""
    ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def _weekly_prompt(rank, team, position, ppr_pt):
    return f"#{rank} this week — {team or '?'} {position or ''} — {ppr_pt:.1f} PPR pts".replace("  ", " ")


def _top100_prompt(year, rank, team):
    return f"#{rank} on the NFL's Top 100 Players of {year} — {team or 'free agent'}"


def build_pool(duckdb_conn, game_type, category):
    """The full set of (item_key, prompt_label, correct_answer) questions
    for a category, for the reveal-style games (award_winners/
    season_leaders/weekly_leaders/nfl_top100) -- shared by both the async
    Solo round engine below and Group's live host-run sessions
    (app/group_games.py), so the two never drift apart on what a category's
    questions actually are."""
    if game_type == "award_winners":
        rows = duckdb_conn.execute(
            """SELECT year, any_value(position) AS position, string_agg(player, '|') AS players
               FROM trivia_award_winners WHERE category = ? GROUP BY year""",
            (category,),
        ).fetchall()
        pool = [(str(year), _award_prompt(year, position), players) for year, position, players in rows]
    elif game_type == "season_leaders":
        rows = duckdb_conn.execute(
            """SELECT rank, player, stat_value, years_active, team_clue
               FROM trivia_season_leaders WHERE category = ?""",
            (category,),
        ).fetchall()
        pool = [
            (str(rank), _season_prompt(category, rank, stat_value, years_active, team_clue), player)
            for rank, player, stat_value, years_active, team_clue in rows
        ]
    elif game_type == "weekly_leaders":
        season, week = parse_weekly_category(category)
        rows = duckdb_conn.execute(
            """SELECT player, team, position, ppr_pt FROM player_week_fantasy_points
               WHERE season = ? AND week = ? ORDER BY ppr_pt DESC LIMIT ?""",
            (season, week, WEEKLY_ROUND_SIZE),
        ).fetchall()
        pool = [
            (str(rank), _weekly_prompt(rank, team, position, ppr_pt), player)
            for rank, (player, team, position, ppr_pt) in enumerate(rows, start=1)
        ]
    elif game_type == "nfl_top100":
        year = int(category)
        rows = duckdb_conn.execute(
            "SELECT rank, player, team FROM nfl_top_100 WHERE year = ?", (year,)
        ).fetchall()
        pool = [(str(rank), _top100_prompt(year, rank, team), player) for rank, player, team in rows]
    else:
        raise ValueError(f"unknown game_type {game_type!r}")
    return pool


def start_round(sqlite_conn, duckdb_conn, user_id, game_type, category):
    """Samples ROUND_SIZE questions (fewer if the category doesn't have
    that many) from build_pool(), snapshots them into a new
    trivia_rounds/trivia_round_items pair, and returns the new round_id."""
    pool = build_pool(duckdb_conn, game_type, category)
    if not pool:
        return None

    # Weekly Top Scorers uses every question in the pool (it IS the round,
    # already capped to WEEKLY_ROUND_SIZE above); the other games sample a
    # random subset of a much larger pool.
    sample = pool if game_type == "weekly_leaders" else random.sample(pool, k=min(ROUND_SIZE, len(pool)))
    cur = sqlite_conn.execute(
        "INSERT INTO trivia_rounds (user_id, game_type, category, total) VALUES (?, ?, ?, ?)",
        (user_id, game_type, category, len(sample)),
    )
    round_id = cur.lastrowid
    sqlite_conn.executemany(
        "INSERT INTO trivia_round_items (round_id, item_key, prompt_label, correct_answer) VALUES (?, ?, ?, ?)",
        [(round_id, item_key, prompt, answer) for item_key, prompt, answer in sample],
    )
    sqlite_conn.commit()
    return round_id


def get_round(conn, round_id, user_id):
    round_row = conn.execute(
        "SELECT * FROM trivia_rounds WHERE round_id = ? AND user_id = ?", (round_id, user_id)
    ).fetchone()
    if round_row is None:
        return None, []
    items = conn.execute(
        "SELECT * FROM trivia_round_items WHERE round_id = ? ORDER BY rowid", (round_id,)
    ).fetchall()
    return round_row, items


def submit_round(conn, round_id, user_id, guesses):
    """guesses: {item_key: raw guess string}. Scores every item, updates
    the round's score/completed_at, and returns the round_id (or None if
    it doesn't belong to this user / is already completed)."""
    round_row = conn.execute(
        "SELECT * FROM trivia_rounds WHERE round_id = ? AND user_id = ?", (round_id, user_id)
    ).fetchone()
    if round_row is None or round_row["completed_at"] is not None:
        return None

    items = conn.execute("SELECT * FROM trivia_round_items WHERE round_id = ?", (round_id,)).fetchall()
    correct_count = 0
    for item in items:
        guess = (guesses.get(item["item_key"]) or "").strip()
        correct_names = {normalize_name(n) for n in item["correct_answer"].split("|")}
        is_correct = bool(guess) and normalize_name(guess) in correct_names
        if is_correct:
            correct_count += 1
        conn.execute(
            "UPDATE trivia_round_items SET guess = ?, is_correct = ? WHERE round_id = ? AND item_key = ?",
            (guess or None, int(is_correct), round_id, item["item_key"]),
        )
    conn.execute(
        "UPDATE trivia_rounds SET score = ?, completed_at = datetime('now') WHERE round_id = ?",
        (correct_count, round_id),
    )
    conn.commit()
    return round_id


def leaderboard(conn, game_type, category=None):
    """Each user's best score (as a fraction of that round's total) for
    one category, or across all of a game_type's categories if category
    is None. Ranked by best correct-fraction, most recent round breaks
    ties (arbitrary but stable)."""
    where = "game_type = ? AND completed_at IS NOT NULL"
    params = [game_type]
    if category is not None:
        where += " AND category = ?"
        params.append(category)

    rows = conn.execute(
        f"""SELECT r.user_id, u.username, r.category, r.score, r.total, r.completed_at
            FROM trivia_rounds r JOIN users u ON u.user_id = r.user_id
            WHERE {where}""",
        params,
    ).fetchall()

    best = {}
    for r in rows:
        key = r["user_id"]
        frac = r["score"] / r["total"] if r["total"] else 0
        if key not in best or frac > best[key]["fraction"]:
            best[key] = {
                "user_id": r["user_id"], "username": r["username"], "category": r["category"],
                "score": r["score"], "total": r["total"], "fraction": frac,
            }
    results = sorted(best.values(), key=lambda r: r["fraction"], reverse=True)
    for i, r in enumerate(results, start=1):
        r["rank"] = i
    return results


def recent_rounds(conn, user_id, game_type, limit=10):
    return conn.execute(
        """SELECT * FROM trivia_rounds WHERE user_id = ? AND game_type = ? AND completed_at IS NOT NULL
           ORDER BY completed_at DESC LIMIT ?""",
        (user_id, game_type, limit),
    ).fetchall()
