"""End-to-end checks through the real ASGI app, real schema, real
templates. Cheap, and it catches the class of mistake unit tests miss --
a route passing the wrong name into a template, a redirect that loses the
session, an auth guard that isn't wired to a router.

Everything runs against a throwaway app.db in tmp_path; nothing here can
touch the real one.
"""
import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA = os.path.join(REPO_ROOT, "fantasy-football-db", "schema", "sqlite_schema.sql")

GOOD_PASSWORD = "correct horse battery staple"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET_KEY", "test-key-not-a-real-secret")

    from app import db
    path = tmp_path / "app.db"
    conn = sqlite3.connect(path)
    with open(SCHEMA) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "SQLITE_PATH", str(path))

    from app.main import app
    # https:// because the session cookie is now Secure -- over plain
    # http the browser (and TestClient) would drop it, which is the
    # point of the flag.
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def signup(client, username="ian", password=GOOD_PASSWORD):
    return client.post("/signup", data={
        "username": username, "password": password, "confirm_password": password,
    }, follow_redirects=False)


def promote(client, username, tier):
    from app import db
    conn = db.get_connection()
    conn.execute("UPDATE users SET tier = ? WHERE username = ?", (tier, username))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- auth flow

def test_anonymous_visitor_is_redirected_to_login(client):
    r = client.get("/games", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_login_and_signup_pages_render_for_anonymous_visitors(client):
    assert client.get("/login").status_code == 200
    body = client.get("/signup").text
    assert body.count("<form") >= 1
    # The form's own minlength must come from the same constant the
    # server enforces, not a number typed into the template.
    from app import auth
    assert f'minlength="{auth.MIN_PASSWORD_LENGTH}"' in body


def test_signup_logs_you_in_and_grants_games_tier(client):
    r = signup(client)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert client.get("/games").status_code == 200


def test_signup_rejects_a_short_password(client):
    r = client.post("/signup", data={
        "username": "ian", "password": "short", "confirm_password": "short"})
    assert r.status_code == 200
    assert "at least" in r.text.lower()


def test_signup_rejects_a_duplicate_username(client):
    signup(client)
    client.post("/logout", follow_redirects=False)
    r = client.post("/signup", data={
        "username": "ian", "password": GOOD_PASSWORD, "confirm_password": GOOD_PASSWORD})
    assert "already taken" in r.text


def test_login_rejects_a_wrong_password(client):
    signup(client)
    client.post("/logout", follow_redirects=False)
    r = client.post("/login", data={"username": "ian", "password": "wrong-password-here"})
    assert r.status_code == 401
    assert "Incorrect username or password" in r.text


def test_login_throttles_after_repeated_failures(client):
    from app import auth
    auth._login_failures.clear()
    signup(client)
    client.post("/logout", follow_redirects=False)
    try:
        for _ in range(auth.MAX_FAILED_LOGINS):
            client.post("/login", data={"username": "ian", "password": "wrong-password-here"})
        r = client.post("/login", data={"username": "ian", "password": "wrong-password-here"})
        assert r.status_code == 429
        # Even the correct password is refused while the throttle holds.
        r = client.post("/login", data={"username": "ian", "password": GOOD_PASSWORD})
        assert r.status_code == 429
    finally:
        auth._login_failures.clear()


def test_session_cookie_is_secure_httponly_and_lax(client):
    """The cookie is the whole of the auth story here, and all three
    flags used to be Starlette's defaults rather than a decision --
    https_only in particular defaulted to False."""
    signup(client)
    cookie = next(c for c in client.cookies.jar if c.name == "session")
    assert cookie.secure                                  # never sent over plain http
    rest = {k.lower(): v for k, v in cookie._rest.items()}
    assert "httponly" in rest                             # not readable from JS
    # SameSite=Lax is what stands in for CSRF tokens on every POST here.
    assert str(rest.get("samesite", "")).lower() == "lax"


# ---------------------------------------------------------------- tiers

def test_games_tier_cannot_reach_the_fantasy_section(client):
    signup(client)
    for path in ("/rosters", "/arbitrage", "/predictions", "/teams", "/coaches"):
        assert client.get(path).status_code == 403, path


def test_games_tier_cannot_reach_admin(client):
    signup(client)
    assert client.get("/admin/users").status_code == 403


def test_admin_can_reach_admin(client):
    signup(client)
    promote(client, "ian", "admin")
    assert client.get("/admin/users").status_code == 200


def test_last_admin_cannot_demote_themselves(client):
    signup(client)
    promote(client, "ian", "admin")
    from app import db
    conn = db.get_connection()
    user_id = conn.execute("SELECT user_id FROM users WHERE username='ian'").fetchone()[0]
    conn.close()

    r = client.post(f"/admin/users/{user_id}/tier", data={"tier": "games"},
                    follow_redirects=False)
    assert r.headers["location"] == "/admin/users?error=last_admin"

    conn = db.get_connection()
    assert conn.execute(
        "SELECT tier FROM users WHERE user_id = ?", (user_id,)).fetchone()[0] == "admin"
    conn.close()
    assert "no admins" in client.get("/admin/users?error=last_admin").text


def test_an_admin_can_be_demoted_when_another_one_remains(client):
    signup(client)
    promote(client, "ian", "admin")
    from app import db
    conn = db.get_connection()
    conn.execute("INSERT INTO users (username, password_hash, tier) "
                 "VALUES ('other', 'x', 'admin')")
    conn.commit()
    user_id = conn.execute("SELECT user_id FROM users WHERE username='ian'").fetchone()[0]
    conn.commit()
    conn.close()

    r = client.post(f"/admin/users/{user_id}/tier", data={"tier": "games"},
                    follow_redirects=False)
    assert r.headers["location"] == "/admin/users"


# ---------------------------------------------------------------- pick'em

def seed_week(games):
    from app import db
    conn = db.get_connection()
    conn.executemany(
        "INSERT INTO pickem_games (game_id, season, week, home_team, away_team,"
        " kickoff_at, spread_line, home_score, away_score, is_final)"
        " VALUES (?,2026,1,'KC','BUF',?,-1.0,?,?,?)", games)
    conn.execute("INSERT INTO pickem_settings (id, pick_mode, confidence_enabled)"
                 " VALUES (1, 'straight_up', 1)")
    conn.commit()
    conn.close()


def test_picks_page_renders_with_confidence_enabled(client):
    signup(client)
    seed_week([("A", "2099-09-13T13:00:00", None, None, 0),
               ("B", "2099-09-13T16:00:00", None, None, 0)])
    r = client.get("/games/pickem/picks")
    assert r.status_code == 200
    assert "Confidence points are on" in r.text


def test_a_kicked_off_game_shows_as_locked_with_no_pick(client):
    signup(client)
    seed_week([("A", "2020-09-13T13:00:00", None, None, 0),   # long past
               ("B", "2099-09-13T16:00:00", None, None, 0)])
    body = client.get("/games/pickem/picks").text
    assert "locked" in body
    assert "no pick" in body


def test_posting_a_pick_for_a_kicked_off_game_is_ignored(client):
    signup(client)
    seed_week([("A", "2020-09-13T13:00:00", None, None, 0)])
    client.post("/games/pickem/picks",
                data={"season": 2026, "week": 1, "pick_A": "KC"},
                follow_redirects=False)
    from app import db
    conn = db.get_connection()
    assert conn.execute("SELECT count(*) FROM pickem_picks").fetchone()[0] == 0
    conn.close()


def test_malformed_pick_submission_is_a_422_not_a_500(client):
    signup(client)
    seed_week([("A", "2099-09-13T13:00:00", None, None, 0)])
    assert client.post("/games/pickem/picks", data={"week": 1}).status_code == 422
    assert client.post("/games/pickem/picks",
                       data={"season": "nope", "week": 1}).status_code == 422


def test_a_games_tier_user_cannot_change_pickem_settings(client):
    signup(client)
    seed_week([("A", "2099-09-13T13:00:00", None, None, 0)])
    r = client.post("/games/pickem/settings",
                    data={"pick_mode": "spread", "confidence_enabled": "true"})
    assert r.status_code == 403


# ---------------------------------------------------------------- trivia

def test_trivia_round_page_is_reachable(client):
    """Exercises a handler that only needs app.db. Worth having as a
    route test rather than a unit test: it catches a name the module
    stopped importing, which no amount of unit-testing trivia.py would."""
    signup(client)
    from app import db
    conn = db.get_connection()
    conn.execute("INSERT INTO trivia_rounds (user_id, game_type, category, total) "
                 "VALUES (1, 'award_winners', 'MVP', 2)")
    conn.execute("INSERT INTO trivia_round_items "
                 "(round_id, item_key, prompt_label, correct_answer) "
                 "VALUES (1, '2015', '2015 (QB)', 'Cam Newton')")
    conn.commit()
    conn.close()

    r = client.get("/games/trivia/round/1")
    assert r.status_code == 200
    assert "2015 (QB)" in r.text
    # An unfinished round must not leak its answers into the page.
    assert "Cam Newton" not in r.text


def test_another_users_trivia_round_is_not_visible(client):
    signup(client)
    from app import db
    conn = db.get_connection()
    conn.execute("INSERT INTO users (user_id, username, password_hash, tier) "
                 "VALUES (2, 'someone', 'x', 'games')")
    conn.execute("INSERT INTO trivia_rounds (user_id, game_type, category, total) "
                 "VALUES (2, 'award_winners', 'MVP', 2)")
    conn.commit()
    conn.close()

    r = client.get("/games/trivia/round/1", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/games/trivia"


# ---------------------------------------------------------------- db missing

def test_database_outage_page_hides_server_paths_from_anonymous_visitors(
        client, tmp_path, monkeypatch):
    from app import db
    monkeypatch.setattr(db, "SQLITE_PATH", str(tmp_path / "gone.db"))
    r = client.post("/login", data={"username": "ian", "password": GOOD_PASSWORD})
    assert r.status_code == 503
    assert "gone.db" not in r.text
    assert str(tmp_path) not in r.text
    assert "build_db.py" not in r.text
