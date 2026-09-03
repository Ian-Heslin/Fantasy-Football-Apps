"""Database connection helpers.

app.db (SQLite) is the one the web page reads for most pages -- it's
small, fast, and has the operational/current-state tables (players,
trade_values, leagues/rosters, arbitrage_signals, model_predictions). The
team/coach/offense reference pages need analytics.duckdb (DuckDB) instead,
since that's where team_offense_season/coach_table/vegas_odds/etc. live --
see docs/local-webapp-and-database-architecture.md for why the data is
split across two databases this way.
"""
import logging
import os
import sqlite3

import duckdb

log = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SQLITE_PATH = os.path.join(ROOT, "fantasy-football-db", "data", "app.db")
DUCKDB_PATH = os.path.join(ROOT, "fantasy-football-db", "data", "analytics.duckdb")


# SQLite's default 5s is short for a Pi serving several people at once --
# a write that waits longer than this raises "database is locked" as a 500.
BUSY_TIMEOUT_SECONDS = 15


def get_connection():
    if not os.path.exists(SQLITE_PATH):
        raise FileNotFoundError(
            f"{SQLITE_PATH} not found -- run fantasy-football-db/scripts/build_db.py first."
        )
    conn = sqlite3.connect(SQLITE_PATH, timeout=BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    # foreign_keys is per-connection and defaults to OFF, so the
    # `PRAGMA foreign_keys = ON` at the top of sqlite_schema.sql applies
    # only to the connection that ran the schema -- it does NOT persist
    # in the file. Without this line every REFERENCES clause in the
    # schema (pickem_picks, trivia_rounds, fantasy_draft_entries) is
    # decorative and orphan rows can be created freely.
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL is a property of the file, not the connection, so this is a
    # no-op after the first time. Worth doing on every connect anyway:
    # it costs nothing and it means a freshly built app.db picks it up
    # without a separate migration step. Readers no longer block behind
    # a writer, which is what this read-heavy workload wants.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_duckdb_connection():
    if not os.path.exists(DUCKDB_PATH):
        raise FileNotFoundError(
            f"{DUCKDB_PATH} not found -- run fantasy-football-db/scripts/build_db.py first."
        )
    # read_only=True: several instances can open it at once (this app plus
    # any script re-running in another terminal) since nothing here writes.
    return duckdb.connect(DUCKDB_PATH, read_only=True)


def open_both():
    """Both connections, or a FileNotFoundError with neither left open.

    Routes needing both databases used to open them in a single try:

        conn = get_connection()               # succeeds
        duckdb_conn = get_duckdb_connection() # raises
        except FileNotFoundError: return db_missing_response(...)

    which leaked the SQLite connection on every request for as long as
    analytics.duckdb was missing while app.db was present."""
    conn = get_connection()
    try:
        return conn, get_duckdb_connection()
    except BaseException:
        conn.close()
        raise


def close_all(*connections):
    """Close every connection even if an earlier one raises on close --
    a plain `finally: a.close(); b.close()` skips b when a throws."""
    for conn in connections:
        if conn is None:
            continue
        try:
            conn.close()
        except Exception:  # noqa: BLE001 -- closing is best-effort
            log.warning("failed to close %r", conn, exc_info=True)


def duckdb_rows(cursor):
    """DuckDB's cursor.fetchall() returns plain tuples -- unlike sqlite3.Row,
    there's no dict-style access for templates. Zip in column names from
    the cursor description so both databases' rows look the same
    (row['col_name']) from inside a template."""
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
