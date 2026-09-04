"""Regular-season schedule generation and lookups. Playoff rounds (the
same pokemon_schedule table, with `round` set instead of `week`) are a
later phase -- this module only ever writes/reads week-numbered rows.

Uses the standard "circle method" round robin: with N coaches (a bye slot
added if N is odd), N-1 rounds pair every coach against every other coach
exactly once. A season's configured number of weeks can be shorter (a
partial round robin) or longer (cycles back through the same round-robin
sequence) than N-1 -- matches the source league's own "you'll play your
division twice and everyone else once"-style asymmetry in spirit, without
this phase needing to model divisions at all (explicitly out of scope for
now).
"""
from app.pokemon_draft import seasons


def round_robin_rounds(coach_ids):
    """[[(home_coach_id, away_coach_id_or_None), ...], ...] -- one list of
    pairs per round, N-1 rounds for N coaches (N rounds if N is odd, one
    of which is a fixed bye each round). away is None for a bye -- home is
    always a real coach id, never the bye slot itself."""
    ids = list(coach_ids)
    if len(ids) < 2:
        return []  # a single (real) coach has no one to play, bye or otherwise
    if len(ids) % 2 == 1:
        ids.append(None)
    n = len(ids)

    rounds = []
    for _ in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = ids[i], ids[n - 1 - i]
            if a is None and b is None:
                continue
            if a is None:
                a, b = b, a
            pairs.append((a, b))
        rounds.append(pairs)
        ids = [ids[0]] + [ids[-1]] + ids[1:-1]
    return rounds


def has_schedule(conn, season_id):
    return conn.execute(
        "SELECT 1 FROM pokemon_schedule WHERE season_id = ? AND week IS NOT NULL LIMIT 1", (season_id,)
    ).fetchone() is not None


def generate_schedule(conn, season_id, num_weeks):
    """(rows_created, None) on success, or (0, error string)."""
    season = seasons.get_season(conn, season_id)
    if season is None:
        return 0, "No such season."
    if has_schedule(conn, season_id):
        return 0, "This season already has a schedule -- clear it first."
    if num_weeks < 1:
        return 0, "Need at least 1 week."
    coaches = seasons.list_coaches(conn, season_id)
    if len(coaches) < 2:
        return 0, "Need at least 2 coaches to generate a schedule."

    rounds = round_robin_rounds([c["coach_id"] for c in coaches])
    created = 0
    for week in range(1, num_weeks + 1):
        pairs = rounds[(week - 1) % len(rounds)]
        for home, away in pairs:
            cur = conn.execute(
                "INSERT INTO pokemon_schedule (season_id, week, coach_id_home, coach_id_away) "
                "VALUES (?, ?, ?, ?)",
                (season_id, week, home, away),
            )
            created += 1
            if away is not None:
                conn.execute(
                    "INSERT INTO pokemon_matches (schedule_id) VALUES (?)", (cur.lastrowid,)
                )
    conn.commit()
    return created, None


def clear_schedule(conn, season_id):
    """None on success, or an error string. Refuses once any match has a
    reported result, so a commissioner can't accidentally wipe real games."""
    reported = conn.execute(
        """SELECT count(*) c FROM pokemon_matches m
           JOIN pokemon_schedule s ON s.schedule_id = m.schedule_id
           WHERE s.season_id = ? AND m.status != 'unreported'""",
        (season_id,),
    ).fetchone()["c"]
    if reported > 0:
        return "Can't clear the schedule -- some matches have already been reported."
    conn.execute(
        "DELETE FROM pokemon_matches WHERE schedule_id IN "
        "(SELECT schedule_id FROM pokemon_schedule WHERE season_id = ? AND week IS NOT NULL)",
        (season_id,),
    )
    conn.execute("DELETE FROM pokemon_schedule WHERE season_id = ? AND week IS NOT NULL", (season_id,))
    conn.commit()
    return None


def overview(conn, season_id):
    """Every regular-season schedule row, with match status and team
    names, grouped implicitly by week (ORDER BY week -- caller groups)."""
    return conn.execute(
        """SELECT sc.schedule_id, sc.week, sc.coach_id_home, sc.coach_id_away,
                  ch.team_name AS home_team, ca.team_name AS away_team,
                  m.match_id, m.status
           FROM pokemon_schedule sc
           JOIN pokemon_season_coaches ch ON ch.coach_id = sc.coach_id_home
           LEFT JOIN pokemon_season_coaches ca ON ca.coach_id = sc.coach_id_away
           LEFT JOIN pokemon_matches m ON m.schedule_id = sc.schedule_id
           WHERE sc.season_id = ? AND sc.week IS NOT NULL
           ORDER BY sc.week, sc.schedule_id""",
        (season_id,),
    ).fetchall()
