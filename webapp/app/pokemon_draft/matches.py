"""Match report/confirm/dispute state machine. A "match" is one Bo3
series between the two coaches in a pokemon_schedule row; individual
games (pokemon_match_games) and per-Pokemon K/D (pokemon_match_stats) are
source-agnostic -- this phase only ever writes them from a hand-typed
report ('manual' entry_method); a later phase adds Showdown replay
parsing as an alternate way to populate the exact same rows without
touching this state machine at all.

State machine: unreported -> pending_confirmation (either coach reports)
-> confirmed (the OTHER coach confirms) or disputed (the other coach
disputes, with a reason) -> confirmed again once the commissioner
resolves the dispute by submitting the authoritative result.
"""
from app.pokemon_draft import roster


def get_match(conn, match_id):
    return conn.execute(
        """SELECT m.*, s.season_id, s.week, s.coach_id_home, s.coach_id_away,
                  ch.team_name AS home_team, ch.user_id AS home_user_id,
                  ca.team_name AS away_team, ca.user_id AS away_user_id
           FROM pokemon_matches m
           JOIN pokemon_schedule s ON s.schedule_id = m.schedule_id
           JOIN pokemon_season_coaches ch ON ch.coach_id = s.coach_id_home
           JOIN pokemon_season_coaches ca ON ca.coach_id = s.coach_id_away
           WHERE m.match_id = ?""",
        (match_id,),
    ).fetchone()


def get_match_for_schedule(conn, schedule_id):
    row = conn.execute("SELECT match_id FROM pokemon_matches WHERE schedule_id = ?", (schedule_id,)).fetchone()
    return get_match(conn, row["match_id"]) if row else None


def get_games(conn, match_id):
    return conn.execute(
        "SELECT * FROM pokemon_match_games WHERE match_id = ? ORDER BY game_num", (match_id,)
    ).fetchall()


def get_stats(conn, game_id):
    return conn.execute(
        """SELECT ms.*, p.display_name FROM pokemon_match_stats ms
           JOIN pokemon p ON p.pokemon_id = ms.pokemon_id
           WHERE ms.game_id = ?""",
        (game_id,),
    ).fetchall()


def coach_in_match(match, user_id):
    """The coach_id this user is in this matchup, or None if they aren't
    one of the two coaches."""
    if match["home_user_id"] == user_id:
        return match["coach_id_home"]
    if match["away_user_id"] == user_id:
        return match["coach_id_away"]
    return None


def _series_winner(match, games):
    """The coach_id who won the majority of games, or (None, error) if
    the submitted games don't add up to a valid Bo3 result."""
    if not 1 <= len(games) <= 3:
        return None, "A series needs 1 to 3 games reported."
    home_wins = sum(1 for g in games if g["winner_coach_id"] == match["coach_id_home"])
    away_wins = sum(1 for g in games if g["winner_coach_id"] == match["coach_id_away"])
    if home_wins + away_wins != len(games):
        return None, "Every game needs a winner from this matchup."
    if home_wins == away_wins:
        return None, "The series needs a clear winner -- games can't tie."
    return (match["coach_id_home"] if home_wins > away_wins else match["coach_id_away"]), None


def _write_result(conn, match_id, games):
    """Replaces this match's games/stats with `games` -- used by both the
    first report and a commissioner's dispute-resolution override.
    games: [{"winner_coach_id": int, "stats": [{"coach_id", "pokemon_id",
    "kills", "deaths"}, ...]}, ...]. Returns (winner_coach_id, None) on
    success or (None, error string) without writing anything."""
    match = get_match(conn, match_id)
    winner, error = _series_winner(match, games)
    if error:
        return None, error

    roster_by_coach = {
        match["coach_id_home"]: {r["pokemon_id"] for r in roster.current_roster(
            conn, match["season_id"], match["coach_id_home"])},
        match["coach_id_away"]: {r["pokemon_id"] for r in roster.current_roster(
            conn, match["season_id"], match["coach_id_away"])},
    }
    for g in games:
        for s in g["stats"]:
            if s["coach_id"] not in roster_by_coach:
                return None, "A stat entry referenced a coach not in this matchup."
            if s["pokemon_id"] not in roster_by_coach[s["coach_id"]]:
                return None, "A stat entry referenced a Pokemon not on that coach's roster."

    conn.execute(
        "DELETE FROM pokemon_match_stats WHERE game_id IN "
        "(SELECT game_id FROM pokemon_match_games WHERE match_id = ?)", (match_id,))
    conn.execute("DELETE FROM pokemon_match_games WHERE match_id = ?", (match_id,))
    for i, g in enumerate(games, start=1):
        cur = conn.execute(
            "INSERT INTO pokemon_match_games (match_id, game_num, entry_method, winner_coach_id) "
            "VALUES (?, ?, 'manual', ?)",
            (match_id, i, g["winner_coach_id"]),
        )
        game_id = cur.lastrowid
        for s in g["stats"]:
            conn.execute(
                "INSERT INTO pokemon_match_stats (game_id, coach_id, pokemon_id, kills, deaths) "
                "VALUES (?, ?, ?, ?, ?)",
                (game_id, s["coach_id"], s["pokemon_id"], s["kills"], s["deaths"]),
            )
    return winner, None


def report_match(conn, match_id, reporting_user_id, games):
    """None on success, or an error string."""
    match = get_match(conn, match_id)
    if match is None:
        return "No such match."
    if match["status"] != "unreported":
        return "This match has already been reported."
    if coach_in_match(match, reporting_user_id) is None:
        return "You're not one of the coaches in this matchup."

    winner, error = _write_result(conn, match_id, games)
    if error:
        return error
    conn.execute(
        """UPDATE pokemon_matches SET status = 'pending_confirmation', reported_by_user_id = ?,
               winner_coach_id = ? WHERE match_id = ?""",
        (reporting_user_id, winner, match_id),
    )
    conn.commit()
    return None


def confirm_match(conn, match_id, confirming_user_id):
    """None on success, or an error string."""
    match = get_match(conn, match_id)
    if match is None:
        return "No such match."
    if match["status"] != "pending_confirmation":
        return "This match isn't waiting on a confirmation right now."
    if coach_in_match(match, confirming_user_id) is None:
        return "You're not one of the coaches in this matchup."
    if confirming_user_id == match["reported_by_user_id"]:
        return "The other coach needs to confirm this result, not you."
    conn.execute(
        "UPDATE pokemon_matches SET status = 'confirmed', confirmed_at = datetime('now') WHERE match_id = ?",
        (match_id,),
    )
    conn.commit()
    return None


def dispute_match(conn, match_id, disputing_user_id, reason):
    """None on success, or an error string."""
    match = get_match(conn, match_id)
    if match is None:
        return "No such match."
    if match["status"] != "pending_confirmation":
        return "This match isn't waiting on a confirmation right now."
    if coach_in_match(match, disputing_user_id) is None:
        return "You're not one of the coaches in this matchup."
    if disputing_user_id == match["reported_by_user_id"]:
        return "You reported this result -- the other coach is the one who can dispute it."
    if not reason or not reason.strip():
        return "Say why you're disputing this result."
    conn.execute(
        "UPDATE pokemon_matches SET status = 'disputed', dispute_reason = ? WHERE match_id = ?",
        (reason.strip(), match_id),
    )
    conn.commit()
    return None


def resolve_dispute(conn, match_id, commissioner_user_id, note, games):
    """None on success, or an error string. The commissioner submits the
    authoritative result (same shape report_match takes), replacing
    whatever was reported before."""
    match = get_match(conn, match_id)
    if match is None:
        return "No such match."
    if match["status"] != "disputed":
        return "This match isn't disputed."
    winner, error = _write_result(conn, match_id, games)
    if error:
        return error
    conn.execute(
        """UPDATE pokemon_matches SET status = 'confirmed', winner_coach_id = ?,
               confirmed_at = datetime('now'), dispute_resolved_by = ?, dispute_resolution_note = ?
           WHERE match_id = ?""",
        (winner, commissioner_user_id, note, match_id),
    )
    conn.commit()
    return None
