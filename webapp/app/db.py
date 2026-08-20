"""SQLite connection helper for app.db.

The web page reads app.db directly, per docs/local-webapp-and-database-
architecture.md -- it's small, fast, and every table the app needs
(players, trade_values, leagues/rosters, arbitrage_signals,
model_predictions) already lives there. analytics.duckdb (the large
historical data behind the models) isn't queried directly by the app in
this first version -- everything the app shows is either already in app.db
or has been joined/enriched into it by the build/model scripts.
"""
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SQLITE_PATH = os.path.join(ROOT, "fantasy-football-db", "data", "app.db")


def get_connection():
    if not os.path.exists(SQLITE_PATH):
        raise FileNotFoundError(
            f"{SQLITE_PATH} not found -- run fantasy-football-db/scripts/build_db.py first."
        )
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn
