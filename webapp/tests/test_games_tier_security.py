"""Adversarial tests: what can a plain `games` account actually do?

`games` is what self-signup hands to anyone on the internet who fills in
the form, so this is the real threat model for this site -- not a
stranger without an account, but a stranger *with* one. Every test here
plays the attacker: it sends the request a hostile user would send by
hand (curl, devtools, a script), not the request the UI would produce,
because the UI's restraint is not a control.

Grouped by what's being attempted:
  * privilege escalation -- become fantasy or admin
  * horizontal access -- read or change another account's data
  * scoring manipulation -- win games by cheating the endpoints
  * injection and redirection -- XSS, SQL, open redirect
  * resource abuse -- make the Pi's SD card or CPU the victim
"""
import pytest

from conftest import GOOD_PASSWORD, query, signup

ATTACKER = "mallory"
VICTIM = "ian"


@pytest.fixture
def attacker(client):
    """A logged-in, ordinary `games` account -- exactly what signup gives
    anyone."""
    signup(client, ATTACKER)
    assert query("SELECT tier FROM users WHERE username = ?", (ATTACKER,))[0]["tier"] == "games"
    return client


def make_victim(tier="games"):
    """A second account, created directly so the attacker's session is
    untouched. Returns its user_id."""
    from app import auth, db
    conn = db.get_connection()
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, tier) VALUES (?, ?, ?)",
        (VICTIM, auth.hash_password(GOOD_PASSWORD), tier))
    conn.commit()
    user_id = cur.lastrowid
    conn.close()
    return user_id


# =====================================================================
# 1. Privilege escalation
# =====================================================================

FANTASY_PAGES = ["/rosters", "/arbitrage", "/predictions", "/teams", "/coaches",
                 "/teams/KC", "/coaches/Andy%20Reid",
                 "/rosters/1/keepers", "/rosters/1/mock-draft"]


@pytest.mark.parametrize("path", FANTASY_PAGES)
def test_cannot_read_fantasy_pages(attacker, path):
    assert attacker.get(path).status_code == 403, path


def test_cannot_read_the_admin_page(attacker):
    assert attacker.get("/admin/users").status_code == 403


def test_cannot_promote_self_through_the_admin_endpoint(attacker):
    """The obvious one: POST straight at the tier endpoint, skipping the
    page you can't load."""
    me = query("SELECT user_id FROM users WHERE username = ?", (ATTACKER,))[0]["user_id"]
    r = attacker.post(f"/admin/users/{me}/tier", data={"tier": "admin"},
                      follow_redirects=False)
    assert r.status_code == 403
    assert query("SELECT tier FROM users WHERE user_id = ?", (me,))[0]["tier"] == "games"


def test_cannot_promote_another_user(attacker):
    victim_id = make_victim()
    r = attacker.post(f"/admin/users/{victim_id}/tier", data={"tier": "admin"},
                      follow_redirects=False)
    assert r.status_code == 403
    assert query("SELECT tier FROM users WHERE user_id = ?", (victim_id,))[0]["tier"] == "games"


def test_cannot_escalate_by_smuggling_tier_into_the_profile_form(attacker):
    """Mass assignment: /profile legitimately updates the users row, so
    try to ride extra columns in on the same POST."""
    me = query("SELECT user_id FROM users WHERE username = ?", (ATTACKER,))[0]["user_id"]
    attacker.post("/profile", data={
        "tier": "admin", "user_id": 1, "username": "root",
        "password_hash": "x", "favorite_team": "kc", "team_colors_enabled": "true",
    })
    row = query("SELECT tier, username FROM users WHERE user_id = ?", (me,))[0]
    assert row["tier"] == "games"
    assert row["username"] == ATTACKER


def test_cannot_escalate_by_smuggling_tier_into_the_quick_toggle(attacker):
    me = query("SELECT user_id FROM users WHERE username = ?", (ATTACKER,))[0]["user_id"]
    attacker.post("/preferences/team-colors", data={
        "tier": "admin", "favorite_team": "kc", "team_colors_enabled": "true", "next": "/",
    }, follow_redirects=False)
    assert query("SELECT tier FROM users WHERE user_id = ?", (me,))[0]["tier"] == "games"


def test_cannot_change_the_shared_pickem_settings(attacker):
    """confidence_enabled/pick_mode are league-wide -- flipping them
    rescores everyone's standings at once."""
    r = attacker.post("/games/pickem/settings",
                      data={"pick_mode": "spread", "confidence_enabled": "true"})
    assert r.status_code == 403
    assert query("SELECT count(*) c FROM pickem_settings")[0]["c"] == 0


def test_a_forged_session_cookie_is_rejected(attacker):
    """The cookie is itsdangerous-signed; a hand-made one naming another
    user_id must not authenticate."""
    import base64, json
    victim_id = make_victim(tier="admin")
    forged = base64.b64encode(json.dumps({"user_id": victim_id}).encode()).decode()
    attacker.cookies.set("session", forged)
    assert attacker.get("/admin/users", follow_redirects=False).status_code == 303


def test_stripping_the_cookie_signature_is_rejected(attacker):
    """Keep the real payload, drop the signature."""
    real = next(c for c in attacker.cookies.jar if c.name == "session").value
    attacker.cookies.set("session", real.split(".")[0])
    assert attacker.get("/games", follow_redirects=False).status_code == 303


# =====================================================================
# 2. Horizontal access -- another account's data
# =====================================================================

def test_cannot_open_another_users_trivia_round(attacker):
    victim_id = make_victim()
    from app import db
    conn = db.get_connection()
    conn.execute("INSERT INTO trivia_rounds (round_id, user_id, game_type, category, total) "
                 "VALUES (1, ?, 'award_winners', 'MVP', 2)", (victim_id,))
    conn.execute("INSERT INTO trivia_round_items "
                 "(round_id, item_key, prompt_label, correct_answer) "
                 "VALUES (1, '2015', '2015 (QB)', 'Cam Newton')")
    conn.commit()
    conn.close()

    r = attacker.get("/games/trivia/round/1", follow_redirects=False)
    assert r.status_code == 303
    # And the answer must not leak in the redirect body either.
    assert "Cam Newton" not in r.text


def test_cannot_submit_answers_into_another_users_trivia_round(attacker):
    victim_id = make_victim()
    from app import db
    conn = db.get_connection()
    conn.execute("INSERT INTO trivia_rounds (round_id, user_id, game_type, category, total) "
                 "VALUES (1, ?, 'award_winners', 'MVP', 1)", (victim_id,))
    conn.execute("INSERT INTO trivia_round_items "
                 "(round_id, item_key, prompt_label, correct_answer) "
                 "VALUES (1, '2015', '2015 (QB)', 'Cam Newton')")
    conn.commit()
    conn.close()

    attacker.post("/games/trivia/round/1", data={"guess_2015": "Cam Newton"},
                  follow_redirects=False)
    row = query("SELECT score, completed_at FROM trivia_rounds WHERE round_id = 1")[0]
    assert row["score"] is None and row["completed_at"] is None


def test_cannot_open_another_users_group_session(attacker):
    victim_id = make_victim()
    from app import db
    conn = db.get_connection()
    conn.execute("INSERT INTO group_sessions (session_id, host_user_id, game_type, category) "
                 "VALUES (1, ?, 'award_winners', 'MVP')", (victim_id,))
    conn.commit()
    conn.close()
    r = attacker.get("/games/group/session/1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/games/group"


def test_cannot_score_another_users_group_session(attacker):
    victim_id = make_victim()
    from app import db
    conn = db.get_connection()
    conn.execute("INSERT INTO group_sessions (session_id, host_user_id, game_type, category) "
                 "VALUES (1, ?, 'award_winners', 'MVP')", (victim_id,))
    conn.execute("INSERT INTO group_participants (session_id, participant_id, name) "
                 "VALUES (1, 1, 'Ian')")
    conn.execute("INSERT INTO group_items (session_id, item_key, sort_order, prompt_label, correct_answer) "
                 "VALUES (1, '2015', 0, '2015 (QB)', 'Cam Newton')")
    conn.commit()
    conn.close()

    attacker.post("/games/group/session/1/reveal",
                  data={"item_key": "2015", "correct_1": "1"}, follow_redirects=False)
    assert query("SELECT count(*) c FROM group_answers")[0]["c"] == 0
    assert query("SELECT revealed FROM group_items WHERE session_id = 1")[0]["revealed"] == 0


def test_cannot_draft_into_another_users_group_draft(attacker):
    victim_id = make_victim()
    from app import db
    conn = db.get_connection()
    conn.execute("INSERT INTO group_sessions (session_id, host_user_id, game_type) "
                 "VALUES (1, ?, 'fantasy_draft')", (victim_id,))
    conn.execute("INSERT INTO group_participants (session_id, participant_id, name) "
                 "VALUES (1, 1, 'Ian'), (1, 2, 'Sam')")
    conn.commit()
    conn.close()

    r = attacker.post("/games/group/draft/1/pick",
                      data={"slot": "QB", "year": "2024", "player": "Patrick Mahomes"},
                      follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/games/group"
    assert query("SELECT count(*) c FROM group_draft_picks")[0]["c"] == 0


def test_cannot_overwrite_another_users_pickem_picks(attacker):
    """picks are keyed (user_id, game_id) and user_id comes from the
    session, so a crafted post can only ever write the attacker's row."""
    victim_id = make_victim()
    from app import db
    conn = db.get_connection()
    conn.execute("INSERT INTO pickem_games (game_id, season, week, home_team, away_team,"
                 " kickoff_at, is_final) VALUES ('A', 2026, 1, 'KC', 'BUF', '2099-09-13T13:00:00', 0)")
    conn.execute("INSERT INTO pickem_picks (user_id, game_id, picked_team, confidence) "
                 "VALUES (?, 'A', 'BUF', 1)", (victim_id,))
    conn.commit()
    conn.close()

    attacker.post("/games/pickem/picks",
                  data={"season": 2026, "week": 1, "pick_A": "KC", "user_id": victim_id},
                  follow_redirects=False)
    assert query("SELECT picked_team FROM pickem_picks WHERE user_id = ?",
                 (victim_id,))[0]["picked_team"] == "BUF"


def test_cannot_read_another_users_daily_picks(attacker):
    victim_id = make_victim()
    from app import db
    conn = db.get_connection()
    conn.execute("INSERT INTO daily_challenge_entries "
                 "(user_id, challenge_date, pick_num, year, player, stat_value) "
                 "VALUES (?, date('now'), 1, 2024, 'Secret Player', 999)", (victim_id,))
    conn.commit()
    conn.close()
    assert "Secret Player" not in attacker.get("/games/daily").text


# =====================================================================
# 3. Scoring manipulation
# =====================================================================

def seed_locked_and_open_week():
    from app import db
    conn = db.get_connection()
    conn.executemany(
        "INSERT INTO pickem_games (game_id, season, week, home_team, away_team,"
        " kickoff_at, spread_line, home_score, away_score, is_final)"
        " VALUES (?,2026,1,'KC','BUF',?,-1.0,?,?,?)",
        [("A", "2020-09-13T13:00:00", 30, 20, 1),      # final, KC won
         ("B", "2099-09-13T16:00:00", None, None, 0),
         ("C", "2099-09-13T20:00:00", None, None, 0)])
    conn.execute("INSERT INTO pickem_settings (id, pick_mode, confidence_enabled)"
                 " VALUES (1, 'straight_up', 1)")
    conn.commit()
    conn.close()


def test_cannot_pick_a_game_that_already_kicked_off(attacker):
    seed_locked_and_open_week()
    attacker.post("/games/pickem/picks",
                  data={"season": 2026, "week": 1, "pick_A": "KC", "pick_B": "KC"},
                  follow_redirects=False)
    picked = {r["game_id"] for r in query("SELECT game_id FROM pickem_picks")}
    assert "A" not in picked        # the finished game
    assert "B" in picked            # the open one still works


def test_cannot_raise_confidence_on_a_finished_game(attacker):
    """The original exploit: wait for the result, then make the game you
    won your highest-confidence pick."""
    seed_locked_and_open_week()
    me = query("SELECT user_id FROM users WHERE username = ?", (ATTACKER,))[0]["user_id"]
    from app import db
    conn = db.get_connection()
    conn.executemany("INSERT INTO pickem_picks (user_id, game_id, picked_team, confidence) "
                     "VALUES (?, ?, ?, ?)",
                     [(me, "A", "KC", 1), (me, "B", "KC", 2), (me, "C", "KC", 3)])
    conn.commit()
    conn.close()

    attacker.post("/games/pickem/confidence",
                  data={"season": 2026, "week": 1, "game_id": "A", "confidence": 3},
                  follow_redirects=False)
    assert query("SELECT confidence FROM pickem_picks WHERE user_id = ? AND game_id = 'A'",
                 (me,))[0]["confidence"] == 1


def test_cannot_steal_a_finished_games_confidence_number_for_an_open_game(attacker):
    seed_locked_and_open_week()
    me = query("SELECT user_id FROM users WHERE username = ?", (ATTACKER,))[0]["user_id"]
    from app import db
    conn = db.get_connection()
    conn.executemany("INSERT INTO pickem_picks (user_id, game_id, picked_team, confidence) "
                     "VALUES (?, ?, ?, ?)",
                     [(me, "A", "KC", 3), (me, "B", "KC", 2), (me, "C", "KC", 1)])
    conn.commit()
    conn.close()

    attacker.post("/games/pickem/confidence",
                  data={"season": 2026, "week": 1, "game_id": "B", "confidence": 3},
                  follow_redirects=False)
    confs = {r["game_id"]: r["confidence"] for r in
             query("SELECT game_id, confidence FROM pickem_picks WHERE user_id = ?", (me,))}
    assert confs == {"A": 3, "B": 2, "C": 1}       # nothing moved


def test_confidence_out_of_range_is_refused(attacker):
    seed_locked_and_open_week()
    me = query("SELECT user_id FROM users WHERE username = ?", (ATTACKER,))[0]["user_id"]
    from app import db
    conn = db.get_connection()
    conn.execute("INSERT INTO pickem_picks (user_id, game_id, picked_team, confidence) "
                 "VALUES (?, 'B', 'KC', 2)", (me,))
    conn.commit()
    conn.close()

    for bogus in (0, -1, 999, 2**40):
        attacker.post("/games/pickem/confidence",
                      data={"season": 2026, "week": 1, "game_id": "B", "confidence": bogus},
                      follow_redirects=False)
    assert query("SELECT confidence FROM pickem_picks WHERE user_id = ? AND game_id = 'B'",
                 (me,))[0]["confidence"] == 2


def test_cannot_invent_fantasy_draft_points(attacker):
    """points are looked up server-side from the reference data; a
    submitted value must be ignored."""
    attacker.post("/games/fantasy-draft", data={
        "year_QB": "2024", "player_QB": "Patrick Mahomes", "points": "999999",
        "points_QB": "999999",
    }, follow_redirects=False)
    rows = query("SELECT points FROM fantasy_draft_entries")
    assert rows and rows[0]["points"] == pytest.approx(320.5)


# =====================================================================
# 4. Injection and redirection
# =====================================================================

XSS = "<script>alert(1)</script>"
SQLI = "'; DROP TABLE users; --"


def test_script_tags_in_a_username_are_escaped_not_executed(client):
    """Usernames render into the nav bar and every leaderboard."""
    signup(client, "x" * 3)
    client.post("/logout", follow_redirects=False)
    # The username charset rejects '<' outright, which is the real
    # control -- assert that first.
    r = client.post("/signup", data={
        "username": XSS, "password": GOOD_PASSWORD, "confirm_password": GOOD_PASSWORD})
    assert "letters, numbers" in r.text
    assert query("SELECT count(*) c FROM users WHERE username = ?", (XSS,))[0]["c"] == 0


def test_script_tags_in_group_participant_names_are_escaped(attacker):
    attacker.post("/games/group/new", data={
        "game_type": "fantasy_draft", "participants": f"{XSS},Sam"},
        follow_redirects=False)
    body = attacker.get("/games/group").text
    assert "<script>alert(1)</script>" not in body
    if "alert(1)" in body:                       # stored, but must be escaped
        assert "&lt;script&gt;" in body


def test_sql_injection_in_form_fields_does_not_execute(attacker):
    seed_locked_and_open_week()
    attacker.post("/games/pickem/picks",
                  data={"season": 2026, "week": 1, "pick_B": SQLI}, follow_redirects=False)
    attacker.post("/profile", data={"sleeper_owner_id": SQLI, "espn_owner_id": SQLI})
    attacker.post("/games/fantasy-draft",
                  data={"year_QB": "2024", "player_QB": SQLI}, follow_redirects=False)
    # The table the payload tries to drop is still there, with our user in it.
    assert query("SELECT count(*) c FROM users")[0]["c"] >= 1


def test_next_parameter_cannot_redirect_off_site(attacker):
    """The team-colors toggle echoes `next` back as a redirect. A
    protocol-relative //host is still an absolute URL to a browser, so
    `startswith('/')` alone is not enough."""
    for hostile in ("//evil.example.com", "https://evil.example.com",
                    "//evil.example.com/path", "/\\evil.example.com",
                    "\\\\evil.example.com"):
        r = attacker.post("/preferences/team-colors",
                          data={"next": hostile, "favorite_team": "kc"},
                          follow_redirects=False)
        location = r.headers.get("location", "")
        assert not location.startswith("//"), f"open redirect via {hostile!r} -> {location!r}"
        assert "evil.example.com" not in location, f"open redirect via {hostile!r} -> {location!r}"


@pytest.mark.parametrize("game_type,category", [
    # weekly_leaders skipped category validation entirely, so anything
    # that isn't "<year> Week <n>" reached parse_weekly_category's raise.
    ("weekly_leaders", "not a week"),
    ("weekly_leaders", ""),
    ("weekly_leaders", "9999 Week"),
    # str.isdigit() is True for superscripts and other Unicode digit
    # forms that int() then refuses -- "²" passed the check and blew up
    # in int(category).
    ("nfl_top100", "²"),
    ("nfl_top100", "¹²³"),
])
def test_a_bogus_trivia_category_does_not_500(attacker, game_type, category):
    r = attacker.post("/games/trivia/start",
                      data={"game_type": game_type, "category": category},
                      follow_redirects=False)
    # 303 back to the hub (rejected by is_valid_category) or 422 (an empty
    # required Form field never reaches the handler) are both graceful.
    # The property under test is that neither path 500s.
    assert r.status_code in (303, 422), f"{game_type}/{category!r} returned {r.status_code}"
    if r.status_code == 303:
        assert r.headers["location"] == "/games/trivia"


@pytest.mark.parametrize("category", ["not a week", "²"])
def test_a_bogus_group_category_does_not_500(attacker, category):
    r = attacker.post("/games/group/new",
                      data={"game_type": "nfl_top100", "category": category,
                            "participants": "Ian,Sam"},
                      follow_redirects=False)
    assert r.status_code == 303
    assert query("SELECT count(*) c FROM group_sessions")[0]["c"] == 0


def test_garbage_in_the_reveal_form_does_not_500(attacker):
    """Every correct_* field used to go through a bare int(), so one
    non-numeric value took the request down with a 500."""
    attacker.post("/games/group/new", data={
        "game_type": "award_winners", "category": "MVP", "participants": "Ian,Sam"},
        follow_redirects=False)
    session_id = query("SELECT session_id FROM group_sessions")[0]["session_id"]
    item = query("SELECT item_key FROM group_items WHERE session_id = ?", (session_id,))[0]

    r = attacker.post(f"/games/group/session/{session_id}/reveal",
                      data={"item_key": item["item_key"], "correct_1": "not-a-number",
                            "correct_2": "", "correct_x": "<script>"},
                      follow_redirects=False)
    assert r.status_code == 303
    # The item still got revealed; the unparseable ids were just skipped.
    assert query("SELECT revealed FROM group_items WHERE session_id = ? AND item_key = ?",
                 (session_id, item["item_key"]))[0]["revealed"] == 1


# =====================================================================
# 5. Resource abuse
# =====================================================================

def test_group_session_participant_count_is_capped(attacker):
    """Nothing about the UI stops a scripted POST with a huge participant
    list, and each name is a row. whose_turn()/standings() are also O(n)
    queries per render, so a big list is CPU as well as disk."""
    attacker.post("/games/group/new", data={
        "game_type": "fantasy_draft", "participants": ",".join(f"p{i}" for i in range(5000))},
        follow_redirects=False)
    count = query("SELECT count(*) c FROM group_participants")[0]["c"]
    assert count <= 100, f"{count} participant rows created from one request"


def test_group_participant_names_are_length_capped(attacker):
    attacker.post("/games/group/new", data={
        "game_type": "fantasy_draft", "participants": "A" * 100_000 + ",Sam"},
        follow_redirects=False)
    rows = query("SELECT name FROM group_participants")
    for r in rows:
        assert len(r["name"]) <= 200, f"stored a {len(r['name'])}-character name"


def test_profile_owner_ids_are_length_capped(attacker):
    """Free-text columns written straight from the form and rendered on
    the admin page."""
    attacker.post("/profile", data={"sleeper_owner_id": "A" * 100_000})
    row = query("SELECT sleeper_owner_id FROM users WHERE username = ?", (ATTACKER,))[0]
    assert len(row["sleeper_owner_id"] or "") <= 200
