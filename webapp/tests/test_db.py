"""Connection settings that are easy to assume and were not actually on."""
import sqlite3

import pytest

from app import db


@pytest.fixture
def app_db(tmp_path, monkeypatch):
    """A real app.db file with just enough schema to test the pragmas."""
    path = tmp_path / "app.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE users (user_id INTEGER PRIMARY KEY, username TEXT);
        CREATE TABLE pickem_picks (
            user_id INTEGER NOT NULL REFERENCES users(user_id),
            game_id TEXT NOT NULL, picked_team TEXT NOT NULL);
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "SQLITE_PATH", str(path))
    return path


def test_foreign_keys_are_enforced_on_every_connection(app_db):
    """`PRAGMA foreign_keys = ON` in sqlite_schema.sql applies only to the
    connection that ran the schema -- it is not stored in the file. Until
    get_connection() set it too, every REFERENCES clause was decorative."""
    conn = db.get_connection()
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO pickem_picks VALUES (999, 'G', 'KC')")  # no such user
            conn.commit()
    finally:
        conn.close()


def test_valid_foreign_key_still_inserts(app_db):
    conn = db.get_connection()
    try:
        conn.execute("INSERT INTO users VALUES (1, 'ian')")
        conn.execute("INSERT INTO pickem_picks VALUES (1, 'G', 'KC')")
        conn.commit()
        assert conn.execute("SELECT count(*) FROM pickem_picks").fetchone()[0] == 1
    finally:
        conn.close()


def test_database_is_in_wal_mode(app_db):
    """WAL lets readers proceed while a writer holds the database, which
    is what stops a Sunday-afternoon pick submission colliding with the
    hourly backup and surfacing as `database is locked`."""
    conn = db.get_connection()
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_missing_database_raises_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "SQLITE_PATH", str(tmp_path / "nope.db"))
    with pytest.raises(FileNotFoundError, match="build_db.py"):
        db.get_connection()


def test_open_both_closes_the_sqlite_connection_when_duckdb_is_missing(
        app_db, tmp_path, monkeypatch):
    """The leak: app.db opens, analytics.duckdb doesn't exist, the route
    returns its 503 page from the except -- and the SQLite handle is
    never closed, once per request for as long as that lasts."""
    monkeypatch.setattr(db, "DUCKDB_PATH", str(tmp_path / "nope.duckdb"))

    opened = []
    real_connect = db.sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(db.sqlite3, "connect", tracking_connect)

    with pytest.raises(FileNotFoundError):
        db.open_both()

    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError):   # already closed
        opened[0].execute("SELECT 1")


def test_close_all_closes_later_connections_even_if_an_earlier_one_raises():
    class Boom:
        def close(self):
            raise RuntimeError("nope")

    class Tracked:
        closed = False

        def close(self):
            self.closed = True

    tracked = Tracked()
    db.close_all(Boom(), tracked, None)
    assert tracked.closed
