"""Season draft pool -- which pokemon are legal to draft and what they
cost. See schema/sqlite_schema.sql's pokemon_draft_pool comment: computed
cost (Phase 4's usage-based engine, not built yet) and cost_override
(commissioner hand-edit) are separate columns so a later re-fetch can't
clobber a manual edit -- effective_cost() is COALESCE(cost_override,
computed_cost). This phase has no automated cost engine yet, so every
pool entry's cost is entered by hand as an override.
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


def undrafted(conn, season_id, query=None):
    """Pool entries still available to pick -- not banned, not already
    drafted. Used by the draft room's pick list."""
    sql = """
        SELECT dp.*, p.slug, p.display_name, p.type1, p.type2, p.sprite_url, p.national_dex_number,
               COALESCE(dp.cost_override, dp.computed_cost) AS effective_cost
        FROM pokemon_draft_pool dp
        JOIN pokemon p ON p.pokemon_id = dp.pokemon_id
        WHERE dp.season_id = ? AND dp.is_banned = 0
          AND dp.pokemon_id NOT IN (
              SELECT pokemon_id FROM pokemon_draft_picks WHERE season_id = dp.season_id)
    """
    params = [season_id]
    if query:
        sql += " AND p.display_name LIKE ?"
        params.append(f"%{query}%")
    sql += " ORDER BY effective_cost DESC, p.national_dex_number"
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


def add_generation_to_pool(conn, season_id, generation, default_cost):
    """Bulk-adds every not-yet-pooled pokemon of one generation at a flat
    default cost -- the practical way to build a pool by hand before
    Phase 4's usage-based engine exists. Returns (count_added, error)."""
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
    """None on success, or an error string."""
    error = _require_unlocked(conn, season_id)
    if error:
        return error
    conn.execute(
        "UPDATE pokemon_draft_pool SET cost_override = ? WHERE season_id = ? AND pokemon_id = ?",
        (cost, season_id, pokemon_id),
    )
    conn.commit()
    return None
