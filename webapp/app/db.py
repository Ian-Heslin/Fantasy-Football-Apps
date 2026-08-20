"""Database connection helpers.

app.db (SQLite) is the one the web page reads for most pages -- it's
small, fast, and has the operational/current-state tables (players,
trade_values, leagues/rosters, arbitrage_signals, model_predictions). The
team/coach/offense reference pages need analytics.duckdb (DuckDB) instead,
since that's where team_offense_season/coach_table/vegas_odds/etc. live --
see docs/local-webapp-and-database-architecture.md for why the data is
split across two databases this way.
"""
import os
import sqlite3

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SQLITE_PATH = os.path.join(ROOT, "fantasy-football-db", "data", "app.db")
DUCKDB_PATH = os.path.join(ROOT, "fantasy-football-db", "data", "analytics.duckdb")


def get_connection():
    if not os.path.exists(SQLITE_PATH):
        raise FileNotFoundError(
            f"{SQLITE_PATH} not found -- run fantasy-football-db/scripts/build_db.py first."
        )
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_duckdb_connection():
    if not os.path.exists(DUCKDB_PATH):
        raise FileNotFoundError(
            f"{DUCKDB_PATH} not found -- run fantasy-football-db/scripts/build_db.py first."
        )
    # read_only=True: several instances can open it at once (this app plus
    # any script re-running in another terminal) since nothing here writes.
    return duckdb.connect(DUCKDB_PATH, read_only=True)


def duckdb_rows(cursor):
    """DuckDB's cursor.fetchall() returns plain tuples -- unlike sqlite3.Row,
    there's no dict-style access for templates. Zip in column names from
    the cursor description so both databases' rows look the same
    (row['col_name']) from inside a template."""
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
