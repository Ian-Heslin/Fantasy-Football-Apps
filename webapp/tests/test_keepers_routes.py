"""End-to-end check of the keeper-prediction + mock-draft pages through
the real ASGI app and real templates -- catches the class of mistake the
pure-logic tests in test_keepers.py can't (a route passing the wrong name
into a template, a Jinja dict-of-tuples lookup that doesn't actually
work, a form field name that doesn't match what the route reads).
"""
from conftest import query, set_tier, signup

LEAGUE_ID = "L1"


def seed_league(kept_round=2, other_round=4):
    """One league, two teams, a small 2025 draft, and current rosters
    that still hold what each team drafted -- enough for both a keeper
    prediction and an auto-filled open slot to be exercised."""
    from app import db
    conn = db.get_connection()
    conn.execute(
        "INSERT INTO leagues (league_id, platform, name, season, format, status) "
        "VALUES (?, 'yahoo', 'Test League', 2026, 'SF', 'pre_draft')", (LEAGUE_ID,))
    conn.execute(
        "INSERT INTO rosters (league_id, roster_id, owner_name, is_mine) VALUES (?, 'R1', 'Team One', 1)",
        (LEAGUE_ID,))
    conn.execute(
        "INSERT INTO rosters (league_id, roster_id, owner_name, is_mine) VALUES (?, 'R2', 'Team Two', 0)",
        (LEAGUE_ID,))

    conn.execute("INSERT INTO players (player_id, name, position, team) VALUES "
                 "('p1', 'Keeper Guy', 'WR', 'KC'), ('p2', 'Open Guy', 'RB', 'BUF')")

    conn.execute(
        "INSERT INTO league_draft_picks (league_id, season, round, overall_pick, roster_id, player_id) "
        "VALUES (?, 2025, ?, 1, 'R1', 'p1')", (LEAGUE_ID, kept_round))
    conn.execute(
        "INSERT INTO league_draft_picks (league_id, season, round, overall_pick, roster_id, player_id) "
        "VALUES (?, 2025, ?, 2, 'R2', 'p2')", (LEAGUE_ID, other_round))

    conn.execute("INSERT INTO roster_players VALUES (?, 'R1', 'p1', '2026-08-01')", (LEAGUE_ID,))
    conn.execute("INSERT INTO roster_players VALUES (?, 'R2', 'p2', '2026-08-01')", (LEAGUE_ID,))

    conn.execute("INSERT INTO arbitrage_signals (player_id, format, as_of_date, dynasty_percentile, "
                 "redraft_percentile, gap, signal) VALUES ('p2', 'sf', '2026-08-01', 0.5, 0.9, -0.4, 'FAIR')")
    conn.commit()
    conn.close()


def as_fantasy_user(client, username="ian"):
    signup(client, username)
    set_tier(username, "fantasy")


def test_keepers_page_renders_and_saves_a_prediction(client):
    as_fantasy_user(client)
    seed_league()

    r = client.get(f"/rosters/{LEAGUE_ID}/keepers")
    assert r.status_code == 200
    assert "Keeper Guy" in r.text

    r = client.post(
        f"/rosters/{LEAGUE_ID}/keepers",
        data={"roster_id": "R1", "player_ids": ["p1"]},
        follow_redirects=False,
    )
    assert r.status_code == 303

    saved = query(
        "SELECT player_id FROM keeper_predictions WHERE league_id = ? AND roster_id = 'R1'",
        (LEAGUE_ID,),
    )
    assert [row["player_id"] for row in saved] == ["p1"]


def test_mock_draft_shows_computed_keeper_round(client):
    as_fantasy_user(client)
    seed_league(kept_round=2)  # -> keeper round 3

    client.post(f"/rosters/{LEAGUE_ID}/keepers", data={"roster_id": "R1", "player_ids": ["p1"]})

    r = client.get(f"/rosters/{LEAGUE_ID}/mock-draft")
    assert r.status_code == 200
    assert "Keeper Guy" in r.text
    assert "Keeper" in r.text


def test_mock_draft_manual_pick_and_conflict_rejection(client):
    as_fantasy_user(client)
    seed_league()

    r = client.post(
        f"/rosters/{LEAGUE_ID}/mock-draft/pick",
        data={"round": 1, "roster_id": "R2", "player_name": "Open Guy"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error" not in (r.headers.get("location") or "")

    saved = query(
        "SELECT player_id FROM mock_draft_picks WHERE league_id = ? AND roster_id = 'R2' AND round = 1",
        (LEAGUE_ID,),
    )
    assert [row["player_id"] for row in saved] == ["p2"]

    # Picking the same player again elsewhere on the board is rejected.
    r = client.post(
        f"/rosters/{LEAGUE_ID}/mock-draft/pick",
        data={"round": 2, "roster_id": "R1", "player_name": "Open Guy"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "error=" in r.headers["location"]


def test_mock_draft_auto_fill_leaves_keeper_slot_alone(client):
    as_fantasy_user(client)
    seed_league(kept_round=1)  # -> keeper round 1

    client.post(f"/rosters/{LEAGUE_ID}/keepers", data={"roster_id": "R1", "player_ids": ["p1"]})
    r = client.post(f"/rosters/{LEAGUE_ID}/mock-draft/auto-fill", follow_redirects=False)
    assert r.status_code == 303

    round1_r1 = query(
        "SELECT * FROM mock_draft_picks WHERE league_id = ? AND roster_id = 'R1' AND round = 1",
        (LEAGUE_ID,),
    )
    assert round1_r1 == []  # round 1 for R1 is a keeper slot -- auto-fill must not touch it
