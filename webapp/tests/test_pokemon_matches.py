"""Pokemon Draft League: match report/confirm/dispute/resolve state
machine tests.

Run with:  python3 -m pytest tests/ -q     (from webapp/)
"""
import sqlite3

from conftest import SQLITE_SCHEMA

from app.pokemon_draft import draft, draft_pool, matches, schedule, seasons


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


def make_match(conn, roster_size_cap=2, point_budget=20):
    """Two coaches (user 1 = home, user 2 = away), each with two drafted
    Pokemon, and one generated (unreported) match between them. Returns
    (season_id, match_id, ian_coach_id, zach_coach_id, [mon ids])."""
    conn.executemany(
        """INSERT INTO pokemon (pokemon_id, species_id, slug, display_name, national_dex_number,
               generation, type1, base_hp, base_atk, base_def, base_spa, base_spd, base_spe)
           VALUES (?, ?, ?, ?, ?, 1, 'normal', 50, 50, 50, 50, 50, 50)""",
        [(i, i, f"mon{i}", f"Mon{i}", i) for i in range(1, 5)],
    )
    seasons.create_format(conn, "gen9ou", "Gen 9 OU", "singles", "", roster_size_cap, point_budget, True)
    season_id, _ = seasons.create_season(conn, "S", "gen9ou", 1)
    seasons.add_coach(conn, season_id, 1, "Ian's Team")
    seasons.add_coach(conn, season_id, 2, "Zach's Team")
    coaches = {c["user_id"]: c["coach_id"] for c in seasons.list_coaches(conn, season_id)}
    ian_coach, zach_coach = coaches[1], coaches[2]
    seasons.set_draft_order(conn, season_id, [ian_coach, zach_coach])
    for pid in (1, 2, 3, 4):
        draft_pool.add_to_pool(conn, season_id, pid, cost_override=2)
    seasons.lock_draft_board(conn, season_id)
    draft.start_draft(conn, season_id)
    draft.make_pick(conn, season_id, 1, 1)
    draft.make_pick(conn, season_id, 2, 2)
    draft.make_pick(conn, season_id, 2, 3)
    draft.make_pick(conn, season_id, 1, 4)

    schedule.generate_schedule(conn, season_id, num_weeks=1)
    row = schedule.overview(conn, season_id)[0]
    return season_id, row["match_id"], ian_coach, zach_coach


def win(coach_id, stats=()):
    return {"winner_coach_id": coach_id, "stats": list(stats)}


# ---------------------------------------------------------------------
# report_match()
# ---------------------------------------------------------------------

def test_only_a_coach_in_the_matchup_can_report():
    conn = make_db()
    season_id, match_id, ian, zach = make_match(conn)
    error = matches.report_match(conn, match_id, 3, [win(ian), win(ian)])  # dick, not a coach
    assert error is not None
    assert matches.get_match(conn, match_id)["status"] == "unreported"


def test_report_requires_a_clear_series_winner():
    conn = make_db()
    season_id, match_id, ian, zach = make_match(conn)
    error = matches.report_match(conn, match_id, 1, [win(ian), win(zach)])  # 1-1 tie, no game 3
    assert error is not None
    assert "clear winner" in error


def test_report_rejects_a_stat_for_a_pokemon_not_on_that_coachs_roster():
    conn = make_db()
    season_id, match_id, ian, zach = make_match(conn)
    # mon2 belongs to zach, not ian -- attributed to ian here
    bad_stats = [{"coach_id": ian, "pokemon_id": 2, "kills": 1, "deaths": 0}]
    error = matches.report_match(conn, match_id, 1, [win(ian, bad_stats), win(ian)])
    assert error is not None and "roster" in error
    assert conn.execute("SELECT count(*) c FROM pokemon_match_games").fetchone()["c"] == 0


def test_successful_report_moves_to_pending_confirmation():
    conn = make_db()
    season_id, match_id, ian, zach = make_match(conn)
    stats = [{"coach_id": ian, "pokemon_id": 1, "kills": 2, "deaths": 0},
              {"coach_id": zach, "pokemon_id": 2, "kills": 0, "deaths": 1}]
    error = matches.report_match(conn, match_id, 1, [win(ian, stats), win(ian)])
    assert error is None
    m = matches.get_match(conn, match_id)
    assert m["status"] == "pending_confirmation"
    assert m["winner_coach_id"] == ian
    assert m["reported_by_user_id"] == 1
    games = matches.get_games(conn, match_id)
    assert len(games) == 2
    assert len(matches.get_stats(conn, games[0]["game_id"])) == 2


def test_cannot_report_a_match_twice():
    conn = make_db()
    season_id, match_id, ian, zach = make_match(conn)
    matches.report_match(conn, match_id, 1, [win(ian), win(ian)])
    error = matches.report_match(conn, match_id, 2, [win(zach), win(zach)])
    assert error is not None
    assert matches.get_match(conn, match_id)["winner_coach_id"] == ian  # unchanged


# ---------------------------------------------------------------------
# confirm_match() / dispute_match()
# ---------------------------------------------------------------------

def test_reporter_cannot_confirm_their_own_report():
    conn = make_db()
    season_id, match_id, ian, zach = make_match(conn)
    matches.report_match(conn, match_id, 1, [win(ian), win(ian)])
    error = matches.confirm_match(conn, match_id, 1)
    assert error is not None
    assert matches.get_match(conn, match_id)["status"] == "pending_confirmation"


def test_a_non_coach_cannot_confirm_or_dispute():
    conn = make_db()
    season_id, match_id, ian, zach = make_match(conn)
    matches.report_match(conn, match_id, 1, [win(ian), win(ian)])
    assert matches.confirm_match(conn, match_id, 3) is not None
    assert matches.dispute_match(conn, match_id, 3, "not fair") is not None


def test_opponent_confirming_finalizes_the_match():
    conn = make_db()
    season_id, match_id, ian, zach = make_match(conn)
    matches.report_match(conn, match_id, 1, [win(ian), win(ian)])
    error = matches.confirm_match(conn, match_id, 2)
    assert error is None
    m = matches.get_match(conn, match_id)
    assert m["status"] == "confirmed" and m["confirmed_at"] is not None


def test_dispute_requires_a_reason():
    conn = make_db()
    season_id, match_id, ian, zach = make_match(conn)
    matches.report_match(conn, match_id, 1, [win(ian), win(ian)])
    error = matches.dispute_match(conn, match_id, 2, "   ")
    assert error is not None
    assert matches.get_match(conn, match_id)["status"] == "pending_confirmation"


def test_opponent_disputing_sets_status_and_reason():
    conn = make_db()
    season_id, match_id, ian, zach = make_match(conn)
    matches.report_match(conn, match_id, 1, [win(ian), win(ian)])
    error = matches.dispute_match(conn, match_id, 2, "that's not what happened")
    assert error is None
    m = matches.get_match(conn, match_id)
    assert m["status"] == "disputed"
    assert m["dispute_reason"] == "that's not what happened"


def test_cannot_confirm_or_dispute_outside_pending_confirmation():
    conn = make_db()
    season_id, match_id, ian, zach = make_match(conn)
    # still unreported
    assert matches.confirm_match(conn, match_id, 2) is not None
    assert matches.dispute_match(conn, match_id, 2, "x") is not None


# ---------------------------------------------------------------------
# resolve_dispute()
# ---------------------------------------------------------------------

def test_resolve_dispute_requires_disputed_status():
    conn = make_db()
    season_id, match_id, ian, zach = make_match(conn)
    matches.report_match(conn, match_id, 1, [win(ian), win(ian)])
    error = matches.resolve_dispute(conn, match_id, 1, "note", [win(zach), win(zach)])
    assert error is not None  # still pending_confirmation, not disputed


def test_resolve_dispute_overrides_the_result_and_confirms():
    conn = make_db()
    season_id, match_id, ian, zach = make_match(conn)
    matches.report_match(conn, match_id, 1, [win(ian), win(ian)])
    matches.dispute_match(conn, match_id, 2, "wrong winner")
    error = matches.resolve_dispute(conn, match_id, 1, "reviewed, zach actually won",
                                     [win(zach), win(zach)])
    assert error is None
    m = matches.get_match(conn, match_id)
    assert m["status"] == "confirmed"
    assert m["winner_coach_id"] == zach
    assert m["dispute_resolved_by"] == 1
    assert m["dispute_resolution_note"] == "reviewed, zach actually won"
    games = matches.get_games(conn, match_id)
    assert all(g["winner_coach_id"] == zach for g in games)
