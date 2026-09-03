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
#
# Optional hints a player can toggle on when starting a round/session --
# each just adds another clue to the prompt text, baked in at build_pool()
# time (see _top100_prompt/_top100_enrichment below). "team" was always
# shown before these toggles existed; it's included here so it can be
# turned off too, for a harder round.
TOP100_HINT_LABELS = {
    "team": "Team", "position": "Position", "side": "Side of the ball",
    "years": "Years in the league", "stats": "Season stats",
}

# Position -> side of ball, for the "side" hint and to pick which stat line
# (offensive vs. defensive) the "stats" hint shows. Covers every raw
# position value seen in player_bio/player_stats_season/
# player_stats_def_season -- special teams positions get a side but no stat
# line (nflverse's player_stats releases don't carry kicking/punting stats
# here).
OFFENSE_POSITIONS = {"QB", "RB", "FB", "HB", "WR", "TE", "OL", "T", "OT", "G", "OG", "C"}
DEFENSE_POSITIONS = {"DL", "DE", "DT", "NT", "LB", "ILB", "OLB", "MLB", "CB", "DB", "S", "FS", "SS", "SAF"}
SPECIAL_TEAMS_POSITIONS = {"K", "P", "LS"}


def _side_of_ball(position):
    if not position:
        return None
    position = position.upper()
    if position in OFFENSE_POSITIONS:
        return "Offense"
    if position in DEFENSE_POSITIONS:
        return "Defense"
    if position in SPECIAL_TEAMS_POSITIONS:
        return "Special Teams"
    return None


def _top100_enrichment(duckdb_conn, year):
    """normalize_name(player) -> {position, side, years_in_league, stat_line}
    for hints on that year's Top 100 list. nfl_top_100 only has free-text
    player names (no player_id), so this loosely matches them against
    nflverse's player_stats_season/player_stats_def_season (that season's
    offense/defense counting stats) and player_bio (career position and
    rookie_season, for years-in-league and as a position fallback for
    anyone who didn't record offensive or defensive stats that year --
    e.g. a returner or a player who missed the season hurt).

    Two real players can share a normalized name across NFL history (e.g.
    a 1988-1996 DE and a 2017-active RB both named Aaron Jones) -- a plain
    name join would silently pick whichever bio row came back first,
    which for an active star can mean showing a decades-dead defensive
    lineman's position as the "hint" for the real player. Bio candidates
    are grouped by name and, per year, resolved to whichever one's
    rookie_season..last_season window actually contains this year."""
    bio_candidates = {}
    for display_name, position, rookie_season, last_season in duckdb_conn.execute(
        "SELECT display_name, position, rookie_season, last_season FROM player_bio"
    ).fetchall():
        bio_candidates.setdefault(normalize_name(display_name), []).append(
            (position, rookie_season, last_season)
        )

    enrichment = {}
    for name, candidates in bio_candidates.items():
        active = [c for c in candidates if c[1] and c[1] <= year <= (c[2] or year)]
        position, rookie_season, _ = (active or candidates)[0]
        e = enrichment.setdefault(name, {})
        if position:
            e["position"] = position
        if rookie_season:
            e["rookie_season"] = rookie_season

    # player_bio's career position (set above) decides which stat line
    # applies below -- an offensive player who happens to have a stray
    # tackle logged (e.g. chasing down a return after their own turnover)
    # shows up in player_stats_def_season too, and shouldn't have that
    # incidental defensive credit clobber their real offensive stat line
    # (or vice versa). Only a player missing from player_bio entirely
    # falls back to "whichever table matched" for both position and side.
    off_rows = duckdb_conn.execute(
        """SELECT player_display_name, any_value(position) AS position,
                  sum(coalesce(passing_yards, 0) + coalesce(rushing_yards, 0) + coalesce(receiving_yards, 0)) AS yards,
                  sum(coalesce(passing_tds, 0) + coalesce(rushing_tds, 0) + coalesce(receiving_tds, 0)) AS tds,
                  sum(coalesce(interceptions, 0) + coalesce(sack_fumbles_lost, 0)
                      + coalesce(rushing_fumbles_lost, 0) + coalesce(receiving_fumbles_lost, 0)) AS turnovers
           FROM player_stats_season WHERE season = ? AND player_display_name IS NOT NULL
           GROUP BY player_display_name""",
        (year,),
    ).fetchall()
    for display_name, position, yards, tds, turnovers in off_rows:
        e = enrichment.setdefault(normalize_name(display_name), {})
        side = _side_of_ball(e.get("position"))
        if side not in (None, "Offense"):
            continue
        if not e.get("position"):
            e["position"] = position
        e["stat_line"] = f"{int(yards)} yds, {int(tds)} TD, {int(turnovers)} TO"

    def_rows = duckdb_conn.execute(
        """SELECT player_display_name, any_value(position) AS position,
                  sum(coalesce(def_tackles, 0)) AS tackles, sum(coalesce(def_sacks, 0)) AS sacks,
                  sum(coalesce(def_pass_defended, 0)) AS pbu,
                  sum(coalesce(def_interceptions, 0) + coalesce(def_fumbles_forced, 0)) AS turnovers_forced,
                  sum(coalesce(def_tds, 0)) AS tds
           FROM player_stats_def_season WHERE season = ? AND player_display_name IS NOT NULL
           GROUP BY player_display_name""",
        (year,),
    ).fetchall()
    for display_name, position, tackles, sacks, pbu, turnovers_forced, tds in def_rows:
        e = enrichment.setdefault(normalize_name(display_name), {})
        side = _side_of_ball(e.get("position"))
        if side not in (None, "Defense"):
            continue
        if not e.get("position"):
            e["position"] = position
        e["stat_line"] = (
            f"{int(tackles)} tkl, {sacks:g} sacks, {int(pbu)} PBU, "
            f"{int(turnovers_forced)} TO forced, {int(tds)} TD"
        )

    for e in enrichment.values():
        e["side"] = _side_of_ball(e.get("position"))
        rookie_season = e.get("rookie_season")
        e["years_in_league"] = (year - rookie_season + 1) if rookie_season else None

    return enrichment


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
    m = WEEKLY_CATEGORY_RE.match(category or "")
    if not m:
        raise ValueError(f"not a weekly-leaders category: {category!r}")
    return int(m.group(1)), int(m.group(2))


def is_valid_category(game_type, category):
    """Whether this (game_type, category) pair is one the games actually
    have, checked the same way for the Solo and Group entry points.

    Both used to check `category.isdigit()` for nfl_top100 and to skip
    category validation entirely for weekly_leaders. Neither is safe:
    str.isdigit() is True for superscripts and other Unicode digit forms
    that int() then rejects ("²"), and an unvalidated weekly category
    reached parse_weekly_category's raise. Either way a signed-in user
    could turn a form post into a 500."""
    if game_type in ("award_winners", "season_leaders"):
        categories = AWARD_CATEGORIES if game_type == "award_winners" else SEASON_CATEGORIES
        return category in categories
    if game_type == "weekly_leaders":
        return WEEKLY_CATEGORY_RE.match(category or "") is not None
    if game_type == "nfl_top100":
        # str.isdigit() is too loose and str.isascii()+isdigit() is the
        # narrow check int() actually accepts.
        return bool(category) and category.isascii() and category.isdigit()
    return False


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


def _top100_prompt(year, rank, team, enrich, hints):
    bits = [f"#{rank} on the NFL's Top 100 Players of {year}"]
    if "team" in hints:
        bits.append(team or "free agent")
    if "position" in hints and enrich.get("position"):
        bits.append(enrich["position"])
    if "side" in hints and enrich.get("side"):
        bits.append(enrich["side"])
    if "years" in hints and enrich.get("years_in_league"):
        years = enrich["years_in_league"]
        bits.append("Rookie season" if years == 1 else f"Year {years} in the league")
    if "stats" in hints and enrich.get("stat_line"):
        bits.append(enrich["stat_line"])
    return " — ".join(bits)


def build_pool(duckdb_conn, game_type, category, hints=None):
    """The full set of (item_key, prompt_label, correct_answer) questions
    for a category, for the reveal-style games (award_winners/
    season_leaders/weekly_leaders/nfl_top100) -- shared by both the async
    Solo round engine below and Group's live host-run sessions
    (app/group_games.py), so the two never drift apart on what a category's
    questions actually are. hints only applies to nfl_top100 -- see
    TOP100_HINT_LABELS/_top100_prompt."""
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
        hints = set(hints or ())
        rows = duckdb_conn.execute(
            "SELECT rank, player, team FROM nfl_top_100 WHERE year = ?", (year,)
        ).fetchall()
        enrichment = _top100_enrichment(duckdb_conn, year) if hints else {}
        pool = [
            (str(rank), _top100_prompt(year, rank, team, enrichment.get(normalize_name(player), {}), hints), player)
            for rank, player, team in rows
        ]
    else:
        raise ValueError(f"unknown game_type {game_type!r}")
    return pool


def start_round(sqlite_conn, duckdb_conn, user_id, game_type, category, hints=None):
    """Samples ROUND_SIZE questions (fewer if the category doesn't have
    that many) from build_pool(), snapshots them into a new
    trivia_rounds/trivia_round_items pair, and returns the new round_id."""
    pool = build_pool(duckdb_conn, game_type, category, hints)
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
    is None. Ranked by best correct-fraction, larger round breaking ties.

    Also reports rounds_played. Nothing caps how many rounds a user
    starts and a round samples ROUND_SIZE questions from a much larger
    pool, so "best score" rewards persistence as well as knowledge --
    keep rolling and an easy sample turns up eventually. Surfacing the
    round count next to the score makes that visible rather than
    silently baked into the ranking; the ranking rule itself is
    unchanged, since changing it would re-rank every round already
    played. Ranking on a rolling average instead would remove the
    incentive outright -- that's a game-design call, not a bug fix."""
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
        entry = best.get(key)
        if entry is None:
            best[key] = {
                "user_id": r["user_id"], "username": r["username"], "category": r["category"],
                "score": r["score"], "total": r["total"], "fraction": frac,
                "rounds_played": 1,
            }
            continue
        entry["rounds_played"] += 1
        # Tie-break a equal fractions on the larger round: 9/10 and 3/3
        # both being "best" would otherwise rank the 3-question round
        # first, which is only reachable in a category whose whole pool
        # is smaller than ROUND_SIZE.
        if (frac, r["total"]) > (entry["fraction"], entry["total"]):
            entry.update(category=r["category"], score=r["score"],
                         total=r["total"], fraction=frac)

    results = sorted(best.values(),
                     key=lambda r: (r["fraction"], r["total"]), reverse=True)
    for i, r in enumerate(results, start=1):
        r["rank"] = i
    return results


def recent_rounds(conn, user_id, game_type, limit=10):
    return conn.execute(
        """SELECT * FROM trivia_rounds WHERE user_id = ? AND game_type = ? AND completed_at IS NOT NULL
           ORDER BY completed_at DESC LIMIT ?""",
        (user_id, game_type, limit),
    ).fetchall()
