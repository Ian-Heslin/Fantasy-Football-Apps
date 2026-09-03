"""Group mode for the reveal-style trivia games (Award Winners, Season
Leaders, NFL Top 100) -- a live, shared-screen, host-run session, closer
to how the original spreadsheet was played than the async Solo version.

One browser (the host's) drives the whole session: participants are
free-text names, not site accounts, since everyone's physically in the
same room and only the host needs to be logged in. The host reads each
clue aloud, marks who got it right, and moves to the next one -- no
per-participant device or real-time sync needed for this version (a
per-phone live version is a bigger follow-up project, not this one).

Reuses app.trivia.build_pool() for the actual questions, so a category's
content can never drift between the Solo and Group versions of the same
game.
"""
import random

from app import trivia

GAME_LABELS = {
    "award_winners": "Award Winners", "season_leaders": "Season Leaders", "nfl_top100": "NFL Top 100",
}

# Bounds on the participant list. This is a shared-screen party game --
# two people minimum, and a couple of dozen is already more than fits on
# one screen -- but the endpoint takes a comma-separated field, so
# without a cap a single scripted POST inserts a row per name. That's
# disk on the Pi's SD card (and in every hourly backup after it), and
# CPU too: whose_turn()/standings() run a query per participant on every
# render of the session. Names are truncated rather than rejected -- a
# 200-character name is a paste accident, not something to fail on.
MIN_PARTICIPANTS = 2
MAX_PARTICIPANTS = 24
MAX_PARTICIPANT_NAME = 40


def clean_participant_names(raw):
    """Parse the comma-separated participants field into a bounded list.

    Returns (names, error) -- error is None when the list is usable."""
    names = [n.strip()[:MAX_PARTICIPANT_NAME] for n in (raw or "").split(",") if n.strip()]
    if len(names) < MIN_PARTICIPANTS:
        return [], f"A group game needs at least {MIN_PARTICIPANTS} participants."
    if len(names) > MAX_PARTICIPANTS:
        return [], f"A group game can have at most {MAX_PARTICIPANTS} participants."
    return names, None


def start_session(conn, duckdb_conn, host_user_id, game_type, category, participant_names, hints=None):
    pool = trivia.build_pool(duckdb_conn, game_type, category, hints)
    if not pool:
        return None
    sample = random.sample(pool, k=min(trivia.ROUND_SIZE, len(pool)))

    cur = conn.execute(
        "INSERT INTO group_sessions (host_user_id, game_type, category) VALUES (?, ?, ?)",
        (host_user_id, game_type, category),
    )
    session_id = cur.lastrowid
    conn.executemany(
        """INSERT INTO group_items (session_id, item_key, sort_order, prompt_label, correct_answer)
           VALUES (?, ?, ?, ?, ?)""",
        [(session_id, item_key, i, prompt, answer) for i, (item_key, prompt, answer) in enumerate(sample)],
    )
    conn.executemany(
        "INSERT INTO group_participants (session_id, participant_id, name) VALUES (?, ?, ?)",
        [(session_id, i, name) for i, name in enumerate(participant_names, start=1)],
    )
    conn.commit()
    return session_id


def get_session(conn, session_id, host_user_id):
    return conn.execute(
        "SELECT * FROM group_sessions WHERE session_id = ? AND host_user_id = ?", (session_id, host_user_id)
    ).fetchone()


def get_participants(conn, session_id):
    return conn.execute(
        "SELECT * FROM group_participants WHERE session_id = ? ORDER BY participant_id", (session_id,)
    ).fetchall()


def get_items(conn, session_id):
    return conn.execute(
        "SELECT * FROM group_items WHERE session_id = ? ORDER BY sort_order", (session_id,)
    ).fetchall()


def current_item(conn, session_id):
    return conn.execute(
        "SELECT * FROM group_items WHERE session_id = ? AND revealed = 0 ORDER BY sort_order LIMIT 1",
        (session_id,),
    ).fetchone()


def mark_and_reveal(conn, session_id, item_key, correct_participant_ids):
    """correct_participant_ids: the set of participant_ids the host marked
    correct for this item; everyone else in the session gets is_correct=0."""
    participants = get_participants(conn, session_id)
    for p in participants:
        is_correct = 1 if p["participant_id"] in correct_participant_ids else 0
        conn.execute(
            """INSERT INTO group_answers (session_id, item_key, participant_id, is_correct)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(session_id, item_key, participant_id) DO UPDATE SET is_correct=excluded.is_correct""",
            (session_id, item_key, p["participant_id"], is_correct),
        )
    conn.execute(
        "UPDATE group_items SET revealed = 1 WHERE session_id = ? AND item_key = ?", (session_id, item_key)
    )
    if current_item(conn, session_id) is None:
        conn.execute(
            "UPDATE group_sessions SET status = 'completed', completed_at = datetime('now') WHERE session_id = ?",
            (session_id,),
        )
    conn.commit()


def standings(conn, session_id):
    participants = get_participants(conn, session_id)
    total_items = conn.execute(
        "SELECT count(*) FROM group_items WHERE session_id = ?", (session_id,)
    ).fetchone()[0]
    results = []
    for p in participants:
        correct = conn.execute(
            "SELECT count(*) FROM group_answers WHERE session_id = ? AND participant_id = ? AND is_correct = 1",
            (session_id, p["participant_id"]),
        ).fetchone()[0]
        results.append({"participant_id": p["participant_id"], "name": p["name"], "correct": correct,
                         "total": total_items})
    results.sort(key=lambda r: r["correct"], reverse=True)
    for i, r in enumerate(results, start=1):
        r["rank"] = i
    return results


def active_sessions(conn, host_user_id):
    return conn.execute(
        """SELECT * FROM group_sessions WHERE host_user_id = ? AND status = 'active'
           AND game_type != 'fantasy_draft' ORDER BY created_at DESC""",
        (host_user_id,),
    ).fetchall()
