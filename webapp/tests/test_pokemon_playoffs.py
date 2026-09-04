"""Pokemon Draft League: playoff bracket tests (seeding, standard-seed
pairing, round advancement, and the clear-bracket guard). Mirrors
test_pokemon_standings.py's self-contained in-memory DB helper rather than
importing it, since the two files test different subsystems and cross-file
test imports aren't a pattern this suite otherwise uses.

Run with:  python3 -m pytest tests/ -q     (from webapp/)
"""
import sqlite3

from conftest import SQLITE_SCHEMA

from app.pokemon_draft import matches, playoffs, schedule, seasons


def make_db(n_coaches, playoff_bracket_size=None):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with open(SQLITE_SCHEMA) as f:
        conn.executescript(f.read())
    conn.executemany(
        "INSERT INTO users (user_id, username, password_hash, tier) VALUES (?, ?, 'x', 'games')",
        [(i, f"user{i}") for i in range(1, max(n_coaches, 1) + 1)],
    )
    seasons.create_format(conn, "gen9ou", "Gen 9 OU", "singles", "", 3, 20, True)
    season_id, _ = seasons.create_season(conn, "S", "gen9ou", 1)
    for uid in range(1, n_coaches + 1):
        seasons.add_coach(conn, season_id, uid, f"Team{uid}")
    coaches = {c["user_id"]: c["coach_id"] for c in seasons.list_coaches(conn, season_id)}
    if playoff_bracket_size is not None:
        season = seasons.get_season(conn, season_id)
        error = seasons.update_ruleset(
            conn, season_id, season["roster_size_cap"], season["point_budget"],
            season["species_clause_enabled"], season["fa_transactions_allowed"],
            season["roster_freeze_week"], playoff_bracket_size)
        assert error is None, error
    return conn, season_id, coaches


def report_and_confirm(conn, match_id, winner, games=2):
    m = matches.get_match(conn, match_id)
    result = [{"winner_coach_id": winner, "stats": []} for _ in range(games)]
    assert matches.report_match(conn, match_id, m["home_user_id"], result) is None
    assert matches.confirm_match(conn, match_id, m["away_user_id"]) is None


def build_pairs(conn, season_id, num_weeks):
    schedule.generate_schedule(conn, season_id, num_weeks=num_weeks)
    rows = schedule.overview(conn, season_id)
    return {frozenset((r["coach_id_home"], r["coach_id_away"])): r["match_id"]
            for r in rows if r["coach_id_away"] is not None}


def rank_coaches_by_series_wins(conn, season_id, coaches, wins_desc):
    """Give coach `wins_desc[i]` exactly `len(wins_desc) - 1 - i` series
    wins by beating everyone ranked below it -- a simple way to produce a
    fully-ordered standings table with no ties to seed a bracket from."""
    pairs = build_pairs(conn, season_id, num_weeks=len(wins_desc))
    for i, winner in enumerate(wins_desc):
        for loser in wins_desc[i + 1:]:
            match_id = pairs[frozenset((winner, loser))]
            report_and_confirm(conn, match_id, winner)


# ---------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------

def test_seed_bracket_size4_pairs_1v4_and_2v3():
    conn, season_id, coaches = make_db(4, playoff_bracket_size=4)
    ranked_coach_ids = [coaches[1], coaches[2], coaches[3], coaches[4]]
    rank_coaches_by_series_wins(conn, season_id, coaches, ranked_coach_ids)

    error = playoffs.seed_bracket(conn, season_id)
    assert error is None, error

    view = {r["slot"]: r for r in playoffs.bracket_view(conn, season_id)}
    assert {view["SF1"]["coach_id_home"], view["SF1"]["coach_id_away"]} == \
        {ranked_coach_ids[0], ranked_coach_ids[3]}
    assert {view["SF2"]["coach_id_home"], view["SF2"]["coach_id_away"]} == \
        {ranked_coach_ids[1], ranked_coach_ids[2]}
    assert view["F"]["coach_id_home"] is None and view["F"]["coach_id_away"] is None
    assert view["F"]["schedule_id"] is None  # not created until both semis decide


def test_seed_bracket_size8_uses_standard_tournament_seeding():
    conn, season_id, coaches = make_db(8, playoff_bracket_size=8)
    ranked_coach_ids = [coaches[i] for i in range(1, 9)]
    rank_coaches_by_series_wins(conn, season_id, coaches, ranked_coach_ids)

    assert playoffs.seed_bracket(conn, season_id) is None
    view = {r["slot"]: r for r in playoffs.bracket_view(conn, season_id)}
    seed = lambda n: ranked_coach_ids[n - 1]  # noqa: E731
    expected = {"QF1": (1, 8), "QF2": (4, 5), "QF3": (2, 7), "QF4": (3, 6)}
    for slot, (a, b) in expected.items():
        assert {view[slot]["coach_id_home"], view[slot]["coach_id_away"]} == {seed(a), seed(b)}


def test_seed_bracket_requires_enough_ranked_coaches():
    conn, season_id, coaches = make_db(3, playoff_bracket_size=4)
    error = playoffs.seed_bracket(conn, season_id)
    assert error is not None
    assert not playoffs.is_seeded(conn, season_id)


def test_seed_bracket_refuses_an_invalid_bracket_size():
    conn, season_id, coaches = make_db(4, playoff_bracket_size=6)
    error = playoffs.seed_bracket(conn, season_id)
    assert error is not None
    assert "2, 4, 8" in error


def test_seed_bracket_refuses_to_reseed():
    conn, season_id, coaches = make_db(2, playoff_bracket_size=2)
    rank_coaches_by_series_wins(conn, season_id, coaches, [coaches[1], coaches[2]])
    assert playoffs.seed_bracket(conn, season_id) is None
    error = playoffs.seed_bracket(conn, season_id)
    assert error is not None and "already been seeded" in error


# ---------------------------------------------------------------------
# Advancement
# ---------------------------------------------------------------------

def test_advance_bracket_walks_winners_into_the_final():
    conn, season_id, coaches = make_db(4, playoff_bracket_size=4)
    ranked = [coaches[1], coaches[2], coaches[3], coaches[4]]
    rank_coaches_by_series_wins(conn, season_id, coaches, ranked)
    assert playoffs.seed_bracket(conn, season_id) is None

    view = {r["slot"]: r for r in playoffs.bracket_view(conn, season_id)}
    sf1_match_id, sf2_match_id = view["SF1"]["match_id"], view["SF2"]["match_id"]

    assert playoffs.champion(conn, season_id) is None

    report_and_confirm(conn, sf1_match_id, ranked[0])
    playoffs.advance_bracket(conn, season_id)
    # Final not creatable yet -- SF2 hasn't decided.
    view = {r["slot"]: r for r in playoffs.bracket_view(conn, season_id)}
    assert view["F"]["schedule_id"] is None
    assert playoffs.champion(conn, season_id) is None

    report_and_confirm(conn, sf2_match_id, ranked[1])
    playoffs.advance_bracket(conn, season_id)
    view = {r["slot"]: r for r in playoffs.bracket_view(conn, season_id)}
    assert {view["F"]["coach_id_home"], view["F"]["coach_id_away"]} == {ranked[0], ranked[1]}

    final_match_id = view["F"]["match_id"]
    report_and_confirm(conn, final_match_id, ranked[0])
    playoffs.advance_bracket(conn, season_id)
    assert playoffs.champion(conn, season_id) == ranked[0]


def test_advance_bracket_is_idempotent():
    conn, season_id, coaches = make_db(2, playoff_bracket_size=2)
    ranked = [coaches[1], coaches[2]]
    rank_coaches_by_series_wins(conn, season_id, coaches, ranked)
    assert playoffs.seed_bracket(conn, season_id) is None
    view = {r["slot"]: r for r in playoffs.bracket_view(conn, season_id)}
    report_and_confirm(conn, view["F"]["match_id"], ranked[0])

    playoffs.advance_bracket(conn, season_id)
    playoffs.advance_bracket(conn, season_id)  # calling twice must not error or duplicate rows
    assert playoffs.champion(conn, season_id) == ranked[0]
    match_count = conn.execute(
        "SELECT count(*) c FROM pokemon_matches m JOIN pokemon_schedule s "
        "ON s.schedule_id = m.schedule_id WHERE s.season_id = ? AND s.round IS NOT NULL",
        (season_id,),
    ).fetchone()["c"]
    assert match_count == 1


# ---------------------------------------------------------------------
# Clearing
# ---------------------------------------------------------------------

def test_clear_bracket_removes_everything_when_untouched():
    conn, season_id, coaches = make_db(2, playoff_bracket_size=2)
    rank_coaches_by_series_wins(conn, season_id, coaches, [coaches[1], coaches[2]])
    assert playoffs.seed_bracket(conn, season_id) is None
    assert playoffs.clear_bracket(conn, season_id) is None
    assert not playoffs.is_seeded(conn, season_id)
    assert playoffs.bracket_view(conn, season_id) == []


def test_clear_bracket_refuses_once_a_playoff_match_has_a_result():
    conn, season_id, coaches = make_db(2, playoff_bracket_size=2)
    ranked = [coaches[1], coaches[2]]
    rank_coaches_by_series_wins(conn, season_id, coaches, ranked)
    assert playoffs.seed_bracket(conn, season_id) is None
    view = {r["slot"]: r for r in playoffs.bracket_view(conn, season_id)}
    m = matches.get_match(conn, view["F"]["match_id"])
    matches.report_match(conn, view["F"]["match_id"], m["home_user_id"], [
        {"winner_coach_id": ranked[0], "stats": []},
        {"winner_coach_id": ranked[0], "stats": []},
    ])  # left pending_confirmation, not confirmed -- still "already reported"

    error = playoffs.clear_bracket(conn, season_id)
    assert error is not None
    assert playoffs.is_seeded(conn, season_id)
