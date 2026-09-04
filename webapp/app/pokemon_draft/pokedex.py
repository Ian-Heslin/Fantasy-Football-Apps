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


def find_by_species_name(conn, species_name):
    """Best-effort match of a Pokemon Showdown battle-log species string
    (e.g. 'Landorus-Therian', from app/pokemon_draft/replay.py's parser)
    to a pokemon_id, or None if nothing matches. Callers skip an
    unmatched stat entry rather than fail an entire replay import over
    one unrecognized name -- most commonly a cosmetic-only form Showdown
    tracks (e.g. a Pikachu cosplay form) that isn't a separate PokeAPI
    entry."""
    cleaned = species_name.strip().replace("(", " ").replace(")", " ")
    slug = " ".join(cleaned.split()).lower().replace(" ", "-").replace("'", "").replace(".", "")
    row = conn.execute("SELECT pokemon_id FROM pokemon WHERE slug = ?", (slug,)).fetchone()
    if row:
        return row["pokemon_id"]
    # A bare species name with no form suffix (e.g. 'Maushold', 'Tatsugiri') has no
    # exact slug match when every one of that species' forms carries a suffixed slug
    # (there's no plain 'maushold' row) -- fall back to whichever of its forms
    # PokeAPI marks as the default variety (pokemon_id == species_id there).
    row = conn.execute(
        "SELECT pokemon_id FROM pokemon WHERE pokemon_id = species_id AND slug LIKE ? ORDER BY slug LIMIT 1",
        (slug + "-%",),
    ).fetchone()
    return row["pokemon_id"] if row else None
