#!/usr/bin/env python3
"""
load_pokemon_pokedex.py -- seeds the `pokemon` table (Pokemon Draft
League's static reference data) from PokeAPI's bulk static JSON mirror,
PokeAPI/api-data. One row per PokeAPI *form* (pokemon resource) -- see
schema/sqlite_schema.sql's `pokemon` table comment for why forms, not
species, are the primary key here.

Uses a blob-filtered, sparse-checkout clone (not the live PokeAPI over
HTTP) so seeding ~1,350 pokemon + ~1,025 species doesn't mean ~2,400
individual network requests -- git fetches only the two directories this
script actually reads (data/api/v2/pokemon, data/api/v2/pokemon-species),
not api-data's much larger full mirror (every move/item/location/etc in
the game).

Sprite URLs are read straight out of the mirrored JSON (PokeAPI's own
sprites.other.official-artwork.front_default, already a full
raw.githubusercontent.com/PokeAPI/sprites/... URL) -- nothing is
downloaded or copied onto disk, same external-hotlink pattern
app/team_colors.py already uses for NFL logos.

Safe to re-run: every generation release adds new forms/species, and this
just re-clones (fetch+reset, like load_pickem_schedule.py) and re-upserts
everything by pokemon_id, which PokeAPI assigns and keeps stable.

Usage:
    python3 scripts/load_pokemon_pokedex.py
    python3 scripts/load_pokemon_pokedex.py --limit 50   # quick smoke test
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SQLITE_PATH = os.path.join(DATA_DIR, "app.db")
POKEAPI_CLONE_DIR = os.path.join(DATA_DIR, "_pokeapi_data", "api-data")
POKEAPI_REPO_URL = "https://github.com/PokeAPI/api-data.git"
SPARSE_PATHS = ["data/api/v2/pokemon", "data/api/v2/pokemon-species"]

GENERATION_NUMBER = {
    "generation-i": 1, "generation-ii": 2, "generation-iii": 3,
    "generation-iv": 4, "generation-v": 5, "generation-vi": 6,
    "generation-vii": 7, "generation-viii": 8, "generation-ix": 9,
}

# PokeAPI stat resource name -> our column name.
STAT_COLUMN = {
    "hp": "base_hp", "attack": "base_atk", "defense": "base_def",
    "special-attack": "base_spa", "special-defense": "base_spd", "speed": "base_spe",
}


def log(msg):
    print(f"[load_pokemon_pokedex] {msg}")


def clone_or_refresh_api_data():
    # --filter=blob:none + --sparse: only the two directories this script
    # reads are ever fetched, not api-data's much larger full mirror
    # (moves/items/locations/abilities/etc for the whole game).
    if os.path.isdir(os.path.join(POKEAPI_CLONE_DIR, ".git")):
        log("PokeAPI/api-data already cloned, refreshing...")
        subprocess.run(["git", "-C", POKEAPI_CLONE_DIR, "fetch", "--depth", "1", "origin"], check=True)
        subprocess.run(["git", "-C", POKEAPI_CLONE_DIR, "reset", "--hard", "FETCH_HEAD"], check=True)
    else:
        log("cloning PokeAPI/api-data (sparse, blobless)...")
        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--sparse", "--depth", "1",
             POKEAPI_REPO_URL, POKEAPI_CLONE_DIR],
            check=True,
        )
        subprocess.run(["git", "-C", POKEAPI_CLONE_DIR, "sparse-checkout", "set", *SPARSE_PATHS], check=True)


def _read_json(*parts):
    path = os.path.join(POKEAPI_CLONE_DIR, *parts)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _id_from_url(url):
    """'/api/v2/pokemon-species/487/' -> 487"""
    match = re.search(r"/(\d+)/?$", url)
    return int(match.group(1)) if match else None


def _national_dex_number(species):
    for entry in species.get("pokedex_numbers", []):
        if entry["pokedex"]["name"] == "national":
            return entry["entry_number"]
    return species["id"]  # fallback -- species id tracks the national dex closely enough to seed with


def _english_name(entries):
    for entry in entries:
        if entry["language"]["name"] == "en":
            return entry["name"]
    return None


def _display_name(pokemon_slug, species):
    base = _english_name(species["names"]) or species["name"].replace("-", " ").title()
    species_slug = species["name"]
    if pokemon_slug == species_slug:
        return base
    # Strip the shared species prefix, title-case what's left as the form
    # label -- 'landorus-therian' minus 'landorus' -> 'Therian'.
    suffix = pokemon_slug[len(species_slug):].lstrip("-")
    form_label = suffix.replace("-", " ").title() if suffix else pokemon_slug.replace("-", " ").title()
    return f"{base} ({form_label})"


def _sprite_url(pokemon):
    other = pokemon.get("sprites", {}).get("other", {})
    artwork = other.get("official-artwork", {}) or {}
    return artwork.get("front_default") or pokemon.get("sprites", {}).get("front_default")


def load_pokemon(limit=None):
    index = _read_json("data", "api", "v2", "pokemon", "index.json")
    entries = index["results"]
    if limit:
        entries = entries[:limit]

    species_cache = {}
    rows = []
    for i, entry in enumerate(entries, start=1):
        pokemon_id = _id_from_url(entry["url"])
        pokemon = _read_json("data", "api", "v2", "pokemon", str(pokemon_id), "index.json")
        species_id = _id_from_url(pokemon["species"]["url"])
        if species_id not in species_cache:
            species_cache[species_id] = _read_json(
                "data", "api", "v2", "pokemon-species", str(species_id), "index.json")
        species = species_cache[species_id]

        types = sorted(pokemon["types"], key=lambda t: t["slot"])
        type1 = types[0]["type"]["name"] if len(types) > 0 else None
        type2 = types[1]["type"]["name"] if len(types) > 1 else None

        stats = {STAT_COLUMN[s["stat"]["name"]]: s["base_stat"]
                 for s in pokemon["stats"] if s["stat"]["name"] in STAT_COLUMN}

        rows.append({
            "pokemon_id": pokemon_id,
            "species_id": species_id,
            "slug": pokemon["name"],
            "display_name": _display_name(pokemon["name"], species),
            "national_dex_number": _national_dex_number(species),
            "generation": GENERATION_NUMBER.get(species["generation"]["name"]),
            "type1": type1,
            "type2": type2,
            "sprite_url": _sprite_url(pokemon),
            **{col: None for col in STAT_COLUMN.values()},
            **stats,
        })
        if i % 200 == 0:
            log(f"...{i}/{len(entries)} parsed")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None,
                         help="only load the first N pokemon (smoke testing)")
    args = parser.parse_args()

    if not os.path.exists(SQLITE_PATH):
        log("app.db not found -- run scripts/build_db.py first.")
        sys.exit(1)

    clone_or_refresh_api_data()
    rows = load_pokemon(limit=args.limit)
    if not rows:
        log("ERROR: parsed zero pokemon -- nothing loaded.")
        sys.exit(1)

    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    for r in rows:
        conn.execute(
            """INSERT INTO pokemon
                   (pokemon_id, species_id, slug, display_name, national_dex_number, generation,
                    type1, type2, base_hp, base_atk, base_def, base_spa, base_spd, base_spe,
                    sprite_url, updated_at)
               VALUES (:pokemon_id, :species_id, :slug, :display_name, :national_dex_number, :generation,
                       :type1, :type2, :base_hp, :base_atk, :base_def, :base_spa, :base_spd, :base_spe,
                       :sprite_url, datetime('now'))
               ON CONFLICT(pokemon_id) DO UPDATE SET
                   species_id=excluded.species_id, slug=excluded.slug, display_name=excluded.display_name,
                   national_dex_number=excluded.national_dex_number, generation=excluded.generation,
                   type1=excluded.type1, type2=excluded.type2,
                   base_hp=excluded.base_hp, base_atk=excluded.base_atk, base_def=excluded.base_def,
                   base_spa=excluded.base_spa, base_spd=excluded.base_spd, base_spe=excluded.base_spe,
                   sprite_url=excluded.sprite_url, updated_at=excluded.updated_at""",
            r,
        )
    conn.execute(
        """INSERT INTO sync_log (table_name, source, last_synced_at, row_count, notes)
           VALUES ('pokemon', 'PokeAPI/api-data', datetime('now'), ?, ?)
           ON CONFLICT(table_name) DO UPDATE SET
               last_synced_at=datetime('now'), row_count=excluded.row_count, notes=excluded.notes""",
        (len(rows), "all forms, all generations"),
    )
    conn.commit()
    conn.close()

    log(f"loaded {len(rows)} pokemon forms")
    log("done.")


if __name__ == "__main__":
    main()
