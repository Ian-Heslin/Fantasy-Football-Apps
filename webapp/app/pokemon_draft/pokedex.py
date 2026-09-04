"""Read-only lookups against the static `pokemon` reference table (seeded
by fantasy-football-db/scripts/load_pokemon_pokedex.py) -- see
schema/sqlite_schema.sql's `pokemon` table comment for the form-vs-species
distinction this and every other pokemon_draft module builds on."""

PAGE_SIZE = 60


def get_pokemon(conn, pokemon_id):
    return conn.execute("SELECT * FROM pokemon WHERE pokemon_id = ?", (pokemon_id,)).fetchone()


def search(conn, query=None, generation=None, page=1):
    """Paginated browse/search. Returns (rows, total_count)."""
    where = []
    params = []
    if query:
        where.append("(display_name LIKE ? OR slug LIKE ?)")
        like = f"%{query}%"
        params += [like, like]
    if generation:
        where.append("generation = ?")
        params.append(generation)
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    total = conn.execute(f"SELECT count(*) FROM pokemon {clause}", params).fetchone()[0]
    offset = max(page - 1, 0) * PAGE_SIZE
    rows = conn.execute(
        f"SELECT * FROM pokemon {clause} ORDER BY national_dex_number, pokemon_id LIMIT ? OFFSET ?",
        params + [PAGE_SIZE, offset],
    ).fetchall()
    return rows, total


def generations(conn):
    return [r[0] for r in conn.execute("SELECT DISTINCT generation FROM pokemon ORDER BY generation")]
