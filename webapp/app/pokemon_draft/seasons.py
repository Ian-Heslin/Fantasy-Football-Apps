"""Format/season/coach CRUD for the Pokemon Draft League -- see
schema/sqlite_schema.sql's pokemon_formats/pokemon_seasons/
pokemon_season_coaches comments for the shape this operates on.

A season's ruleset (roster_size_cap, point_budget, species_clause_enabled,
fa_transactions_allowed, roster_freeze_week, playoff_bracket_size) and its
coach list are only editable before its draft locks (draft_locked_at IS
NULL) -- once picking can start, changing the budget or roster out from
under an in-progress draft would leave already-made picks retroactively
illegal.
"""


def list_formats(conn):
    return conn.execute("SELECT * FROM pokemon_formats ORDER BY display_name").fetchall()


def get_format(conn, format_id):
    return conn.execute("SELECT * FROM pokemon_formats WHERE format_id = ?", (format_id,)).fetchone()


def create_format(conn, format_id, display_name, battle_style, rules_text,
                   default_roster_size, default_point_budget, default_species_clause):
    """None on success, or an error string."""
    if battle_style not in ("singles", "doubles"):
        return "Battle style must be 'singles' or 'doubles'."
    if not format_id or not format_id.strip():
        return "Format needs an id."
    if get_format(conn, format_id) is not None:
        return f"A format called '{format_id}' already exists."
    conn.execute(
        """INSERT INTO pokemon_formats
               (format_id, display_name, battle_style, rules_text,
                default_roster_size, default_point_budget, default_species_clause)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (format_id.strip(), display_name, battle_style, rules_text,
         default_roster_size, default_point_budget, int(default_species_clause)),
    )
    conn.commit()
    return None


def list_seasons(conn):
    """Newest first -- the archive view."""
    return conn.execute(
        """SELECT s.*, f.display_name AS format_name, f.battle_style, u.username AS commissioner_name
           FROM pokemon_seasons s
           JOIN pokemon_formats f ON f.format_id = s.format_id
           JOIN users u ON u.user_id = s.commissioner_user_id
           ORDER BY s.created_at DESC"""
    ).fetchall()


def get_season(conn, season_id):
    return conn.execute(
        """SELECT s.*, f.display_name AS format_name, f.battle_style, f.rules_text AS format_rules_text,
                  u.username AS commissioner_name
           FROM pokemon_seasons s
           JOIN pokemon_formats f ON f.format_id = s.format_id
           JOIN users u ON u.user_id = s.commissioner_user_id
           WHERE s.season_id = ?""",
        (season_id,),
    ).fetchone()


def active_season(conn):
    return conn.execute("SELECT * FROM pokemon_seasons WHERE status = 'active'").fetchone()


def create_season(conn, name, format_id, commissioner_user_id):
    """(season_id, None) on success, or (None, error string)."""
    fmt = get_format(conn, format_id)
    if fmt is None:
        return None, "Unknown format."
    if not name or not name.strip():
        return None, "Season needs a name."
    cur = conn.execute(
        """INSERT INTO pokemon_seasons
               (name, format_id, commissioner_user_id, status, roster_size_cap,
                point_budget, species_clause_enabled)
           VALUES (?, ?, ?, 'draft', ?, ?, ?)""",
        (name.strip(), format_id, commissioner_user_id,
         fmt["default_roster_size"], fmt["default_point_budget"], fmt["default_species_clause"]),
    )
    conn.commit()
    return cur.lastrowid, None


def update_ruleset(conn, season_id, roster_size_cap, point_budget, species_clause_enabled,
                    fa_transactions_allowed, roster_freeze_week, playoff_bracket_size):
    """None on success, or an error string."""
    season = get_season(conn, season_id)
    if season is None:
        return "No such season."
    if season["draft_locked_at"]:
        return "The draft board is locked -- the ruleset can no longer be changed."
    conn.execute(
        """UPDATE pokemon_seasons SET
               roster_size_cap = ?, point_budget = ?, species_clause_enabled = ?,
               fa_transactions_allowed = ?, roster_freeze_week = ?, playoff_bracket_size = ?
           WHERE season_id = ?""",
        (roster_size_cap, point_budget, int(species_clause_enabled),
         fa_transactions_allowed, roster_freeze_week, playoff_bracket_size, season_id),
    )
    conn.commit()
    return None


def activate_season(conn, season_id):
    """None on success, or an error string. The DB's own unique partial
    index on pokemon_seasons(status) WHERE status='active' enforces the
    one-active-season invariant too, but that surfaces as a raw
    IntegrityError -- this check gives a clean message first."""
    other = active_season(conn)
    if other is not None and other["season_id"] != season_id:
        return f"'{other['name']}' is already the active season -- archive or complete it first."
    conn.execute("UPDATE pokemon_seasons SET status = 'active' WHERE season_id = ?", (season_id,))
    conn.commit()
    return None


def archive_season(conn, season_id):
    """Archiving works from any status, including 'active' -- a
    commissioner ending a season early shouldn't have to route through
    'complete' first, and the one-active-season unique index only
    requires at most one active season, never exactly one."""
    conn.execute(
        "UPDATE pokemon_seasons SET status = 'archived' WHERE season_id = ?",
        (season_id,),
    )
    conn.commit()


def complete_season(conn, season_id):
    conn.execute("UPDATE pokemon_seasons SET status = 'complete' WHERE season_id = ?", (season_id,))
    conn.commit()


def lock_draft_board(conn, season_id):
    conn.execute(
        """UPDATE pokemon_seasons SET draft_locked_at = datetime('now')
           WHERE season_id = ? AND draft_locked_at IS NULL""",
        (season_id,),
    )
    conn.execute(
        "INSERT INTO pokemon_draft_sessions (season_id) VALUES (?) ON CONFLICT(season_id) DO NOTHING",
        (season_id,),
    )
    conn.commit()


def list_coaches(conn, season_id):
    return conn.execute(
        """SELECT c.*, u.username FROM pokemon_season_coaches c
           JOIN users u ON u.user_id = c.user_id
           WHERE c.season_id = ? ORDER BY c.draft_order IS NULL, c.draft_order, c.team_name""",
        (season_id,),
    ).fetchall()


def coach_seat_for(conn, season_id, user_id):
    """This user's coach row in a season, or None if they aren't a coach here."""
    return conn.execute(
        "SELECT * FROM pokemon_season_coaches WHERE season_id = ? AND user_id = ?",
        (season_id, user_id),
    ).fetchone()


def add_coach(conn, season_id, user_id, team_name):
    """None on success, or an error string."""
    season = get_season(conn, season_id)
    if season is None:
        return "No such season."
    if season["draft_locked_at"]:
        return "The draft board is locked -- coaches can no longer be added."
    if not team_name or not team_name.strip():
        return "Team needs a name."
    if coach_seat_for(conn, season_id, user_id) is not None:
        return "That coach already has a seat this season."
    conn.execute(
        "INSERT INTO pokemon_season_coaches (season_id, user_id, team_name) VALUES (?, ?, ?)",
        (season_id, user_id, team_name.strip()),
    )
    conn.commit()
    return None


def remove_coach(conn, season_id, coach_id):
    """None on success, or an error string."""
    season = get_season(conn, season_id)
    if season is None:
        return "No such season."
    if season["draft_locked_at"]:
        return "The draft board is locked -- coaches can no longer be removed."
    conn.execute(
        "DELETE FROM pokemon_season_coaches WHERE season_id = ? AND coach_id = ?",
        (season_id, coach_id),
    )
    conn.commit()
    return None


def set_draft_order(conn, season_id, ordered_coach_ids):
    """Assigns draft_order 1..N following ordered_coach_ids. None on
    success, or an error string."""
    coaches = {c["coach_id"] for c in list_coaches(conn, season_id)}
    if set(ordered_coach_ids) != coaches or len(ordered_coach_ids) != len(coaches):
        return "Draft order must include every coach in this season exactly once."
    for i, coach_id in enumerate(ordered_coach_ids, start=1):
        conn.execute(
            "UPDATE pokemon_season_coaches SET draft_order = ? WHERE season_id = ? AND coach_id = ?",
            (i, season_id, coach_id),
        )
    conn.commit()
    return None
