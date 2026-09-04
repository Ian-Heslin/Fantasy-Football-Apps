"""Keeper round-assignment/collision rules and the DB-backed pieces built
on top of them.

The rule under test (a WHMFFL house rule): a kept player costs the round
after where they were drafted last year, except a 1st-round pick keeps
its 1st-round slot; if two of one team's keepers land on the same round,
the later one (by original draft round) moves up a round, cascading
further if that's also taken.

Run with:  python3 -m pytest tests/ -q     (from webapp/)
"""
import sqlite3

from app import keepers

SEASON, USER = 2026, 1


def make_db():
    """In-memory app.db with just the tables app/keepers.py touches."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE players (
            player_id TEXT PRIMARY KEY, name TEXT, position TEXT, team TEXT);
        CREATE TABLE rosters (
            league_id TEXT, roster_id TEXT, owner_name TEXT, is_mine INTEGER);
        CREATE TABLE roster_players (
            league_id TEXT, roster_id TEXT, player_id TEXT, as_of_date TEXT);
        CREATE TABLE league_draft_picks (
            league_id TEXT, season INTEGER, round INTEGER, overall_pick INTEGER,
            roster_id TEXT, player_id TEXT,
            PRIMARY KEY (league_id, season, overall_pick));
        CREATE TABLE keeper_predictions (
            user_id INTEGER, league_id TEXT, season INTEGER, roster_id TEXT, player_id TEXT,
            PRIMARY KEY (user_id, league_id, season, roster_id, player_id));
        CREATE TABLE mock_draft_picks (
            user_id INTEGER, league_id TEXT, season INTEGER, round INTEGER, roster_id TEXT,
            player_id TEXT, source TEXT, updated_at TEXT,
            PRIMARY KEY (user_id, league_id, season, round, roster_id));
        CREATE TABLE arbitrage_signals (
            player_id TEXT, format TEXT, as_of_date TEXT, redraft_percentile REAL);
    """)
    conn.commit()
    return conn


def add_player(conn, player_id, name, position="WR", team="KC"):
    conn.execute("INSERT INTO players VALUES (?, ?, ?, ?)", (player_id, name, position, team))


def add_draft_pick(conn, league_id, season, round_, overall_pick, roster_id, player_id):
    conn.execute(
        "INSERT INTO league_draft_picks VALUES (?, ?, ?, ?, ?, ?)",
        (league_id, season, round_, overall_pick, roster_id, player_id),
    )


def add_roster_player(conn, league_id, roster_id, player_id, as_of_date="2026-08-01"):
    conn.execute(
        "INSERT INTO roster_players VALUES (?, ?, ?, ?)",
        (league_id, roster_id, player_id, as_of_date),
    )


# ---------------------------------------------------------------------------
# Pure round-assignment logic -- no DB needed.
# ---------------------------------------------------------------------------

def test_keeper_round_first_round_keeps_first_round():
    assert keepers.keeper_round(1) == 1


def test_keeper_round_is_drafted_round_plus_one():
    assert keepers.keeper_round(2) == 3
    assert keepers.keeper_round(15) == 16


def test_single_keeper_no_collision():
    result = keepers.assign_team_keepers([{"player_id": "a", "drafted_round": 5}])
    assert result[0]["keeper_round"] == 6
    assert result[0]["conflict"] is False


def test_first_round_keeper_alongside_others_no_collision():
    result = keepers.assign_team_keepers([
        {"player_id": "a", "drafted_round": 1},
        {"player_id": "b", "drafted_round": 4},
    ])
    by_id = {k["player_id"]: k for k in result}
    assert by_id["a"]["keeper_round"] == 1
    assert by_id["b"]["keeper_round"] == 5


def test_collision_bumps_later_keeper_up_one_round():
    # Both drafted round 2 -> both compute to keeper round 3.
    result = keepers.assign_team_keepers([
        {"player_id": "early", "drafted_round": 2},
        {"player_id": "late", "drafted_round": 2},
    ])
    by_id = {k["player_id"]: k for k in result}
    # Order within a tie is stable -- whichever sorts first claims round 3,
    # the other bumps to round 2. Both should land on distinct rounds.
    rounds = {k["keeper_round"] for k in result}
    assert rounds == {2, 3}
    assert not any(k["conflict"] for k in result)


def test_more_valuable_keeper_keeps_its_round_on_collision():
    # round-1 keeper (keeper_round=1) and a round-2 keeper (keeper_round=3)
    # and a round-3 keeper (keeper_round=4) don't collide with each other,
    # but two round-3-drafted keepers (both -> keeper_round 4) do: the
    # earlier-processed one keeps 4, the other cascades to 3 -- except 3 is
    # already legitimately used by the round-2 keeper, so it must cascade
    # again to 2.
    result = keepers.assign_team_keepers([
        {"player_id": "r1", "drafted_round": 1},   # -> 1
        {"player_id": "r2", "drafted_round": 2},   # -> 3
        {"player_id": "r3a", "drafted_round": 3},  # -> 4
        {"player_id": "r3b", "drafted_round": 3},  # -> 4, collides
    ])
    by_id = {k["player_id"]: k for k in result}
    assert by_id["r1"]["keeper_round"] == 1
    assert by_id["r2"]["keeper_round"] == 3
    assert by_id["r3a"]["keeper_round"] == 4
    assert by_id["r3b"]["keeper_round"] == 2
    assert not any(k["conflict"] for k in result)


def test_cascading_collision_flags_conflict_when_it_runs_out_of_room():
    # Four keepers that all collapse toward round 1 with no room left.
    result = keepers.assign_team_keepers([
        {"player_id": "a", "drafted_round": 1},  # -> 1
        {"player_id": "b", "drafted_round": 1},  # -> 1, cascades... nowhere (floor)
    ])
    by_id = {k["player_id"]: k for k in result}
    rounds = [k["keeper_round"] for k in result]
    assert rounds.count(1) == 2  # both pinned at the floor
    assert sum(k["conflict"] for k in result) == 1  # the second one is flagged


# ---------------------------------------------------------------------------
# DB-backed pieces.
# ---------------------------------------------------------------------------

def test_keeper_eligible_players_excludes_players_no_longer_on_roster():
    conn = make_db()
    add_player(conn, "p1", "Kept Guy")
    add_player(conn, "p2", "Traded Away Guy")
    add_draft_pick(conn, "L1", 2025, 4, 40, "R1", "p1")
    add_draft_pick(conn, "L1", 2025, 6, 60, "R1", "p2")
    add_roster_player(conn, "L1", "R1", "p1")  # p2 not on the current snapshot

    eligible = keepers.keeper_eligible_players(conn, "L1", 2025)
    names = {row["name"] for row in eligible["R1"]}
    assert names == {"Kept Guy"}


def test_compute_keeper_board_end_to_end():
    conn = make_db()
    add_player(conn, "p1", "Round2 Guy")
    add_player(conn, "p2", "Round4 Guy")
    add_draft_pick(conn, "L1", 2025, 2, 20, "R1", "p1")
    add_draft_pick(conn, "L1", 2025, 4, 40, "R1", "p2")
    add_roster_player(conn, "L1", "R1", "p1")
    add_roster_player(conn, "L1", "R1", "p2")
    keepers.save_keeper_predictions(conn, USER, "L1", SEASON, "R1", ["p1", "p2"])

    board = keepers.compute_keeper_board(conn, "L1", 2025, SEASON, USER)
    by_id = {k["player_id"]: k for k in board["R1"]}
    assert by_id["p1"]["keeper_round"] == 3
    assert by_id["p2"]["keeper_round"] == 5


def test_save_keeper_predictions_caps_at_max_keepers():
    conn = make_db()
    for i in range(5):
        add_player(conn, f"p{i}", f"Guy {i}")
    keepers.save_keeper_predictions(
        conn, USER, "L1", SEASON, "R1", [f"p{i}" for i in range(5)]
    )
    saved = keepers.get_keeper_predictions(conn, USER, "L1", SEASON)
    assert len(saved["R1"]) == keepers.MAX_KEEPERS


def test_set_mock_draft_pick_rejects_keeper_round():
    conn = make_db()
    add_player(conn, "p1", "Open Guy")
    board = {"R1": [{"player_id": "kept", "keeper_round": 3, "conflict": False}]}
    error = keepers.set_mock_draft_pick(
        conn, USER, "L1", SEASON, 3, "R1", "p1", "manual", board, {}
    )
    assert error is not None


def test_set_mock_draft_pick_rejects_duplicate_player():
    conn = make_db()
    add_player(conn, "p1", "Dup Guy")
    board = {}
    existing = {(2, "R2"): {"player_id": "p1", "name": "Dup Guy", "position": "WR",
                             "team": "KC", "source": "manual"}}
    error = keepers.set_mock_draft_pick(
        conn, USER, "L1", SEASON, 5, "R1", "p1", "manual", board, existing
    )
    assert error is not None


def test_set_mock_draft_pick_succeeds_on_open_cell():
    conn = make_db()
    add_player(conn, "p1", "Open Guy")
    error = keepers.set_mock_draft_pick(conn, USER, "L1", SEASON, 5, "R1", "p1", "manual", {}, {})
    assert error is None
    saved = keepers.get_mock_draft_picks(conn, USER, "L1", SEASON)
    assert saved[(5, "R1")]["name"] == "Open Guy"


def test_auto_fill_skips_keeper_and_already_picked_cells():
    conn = make_db()
    add_player(conn, "keeper_p", "Keeper Guy")
    add_player(conn, "avail1", "Available One")
    add_player(conn, "avail2", "Available Two")
    conn.execute("INSERT INTO arbitrage_signals VALUES ('avail1', '1qb', '2026-08-01', 0.9)")
    conn.execute("INSERT INTO arbitrage_signals VALUES ('avail2', '1qb', '2026-08-01', 0.5)")

    board = {"R1": [{"player_id": "keeper_p", "keeper_round": 1, "conflict": False}]}
    existing = {}
    filled = keepers.auto_fill(
        conn, USER, "L1", SEASON, rounds=2, roster_ids=["R1"],
        arb_format="1qb", board=board, existing_picks=existing,
    )
    # Round 1 is a keeper slot -- only round 2 should get filled.
    assert filled == 1
    saved = keepers.get_mock_draft_picks(conn, USER, "L1", SEASON)
    assert (1, "R1") not in saved
    assert saved[(2, "R1")]["name"] == "Available One"  # higher redraft_percentile first
