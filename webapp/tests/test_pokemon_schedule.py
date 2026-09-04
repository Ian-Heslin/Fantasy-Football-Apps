"""Pokemon Draft League: round-robin schedule generation tests.

Run with:  python3 -m pytest tests/ -q     (from webapp/)
"""
import sqlite3

from conftest import SQLITE_SCHEMA

from app.pokemon_draft import matches, schedule, seasons


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with open(SQLITE_SCHEMA) as f:
        conn.executescript(f.read())
    conn.executemany(
        "INSERT INTO users (user_id, username, password_hash, tier) VALUES (?, ?, 'x', 'games')",
        [(1, "a"), (2, "b"), (3, "c"), (4, "d"), (5, "e")],
    )
    conn.commit()
    return conn


def make_season_with_coaches(conn, n):
    seasons.create_format(conn, "gen9ou", "Gen 9 OU", "singles", "", 10, 100, True)
    season_id, _ = seasons.create_season(conn, "S", "gen9ou", 1)
    for uid in range(1, n + 1):
        seasons.add_coach(conn, season_id, uid, f"Team{uid}")
    return season_id, [c["coach_id"] for c in seasons.list_coaches(conn, season_id)]


# ---------------------------------------------------------------------
# round_robin_rounds() -- pure math, no DB
# ---------------------------------------------------------------------

def test_even_coach_count_has_no_byes_and_covers_every_pair_once():
    rounds = schedule.round_robin_rounds([1, 2, 3, 4])
    assert len(rounds) == 3
    for r in rounds:
        assert len(r) == 2
        assert all(a is not None and b is not None for a, b in r)
    pairs = {frozenset(p) for r in rounds for p in r}
    assert len(pairs) == 6  # C(4,2)


def test_odd_coach_count_gives_each_coach_exactly_one_bye():
    rounds = schedule.round_robin_rounds([1, 2, 3])
    byes = [a for r in rounds for a, b in r if b is None]
    assert sorted(byes) == [1, 2, 3]
    real_pairs = {frozenset((a, b)) for r in rounds for a, b in r if b is not None}
    assert len(real_pairs) == 3  # C(3,2)


def test_fewer_than_two_coaches_has_no_rounds():
    assert schedule.round_robin_rounds([1]) == []
    assert schedule.round_robin_rounds([]) == []


# ---------------------------------------------------------------------
# generate_schedule() / clear_schedule()
# ---------------------------------------------------------------------

def test_generate_schedule_requires_at_least_two_coaches():
    conn = make_db()
    season_id, _ = make_season_with_coaches(conn, 1)
    count, error = schedule.generate_schedule(conn, season_id, num_weeks=3)
    assert count == 0 and error is not None


def test_generate_schedule_creates_a_match_row_per_non_bye_game():
    conn = make_db()
    season_id, coach_ids = make_season_with_coaches(conn, 4)
    count, error = schedule.generate_schedule(conn, season_id, num_weeks=3)
    assert error is None
    assert count == 6  # 3 rounds x 2 games, no byes with 4 coaches
    match_count = conn.execute("SELECT count(*) c FROM pokemon_matches").fetchone()["c"]
    assert match_count == 6
    for row in conn.execute("SELECT status FROM pokemon_matches"):
        assert row["status"] == "unreported"


def test_generate_schedule_cycles_through_the_round_robin_for_extra_weeks():
    conn = make_db()
    season_id, coach_ids = make_season_with_coaches(conn, 4)
    schedule.generate_schedule(conn, season_id, num_weeks=6)  # 2x a 3-week round robin
    weeks = {r["week"] for r in schedule.overview(conn, season_id)}
    assert weeks == {1, 2, 3, 4, 5, 6}


def test_bye_week_gets_a_schedule_row_with_no_match():
    conn = make_db()
    season_id, coach_ids = make_season_with_coaches(conn, 3)
    schedule.generate_schedule(conn, season_id, num_weeks=3)
    rows = schedule.overview(conn, season_id)
    byes = [r for r in rows if r["coach_id_away"] is None]
    assert len(byes) == 3  # one per coach across 3 rounds
    assert all(r["match_id"] is None for r in byes)


def test_cannot_regenerate_an_existing_schedule():
    conn = make_db()
    season_id, _ = make_season_with_coaches(conn, 4)
    schedule.generate_schedule(conn, season_id, num_weeks=3)
    count, error = schedule.generate_schedule(conn, season_id, num_weeks=3)
    assert count == 0 and error is not None


def test_clear_schedule_refuses_once_a_match_is_reported():
    conn = make_db()
    season_id, coach_ids = make_season_with_coaches(conn, 2)
    schedule.generate_schedule(conn, season_id, num_weeks=1)
    row = schedule.overview(conn, season_id)[0]
    matches.report_match(conn, row["match_id"], 1, [{"winner_coach_id": coach_ids[0], "stats": []},
                                                      {"winner_coach_id": coach_ids[0], "stats": []}])
    error = schedule.clear_schedule(conn, season_id)
    assert error is not None
    assert schedule.has_schedule(conn, season_id)


def test_clear_schedule_works_when_nothing_reported_and_allows_regeneration():
    conn = make_db()
    season_id, _ = make_season_with_coaches(conn, 4)
    schedule.generate_schedule(conn, season_id, num_weeks=3)
    assert schedule.clear_schedule(conn, season_id) is None
    assert not schedule.has_schedule(conn, season_id)
    count, error = schedule.generate_schedule(conn, season_id, num_weeks=5)
    assert error is None and count > 0
