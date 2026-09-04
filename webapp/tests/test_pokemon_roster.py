"""Pokemon Draft League: free agency (add/drop) and trade logic tests.
FA transactions only count toward the season cap on 'fa_add' -- drops
(standalone or trade-bundled) are always free (confirmed requirement).
Trades re-price every INCOMING Pokemon at its CURRENT effective_cost (not
whatever the previous owner paid) and reject the whole offer, writing
nothing, if either resulting roster would exceed budget or the roster-size
cap -- see app/pokemon_draft/roster.py's module docstring.

Run with:  python3 -m pytest tests/ -q     (from webapp/)
"""
import sqlite3

from conftest import SQLITE_SCHEMA

from app.pokemon_draft import draft_pool, roster, seasons


def make_db(n_coaches, roster_size_cap=6, point_budget=20, species_clause_enabled=True,
            fa_transactions_allowed=2, roster_freeze_week=None):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with open(SQLITE_SCHEMA) as f:
        conn.executescript(f.read())
    conn.executemany(
        "INSERT INTO users (user_id, username, password_hash, tier) VALUES (?, ?, 'x', 'games')",
        [(i, f"user{i}") for i in range(1, max(n_coaches, 1) + 1)],
    )
    seasons.create_format(conn, "gen9ou", "Gen 9 OU", "singles", "", roster_size_cap, point_budget, True)
    season_id, _ = seasons.create_season(conn, "S", "gen9ou", 1)
    seasons.update_ruleset(conn, season_id, roster_size_cap, point_budget, species_clause_enabled,
                            fa_transactions_allowed, roster_freeze_week, 4)
    for uid in range(1, n_coaches + 1):
        seasons.add_coach(conn, season_id, uid, f"Team{uid}")
    coaches = {c["user_id"]: c["coach_id"] for c in seasons.list_coaches(conn, season_id)}
    return conn, season_id, coaches


def add_pokemon(conn, pokemon_id, species_id=None, display_name=None):
    conn.execute(
        """INSERT INTO pokemon (pokemon_id, species_id, slug, display_name, national_dex_number,
               generation, type1, base_hp, base_atk, base_def, base_spa, base_spd, base_spe)
           VALUES (?, ?, ?, ?, ?, 1, 'normal', 50, 50, 50, 50, 50, 50)""",
        (pokemon_id, species_id if species_id is not None else pokemon_id, f"mon{pokemon_id}",
         display_name or f"Mon{pokemon_id}", pokemon_id),
    )


def draft_pick(conn, season_id, coach_id, pokemon_id, cost):
    """Seeds an initial roster slot the way draft.make_pick() would --
    used here instead of running a full draft so FA/trade tests can set up
    a starting roster directly."""
    conn.execute(
        """INSERT INTO pokemon_roster_moves (season_id, coach_id, pokemon_id, move_type, cost,
               counts_toward_fa_cap) VALUES (?, ?, ?, 'draft', ?, 0)""",
        (season_id, coach_id, pokemon_id, cost),
    )
    conn.commit()


# ---------------------------------------------------------------------
# Free agency: add
# ---------------------------------------------------------------------

def test_fa_add_writes_a_roster_move_and_counts_toward_cap():
    conn, season_id, coaches = make_db(1)
    A = coaches[1]
    add_pokemon(conn, 1)
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=5)

    error = roster.fa_add(conn, season_id, A, 1)
    assert error is None
    assert {r["pokemon_id"] for r in roster.current_roster(conn, season_id, A)} == {1}
    assert roster.fa_transactions_used(conn, season_id, A) == 1


def test_fa_add_rejects_pokemon_with_no_cost_set():
    conn, season_id, coaches = make_db(1)
    A = coaches[1]
    add_pokemon(conn, 1)
    draft_pool.add_to_pool(conn, season_id, 1)  # no cost_override, no computed_cost either

    error = roster.fa_add(conn, season_id, A, 1)
    assert error is not None and "cost" in error
    assert roster.current_roster(conn, season_id, A) == []


def test_fa_add_rejects_a_pokemon_already_on_a_roster():
    conn, season_id, coaches = make_db(2)
    A, B = coaches[1], coaches[2]
    add_pokemon(conn, 1)
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=5)
    draft_pick(conn, season_id, A, 1, 5)

    error = roster.fa_add(conn, season_id, B, 1)
    assert error is not None and "already on a roster" in error


def test_fa_add_enforces_species_clause_across_forms():
    conn, season_id, coaches = make_db(1, species_clause_enabled=True)
    A = coaches[1]
    add_pokemon(conn, 1, species_id=100, display_name="Landorus (Incarnate)")
    add_pokemon(conn, 2, species_id=100, display_name="Landorus (Therian)")
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=5)
    draft_pool.add_to_pool(conn, season_id, 2, cost_override=5)
    draft_pick(conn, season_id, A, 1, 5)

    error = roster.fa_add(conn, season_id, A, 2)
    assert error is not None and "Species clause" in error


def test_fa_add_species_clause_only_blocks_when_enabled():
    conn, season_id, coaches = make_db(1, species_clause_enabled=False)
    A = coaches[1]
    add_pokemon(conn, 1, species_id=100)
    add_pokemon(conn, 2, species_id=100)
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=5)
    draft_pool.add_to_pool(conn, season_id, 2, cost_override=5)
    draft_pick(conn, season_id, A, 1, 5)

    assert roster.fa_add(conn, season_id, A, 2) is None


def test_fa_add_rejects_over_roster_size_cap():
    conn, season_id, coaches = make_db(1, roster_size_cap=1)
    A = coaches[1]
    add_pokemon(conn, 1)
    add_pokemon(conn, 2)
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=1)
    draft_pool.add_to_pool(conn, season_id, 2, cost_override=1)
    draft_pick(conn, season_id, A, 1, 1)

    error = roster.fa_add(conn, season_id, A, 2)
    assert error is not None and "full" in error


def test_fa_add_rejects_over_point_budget():
    conn, season_id, coaches = make_db(1, point_budget=5)
    A = coaches[1]
    add_pokemon(conn, 1)
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=6)

    error = roster.fa_add(conn, season_id, A, 1)
    assert error is not None and "budget" in error


def test_fa_add_rejects_once_transaction_cap_used_up():
    conn, season_id, coaches = make_db(1, fa_transactions_allowed=1)
    A = coaches[1]
    add_pokemon(conn, 1)
    add_pokemon(conn, 2)
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=1)
    draft_pool.add_to_pool(conn, season_id, 2, cost_override=1)
    assert roster.fa_add(conn, season_id, A, 1) is None

    error = roster.fa_add(conn, season_id, A, 2)
    assert error is not None and "free agent transactions" in error


# ---------------------------------------------------------------------
# Free agency: drop
# ---------------------------------------------------------------------

def test_fa_drop_is_free_and_does_not_count_toward_cap():
    conn, season_id, coaches = make_db(1)
    A = coaches[1]
    add_pokemon(conn, 1)
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=5)
    draft_pick(conn, season_id, A, 1, 5)

    assert roster.fa_drop(conn, season_id, A, 1) is None
    assert roster.current_roster(conn, season_id, A) == []
    assert roster.fa_transactions_used(conn, season_id, A) == 0


def test_fa_drop_rejects_a_pokemon_not_on_that_roster():
    conn, season_id, coaches = make_db(1)
    A = coaches[1]
    add_pokemon(conn, 1)
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=5)

    error = roster.fa_drop(conn, season_id, A, 1)
    assert error is not None and "isn't on your roster" in error


def test_a_dropped_pokemon_becomes_available_for_another_coach():
    conn, season_id, coaches = make_db(2)
    A, B = coaches[1], coaches[2]
    add_pokemon(conn, 1)
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=5)
    draft_pick(conn, season_id, A, 1, 5)
    assert roster.fa_drop(conn, season_id, A, 1) is None
    assert roster.fa_add(conn, season_id, B, 1) is None
    assert {r["pokemon_id"] for r in roster.current_roster(conn, season_id, B)} == {1}


# ---------------------------------------------------------------------
# Roster freeze
# ---------------------------------------------------------------------

def test_roster_freeze_blocks_fa_add_and_drop_once_the_freeze_week_is_reached():
    conn, season_id, coaches = make_db(1, roster_freeze_week=1)
    A = coaches[1]
    add_pokemon(conn, 1)
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=5)
    draft_pick(conn, season_id, A, 1, 5)
    # current_week() falls back to None with no schedule at all, so give it
    # one week-1 schedule row (unconfirmed) to make week 1 "current".
    conn.execute(
        "INSERT INTO pokemon_schedule (season_id, week, coach_id_home, coach_id_away) VALUES (?, 1, ?, NULL)",
        (season_id, A),
    )
    conn.commit()

    error = roster.fa_add(conn, season_id, A, 1)
    assert error is not None and "frozen" in error
    error = roster.fa_drop(conn, season_id, A, 1)
    assert error is not None and "frozen" in error


def test_no_freeze_configured_never_blocks_moves():
    conn, season_id, coaches = make_db(1, roster_freeze_week=None)
    A = coaches[1]
    add_pokemon(conn, 1)
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=5)
    assert roster.fa_add(conn, season_id, A, 1) is None


# ---------------------------------------------------------------------
# Trades: proposing
# ---------------------------------------------------------------------

def _two_coach_setup(**kwargs):
    conn, season_id, coaches = make_db(2, **kwargs)
    A, B = coaches[1], coaches[2]
    add_pokemon(conn, 1)
    add_pokemon(conn, 2)
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=5)
    draft_pool.add_to_pool(conn, season_id, 2, cost_override=5)
    draft_pick(conn, season_id, A, 1, 5)
    draft_pick(conn, season_id, B, 2, 5)
    return conn, season_id, A, B


def test_propose_trade_rejects_trading_with_yourself():
    conn, season_id, A, B = _two_coach_setup()
    _tid, error = roster.propose_trade(conn, season_id, A, A, [
        {"pokemon_id": 1, "from_coach_id": A, "action": "trade"}])
    assert error is not None and "yourself" in error


def test_propose_trade_requires_at_least_one_pokemon_actually_trading():
    conn, season_id, A, B = _two_coach_setup()
    _tid, error = roster.propose_trade(conn, season_id, A, B, [
        {"pokemon_id": 1, "from_coach_id": A, "action": "drop"}])
    assert error is not None and "changing hands" in error


def test_propose_trade_rejects_a_pokemon_not_on_that_coachs_roster():
    conn, season_id, A, B = _two_coach_setup()
    _tid, error = roster.propose_trade(conn, season_id, A, B, [
        {"pokemon_id": 2, "from_coach_id": A, "action": "trade"}])  # 2 belongs to B, not A
    assert error is not None and "current roster" in error


def test_propose_trade_succeeds_and_is_listed_pending_for_both_coaches():
    conn, season_id, A, B = _two_coach_setup()
    trade_id, error = roster.propose_trade(conn, season_id, A, B, [
        {"pokemon_id": 1, "from_coach_id": A, "action": "trade"}])
    assert error is None
    assert any(t["trade_id"] == trade_id for t in roster.list_pending_trades(conn, season_id, A))
    assert any(t["trade_id"] == trade_id for t in roster.list_pending_trades(conn, season_id, B))


# ---------------------------------------------------------------------
# Trades: accepting
# ---------------------------------------------------------------------

def test_accept_trade_swaps_rosters_and_reprices_at_current_effective_cost():
    conn, season_id, A, B = _two_coach_setup(point_budget=20)
    # Re-price pokemon 1 upward after the trade is proposed but before it's
    # accepted -- the trade must charge B the CURRENT cost (8), not the 5 A paid.
    trade_id, error = roster.propose_trade(conn, season_id, A, B, [
        {"pokemon_id": 1, "from_coach_id": A, "action": "trade"}])
    assert error is None
    draft_pool.set_cost_override(conn, season_id, 1, 8)

    b_user_id = 2  # user_id == coach's owning user in make_db()'s 1:1 setup
    error = roster.accept_trade(conn, trade_id, b_user_id)
    assert error is None

    a_roster = roster.current_roster(conn, season_id, A)
    b_roster = {r["pokemon_id"]: r["cost"] for r in roster.current_roster(conn, season_id, B)}
    assert a_roster == []
    assert b_roster == {2: 5, 1: 8}
    offer = roster.get_trade_offer(conn, trade_id)[0]
    assert offer["status"] == "accepted"


def test_accept_trade_rejects_when_it_would_exceed_the_point_budget():
    conn, season_id, A, B = _two_coach_setup(point_budget=6)  # B already at 5/6
    trade_id, error = roster.propose_trade(conn, season_id, A, B, [
        {"pokemon_id": 1, "from_coach_id": A, "action": "trade"}])
    assert error is None
    draft_pool.set_cost_override(conn, season_id, 1, 5)  # 5 (kept: pokemon 2) + 5 (incoming) > 6

    error = roster.accept_trade(conn, trade_id, 2)
    assert error is not None and "point cap" in error
    # Nothing written -- both rosters unchanged, offer still pending.
    assert {r["pokemon_id"] for r in roster.current_roster(conn, season_id, A)} == {1}
    assert {r["pokemon_id"] for r in roster.current_roster(conn, season_id, B)} == {2}
    assert roster.get_trade_offer(conn, trade_id)[0]["status"] == "pending"


def test_a_bundled_drop_keeps_an_otherwise_over_budget_trade_legal():
    conn, season_id, A, B = _two_coach_setup(point_budget=10, roster_size_cap=6)
    add_pokemon(conn, 3)
    draft_pool.add_to_pool(conn, season_id, 3, cost_override=5)
    draft_pick(conn, season_id, B, 3, 5)  # B: pokemon 2 (5) + pokemon 3 (5) = 10/10, no room for more

    draft_pool.set_cost_override(conn, season_id, 1, 5)
    # Without dropping 3, B receiving 1 would be 5 (kept 2) + 5 (kept 3) + 5 (incoming 1) = 15 > 10.
    # Dropping 3 alongside it brings B back to 5 (kept 2) + 5 (incoming 1) = 10, exactly at cap.
    trade_id, error = roster.propose_trade(conn, season_id, A, B, [
        {"pokemon_id": 1, "from_coach_id": A, "action": "trade"},
        {"pokemon_id": 3, "from_coach_id": B, "action": "drop"},
    ])
    assert error is None
    assert roster.accept_trade(conn, trade_id, 2) is None
    assert {r["pokemon_id"] for r in roster.current_roster(conn, season_id, B)} == {2, 1}
    # The bundled drop never touched the FA cap.
    assert roster.fa_transactions_used(conn, season_id, B) == 0


def test_accept_trade_rejects_when_a_traded_pokemon_already_left_the_roster():
    conn, season_id, A, B = _two_coach_setup()
    trade_id, error = roster.propose_trade(conn, season_id, A, B, [
        {"pokemon_id": 1, "from_coach_id": A, "action": "trade"}])
    assert error is None
    assert roster.fa_drop(conn, season_id, A, 1) is None  # A drops it before B accepts

    error = roster.accept_trade(conn, trade_id, 2)
    assert error is not None and "already left" in error


def test_only_the_receiving_coachs_user_can_accept():
    conn, season_id, A, B = _two_coach_setup()
    trade_id, error = roster.propose_trade(conn, season_id, A, B, [
        {"pokemon_id": 1, "from_coach_id": A, "action": "trade"}])
    assert error is None
    error = roster.accept_trade(conn, trade_id, 1)  # A's own user_id, not B's
    assert error is not None and "receiving coach" in error


def test_cannot_accept_a_trade_thats_no_longer_pending():
    conn, season_id, A, B = _two_coach_setup()
    trade_id, error = roster.propose_trade(conn, season_id, A, B, [
        {"pokemon_id": 1, "from_coach_id": A, "action": "trade"}])
    assert error is None
    assert roster.respond_to_trade(conn, trade_id, 1) is None  # proposer cancels

    error = roster.accept_trade(conn, trade_id, 2)
    assert error is not None and "no longer pending" in error


def test_roster_freeze_blocks_trade_acceptance():
    conn, season_id, A, B = _two_coach_setup(roster_freeze_week=1)
    trade_id, error = roster.propose_trade(conn, season_id, A, B, [
        {"pokemon_id": 1, "from_coach_id": A, "action": "trade"}])
    assert error is None
    conn.execute(
        "INSERT INTO pokemon_schedule (season_id, week, coach_id_home, coach_id_away) VALUES (?, 1, ?, NULL)",
        (season_id, A),
    )
    conn.commit()

    error = roster.accept_trade(conn, trade_id, 2)
    assert error is not None and "frozen" in error


# ---------------------------------------------------------------------
# Trades: reject / cancel
# ---------------------------------------------------------------------

def test_receiving_coach_rejects_a_pending_offer():
    conn, season_id, A, B = _two_coach_setup()
    trade_id, error = roster.propose_trade(conn, season_id, A, B, [
        {"pokemon_id": 1, "from_coach_id": A, "action": "trade"}])
    assert error is None
    assert roster.respond_to_trade(conn, trade_id, 2) is None
    assert roster.get_trade_offer(conn, trade_id)[0]["status"] == "rejected"


def test_proposing_coach_cancels_a_pending_offer():
    conn, season_id, A, B = _two_coach_setup()
    trade_id, error = roster.propose_trade(conn, season_id, A, B, [
        {"pokemon_id": 1, "from_coach_id": A, "action": "trade"}])
    assert error is None
    assert roster.respond_to_trade(conn, trade_id, 1) is None
    assert roster.get_trade_offer(conn, trade_id)[0]["status"] == "cancelled"


def test_a_third_party_cannot_respond_to_a_trade_theyre_not_part_of():
    conn, season_id, coaches = make_db(3)
    A, B, C = coaches[1], coaches[2], coaches[3]
    add_pokemon(conn, 1)
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=5)
    draft_pick(conn, season_id, A, 1, 5)
    trade_id, error = roster.propose_trade(conn, season_id, A, B, [
        {"pokemon_id": 1, "from_coach_id": A, "action": "trade"}])
    assert error is None

    error = roster.respond_to_trade(conn, trade_id, 3)  # C's user_id
    assert error is not None and "not part of this trade" in error
    assert roster.get_trade_offer(conn, trade_id)[0]["status"] == "pending"
