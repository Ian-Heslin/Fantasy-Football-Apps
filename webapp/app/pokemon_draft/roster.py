"""Current-roster computation for the Pokemon Draft League -- read-only in
this phase (FA transactions and trades land in a later phase). Reads the
append-only pokemon_roster_moves ledger via a window function rather than
a stored "current roster" table, matching app/pickem.py's
compute-don't-cache philosophy -- see schema/sqlite_schema.sql's
pokemon_roster_moves comment for why.

The window function partitions by pokemon_id ONLY (not also coach_id) --
a pokemon's most recent move might be a 'trade_out' recorded under its
OLD coach, so filtering to one coach's own rows before ranking would miss
that it already left them. coach_id is filtered in the outer query
instead, once ownership is correctly resolved.
"""


def current_roster(conn, season_id, coach_id=None):
    """Every currently-held (coach_id, pokemon_id, cost) row this season,
    or just one coach's if coach_id is given."""
    sql = """
        WITH latest AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY pokemon_id ORDER BY move_id DESC
            ) AS rn
            FROM pokemon_roster_moves WHERE season_id = ?
        )
        SELECT coach_id, pokemon_id, cost FROM latest
        WHERE rn = 1 AND move_type IN ('draft', 'fa_add', 'trade_in')
    """
    params = [season_id]
    if coach_id is not None:
        sql += " AND coach_id = ?"
        params.append(coach_id)
    return conn.execute(sql, params).fetchall()


def roster_summary(conn, season_id, coach_id):
    """(pokemon_count, points_spent) for one coach's current roster."""
    rows = current_roster(conn, season_id, coach_id)
    return len(rows), sum(r["cost"] or 0 for r in rows)


def current_roster_with_pokemon(conn, season_id, coach_id):
    """Like current_roster(), but joined with the pokemon table for
    display purposes (name, sprite, types) -- kept separate from
    current_roster() so the hot paths that only need pokemon_id/cost
    (make_pick's budget check, match reporting's roster validation) don't
    pay for a join they don't use."""
    ids = {r["pokemon_id"] for r in current_roster(conn, season_id, coach_id)}
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return conn.execute(
        f"""SELECT pokemon_id, display_name, sprite_url, type1, type2
            FROM pokemon WHERE pokemon_id IN ({placeholders})
            ORDER BY display_name""",
        list(ids),
    ).fetchall()
