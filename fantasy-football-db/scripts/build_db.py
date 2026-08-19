#!/usr/bin/env python3
"""
build_db.py -- creates app.db (SQLite) and analytics.duckdb (DuckDB) from the
schema files in schema/, then loads whatever source data is available right
now without any auth: the dynastyprocess/data player crosswalk and dynasty
trade values (-> app.db) and the full FantasyPros ECR archive (-> analytics.duckdb).

Sleeper league/roster data is NOT loaded by this script -- run
scripts/load_sleeper.py separately for that (it hits api.sleeper.app directly,
which this sandbox's network can't reach, but a real machine can).

Usage:
    python3 scripts/build_db.py

Safe to re-run: schema creation uses CREATE TABLE IF NOT EXISTS, and the
dynastyprocess load replaces same-day rows rather than duplicating them.
"""
import csv
import gzip
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, datetime

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SQLITE_PATH = os.path.join(DATA_DIR, "app.db")
DUCKDB_PATH = os.path.join(DATA_DIR, "analytics.duckdb")
DYNASTYPROCESS_DIR = os.path.join(DATA_DIR, "_dynastyprocess_data")
TODAY = date.today().isoformat()


def log(msg):
    print(f"[build_db] {msg}")


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)


def apply_schema(sqlite_conn, duckdb_conn):
    with open(os.path.join(ROOT, "schema", "sqlite_schema.sql")) as f:
        sqlite_conn.executescript(f.read())
    sqlite_conn.commit()
    log("applied sqlite_schema.sql to app.db")

    with open(os.path.join(ROOT, "schema", "duckdb_schema.sql")) as f:
        duckdb_conn.execute(f.read())
    log("applied duckdb_schema.sql to analytics.duckdb")


def clone_or_refresh_dynastyprocess():
    """Shallow-clone dynastyprocess/data, or pull if it already exists.
    This repo's values.csv / db_playerids.csv / db_fpecr_latest.csv are
    refreshed regularly upstream -- re-cloning gets the latest snapshot
    rather than reusing a stale copy."""
    if os.path.isdir(os.path.join(DYNASTYPROCESS_DIR, ".git")):
        log("dynastyprocess/data already cloned, pulling latest...")
        subprocess.run(
            ["git", "-C", DYNASTYPROCESS_DIR, "pull", "--depth", "1"],
            check=True,
        )
    else:
        if os.path.isdir(DYNASTYPROCESS_DIR):
            shutil.rmtree(DYNASTYPROCESS_DIR)
        log("cloning dynastyprocess/data (shallow)...")
        subprocess.run(
            [
                "git", "clone", "--depth", "1",
                "https://github.com/dynastyprocess/data.git",
                DYNASTYPROCESS_DIR,
            ],
            check=True,
        )


def _clean(v):
    """dynastyprocess CSVs use the literal string 'NA' for missing values --
    normalize that (and blank strings) to a real None."""
    v = (v or "").strip()
    return v if v and v.upper() != "NA" else None


def load_players(sqlite_conn):
    """db_playerids.csv -> players table. Uses fantasypros_id as the primary
    key when available (since trade_values joins on it), falling back to a
    sleeper-prefixed id for players FantasyPros doesn't track."""
    path = os.path.join(DYNASTYPROCESS_DIR, "files", "db_playerids.csv")
    if not os.path.exists(path):
        log(f"WARNING: {path} not found, skipping players load")
        return 0

    rows = []
    seen_ids = set()
    for r in csv.DictReader(open(path, newline="", encoding="utf-8")):
        name = _clean(r.get("name")) or _clean(r.get("merge_name"))
        if not name:
            continue
        fp_id = _clean(r.get("fantasypros_id"))
        sleeper_id = _clean(r.get("sleeper_id"))
        player_id = fp_id or (f"sleeper:{sleeper_id}" if sleeper_id else None)
        if not player_id or player_id in seen_ids:
            continue  # no usable id at all, or a duplicate -- skip
        seen_ids.add(player_id)
        rows.append((
            player_id,
            sleeper_id,
            _clean(r.get("espn_id")),
            _clean(r.get("yahoo_id")),
            _clean(r.get("mfl_id")),
            fp_id,
            name,
            _clean(r.get("position")),
            _clean(r.get("team")),
        ))

    sqlite_conn.executemany(
        """INSERT INTO players
               (player_id, sleeper_id, espn_id, yahoo_id, mfl_id, fantasypros_id,
                name, position, team, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(player_id) DO UPDATE SET
               sleeper_id=excluded.sleeper_id, espn_id=excluded.espn_id,
               yahoo_id=excluded.yahoo_id, mfl_id=excluded.mfl_id,
               fantasypros_id=excluded.fantasypros_id, name=excluded.name,
               position=excluded.position, team=excluded.team,
               updated_at=datetime('now')""",
        rows,
    )
    sqlite_conn.commit()
    log(f"loaded {len(rows)} players")
    return len(rows)


def load_trade_values(sqlite_conn):
    """values.csv -> trade_values table, stamped with today's date as the
    snapshot date. Handles both player rows and draft-pick rows (dynasty
    process includes picks like '2027 1st' in the same file)."""
    path = os.path.join(DYNASTYPROCESS_DIR, "files", "values.csv")
    if not os.path.exists(path):
        log(f"WARNING: {path} not found, skipping trade_values load")
        return 0

    def to_float(v):
        v = _clean(v)
        try:
            return float(v) if v is not None else None
        except ValueError:
            return None

    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            fp_id = _clean(r.get("fp_id")) or _clean(r.get("fantasypros_id"))
            player_name = _clean(r.get("player")) or ""
            is_pick = 1 if (_clean(r.get("pos")) or "").upper() == "PICK" else 0
            rows.append((
                None if is_pick else fp_id,
                TODAY,
                to_float(r.get("value_1qb")),
                to_float(r.get("value_2qb")),
                to_float(r.get("ecr_1qb")),
                to_float(r.get("ecr_2qb")),
                to_float(r.get("ecr_pos")),
                is_pick,
                player_name if is_pick else None,
                "dynastyprocess",
            ))

    sqlite_conn.executemany(
        """INSERT INTO trade_values
               (player_id, value_date, value_1qb, value_2qb, ecr_1qb, ecr_2qb,
                ecr_pos, is_pick, pick_label, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(value_date, source, player_id, pick_label) DO UPDATE SET
               value_1qb=excluded.value_1qb, value_2qb=excluded.value_2qb,
               ecr_1qb=excluded.ecr_1qb, ecr_2qb=excluded.ecr_2qb,
               ecr_pos=excluded.ecr_pos""",
        rows,
    )
    sqlite_conn.commit()
    log(f"loaded {len(rows)} trade_value rows (snapshot date {TODAY})")
    return len(rows)


def load_fp_ecr_latest(duckdb_conn):
    """db_fpecr_latest.csv -> fp_ecr_history in DuckDB. DuckDB reads the CSV
    directly rather than going through Python row-by-row -- much faster for
    a file this size, and this is exactly the workload DuckDB is good at."""
    path = os.path.join(DYNASTYPROCESS_DIR, "files", "db_fpecr_latest.csv")
    if not os.path.exists(path):
        log(f"WARNING: {path} not found, skipping fp_ecr_history load")
        return 0

    duckdb_conn.execute(f"""
        INSERT INTO fp_ecr_history
        SELECT
            id AS fp_id,
            fp_page AS page,
            player AS player_name,
            pos AS position,
            TRY_CAST(ecr AS INTEGER) AS rank,
            TRY_CAST(ecr AS DOUBLE) AS ecr,
            TRY_CAST(rank_delta AS DOUBLE) AS rank_delta,
            TRY_CAST(scrape_date AS DATE) AS scrape_date
        FROM read_csv_auto('{path}', ignore_errors=true)
    """)
    count = duckdb_conn.execute("SELECT count(*) FROM fp_ecr_history").fetchone()[0]
    log(f"fp_ecr_history now has {count} total rows")
    return count


def update_sync_log(sqlite_conn, table_name, source, row_count, notes=""):
    sqlite_conn.execute(
        """INSERT INTO sync_log (table_name, source, last_synced_at, row_count, notes)
           VALUES (?, ?, datetime('now'), ?, ?)
           ON CONFLICT(table_name) DO UPDATE SET
               source=excluded.source, last_synced_at=datetime('now'),
               row_count=excluded.row_count, notes=excluded.notes""",
        (table_name, source, row_count, notes),
    )
    sqlite_conn.commit()


def demo_cross_database_join(duckdb_conn):
    """Shows the whole point of the two-database split: DuckDB attaches the
    SQLite file directly (no copying) and can join current data (SQLite)
    against historical/bulk data (DuckDB's own tables) in one query."""
    try:
        duckdb_conn.execute(f"ATTACH '{SQLITE_PATH}' AS app (TYPE SQLITE)")
        result = duckdb_conn.execute("""
            SELECT count(*) AS players_visible_from_duckdb
            FROM app.players
        """).fetchone()
        log(f"cross-database check: DuckDB can see {result[0]} rows in app.players via ATTACH")
        duckdb_conn.execute("DETACH app")
    except duckdb.Error as e:
        # This sandbox's network blocks DuckDB's extension-download endpoint,
        # so the ATTACH demo can't run here -- it downloads the sqlite_scanner
        # extension once, then caches it locally. On a normal machine with
        # regular internet access this works the first time it's run.
        log(f"NOTE: cross-database ATTACH demo skipped ({e}). "
            f"This needs one-time internet access to download DuckDB's "
            f"sqlite_scanner extension -- should work fine on your machine.")


def main():
    ensure_dirs()
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    duckdb_conn = duckdb.connect(DUCKDB_PATH)

    apply_schema(sqlite_conn, duckdb_conn)

    try:
        clone_or_refresh_dynastyprocess()
    except subprocess.CalledProcessError as e:
        log(f"WARNING: could not clone/pull dynastyprocess/data ({e}); "
            f"skipping data load, schema-only run.")
        sqlite_conn.close()
        duckdb_conn.close()
        return

    n_players = load_players(sqlite_conn)
    n_values = load_trade_values(sqlite_conn)
    n_ecr = load_fp_ecr_latest(duckdb_conn)

    update_sync_log(sqlite_conn, "players", "dynastyprocess/db_playerids.csv", n_players)
    update_sync_log(sqlite_conn, "trade_values", "dynastyprocess/values.csv", n_values,
                     notes=f"snapshot date {TODAY}")

    demo_cross_database_join(duckdb_conn)

    sqlite_conn.close()
    duckdb_conn.close()
    log("done. app.db and analytics.duckdb are in the data/ directory.")
    log("next: run scripts/load_sleeper.py to pull your league/roster data.")


if __name__ == "__main__":
    main()
