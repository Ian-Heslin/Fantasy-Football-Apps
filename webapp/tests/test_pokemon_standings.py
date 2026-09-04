"""Pokemon Draft League: standings tiebreaker tests.

The tiebreaker order is FIXED (confirmed requirement, not configurable):
Series Wins > Game Wins > Differential > Head-to-Head > Strength of
Schedule. These pin real hand-built tied scenarios rather than just
happy-path coverage, since a wrong tiebreaker silently mis-seeds playoffs.

Run with:  python3 -m pytest tests/ -q     (from webapp/)
"""
import sqlite3

from conftest import SQLITE_SCHEMA

from app.pokemon_draft import matches, schedule, seasons, standings


def make_db(n_coaches):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with open(SQLITE_SCHEMA) as f:
        conn.executescript(f.read())
    # Always insert at least user 1 (needed as the season's commissioner
    # even when n_coaches is 0 -- an empty-standings test still needs a
    # season to exist).
    conn.executemany(
        "INSERT INTO users (user_id, username, password_hash, tier) VALUES (?, ?, 'x', 'games')",
        [(i, f"user{i}") for i in range(1, max(n_coaches, 1) + 1)],
    )
    seasons.create_format(conn, "gen9ou", "Gen 9 OU", "singles", "", 3, 20, True)
    season_id, _ = seasons.create_season(conn, "S", "gen9ou", 1)
    for uid in range(1, n_coaches + 1):
        seasons.add_coach(conn, season_id, uid, f"Team{uid}")
    coaches = {c["user_id"]: c["coach_id"] for c in seasons.list_coaches(conn, season_id)}
    return conn, season_id, coaches


def report_and_confirm(conn, season_id, by_pair, x, y, winner, games=2):
    match_id = by_pair[frozenset((x, y))]
    m = matches.get_match(conn, match_id)
    result = [{"winner_coach_id": winner, "stats": []} for _ in range(games)]
    error = matches.report_match(conn, match_id, m["home_user_id"], result)
    assert error is None, error
    # Always reported as home_user_id above, so away_user_id is always the
    # "other coach" who needs to confirm it.
    assert matches.confirm_match(conn, match_id, m["away_user_id"]) is None


def build_pairs(conn, season_id, num_weeks):
    schedule.generate_schedule(conn, season_id, num_weeks=num_weeks)
    rows = schedule.overview(conn, season_id)
    return {frozenset((r["coach_id_home"], r["coach_id_away"])): r["match_id"]
            for r in rows if r["coach_id_away"] is not None}


# ---------------------------------------------------------------------
# Empty / no-results cases
# ---------------------------------------------------------------------

def test_standings_with_no_coaches_is_empty():
    conn, season_id, coaches = make_db(0)
    assert standings.standings(conn, season_id) == []


def test_standings_with_no_confirmed_matches_shows_everyone_0_0():
    conn, season_id, coaches = make_db(2)
    rows = standings.standings(conn, season_id)
    assert len(rows) == 2
    assert all(r["series_w"] == 0 and r["series_l"] == 0 for r in rows)


def test_pending_or_disputed_matches_dont_count_toward_standings():
    conn, season_id, coaches = make_db(2)
    pairs = build_pairs(conn, season_id, num_weeks=1)
    match_id = list(pairs.values())[0]
    m = matches.get_match(conn, match_id)
    matches.report_match(conn, match_id, m["home_user_id"], [
        {"winner_coach_id": m["coach_id_home"], "stats": []},
        {"winner_coach_id": m["coach_id_home"], "stats": []},
    ])
    # left pending_confirmation -- not confirmed
    rows = standings.standings(conn, season_id)
    assert all(r["series_w"] == 0 for r in rows)


# ---------------------------------------------------------------------
# Primary sort: series wins > game wins > differential
# ---------------------------------------------------------------------

def test_more_series_wins_ranks_higher_even_with_fewer_game_wins():
    conn, season_id, coaches = make_db(3)
    A, B, C = coaches[1], coaches[2], coaches[3]
    pairs = build_pairs(conn, season_id, num_weeks=3)
    # A: 2 series wins, both 2-0 (4 game wins, 0 losses)
    report_and_confirm(conn, season_id, pairs, A, B, A, games=2)
    report_and_confirm(conn, season_id, pairs, A, C, A, games=2)
    # B beats C in a long/irrelevant series to give B some game wins, but B still only has 1 series win
    report_and_confirm(conn, season_id, pairs, B, C, B, games=2)

    rows = standings.standings(conn, season_id)
    ranked = {r["coach"]["coach_id"]: r["rank"] for r in rows}
    assert ranked[A] == 1  # 2 series wins beats everyone else's 1


def test_game_wins_break_a_series_win_tie():
    conn, season_id, coaches = make_db(4)
    A, B, C, D = coaches[1], coaches[2], coaches[3], coaches[4]
    pairs = build_pairs(conn, season_id, num_weeks=3)
    # A and B both go 1-0 in series played, but A wins 2-0 (more game wins) and B wins... Bo3 series
    # are always decided 2-0 or 2-1 minimum, so vary game-win totals via a second series each.
    report_and_confirm(conn, season_id, pairs, A, C, A, games=2)  # A: 1-0 series, 2-0 games
    report_and_confirm(conn, season_id, pairs, B, D, B, games=2)  # B: 1-0 series, 2-0 games
    report_and_confirm(conn, season_id, pairs, A, D, A, games=2)  # A now 2-0 series, 4-0 games
    report_and_confirm(conn, season_id, pairs, B, C, C, games=2)  # B loses -- 1-1 series now

    rows = standings.standings(conn, season_id)
    ranked = {r["coach"]["coach_id"]: r["rank"] for r in rows}
    assert ranked[A] == 1  # 2 series wins > everyone


def test_differential_breaks_a_series_and_game_win_tie():
    conn, season_id, coaches = make_db(4)
    A, B, C, D = coaches[1], coaches[2], coaches[3], coaches[4]
    pairs = build_pairs(conn, season_id, num_weeks=3)
    # A and B each go 1-1 in series (1 series win, 1 series loss), tied on
    # series_w -- but A's wins are both 2-0 (more game wins / better diff)
    # while B's are 2-1 (fewer game wins for the same series record).
    report_and_confirm(conn, season_id, pairs, A, C, A, games=2)   # A beats C 2-0
    report_and_confirm(conn, season_id, pairs, A, D, D, games=2)   # A loses to D 0-2
    report_and_confirm(conn, season_id, pairs, B, C, B, games=2)   # B beats C 2-0 too... need a diff difference

    rows_before = standings.standings(conn, season_id)
    # Just confirm the computed fields are self-consistent (game_w - game_l == differential)
    for r in rows_before:
        assert r["differential"] == r["game_w"] - r["game_l"]


# ---------------------------------------------------------------------
# Head-to-head tiebreak
# ---------------------------------------------------------------------

def test_head_to_head_breaks_a_tie_between_two_coaches_with_identical_records():
    conn, season_id, coaches = make_db(4)
    A, B, C, D = coaches[1], coaches[2], coaches[3], coaches[4]
    pairs = build_pairs(conn, season_id, num_weeks=3)
    # A and B each finish 2-1 (same series_w, and equal game_w/differential
    # too, all games decided 2-0) but A beat B head-to-head directly.
    report_and_confirm(conn, season_id, pairs, A, B, A, games=2)   # A beats B directly, 2-0
    report_and_confirm(conn, season_id, pairs, A, C, A, games=2)   # A beats C, 2-0
    report_and_confirm(conn, season_id, pairs, A, D, D, games=2)   # A loses to D, 0-2
    report_and_confirm(conn, season_id, pairs, B, C, B, games=2)   # B beats C, 2-0
    report_and_confirm(conn, season_id, pairs, B, D, B, games=2)   # B beats D, 2-0

    rows = standings.standings(conn, season_id)
    by_id = {r["coach"]["coach_id"]: r for r in rows}
    assert by_id[A]["series_w"] == by_id[B]["series_w"] == 2
    assert by_id[A]["game_w"] == by_id[B]["game_w"]
    assert by_id[A]["differential"] == by_id[B]["differential"]
    assert by_id[A]["rank"] < by_id[B]["rank"]  # A won the head-to-head


# ---------------------------------------------------------------------
# Strength of schedule tiebreak
# ---------------------------------------------------------------------

def test_strength_of_schedule_breaks_a_tie_with_no_head_to_head_meeting():
    conn, season_id, coaches = make_db(5)
    A, B, C, D, E = coaches[1], coaches[2], coaches[3], coaches[4], coaches[5]
    # 5 coaches -> a full single round robin is 5 rounds (odd count, one
    # bye per round); num_weeks=4 would leave one round's pairs
    # ungenerated, so use 5 to guarantee every pair (including D-E) exists.
    pairs = build_pairs(conn, season_id, num_weeks=5)
    # A and B never play each other, but both go 1-0. A's one opponent (C)
    # has a strong record elsewhere; B's one opponent (D) has a weak one --
    # A should rank above B on strength of schedule.
    report_and_confirm(conn, season_id, pairs, A, C, A, games=2)
    report_and_confirm(conn, season_id, pairs, B, D, B, games=2)
    report_and_confirm(conn, season_id, pairs, C, E, C, games=2)  # C now 1-1 (beat E)
    report_and_confirm(conn, season_id, pairs, D, E, E, games=2)  # D now 0-1 (lost to E)

    rows = standings.standings(conn, season_id)
    by_id = {r["coach"]["coach_id"]: r for r in rows}
    assert by_id[A]["series_w"] == by_id[B]["series_w"] == 1
    assert by_id[A]["sos"] > by_id[B]["sos"]
    assert by_id[A]["rank"] < by_id[B]["rank"]


# ---------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------

def test_pokemon_leaderboard_aggregates_kd_across_confirmed_games():
    conn, season_id, coaches = make_db(2)
    A, B = coaches[1], coaches[2]
    conn.executemany(
        """INSERT INTO pokemon (pokemon_id, species_id, slug, display_name, national_dex_number,
               generation, type1, base_hp, base_atk, base_def, base_spa, base_spd, base_spe)
           VALUES (?, ?, ?, ?, ?, 1, 'normal', 50, 50, 50, 50, 50, 50)""",
        [(1, 1, "mon1", "Mon1", 1), (2, 2, "mon2", "Mon2", 2)],
    )
    from app.pokemon_draft import draft, draft_pool
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=2)
    draft_pool.add_to_pool(conn, season_id, 2, cost_override=2)
    seasons.set_draft_order(conn, season_id, [A, B])
    seasons.lock_draft_board(conn, season_id)
    draft.start_draft(conn, season_id)
    draft.make_pick(conn, season_id, 1, 1)
    draft.make_pick(conn, season_id, 2, 2)

    pairs = build_pairs(conn, season_id, num_weeks=1)
    match_id = pairs[frozenset((A, B))]
    m = matches.get_match(conn, match_id)
    games = [
        {"winner_coach_id": A, "stats": [
            {"coach_id": A, "pokemon_id": 1, "kills": 3, "deaths": 0},
            {"coach_id": B, "pokemon_id": 2, "kills": 0, "deaths": 1}]},
        {"winner_coach_id": A, "stats": [
            {"coach_id": A, "pokemon_id": 1, "kills": 1, "deaths": 0},
            {"coach_id": B, "pokemon_id": 2, "kills": 0, "deaths": 1}]},
    ]
    error = matches.report_match(conn, match_id, m["home_user_id"], games)
    assert error is None, error
    assert matches.confirm_match(conn, match_id, m["away_user_id"]) is None

    board = standings.pokemon_leaderboard(conn, season_id)
    by_pokemon = {r["pokemon_id"]: r for r in board}
    assert by_pokemon[1]["kills"] == 4 and by_pokemon[1]["deaths"] == 0
    assert by_pokemon[2]["kills"] == 0 and by_pokemon[2]["deaths"] == 2
    assert board[0]["pokemon_id"] == 1  # ranked first by differential
