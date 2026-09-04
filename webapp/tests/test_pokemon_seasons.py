"""Pokemon Draft League: season/format/coach logic tests.

Pure functions against an in-memory copy of the REAL schema, not a
hand-copied subset like test_pickem.py's make_db() -- this domain's tables
are numerous and FK-heavy enough that a hand-maintained subset could drift
from schema/sqlite_schema.sql silently.

Run with:  python3 -m pytest tests/ -q     (from webapp/)
"""
import sqlite3

from conftest import SQLITE_SCHEMA

from app.pokemon_draft import seasons


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with open(SQLITE_SCHEMA) as f:
        conn.executescript(f.read())
    conn.executemany(
        "INSERT INTO users (user_id, username, password_hash, tier) VALUES (?, ?, 'x', 'games')",
        [(1, "ian"), (2, "zach"), (3, "dick")],
    )
    conn.commit()
    return conn


def make_format(conn, format_id="gen9ou", **overrides):
    fields = {
        "display_name": "Gen 9 OU", "battle_style": "singles", "rules_text": "",
        "default_roster_size": 12, "default_point_budget": 125, "default_species_clause": True,
    }
    fields.update(overrides)
    error = seasons.create_format(
        conn, format_id, fields["display_name"], fields["battle_style"], fields["rules_text"],
        fields["default_roster_size"], fields["default_point_budget"], fields["default_species_clause"])
    assert error is None
    return format_id


# ---------------------------------------------------------------------
# Format / season creation
# ---------------------------------------------------------------------

def test_create_season_inherits_format_defaults():
    conn = make_db()
    make_format(conn, default_roster_size=10, default_point_budget=70, default_species_clause=False)
    season_id, error = seasons.create_season(conn, "Season 1", "gen9ou", commissioner_user_id=1)
    assert error is None
    season = seasons.get_season(conn, season_id)
    assert season["roster_size_cap"] == 10
    assert season["point_budget"] == 70
    assert season["species_clause_enabled"] == 0
    assert season["status"] == "draft"


def test_create_season_rejects_unknown_format():
    conn = make_db()
    season_id, error = seasons.create_season(conn, "Season 1", "no-such-format", 1)
    assert season_id is None
    assert error is not None


def test_create_format_rejects_duplicate_id():
    conn = make_db()
    make_format(conn, "gen9ou")
    error = seasons.create_format(conn, "gen9ou", "Dupe", "singles", "", 10, 100, True)
    assert error is not None and "already exists" in error


def test_create_format_rejects_bad_battle_style():
    conn = make_db()
    error = seasons.create_format(conn, "weird", "Weird", "chess", "", 10, 100, True)
    assert error is not None


# ---------------------------------------------------------------------
# One-active-season invariant
# ---------------------------------------------------------------------

def test_only_one_season_can_be_active():
    conn = make_db()
    make_format(conn)
    s1, _ = seasons.create_season(conn, "Season 1", "gen9ou", 1)
    s2, _ = seasons.create_season(conn, "Season 2", "gen9ou", 1)

    assert seasons.activate_season(conn, s1) is None
    assert seasons.get_season(conn, s1)["status"] == "active"

    error = seasons.activate_season(conn, s2)
    assert error is not None
    assert seasons.get_season(conn, s2)["status"] == "draft"  # unchanged


def test_reactivating_the_already_active_season_is_a_noop_not_an_error():
    conn = make_db()
    make_format(conn)
    s1, _ = seasons.create_season(conn, "Season 1", "gen9ou", 1)
    seasons.activate_season(conn, s1)
    assert seasons.activate_season(conn, s1) is None


def test_archiving_frees_the_active_slot_for_another_season():
    conn = make_db()
    make_format(conn)
    s1, _ = seasons.create_season(conn, "Season 1", "gen9ou", 1)
    s2, _ = seasons.create_season(conn, "Season 2", "gen9ou", 1)
    seasons.activate_season(conn, s1)
    seasons.archive_season(conn, s1)
    assert seasons.get_season(conn, s1)["status"] == "archived"
    assert seasons.activate_season(conn, s2) is None


# ---------------------------------------------------------------------
# Coaches
# ---------------------------------------------------------------------

def test_add_coach_and_duplicate_seat_rejected():
    conn = make_db()
    make_format(conn)
    s1, _ = seasons.create_season(conn, "Season 1", "gen9ou", 1)
    assert seasons.add_coach(conn, s1, 1, "Ian's Team") is None
    error = seasons.add_coach(conn, s1, 1, "Ian's Team Again")
    assert error is not None and "already has a seat" in error
    assert len(seasons.list_coaches(conn, s1)) == 1


def test_coaches_locked_once_draft_board_locks():
    conn = make_db()
    make_format(conn)
    s1, _ = seasons.create_season(conn, "Season 1", "gen9ou", 1)
    seasons.add_coach(conn, s1, 1, "Ian's Team")
    seasons.lock_draft_board(conn, s1)

    assert seasons.add_coach(conn, s1, 2, "Zach's Team") is not None
    coach_id = seasons.list_coaches(conn, s1)[0]["coach_id"]
    assert seasons.remove_coach(conn, s1, coach_id) is not None
    assert len(seasons.list_coaches(conn, s1)) == 1


def test_ruleset_locked_once_draft_board_locks():
    conn = make_db()
    make_format(conn)
    s1, _ = seasons.create_season(conn, "Season 1", "gen9ou", 1)
    seasons.lock_draft_board(conn, s1)
    error = seasons.update_ruleset(conn, s1, 8, 90, True, 3, 5, 4)
    assert error is not None
    assert seasons.get_season(conn, s1)["point_budget"] != 90


def test_set_draft_order_requires_every_coach_exactly_once():
    conn = make_db()
    make_format(conn)
    s1, _ = seasons.create_season(conn, "Season 1", "gen9ou", 1)
    seasons.add_coach(conn, s1, 1, "Ian's Team")
    seasons.add_coach(conn, s1, 2, "Zach's Team")
    ids = [c["coach_id"] for c in seasons.list_coaches(conn, s1)]

    assert seasons.set_draft_order(conn, s1, [ids[0]]) is not None       # missing one
    assert seasons.set_draft_order(conn, s1, ids + [ids[0]]) is not None  # duplicate

    assert seasons.set_draft_order(conn, s1, list(reversed(ids))) is None
    ordered = seasons.list_coaches(conn, s1)
    assert ordered[0]["coach_id"] == ids[-1]
    assert ordered[0]["draft_order"] == 1
