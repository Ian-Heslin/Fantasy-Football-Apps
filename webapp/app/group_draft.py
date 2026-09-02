"""Group live Fantasy Draft -- a shared-screen, host-run synchronized
draft. Unlike Solo Fantasy Draft, this has real draft-conflict
enforcement (the same year+player can't be taken twice in one session)
and a snake turn order across participants, closer to a real fantasy
draft. The host enters every pick on their own browser on behalf of
whoever's turn it is -- no per-participant device needed for this
version (a per-phone live version is a bigger follow-up project).

Reuses app.fantasy_draft's SLOTS/SLOT_POSITIONS/find_player/suggestions,
so player lookup/matching never drifts from the Solo version.
"""
from app import fantasy_draft
from app.trivia import normalize_name


def start_session(conn, host_user_id, participant_names):
    cur = conn.execute(
        "INSERT INTO group_sessions (host_user_id, game_type, category) VALUES (?, 'fantasy_draft', NULL)",
        (host_user_id,),
    )
    session_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO group_participants (session_id, participant_id, name) VALUES (?, ?, ?)",
        [(session_id, i, name) for i, name in enumerate(participant_names, start=1)],
    )
    conn.commit()
    return session_id


def get_session(conn, session_id, host_user_id):
    return conn.execute(
        "SELECT * FROM group_sessions WHERE session_id = ? AND host_user_id = ? AND game_type = 'fantasy_draft'",
        (session_id, host_user_id),
    ).fetchone()


def get_participants(conn, session_id):
    return conn.execute(
        "SELECT * FROM group_participants WHERE session_id = ? ORDER BY participant_id", (session_id,)
    ).fetchall()


def get_picks(conn, session_id):
    return conn.execute(
        "SELECT * FROM group_draft_picks WHERE session_id = ? ORDER BY pick_order", (session_id,)
    ).fetchall()


def whose_turn(conn, session_id):
    """(participant, open_slots) for the current pick, or None if the
    draft is complete. Snake order: round 0 goes participants 1..N, round
    1 goes N..1, etc., across len(SLOTS) rounds."""
    session = conn.execute("SELECT turn_index FROM group_sessions WHERE session_id = ?", (session_id,)).fetchone()
    participants = get_participants(conn, session_id)
    n = len(participants)
    total_picks = n * len(fantasy_draft.SLOTS)
    turn_index = session["turn_index"]
    if turn_index >= total_picks:
        return None

    round_num = turn_index // n
    pos_in_round = turn_index % n
    order_index = pos_in_round if round_num % 2 == 0 else (n - 1 - pos_in_round)
    participant = participants[order_index]

    filled = {
        r["slot"] for r in conn.execute(
            "SELECT slot FROM group_draft_picks WHERE session_id = ? AND participant_id = ?",
            (session_id, participant["participant_id"]),
        ).fetchall()
    }
    open_slots = [s for s in fantasy_draft.SLOTS if s not in filled]
    return participant, open_slots


def drafted_players(conn, session_id):
    """{(year, normalized_player_name)} already taken in this session."""
    rows = conn.execute(
        "SELECT year, player FROM group_draft_picks WHERE session_id = ?", (session_id,)
    ).fetchall()
    return {(r["year"], normalize_name(r["player"])) for r in rows}


def make_pick(conn, duckdb_conn, session_id, slot, year_raw, player_raw):
    """Returns None on success, or an error message (nothing is saved on
    error)."""
    turn = whose_turn(conn, session_id)
    if turn is None:
        return "This draft is already complete."
    participant, open_slots = turn
    if slot not in open_slots:
        return f"{participant['name']} doesn't have an open {slot} slot."

    try:
        year = int(year_raw)
    except (ValueError, TypeError):
        return f"'{year_raw}' isn't a year."

    match = fantasy_draft.find_player(duckdb_conn, year, player_raw, fantasy_draft.SLOT_POSITIONS[slot])
    if match is None:
        hint = fantasy_draft.suggestions(duckdb_conn, year, player_raw, fantasy_draft.SLOT_POSITIONS[slot])
        return (
            f"No {'/'.join(fantasy_draft.SLOT_POSITIONS[slot])} named '{player_raw}' found in {year}."
            + (f" Did you mean: {', '.join(hint)}?" if hint else "")
        )

    player, team, position, games, ppr_pt = match
    if (year, normalize_name(player)) in drafted_players(conn, session_id):
        return f"{player} ({year}) was already drafted earlier in this session."

    session = conn.execute("SELECT turn_index FROM group_sessions WHERE session_id = ?", (session_id,)).fetchone()
    pick_order = session["turn_index"] + 1
    conn.execute(
        """INSERT INTO group_draft_picks (session_id, participant_id, slot, year, player, points, pick_order)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (session_id, participant["participant_id"], slot, year, player, ppr_pt, pick_order),
    )
    conn.execute("UPDATE group_sessions SET turn_index = turn_index + 1 WHERE session_id = ?", (session_id,))
    if whose_turn(conn, session_id) is None:
        conn.execute(
            "UPDATE group_sessions SET status = 'completed', completed_at = datetime('now') WHERE session_id = ?",
            (session_id,),
        )
    conn.commit()
    return None


def standings(conn, session_id):
    participants = get_participants(conn, session_id)
    results = []
    for p in participants:
        row = conn.execute(
            """SELECT sum(points) AS total, count(*) AS picks_made FROM group_draft_picks
               WHERE session_id = ? AND participant_id = ?""",
            (session_id, p["participant_id"]),
        ).fetchone()
        results.append({
            "participant_id": p["participant_id"], "name": p["name"],
            "total_points": row["total"] or 0, "picks_made": row["picks_made"],
        })
    results.sort(key=lambda r: r["total_points"], reverse=True)
    for i, r in enumerate(results, start=1):
        r["rank"] = i
    return results


def active_sessions(conn, host_user_id):
    return conn.execute(
        """SELECT * FROM group_sessions WHERE host_user_id = ? AND game_type = 'fantasy_draft'
           AND status = 'active' ORDER BY created_at DESC""",
        (host_user_id,),
    ).fetchall()
