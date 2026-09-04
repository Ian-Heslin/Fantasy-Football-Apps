"""Shared fixtures.

Puts webapp/ on sys.path so tests can `from app import ...` the same way
the running app does, whatever directory pytest is invoked from, and
builds throwaway app.db / analytics.duckdb files. Nothing here ever
touches a real database.
"""
import os
import sqlite3
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
WEBAPP = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(WEBAPP)
sys.path.insert(0, WEBAPP)

SQLITE_SCHEMA = os.path.join(REPO_ROOT, "fantasy-football-db", "schema", "sqlite_schema.sql")
DUCKDB_SCHEMA = os.path.join(REPO_ROOT, "fantasy-football-db", "schema", "duckdb_schema.sql")

GOOD_PASSWORD = "correct horse battery staple"

# player_bio / player_stats_season / player_stats_def_season are created by
# the load scripts rather than duckdb_schema.sql, so the fixture declares
# the columns app/trivia.py's Top 100 hint enrichment actually reads.
EXTRA_DUCKDB_TABLES = """
CREATE TABLE IF NOT EXISTS player_bio (
    display_name TEXT, position TEXT, rookie_season INTEGER, last_season INTEGER);
CREATE TABLE IF NOT EXISTS player_stats_season (
    season INTEGER, player_display_name TEXT, position TEXT,
    passing_yards DOUBLE, rushing_yards DOUBLE, receiving_yards DOUBLE,
    passing_tds DOUBLE, rushing_tds DOUBLE, receiving_tds DOUBLE,
    interceptions DOUBLE, sack_fumbles_lost DOUBLE,
    rushing_fumbles_lost DOUBLE, receiving_fumbles_lost DOUBLE);
CREATE TABLE IF NOT EXISTS player_stats_def_season (
    season INTEGER, player_display_name TEXT, position TEXT,
    def_tackles DOUBLE, def_sacks DOUBLE, def_pass_defended DOUBLE,
    def_interceptions DOUBLE, def_fumbles_forced DOUBLE, def_tds DOUBLE);
"""


@pytest.fixture
def databases(tmp_path, monkeypatch):
    """Throwaway app.db + analytics.duckdb, wired into app.db's module
    globals. Returns (sqlite_path, duckdb_path)."""
    import duckdb

    from app import db

    sqlite_path = tmp_path / "app.db"
    conn = sqlite3.connect(sqlite_path)
    with open(SQLITE_SCHEMA) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()

    duckdb_path = tmp_path / "analytics.duckdb"
    dconn = duckdb.connect(str(duckdb_path))
    with open(DUCKDB_SCHEMA) as f:
        dconn.execute(f.read())
    dconn.execute(EXTRA_DUCKDB_TABLES)
    # Enough rows that the Group and Daily pages have something to render.
    dconn.execute("INSERT INTO nfl_top_100 (year, rank, player, team) VALUES "
                  "(2025, 1, 'Patrick Mahomes', 'KC'), (2025, 2, 'Josh Allen', 'BUF')")
    dconn.execute(
        "INSERT INTO player_season_fantasy_points "
        "(season, player_id, player, team, position, games, ppr_pt, passing_yards) VALUES "
        "(2024, 'p1', 'Patrick Mahomes', 'KC', 'QB', 17, 320.5, 4183), "
        "(2024, 'p2', 'Saquon Barkley', 'PHI', 'RB', 16, 350.1, 0)")
    dconn.execute("INSERT INTO fantasy_draft_stats (year, player, team, position, games, ppr_pt) VALUES "
                  "(1985, 'Walter Payton', 'CHI', 'RB', 16, 300.0)")
    dconn.execute("INSERT INTO player_week_fantasy_points "
                  "(season, week, player_id, player, team, position, ppr_pt) VALUES "
                  "(2024, 1, 'p1', 'Patrick Mahomes', 'KC', 'QB', 25.5)")
    dconn.execute("INSERT INTO player_bio VALUES ('Patrick Mahomes', 'QB', 2017, NULL)")
    dconn.execute("INSERT INTO trivia_award_winners (category, year, position, player, team) VALUES "
                  "('MVP', 2015, 'QB', 'Cam Newton', 'CAR'), "
                  "('MVP', 2018, 'QB', 'Patrick Mahomes', 'KC'), "
                  "('MVP', 2023, 'QB', 'Lamar Jackson', 'BAL')")
    dconn.execute("INSERT INTO trivia_season_leaders "
                  "(category, rank, player, stat_value, years_active, team_clue) VALUES "
                  "('Points Leaders', 1, 'Adam Vinatieri', 2673, '1996-2019', 'NE/IND')")
    dconn.close()

    monkeypatch.setattr(db, "SQLITE_PATH", str(sqlite_path))
    monkeypatch.setattr(db, "DUCKDB_PATH", str(duckdb_path))
    return sqlite_path, duckdb_path


@pytest.fixture
def client(databases, monkeypatch):
    """TestClient over the real ASGI app, on https:// so the Secure
    session cookie is actually sent back."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SESSION_SECRET_KEY", "test-key-not-a-real-secret")
    from app.main import app

    with TestClient(app, base_url="https://testserver") as c:
        yield c


@pytest.fixture(autouse=True)
def reset_login_throttle():
    """The throttle is process-global; keep tests from leaking into each
    other."""
    from app import auth
    auth._login_failures.clear()
    yield
    auth._login_failures.clear()


def signup(client, username="ian", password=GOOD_PASSWORD):
    return client.post("/signup", data={
        "username": username, "password": password, "confirm_password": password,
    }, follow_redirects=False)


def set_tier(username, tier):
    from app import db
    conn = db.get_connection()
    conn.execute("UPDATE users SET tier = ? WHERE username = ?", (tier, username))
    conn.commit()
    conn.close()


def query(sql, params=()):
    from app import db
    conn = db.get_connection()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()
