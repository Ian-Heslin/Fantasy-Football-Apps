"""Season draft pool -- which pokemon are legal to draft and what they
cost. See schema/sqlite_schema.sql's pokemon_draft_pool comment: computed
cost (app/pokemon_draft/points.py's usage-based engine) and cost_override
(commissioner hand-edit) are separate columns so a later re-fetch can't
clobber a manual edit -- effective_cost() is COALESCE(cost_override,
computed_cost). Note this cuts both ways: add_to_pool()/
add_generation_to_pool() below both accept an optional cost that, if
given, lands in cost_override -- pass None (no cost yet) for any pool
entry that's meant to be priced later by points.fetch_and_apply(), since
a non-None value here permanently shadows a later computed_cost fetch.
"""
from app.pokemon_draft import seasons


def list_pool(conn, season_id):
    return conn.execute(
        """SELECT dp.*, p.slug, p.display_name, p.type1, p.type2, p.sprite_url,
                  p.generation, p.national_dex_number,
                  COALESCE(dp.cost_override, dp.computed_cost) AS effective_cost,
                  (pick.pokemon_id IS NOT NULL) AS is_drafted
           FROM pokemon_draft_pool dp
           JOIN pokemon p ON p.pokemon_id = dp.pokemon_id
           LEFT JOIN pokemon_draft_picks pick
                  ON pick.season_id = dp.season_id AND pick.pokemon_id = dp.pokemon_id
           WHERE dp.season_id = ?
           ORDER BY p.national_dex_number, p.pokemon_id""",
        (season_id,),
    ).fetchall()


def pool_base_query(season_id, query=None):
    """(sql, params) for a season's non-banned pool entries joined with
    display columns and optionally name-filtered -- the WHERE clause
    returned has no trailing ORDER BY, so a caller can AND in its own
    "already taken" exclusion before sorting. Shared by undrafted() below
    and roster.available_for_fa(), which differ only in what counts as
    already taken (permanent draft-pick history here vs. the live roster
    ledger there) -- kept as two callers rather than one merged function
    since unifying that exclusion would mean re-deriving "current roster"
    in raw SQL instead of reusing roster.current_roster()'s single
    window-function implementation of it."""
    sql = """
        SELECT dp.*, p.slug, p.display_name, p.type1, p.type2, p.sprite_url, p.national_dex_number,
               COALESCE(dp.cost_override, dp.computed_cost) AS effective_cost
        FROM pokemon_draft_pool dp
        JOIN pokemon p ON p.pokemon_id = dp.pokemon_id
        WHERE dp.season_id = ? AND dp.is_banned = 0
    """
    params = [season_id]
    if query:
        sql += " AND p.display_name LIKE ?"
        params.append(f"%{query}%")
    return sql, params


def undrafted(conn, season_id, query=None):
    """Pool entries still available to pick -- not banned, not already
    drafted. Used by the draft room's pick list."""
    sql, params = pool_base_query(season_id, query)
    sql += (" AND dp.pokemon_id NOT IN "
            "(SELECT pokemon_id FROM pokemon_draft_picks WHERE season_id = dp.season_id)"
            " ORDER BY effective_cost DESC, p.national_dex_number")
    return conn.execute(sql, params).fetchall()


def get_pool_entry(conn, season_id, pokemon_id):
    return conn.execute(
        "SELECT * FROM pokemon_draft_pool WHERE season_id = ? AND pokemon_id = ?",
        (season_id, pokemon_id),
    ).fetchone()


def effective_cost(pool_row):
    return pool_row["cost_override"] if pool_row["cost_override"] is not None else pool_row["computed_cost"]


def _require_unlocked(conn, season_id):
    season = seasons.get_season(conn, season_id)
    if season is None:
        return "No such season."
    if season["draft_locked_at"]:
        return "The draft board is locked -- the pool can no longer be changed."
    return None


def add_to_pool(conn, season_id, pokemon_id, cost_override=None):
    """None on success, or an error string."""
    error = _require_unlocked(conn, season_id)
    if error:
        return error
    if get_pool_entry(conn, season_id, pokemon_id) is not None:
        return "That Pokemon is already in the pool."
    conn.execute(
        "INSERT INTO pokemon_draft_pool (season_id, pokemon_id, cost_override) VALUES (?, ?, ?)",
        (season_id, pokemon_id, cost_override),
    )
    conn.commit()
    return None


def add_generation_to_pool(conn, season_id, generation, default_cost=None):
    """Bulk-adds every not-yet-pooled pokemon of one generation. default_cost
    is optional: pass a flat cost for a season pricing everything by hand,
    or leave it None to add the generation unpriced so a later
    points.fetch_and_apply() usage-stat fetch can price it -- a non-None
    default_cost lands in cost_override same as a hand-typed price, and
    since effective_cost() is COALESCE(cost_override, computed_cost), a
    set cost_override permanently shadows any later computed_cost fetch.
    Returns (count_added, error)."""
    error = _require_unlocked(conn, season_id)
    if error:
        return 0, error
    rows = conn.execute(
        """SELECT pokemon_id FROM pokemon WHERE generation = ?
           AND pokemon_id NOT IN (SELECT pokemon_id FROM pokemon_draft_pool WHERE season_id = ?)""",
        (generation, season_id),
    ).fetchall()
    conn.executemany(
        "INSERT INTO pokemon_draft_pool (season_id, pokemon_id, cost_override) VALUES (?, ?, ?)",
        [(season_id, r["pokemon_id"], default_cost) for r in rows],
    )
    conn.commit()
    return len(rows), None


def remove_from_pool(conn, season_id, pokemon_id):
    """None on success, or an error string."""
    error = _require_unlocked(conn, season_id)
    if error:
        return error
    conn.execute(
        "DELETE FROM pokemon_draft_pool WHERE season_id = ? AND pokemon_id = ?",
        (season_id, pokemon_id),
    )
    conn.commit()
    return None


def set_ban(conn, season_id, pokemon_id, banned):
    """None on success, or an error string."""
    error = _require_unlocked(conn, season_id)
    if error:
        return error
    conn.execute(
        "UPDATE pokemon_draft_pool SET is_banned = ? WHERE season_id = ? AND pokemon_id = ?",
        (int(banned), season_id, pokemon_id),
    )
    conn.commit()
    return None


def set_cost_override(conn, season_id, pokemon_id, cost):
    """None on success, or an error string. cost=None clears the override
    back to letting computed_cost (a Smogon usage-stat fetch) drive
    effective_cost() again."""
    error = _require_unlocked(conn, season_id)
    if error:
        return error
    conn.execute(
        "UPDATE pokemon_draft_pool SET cost_override = ? WHERE season_id = ? AND pokemon_id = ?",
        (cost, season_id, pokemon_id),
    )
    conn.commit()
    return None
