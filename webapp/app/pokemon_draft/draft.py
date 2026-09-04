"""Live snake draft. See app/group_draft.py for the turn/legality shape
this mirrors -- whose_turn()/make_pick() returning None or an error
string, nothing saved on error, whose_turn() re-derived fresh from the DB
on every call so SQLite's serialized-writer model (see app/db.py's
BUSY_TIMEOUT_SECONDS) keeps concurrent picks race-safe.

Differs from group_draft.py in exactly one load-bearing way: every coach
submits their OWN pick from their OWN account -- there is no host who
enters every pick on everyone's behalf, so make_pick() checks the
submitting user against the coach whose turn it actually is.

Snake order needs no per-slot bookkeeping the way group_draft.py's
fantasy-draft slots do: every coach picks exactly
season['roster_size_cap'] times, so turn_index alone (0-based, total =
n_coaches * roster_size_cap) determines both whose turn it is and how many
rounds remain.
"""
from app.pokemon_draft import draft_pool, roster, seasons


def get_session(conn, season_id):
    return conn.execute(
        "SELECT * FROM pokemon_draft_sessions WHERE season_id = ?", (season_id,)
    ).fetchone()


def _draft_order(conn, season_id):
    return [c for c in seasons.list_coaches(conn, season_id) if c["draft_order"] is not None]


def start_draft(conn, season_id):
    """None on success, or an error string."""
    season = seasons.get_season(conn, season_id)
    if season is None:
        return "No such season."
    if not season["draft_locked_at"]:
        return "Lock the draft board first."
    coaches = seasons.list_coaches(conn, season_id)
    if not coaches:
        return "Add coaches before starting the draft."
    if any(c["draft_order"] is None for c in coaches):
        return "Set a draft order for every coach first."
    session = get_session(conn, season_id)
    if session is None:
        return "No draft session for this season -- lock the draft board again."
    if session["status"] != "not_started":
        return "The draft has already started."
    conn.execute(
        """UPDATE pokemon_draft_sessions SET status = 'in_progress', started_at = datetime('now')
           WHERE season_id = ?""",
        (season_id,),
    )
    conn.commit()
    return None


def whose_turn(conn, season_id):
    """{coach, pick_number, round, pick_in_round} for the next pick, or
    None if the draft isn't running or is already complete. Snake order:
    round 0 goes coaches 1..N in draft_order, round 1 goes N..1, etc."""
    season = seasons.get_season(conn, season_id)
    session = get_session(conn, season_id)
    if season is None or session is None or session["status"] != "in_progress":
        return None
    coaches = _draft_order(conn, season_id)
    n = len(coaches)
    if n == 0:
        return None
    total_picks = n * season["roster_size_cap"]
    turn_index = session["turn_index"]
    if turn_index >= total_picks:
        return None

    round_num = turn_index // n
    pos_in_round = turn_index % n
    order_index = pos_in_round if round_num % 2 == 0 else (n - 1 - pos_in_round)
    return {
        "coach": coaches[order_index], "pick_number": turn_index + 1,
        "round": round_num + 1, "pick_in_round": pos_in_round + 1,
    }


def drafted_species_ids(conn, season_id):
    return {
        r["species_id"] for r in conn.execute(
            """SELECT p.species_id FROM pokemon_draft_picks dp
               JOIN pokemon p ON p.pokemon_id = dp.pokemon_id
               WHERE dp.season_id = ?""",
            (season_id,),
        ).fetchall()
    }


def board(conn, season_id):
    """Every pick made so far, in order -- the live draft board."""
    return conn.execute(
        """SELECT dp.*, p.display_name, p.sprite_url, p.type1, p.type2,
                  c.team_name, u.username
           FROM pokemon_draft_picks dp
           JOIN pokemon p ON p.pokemon_id = dp.pokemon_id
           JOIN pokemon_season_coaches c ON c.coach_id = dp.coach_id
           JOIN users u ON u.user_id = c.user_id
           WHERE dp.season_id = ?
           ORDER BY dp.pick_order""",
        (season_id,),
    ).fetchall()


def make_pick(conn, season_id, submitting_user_id, pokemon_id):
    """None on success, or an error string -- nothing is saved on error."""
    season = seasons.get_season(conn, season_id)
    if season is None:
        return "No such season."

    turn = whose_turn(conn, season_id)
    if turn is None:
        return "The draft isn't running right now."
    coach = turn["coach"]
    if submitting_user_id != coach["user_id"]:
        return "It's not your turn."

    pool_entry = draft_pool.get_pool_entry(conn, season_id, pokemon_id)
    if pool_entry is None:
        return "That Pokemon isn't in this season's draft pool."
    if pool_entry["is_banned"]:
        return "That Pokemon is banned this season."

    already_picked = conn.execute(
        "SELECT 1 FROM pokemon_draft_picks WHERE season_id = ? AND pokemon_id = ?",
        (season_id, pokemon_id),
    ).fetchone()
    if already_picked is not None:
        return "That Pokemon has already been drafted."

    if season["species_clause_enabled"]:
        pokemon = conn.execute(
            "SELECT species_id FROM pokemon WHERE pokemon_id = ?", (pokemon_id,)
        ).fetchone()
        if pokemon["species_id"] in drafted_species_ids(conn, season_id):
            return "Species clause: a different form of that Pokemon is already drafted this season."

    cost = draft_pool.effective_cost(pool_entry)
    if cost is None:
        return "That Pokemon doesn't have a point cost set yet."

    count, spent = roster.roster_summary(conn, season_id, coach["coach_id"])
    if count >= season["roster_size_cap"]:
        return f"{coach['team_name']}'s roster is already full."
    if spent + cost > season["point_budget"]:
        return (f"Not enough budget: {cost} points would put {coach['team_name']} over "
                f"the {season['point_budget']}-point cap ({spent} already spent).")

    pick_order = turn["pick_number"]
    conn.execute(
        """INSERT INTO pokemon_draft_picks (season_id, coach_id, pokemon_id, pick_order, cost_paid)
           VALUES (?, ?, ?, ?, ?)""",
        (season_id, coach["coach_id"], pokemon_id, pick_order, cost),
    )
    conn.execute(
        """INSERT INTO pokemon_roster_moves (season_id, coach_id, pokemon_id, move_type, cost)
           VALUES (?, ?, ?, 'draft', ?)""",
        (season_id, coach["coach_id"], pokemon_id, cost),
    )
    conn.execute(
        "UPDATE pokemon_draft_sessions SET turn_index = turn_index + 1 WHERE season_id = ?",
        (season_id,),
    )
    if whose_turn(conn, season_id) is None:
        conn.execute(
            """UPDATE pokemon_draft_sessions SET status = 'complete', completed_at = datetime('now')
               WHERE season_id = ?""",
            (season_id,),
        )
    conn.commit()
    return None
