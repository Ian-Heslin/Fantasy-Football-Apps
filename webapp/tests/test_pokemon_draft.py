"""Pokemon Draft League: live snake draft logic tests.

Pure functions against an in-memory copy of the real schema (same
approach as test_pokemon_seasons.py -- this domain's tables are too
numerous/FK-heavy to hand-maintain a subset safely).

Run with:  python3 -m pytest tests/ -q     (from webapp/)
"""
import sqlite3

from conftest import SQLITE_SCHEMA

from app.pokemon_draft import draft, draft_pool, roster, seasons


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


def make_pokemon(conn, entries):
    """entries: [(pokemon_id, species_id, name), ...] -- generation always
    1, types/stats are filler."""
    conn.executemany(
        """INSERT INTO pokemon (pokemon_id, species_id, slug, display_name, national_dex_number,
               generation, type1, base_hp, base_atk, base_def, base_spa, base_spd, base_spe)
           VALUES (?, ?, ?, ?, ?, 1, 'normal', 50, 50, 50, 50, 50, 50)""",
        [(pid, sid, name.lower(), name, pid) for pid, sid, name in entries],
    )
    conn.commit()


def make_season(conn, roster_size_cap=3, point_budget=20, species_clause=True, coach_user_ids=(1, 2)):
    """A locked-but-not-started draft with the given coaches, in
    user_id order. Returns (season_id, [coach_id, ...] in draft order)."""
    seasons.create_format(conn, "gen9ou", "Gen 9 OU", "singles", "", roster_size_cap,
                           point_budget, species_clause)
    season_id, _ = seasons.create_season(conn, "Test Season", "gen9ou", coach_user_ids[0])
    for uid in coach_user_ids:
        seasons.add_coach(conn, season_id, uid, f"Team {uid}")
    coaches = seasons.list_coaches(conn, season_id)
    coach_ids = [c["coach_id"] for c in coaches]
    seasons.set_draft_order(conn, season_id, coach_ids)
    return season_id, coach_ids


def pool_everything(conn, season_id, cost=2):
    for row in conn.execute("SELECT pokemon_id FROM pokemon"):
        draft_pool.add_to_pool(conn, season_id, row["pokemon_id"], cost_override=cost)


# ---------------------------------------------------------------------
# start_draft() preconditions
# ---------------------------------------------------------------------

def test_start_draft_requires_locked_board():
    conn = make_db()
    make_pokemon(conn, [(1, 1, "Mon1")])
    season_id, _ = make_season(conn)
    error = draft.start_draft(conn, season_id)
    assert error is not None and "Lock" in error
    assert draft.whose_turn(conn, season_id) is None


def test_start_draft_requires_draft_order_for_every_coach():
    conn = make_db()
    make_pokemon(conn, [(1, 1, "Mon1")])
    seasons.create_format(conn, "gen9ou", "Gen 9 OU", "singles", "", 3, 20, True)
    season_id, _ = seasons.create_season(conn, "Test", "gen9ou", 1)
    seasons.add_coach(conn, season_id, 1, "Team 1")
    seasons.add_coach(conn, season_id, 2, "Team 2")  # no draft_order set
    seasons.lock_draft_board(conn, season_id)
    error = draft.start_draft(conn, season_id)
    assert error is not None and "order" in error


def test_start_draft_succeeds_once_locked_and_ordered():
    conn = make_db()
    make_pokemon(conn, [(1, 1, "Mon1")])
    season_id, coach_ids = make_season(conn)
    seasons.lock_draft_board(conn, season_id)
    assert draft.start_draft(conn, season_id) is None
    assert draft.start_draft(conn, season_id) is not None  # already started


# ---------------------------------------------------------------------
# Snake order
# ---------------------------------------------------------------------

def test_snake_order_alternates_by_round():
    conn = make_db()
    make_pokemon(conn, [(i, i, f"Mon{i}") for i in range(1, 10)])
    season_id, coach_ids = make_season(conn, roster_size_cap=3, coach_user_ids=(1, 2, 3))
    pool_everything(conn, season_id, cost=1)
    seasons.lock_draft_board(conn, season_id)
    draft.start_draft(conn, season_id)

    # 3 coaches x 3 rounds: round1 forward, round2 reversed, round3 forward.
    expected = [coach_ids[0], coach_ids[1], coach_ids[2],
                coach_ids[2], coach_ids[1], coach_ids[0],
                coach_ids[0], coach_ids[1], coach_ids[2]]
    seen = []
    for pokemon_id in range(1, 10):
        turn = draft.whose_turn(conn, season_id)
        seen.append(turn["coach"]["coach_id"])
        user_id = conn.execute(
            "SELECT user_id FROM pokemon_season_coaches WHERE coach_id = ?",
            (turn["coach"]["coach_id"],),
        ).fetchone()["user_id"]
        assert draft.make_pick(conn, season_id, user_id, pokemon_id) is None
    assert seen == expected
    assert draft.whose_turn(conn, season_id) is None
    assert draft.get_session(conn, season_id)["status"] == "complete"


def test_snake_order_with_two_coaches():
    conn = make_db()
    make_pokemon(conn, [(i, i, f"Mon{i}") for i in range(1, 5)])
    season_id, coach_ids = make_season(conn, roster_size_cap=2, coach_user_ids=(1, 2))
    pool_everything(conn, season_id, cost=1)
    seasons.lock_draft_board(conn, season_id)
    draft.start_draft(conn, season_id)

    expected = [coach_ids[0], coach_ids[1], coach_ids[1], coach_ids[0]]
    seen = []
    for pokemon_id in range(1, 5):
        turn = draft.whose_turn(conn, season_id)
        seen.append(turn["coach"]["coach_id"])
        user_id = conn.execute(
            "SELECT user_id FROM pokemon_season_coaches WHERE coach_id = ?",
            (turn["coach"]["coach_id"],),
        ).fetchone()["user_id"]
        draft.make_pick(conn, season_id, user_id, pokemon_id)
    assert seen == expected


# ---------------------------------------------------------------------
# Turn enforcement
# ---------------------------------------------------------------------

def test_only_the_coach_on_the_clock_can_pick():
    conn = make_db()
    make_pokemon(conn, [(1, 1, "Mon1")])
    season_id, coach_ids = make_season(conn, coach_user_ids=(1, 2))
    pool_everything(conn, season_id)
    seasons.lock_draft_board(conn, season_id)
    draft.start_draft(conn, season_id)

    error = draft.make_pick(conn, season_id, 2, 1)  # zach, but ian's turn (draft_order[0])
    assert error is not None and "turn" in error
    assert conn.execute("SELECT count(*) c FROM pokemon_draft_picks").fetchone()["c"] == 0


def test_pick_before_draft_started_is_rejected():
    conn = make_db()
    make_pokemon(conn, [(1, 1, "Mon1")])
    season_id, _ = make_season(conn)
    pool_everything(conn, season_id)
    error = draft.make_pick(conn, season_id, 1, 1)
    assert error is not None


# ---------------------------------------------------------------------
# Species clause / pool / bans / duplicates
# ---------------------------------------------------------------------

def test_species_clause_blocks_a_different_form_of_a_drafted_species():
    conn = make_db()
    make_pokemon(conn, [(1, 100, "FormA"), (2, 100, "FormB"), (3, 200, "Other")])
    season_id, coach_ids = make_season(conn, roster_size_cap=2, coach_user_ids=(1, 2))
    pool_everything(conn, season_id)
    seasons.lock_draft_board(conn, season_id)
    draft.start_draft(conn, season_id)

    assert draft.make_pick(conn, season_id, 1, 1) is None  # ian drafts FormA (species 100)
    error = draft.make_pick(conn, season_id, 2, 2)          # zach tries FormB (species 100)
    assert error is not None and "clause" in error
    assert draft.make_pick(conn, season_id, 2, 3) is None    # zach drafts Other instead


def test_species_clause_disabled_allows_both_forms():
    conn = make_db()
    make_pokemon(conn, [(1, 100, "FormA"), (2, 100, "FormB")])
    season_id, coach_ids = make_season(conn, roster_size_cap=2, species_clause=False, coach_user_ids=(1, 2))
    pool_everything(conn, season_id)
    seasons.lock_draft_board(conn, season_id)
    draft.start_draft(conn, season_id)
    assert draft.make_pick(conn, season_id, 1, 1) is None
    assert draft.make_pick(conn, season_id, 2, 2) is None


def test_pokemon_not_in_pool_is_rejected():
    conn = make_db()
    make_pokemon(conn, [(1, 1, "Mon1")])
    season_id, _ = make_season(conn, coach_user_ids=(1, 2))
    # deliberately not pooled
    seasons.lock_draft_board(conn, season_id)
    draft.start_draft(conn, season_id)
    error = draft.make_pick(conn, season_id, 1, 1)
    assert error is not None and "pool" in error


def test_banned_pokemon_is_rejected():
    conn = make_db()
    make_pokemon(conn, [(1, 1, "Mon1")])
    season_id, _ = make_season(conn, coach_user_ids=(1, 2))
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=2)
    draft_pool.set_ban(conn, season_id, 1, True)
    seasons.lock_draft_board(conn, season_id)
    draft.start_draft(conn, season_id)
    error = draft.make_pick(conn, season_id, 1, 1)
    assert error is not None and "banned" in error


def test_already_drafted_pokemon_cannot_be_drafted_again():
    conn = make_db()
    make_pokemon(conn, [(1, 1, "Mon1"), (2, 2, "Mon2")])
    season_id, coach_ids = make_season(conn, roster_size_cap=2, coach_user_ids=(1, 2))
    pool_everything(conn, season_id)
    seasons.lock_draft_board(conn, season_id)
    draft.start_draft(conn, season_id)
    draft.make_pick(conn, season_id, 1, 1)
    # zach's turn now -- try mon1 again directly (bypassing "already picked"
    # via drafted_species check too, since species differ here)
    error = draft.make_pick(conn, season_id, 2, 1)
    assert error is not None and "already been drafted" in error


# ---------------------------------------------------------------------
# Budget / roster cap
# ---------------------------------------------------------------------

def test_budget_cap_enforced():
    conn = make_db()
    make_pokemon(conn, [(1, 1, "Expensive"), (2, 2, "Cheap")])
    season_id, _ = make_season(conn, roster_size_cap=2, point_budget=10, coach_user_ids=(1, 2))
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=15)
    draft_pool.add_to_pool(conn, season_id, 2, cost_override=5)
    seasons.lock_draft_board(conn, season_id)
    draft.start_draft(conn, season_id)
    error = draft.make_pick(conn, season_id, 1, 1)
    assert error is not None and "budget" in error
    assert draft.make_pick(conn, season_id, 1, 2) is None  # fits


def test_roster_cap_enforced():
    conn = make_db()
    make_pokemon(conn, [(i, i, f"Mon{i}") for i in range(1, 4)])
    season_id, coach_ids = make_season(conn, roster_size_cap=1, point_budget=100, coach_user_ids=(1, 2))
    pool_everything(conn, season_id)
    seasons.lock_draft_board(conn, season_id)
    draft.start_draft(conn, season_id)
    assert draft.make_pick(conn, season_id, 1, 1) is None  # ian fills their 1 slot
    assert draft.make_pick(conn, season_id, 2, 2) is None  # zach fills their 1 slot
    # draft is now complete (1 coach-slot each x 2 coaches = 2 picks)
    assert draft.whose_turn(conn, season_id) is None


# ---------------------------------------------------------------------
# Roster ledger written alongside each pick
# ---------------------------------------------------------------------

def test_pick_writes_a_roster_moves_ledger_row():
    conn = make_db()
    make_pokemon(conn, [(1, 1, "Mon1")])
    season_id, coach_ids = make_season(conn, coach_user_ids=(1, 2))
    pool_everything(conn, season_id, cost=7)
    seasons.lock_draft_board(conn, season_id)
    draft.start_draft(conn, season_id)
    draft.make_pick(conn, season_id, 1, 1)

    count, spent = roster.roster_summary(conn, season_id, coach_ids[0])
    assert count == 1 and spent == 7
    move = conn.execute("SELECT * FROM pokemon_roster_moves WHERE season_id = ?", (season_id,)).fetchone()
    assert move["move_type"] == "draft" and move["cost"] == 7 and move["pokemon_id"] == 1
