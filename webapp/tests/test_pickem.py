"""Pick'em scoring and confidence-ordering tests.

These cover the rules a player would notice being wrong: when a game
locks, what a confidence number is worth, and -- the reason this file
exists -- that a game's number and score stop moving the moment it
kicks off. Two real bugs are pinned here:

  * confidence used to be reorderable on games that were already final,
    so a direct POST could set a finished game's number once its result
    was known, and an ordinary reorder of an upcoming game silently
    rewrote the number on a game that was already scored;
  * is_locked compared a naive Eastern kickoff against a naive server
    clock, so on a UTC host every game locked ~5 hours early.

Run with:  python3 -m pytest tests/ -q     (from webapp/)
"""
import sqlite3
from datetime import datetime, timezone

import pytest
from zoneinfo import ZoneInfo

from app import pickem

ET = ZoneInfo("America/New_York")

STRAIGHT_UP = {"pick_mode": "straight_up", "confidence_enabled": False}
SPREAD = {"pick_mode": "spread", "confidence_enabled": False}
CONFIDENCE = {"pick_mode": "straight_up", "confidence_enabled": True}

SEASON, WEEK, USER = 2026, 1, 1


def et(text):
    """An aware instant from an Eastern wall-clock string."""
    return datetime.fromisoformat(text).replace(tzinfo=ET)


def make_db(games, picks=()):
    """In-memory app.db with just the two Pick'em tables populated.

    games: (game_id, kickoff_at, home_score, away_score, is_final) --
    home is always KC, away always BUF, spread_line -1.0 (away favored).
    picks: (game_id, picked_team, confidence)
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE pickem_games (
            game_id TEXT PRIMARY KEY, season INTEGER, week INTEGER,
            home_team TEXT, away_team TEXT, kickoff_at TEXT, spread_line REAL,
            home_score INTEGER, away_score INTEGER, is_final INTEGER DEFAULT 0);
        CREATE TABLE pickem_picks (
            user_id INTEGER, game_id TEXT, picked_team TEXT, confidence INTEGER,
            submitted_at TEXT, PRIMARY KEY (user_id, game_id));
    """)
    conn.executemany(
        "INSERT INTO pickem_games VALUES (?,?,?,'KC','BUF',?,-1.0,?,?,?)",
        [(gid, SEASON, WEEK, kickoff, hs, aw, final)
         for gid, kickoff, hs, aw, final in games],
    )
    conn.executemany(
        "INSERT INTO pickem_picks VALUES (?,?,?,?,datetime('now'))",
        [(USER, gid, team, conf) for gid, team, conf in picks],
    )
    conn.commit()
    return conn


def game(conn, game_id):
    return conn.execute(
        "SELECT * FROM pickem_games WHERE game_id = ?", (game_id,)).fetchone()


def pick(conn, game_id):
    return conn.execute(
        "SELECT * FROM pickem_picks WHERE user_id = ? AND game_id = ?",
        (USER, game_id)).fetchone()


def confidences(conn):
    return {r["game_id"]: r["confidence"] for r in conn.execute(
        "SELECT game_id, confidence FROM pickem_picks WHERE user_id = ?", (USER,))}


# --------------------------------------------------------------------
# is_locked -- kickoff is Eastern, and the host's timezone must not matter
# --------------------------------------------------------------------

def row(**overrides):
    base = {"game_id": "G", "kickoff_at": "2026-09-13T13:00:00", "is_final": 0,
            "home_score": None, "away_score": None, "spread_line": -1.0,
            "home_team": "KC", "away_team": "BUF"}
    base.update(overrides)
    return base


def test_game_is_open_before_its_eastern_kickoff():
    # 15:00 UTC is 11:00 ET -- two hours before a 13:00 ET kickoff. The
    # naive comparison this replaced called this locked on a UTC host.
    assert not pickem.is_locked(row(), now=datetime(2026, 9, 13, 15, 0, tzinfo=timezone.utc))


def test_game_locks_at_its_eastern_kickoff():
    # 17:00 UTC is 13:00 ET, exactly kickoff.
    assert pickem.is_locked(row(), now=datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc))


def test_lock_is_unaffected_by_host_timezone():
    # The same instant expressed three ways must give the same answer.
    instant = datetime(2026, 9, 13, 15, 0, tzinfo=timezone.utc)
    assert not pickem.is_locked(row(), now=instant)
    assert not pickem.is_locked(row(), now=instant.astimezone(ET))
    assert not pickem.is_locked(row(), now=instant.astimezone(ZoneInfo("Asia/Tokyo")))


def test_final_game_is_locked_regardless_of_clock():
    assert pickem.is_locked(row(is_final=1), now=datetime(1999, 1, 1, tzinfo=timezone.utc))


def test_missing_or_unparseable_kickoff_leaves_game_open():
    assert not pickem.is_locked(row(kickoff_at=None), now=datetime.now(timezone.utc))
    assert not pickem.is_locked(row(kickoff_at="not a date"), now=datetime.now(timezone.utc))


# --------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------

def test_straight_up_pick_scores_one_for_the_winner():
    g = row(is_final=1, home_score=30, away_score=20)
    assert pickem.score_pick(g, {"picked_team": "KC", "confidence": None}, STRAIGHT_UP) == 1
    assert pickem.score_pick(g, {"picked_team": "BUF", "confidence": None}, STRAIGHT_UP) == 0


def test_unplayed_game_and_missing_pick_both_score_nothing():
    assert pickem.score_pick(row(), {"picked_team": "KC", "confidence": 5}, STRAIGHT_UP) is None
    assert pickem.score_pick(row(is_final=1, home_score=30, away_score=20), None, STRAIGHT_UP) is None


def test_tie_is_a_push_worth_zero():
    g = row(is_final=1, home_score=20, away_score=20)
    assert pickem.score_pick(g, {"picked_team": "KC", "confidence": 9}, STRAIGHT_UP) == 0


def test_spread_mode_scores_the_cover_not_the_win():
    # spread_line -1.0 means the AWAY team is favoured by 1. KC wins by 5,
    # so KC covers and the straight-up winner is also the cover here...
    g = row(is_final=1, home_score=25, away_score=20)
    assert pickem.cover_side(g) == "home"
    assert pickem.score_pick(g, {"picked_team": "KC", "confidence": None}, SPREAD) == 1
    # ...but a 1-point KC win does not cover a -1 away line: margin
    # (1) - (-1) = 2 > 0, still home. A KC loss by 3 gives away the cover.
    g = row(is_final=1, home_score=20, away_score=23)
    assert pickem.cover_side(g) == "away"
    assert pickem.score_pick(g, {"picked_team": "KC", "confidence": None}, SPREAD) == 0


def test_exact_cover_is_a_push():
    # margin (home - away) - spread_line == 0
    g = row(is_final=1, home_score=20, away_score=21)
    assert pickem.cover_side(g) == "push"
    assert pickem.score_pick(g, {"picked_team": "KC", "confidence": 7}, SPREAD) == 0


def test_positive_spread_line_means_home_is_favoured():
    # The convention the module docstring warns not to flip.
    assert pickem.favorite_team(row(spread_line=3.0)) == "KC"
    assert pickem.favorite_team(row(spread_line=-3.0)) == "BUF"
    assert pickem.favorite_team(row(spread_line=0)) is None
    assert pickem.favorite_team(row(spread_line=None)) is None


def test_confidence_mode_scores_the_confidence_value():
    g = row(is_final=1, home_score=30, away_score=20)
    assert pickem.score_pick(g, {"picked_team": "KC", "confidence": 6}, CONFIDENCE) == 6
    assert pickem.score_pick(g, {"picked_team": "BUF", "confidence": 6}, CONFIDENCE) == 0


# --------------------------------------------------------------------
# confidence_layout
# --------------------------------------------------------------------

NOW = datetime(2026, 9, 13, 18, 0, tzinfo=timezone.utc)  # 14:00 ET
PLAYED = "2026-09-13T13:00:00"     # kicked off an hour ago
UPCOMING = "2026-09-13T16:00:00"   # two hours away
LATER = "2026-09-13T20:00:00"


def test_layout_is_always_a_full_permutation():
    conn = make_db([("A", PLAYED, 30, 20, 1), ("B", UPCOMING, None, None, 0),
                    ("C", LATER, None, None, 0)],
                   picks=[("A", "KC", 3), ("B", "KC", 2)])
    games = pickem.week_games(conn, SEASON, WEEK)
    assignment, _, _ = pickem.confidence_layout(
        games, pickem.week_picks(conn, USER, SEASON, WEEK), NOW)
    assert sorted(assignment.values()) == [1, 2, 3]


def test_kicked_off_game_with_no_pick_still_holds_a_number():
    # A kicked off and was never picked. It must keep a number so the
    # open games can't inherit it -- and it takes the cheapest one.
    conn = make_db([("A", PLAYED, None, None, 0), ("B", UPCOMING, None, None, 0),
                    ("C", LATER, None, None, 0)])
    games = pickem.week_games(conn, SEASON, WEEK)
    assignment, frozen, free = pickem.confidence_layout(games, {}, NOW)
    assert assignment["A"] == 1
    assert frozen == {"A"}
    assert free == [2, 3]


def test_free_values_exclude_every_number_a_kicked_off_game_holds():
    conn = make_db([("A", PLAYED, 30, 20, 1), ("B", PLAYED, None, None, 0),
                    ("C", UPCOMING, None, None, 0), ("D", LATER, None, None, 0)],
                   picks=[("A", "KC", 4)])
    games = pickem.week_games(conn, SEASON, WEEK)
    assignment, frozen, free = pickem.confidence_layout(
        games, pickem.week_picks(conn, USER, SEASON, WEEK), NOW)
    assert frozen == {"A", "B"}
    assert assignment["A"] == 4          # stored pick keeps its number
    assert assignment["B"] == 1          # unpicked, kicked off -> cheapest
    assert free == [2, 3]                # only C and D can move
    assert sorted(assignment.values()) == [1, 2, 3, 4]


def test_open_games_take_the_highest_numbers_left_in_kickoff_order():
    conn = make_db([("A", PLAYED, None, None, 0), ("B", UPCOMING, None, None, 0),
                    ("C", LATER, None, None, 0)])
    games = pickem.week_games(conn, SEASON, WEEK)
    assignment, _, _ = pickem.confidence_layout(games, {}, NOW)
    assert assignment == {"A": 1, "B": 3, "C": 2}


def test_layout_survives_a_duplicated_or_out_of_range_stored_value():
    conn = make_db([("A", UPCOMING, None, None, 0), ("B", UPCOMING, None, None, 0),
                    ("C", LATER, None, None, 0)],
                   picks=[("A", "KC", 99), ("B", "KC", 2), ("C", "KC", 2)])
    games = pickem.week_games(conn, SEASON, WEEK)
    assignment, _, _ = pickem.confidence_layout(
        games, pickem.week_picks(conn, USER, SEASON, WEEK), NOW)
    assert sorted(assignment.values()) == [1, 2, 3]


# --------------------------------------------------------------------
# reorder_confidence -- the regressions
# --------------------------------------------------------------------

def test_reordering_an_open_game_leaves_a_final_games_score_alone():
    """The bug that needed no bad intent: shifting an upcoming game's
    number used to renumber a game that was already final and scored."""
    conn = make_db([("A", PLAYED, 30, 20, 1), ("B", UPCOMING, None, None, 0),
                    ("C", LATER, None, None, 0)],
                   picks=[("A", "KC", 3), ("B", "KC", 2), ("C", "KC", 1)])
    before = pickem.score_pick(game(conn, "A"), pick(conn, "A"), CONFIDENCE)
    assert before == 3

    pickem.reorder_confidence(conn, USER, SEASON, WEEK, "C", 2, now=NOW)

    assert pick(conn, "A")["confidence"] == 3
    assert pickem.score_pick(game(conn, "A"), pick(conn, "A"), CONFIDENCE) == 3
    assert sorted(confidences(conn).values()) == [1, 2, 3]


def test_a_kicked_off_games_confidence_cannot_be_set_directly():
    """The exploit: a direct POST setting a finished game's number once
    the result was known."""
    conn = make_db([("A", PLAYED, 30, 20, 1), ("B", UPCOMING, None, None, 0),
                    ("C", LATER, None, None, 0)],
                   picks=[("A", "KC", 1), ("B", "KC", 2), ("C", "KC", 3)])

    assert pickem.reorder_confidence(conn, USER, SEASON, WEEK, "A", 3, now=NOW) is False

    assert pick(conn, "A")["confidence"] == 1
    assert pickem.score_pick(game(conn, "A"), pick(conn, "A"), CONFIDENCE) == 1


def test_an_open_game_cannot_steal_a_frozen_number():
    conn = make_db([("A", PLAYED, 30, 20, 1), ("B", UPCOMING, None, None, 0),
                    ("C", LATER, None, None, 0)],
                   picks=[("A", "KC", 3), ("B", "KC", 2), ("C", "KC", 1)])

    assert pickem.reorder_confidence(conn, USER, SEASON, WEEK, "B", 3, now=NOW) is False

    assert confidences(conn) == {"A": 3, "B": 2, "C": 1}


def test_open_games_reorder_among_the_numbers_that_are_left():
    conn = make_db([("A", PLAYED, 30, 20, 1), ("B", UPCOMING, None, None, 0),
                    ("C", LATER, None, None, 0)],
                   picks=[("A", "KC", 3), ("B", "KC", 1), ("C", "KC", 2)])

    assert pickem.reorder_confidence(conn, USER, SEASON, WEEK, "B", 2, now=NOW) is True

    assert confidences(conn) == {"A": 3, "B": 2, "C": 1}


def test_reorder_steps_over_a_frozen_number_in_the_middle():
    """A is frozen holding 3. B and C hold 4 and 1. Moving C up must land
    it on 4 and push B down to 1 -- skipping 3 entirely, not doing
    conf +/- 1 arithmetic through it."""
    conn = make_db([("A", PLAYED, 30, 20, 1), ("B", UPCOMING, None, None, 0),
                    ("C", LATER, None, None, 0), ("D", PLAYED, None, None, 0)],
                   picks=[("A", "KC", 3), ("B", "KC", 4), ("C", "KC", 1)])
    # D kicked off unpicked and burns 2, so free_values == [1, 4].
    _, frozen, free = pickem.confidence_layout(
        pickem.week_games(conn, SEASON, WEEK),
        pickem.week_picks(conn, USER, SEASON, WEEK), NOW)
    assert frozen == {"A", "D"} and free == [1, 4]

    assert pickem.reorder_confidence(conn, USER, SEASON, WEEK, "C", 4, now=NOW) is True

    assert confidences(conn) == {"A": 3, "B": 1, "C": 4}


def test_reorder_refuses_a_game_with_no_pick_yet():
    conn = make_db([("A", UPCOMING, None, None, 0), ("B", LATER, None, None, 0)],
                   picks=[("A", "KC", 2)])
    assert pickem.reorder_confidence(conn, USER, SEASON, WEEK, "B", 1, now=NOW) is False


def test_reorder_to_the_same_number_is_a_harmless_write():
    conn = make_db([("A", UPCOMING, None, None, 0), ("B", LATER, None, None, 0)],
                   picks=[("A", "KC", 2), ("B", "KC", 1)])
    assert pickem.reorder_confidence(conn, USER, SEASON, WEEK, "A", 2, now=NOW) is True
    assert confidences(conn) == {"A": 2, "B": 1}


def test_every_reorder_leaves_a_valid_permutation():
    """Property check: whatever sequence of legal moves gets made, the
    week's numbers stay a permutation of 1..n and frozen games never
    move."""
    conn = make_db([("A", PLAYED, 30, 20, 1), ("B", PLAYED, None, None, 0),
                    ("C", UPCOMING, None, None, 0), ("D", LATER, None, None, 0),
                    ("E", LATER, None, None, 0)],
                   picks=[("A", "KC", 5), ("C", "KC", 4), ("D", "KC", 3), ("E", "KC", 2)])
    frozen_before = pick(conn, "A")["confidence"]

    for target, value in [("C", 2), ("E", 4), ("D", 2), ("C", 3), ("E", 2)]:
        pickem.reorder_confidence(conn, USER, SEASON, WEEK, target, value, now=NOW)
        games = pickem.week_games(conn, SEASON, WEEK)
        assignment, frozen, _ = pickem.confidence_layout(
            games, pickem.week_picks(conn, USER, SEASON, WEEK), NOW)
        assert sorted(assignment.values()) == [1, 2, 3, 4, 5]
        assert frozen == {"A", "B"}
        assert pick(conn, "A")["confidence"] == frozen_before


# --------------------------------------------------------------------
# standings
# --------------------------------------------------------------------

def test_a_kicked_off_game_with_no_pick_counts_as_a_miss_not_a_skip():
    conn = make_db([("A", PLAYED, 30, 20, 1), ("B", PLAYED, 30, 20, 1)],
                   picks=[("A", "KC", 2)])
    conn.executescript(
        "CREATE TABLE users (user_id INTEGER, username TEXT);"
        "INSERT INTO users VALUES (1, 'ian');"
        "CREATE TABLE pickem_settings (id INTEGER PRIMARY KEY, pick_mode TEXT,"
        " confidence_enabled INTEGER);"
        "INSERT INTO pickem_settings VALUES (1, 'straight_up', 0);")
    board = pickem.standings(conn, SEASON)
    assert board[0]["points"] == 1
    assert board[0]["correct"] == 1
    assert board[0]["total"] == 2   # both final games count against you


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
