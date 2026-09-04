"""Pokemon Draft League: adversarial route tests -- can a plain `games`
account read the pages it's meant to (this feature is open to everyone
who signs up), and is every commissioner-only mutation actually blocked
for someone who isn't that season's commissioner? Same adversarial framing
as test_games_tier_security.py: attacker sends the request a hostile user
would send by hand (a direct POST, skipping the UI), not the request the
UI would produce.
"""
import pytest

from conftest import GOOD_PASSWORD, query, set_tier, signup

ATTACKER = "mallory"
COMMISSIONER = "ian"


@pytest.fixture
def attacker(client):
    signup(client, ATTACKER)
    assert query("SELECT tier FROM users WHERE username = ?", (ATTACKER,))[0]["tier"] == "games"
    return client


def make_commissioner_season(commissioner_tier="games"):
    """A format + season commissioned by a SECOND account, inserted
    directly so the attacker's own session is untouched. Returns
    (season_id, commissioner_user_id)."""
    from app import auth, db
    from app.pokemon_draft import seasons as pk_seasons

    conn = db.get_connection()
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, tier) VALUES (?, ?, ?)",
        (COMMISSIONER, auth.hash_password(GOOD_PASSWORD), commissioner_tier))
    commissioner_id = cur.lastrowid
    pk_seasons.create_format(conn, "gen9ou", "Gen 9 OU", "singles", "", 12, 125, True)
    season_id, _ = pk_seasons.create_season(conn, "Ian's Season", "gen9ou", commissioner_id)
    conn.close()
    return season_id, commissioner_id


# =====================================================================
# 1. Plain `games` accounts can reach every page -- this feature is open
#    to everyone who signs up, not gated behind fantasy/admin.
# =====================================================================

READABLE_PAGES = ["/pokemon", "/pokemon/seasons", "/pokemon/seasons/new",
                   "/pokemon/pokedex", "/pokemon/formats/new"]


@pytest.mark.parametrize("path", READABLE_PAGES)
def test_games_tier_can_read_every_pokemon_page(attacker, path):
    r = attacker.get(path, follow_redirects=False)
    assert r.status_code in (200, 303), path  # /pokemon redirects once a season exists


def test_games_tier_can_create_a_format_and_a_season(attacker):
    r = attacker.post("/pokemon/formats", data={
        "format_id": "gen9ou", "display_name": "Gen 9 OU", "battle_style": "singles",
        "rules_text": "", "default_roster_size": "12", "default_point_budget": "125"},
        follow_redirects=False)
    assert r.status_code == 303
    r = attacker.post("/pokemon/seasons", data={"name": "Mallory's Season", "format_id": "gen9ou"},
                       follow_redirects=False)
    assert r.status_code == 303
    assert query("SELECT count(*) c FROM pokemon_seasons")[0]["c"] == 1


# =====================================================================
# 2. Commissioner-only mutations are blocked for a non-commissioner
# =====================================================================

def test_cannot_edit_another_seasons_ruleset(attacker):
    season_id, _ = make_commissioner_season()
    r = attacker.post(f"/pokemon/seasons/{season_id}/ruleset", data={
        "roster_size_cap": "1", "point_budget": "1", "fa_transactions_allowed": "0",
        "playoff_bracket_size": "2"}, follow_redirects=False)
    assert r.status_code == 403
    row = query("SELECT point_budget FROM pokemon_seasons WHERE season_id = ?", (season_id,))[0]
    assert row["point_budget"] == 125  # unchanged


def test_cannot_activate_another_seasons(attacker):
    season_id, _ = make_commissioner_season()
    r = attacker.post(f"/pokemon/seasons/{season_id}/activate", follow_redirects=False)
    assert r.status_code == 403
    row = query("SELECT status FROM pokemon_seasons WHERE season_id = ?", (season_id,))[0]
    assert row["status"] == "draft"


def test_cannot_archive_another_seasons(attacker):
    season_id, _ = make_commissioner_season()
    r = attacker.post(f"/pokemon/seasons/{season_id}/archive", follow_redirects=False)
    assert r.status_code == 403
    row = query("SELECT status FROM pokemon_seasons WHERE season_id = ?", (season_id,))[0]
    assert row["status"] == "draft"


def test_cannot_add_a_coach_to_another_seasons(attacker):
    season_id, _ = make_commissioner_season()
    r = attacker.post(f"/pokemon/seasons/{season_id}/coaches",
                       data={"username": ATTACKER, "team_name": "Mallory's Team"},
                       follow_redirects=False)
    assert r.status_code == 403
    assert query("SELECT count(*) c FROM pokemon_season_coaches WHERE season_id = ?",
                 (season_id,))[0]["c"] == 0


def test_cannot_remove_a_coach_from_another_seasons(attacker):
    from app import db
    from app.pokemon_draft import seasons as pk_seasons

    season_id, commissioner_id = make_commissioner_season()
    conn = db.get_connection()
    pk_seasons.add_coach(conn, season_id, commissioner_id, "Ian's Team")
    coach_id = pk_seasons.list_coaches(conn, season_id)[0]["coach_id"]
    conn.close()

    r = attacker.post(f"/pokemon/seasons/{season_id}/coaches/{coach_id}/delete", follow_redirects=False)
    assert r.status_code == 403
    assert query("SELECT count(*) c FROM pokemon_season_coaches")[0]["c"] == 1


def test_cannot_set_draft_order_for_another_seasons(attacker):
    from app import db
    from app.pokemon_draft import seasons as pk_seasons

    season_id, commissioner_id = make_commissioner_season()
    conn = db.get_connection()
    pk_seasons.add_coach(conn, season_id, commissioner_id, "Ian's Team")
    conn.close()

    r = attacker.post(f"/pokemon/seasons/{season_id}/coaches/order", data={}, follow_redirects=False)
    assert r.status_code == 403


def test_a_nonexistent_season_404s_rather_than_500ing_on_commissioner_routes(attacker):
    r = attacker.post("/pokemon/seasons/999999/activate", follow_redirects=False)
    assert r.status_code == 404


# =====================================================================
# 3. Site admin acts as a cross-season commissioner override
# =====================================================================

def test_site_admin_can_act_as_commissioner_on_any_season(client):
    signup(client, "root-admin")
    set_tier("root-admin", "admin")
    season_id, _ = make_commissioner_season()

    r = client.post(f"/pokemon/seasons/{season_id}/activate", follow_redirects=False)
    assert r.status_code == 303
    row = query("SELECT status FROM pokemon_seasons WHERE season_id = ?", (season_id,))[0]
    assert row["status"] == "active"


# =====================================================================
# 4. Draft pool + live draft room
# =====================================================================

def _pool_pokemon(count=3):
    from app import db
    conn = db.get_connection()
    conn.executemany(
        """INSERT INTO pokemon (pokemon_id, species_id, slug, display_name, national_dex_number,
               generation, type1, base_hp, base_atk, base_def, base_spa, base_spd, base_spe)
           VALUES (?, ?, ?, ?, ?, 1, 'normal', 50, 50, 50, 50, 50, 50)""",
        [(i, i, f"mon{i}", f"Mon{i}", i) for i in range(1, count + 1)],
    )
    conn.commit()
    conn.close()


def test_cannot_add_to_another_seasons_pool(attacker):
    season_id, _ = make_commissioner_season()
    _pool_pokemon()
    r = attacker.post(f"/pokemon/seasons/{season_id}/pool/add",
                       data={"pokemon_id": "1", "cost": "5"}, follow_redirects=False)
    assert r.status_code == 403
    assert query("SELECT count(*) c FROM pokemon_draft_pool")[0]["c"] == 0


def test_cannot_bulk_add_generation_to_another_seasons_pool(attacker):
    season_id, _ = make_commissioner_season()
    _pool_pokemon()
    r = attacker.post(f"/pokemon/seasons/{season_id}/pool/add-generation",
                       data={"generation": "1", "default_cost": "3"}, follow_redirects=False)
    assert r.status_code == 403
    assert query("SELECT count(*) c FROM pokemon_draft_pool")[0]["c"] == 0


def test_cannot_ban_or_recost_or_remove_from_another_seasons_pool(attacker):
    from app import db
    from app.pokemon_draft import draft_pool as pk_pool

    season_id, _ = make_commissioner_season()
    _pool_pokemon()
    conn = db.get_connection()
    pk_pool.add_to_pool(conn, season_id, 1, cost_override=5)
    conn.close()

    r = attacker.post(f"/pokemon/seasons/{season_id}/pool/1/ban", data={"banned": "1"}, follow_redirects=False)
    assert r.status_code == 403
    r = attacker.post(f"/pokemon/seasons/{season_id}/pool/1/cost", data={"cost": "999"}, follow_redirects=False)
    assert r.status_code == 403
    r = attacker.post(f"/pokemon/seasons/{season_id}/pool/1/remove", follow_redirects=False)
    assert r.status_code == 403

    row = query("SELECT is_banned, cost_override FROM pokemon_draft_pool WHERE season_id = ? AND pokemon_id = 1",
                (season_id,))[0]
    assert row["is_banned"] == 0 and row["cost_override"] == 5


def test_cannot_lock_or_start_another_seasons_draft(attacker):
    season_id, _ = make_commissioner_season()
    r = attacker.post(f"/pokemon/seasons/{season_id}/lock", follow_redirects=False)
    assert r.status_code == 403
    r = attacker.post(f"/pokemon/seasons/{season_id}/draft/start", follow_redirects=False)
    assert r.status_code == 403
    row = query("SELECT draft_locked_at FROM pokemon_seasons WHERE season_id = ?", (season_id,))[0]
    assert row["draft_locked_at"] is None


def _live_draft(commissioner_tier="games"):
    """A fully set-up, in-progress draft: two coaches (COMMISSIONER and
    ATTACKER), one pokemon in the pool, drafting not yet done. Returns
    (season_id, commissioner_user_id, attacker_user_id, attacker_coach_id)."""
    from app import auth, db
    from app.pokemon_draft import draft as pk_draft
    from app.pokemon_draft import draft_pool as pk_pool
    from app.pokemon_draft import seasons as pk_seasons

    _pool_pokemon(2)
    conn = db.get_connection()
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, tier) VALUES (?, ?, ?)",
        (COMMISSIONER, auth.hash_password(GOOD_PASSWORD), commissioner_tier))
    commissioner_id = cur.lastrowid
    attacker_id = query("SELECT user_id FROM users WHERE username = ?", (ATTACKER,))[0]["user_id"]

    pk_seasons.create_format(conn, "gen9ou", "Gen 9 OU", "singles", "", 2, 20, True)
    season_id, _ = pk_seasons.create_season(conn, "Live Season", "gen9ou", commissioner_id)
    pk_seasons.add_coach(conn, season_id, commissioner_id, "Commissioner's Team")
    pk_seasons.add_coach(conn, season_id, attacker_id, "Attacker's Team")
    coaches = pk_seasons.list_coaches(conn, season_id)
    commissioner_coach_id = next(c["coach_id"] for c in coaches if c["user_id"] == commissioner_id)
    attacker_coach_id = next(c["coach_id"] for c in coaches if c["user_id"] == attacker_id)
    # Explicit order (commissioner on the clock first) -- list_coaches sorts
    # alphabetically by team_name when draft_order is unset, which doesn't
    # reliably put the commissioner first, so this can't be left implicit.
    pk_seasons.set_draft_order(conn, season_id, [commissioner_coach_id, attacker_coach_id])
    pk_pool.add_to_pool(conn, season_id, 1, cost_override=5)
    pk_pool.add_to_pool(conn, season_id, 2, cost_override=5)
    pk_seasons.lock_draft_board(conn, season_id)
    pk_draft.start_draft(conn, season_id)
    conn.close()
    return season_id, commissioner_id, attacker_id, attacker_coach_id


def test_a_real_coach_cannot_pick_out_of_turn(attacker):
    season_id, commissioner_id, attacker_id, attacker_coach_id = _live_draft()
    # draft order = [commissioner's coach, attacker's coach] (insertion order);
    # commissioner is on the clock first, so attacker's own pick is out of turn.
    r = attacker.post(f"/pokemon/seasons/{season_id}/draft/pick",
                       data={"pokemon_id": "1"}, follow_redirects=False)
    assert r.status_code == 303
    assert "error=" in r.headers["location"]
    assert query("SELECT count(*) c FROM pokemon_draft_picks")[0]["c"] == 0


def test_a_non_coach_cannot_pick_at_all(attacker):
    """attacker here is signed up but never added as a coach to this
    season -- distinct from the previous test's real-coach-out-of-turn."""
    from app import auth, db
    from app.pokemon_draft import draft as pk_draft
    from app.pokemon_draft import draft_pool as pk_pool
    from app.pokemon_draft import seasons as pk_seasons

    _pool_pokemon(1)
    conn = db.get_connection()
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, tier) VALUES (?, ?, ?)",
        (COMMISSIONER, auth.hash_password(GOOD_PASSWORD), "games"))
    commissioner_id = cur.lastrowid
    pk_seasons.create_format(conn, "gen9ou", "Gen 9 OU", "singles", "", 1, 20, True)
    season_id, _ = pk_seasons.create_season(conn, "Live Season", "gen9ou", commissioner_id)
    pk_seasons.add_coach(conn, season_id, commissioner_id, "Commissioner's Team")
    coach = pk_seasons.list_coaches(conn, season_id)[0]
    pk_seasons.set_draft_order(conn, season_id, [coach["coach_id"]])
    pk_pool.add_to_pool(conn, season_id, 1, cost_override=5)
    pk_seasons.lock_draft_board(conn, season_id)
    pk_draft.start_draft(conn, season_id)
    conn.close()

    r = attacker.post(f"/pokemon/seasons/{season_id}/draft/pick",
                       data={"pokemon_id": "1"}, follow_redirects=False)
    assert "error=" in r.headers["location"]
    assert query("SELECT count(*) c FROM pokemon_draft_picks")[0]["c"] == 0


def test_nonexistent_season_does_not_500_on_pool_or_draft_pages(attacker):
    assert attacker.get("/pokemon/seasons/999999/pool", follow_redirects=False).status_code == 303
    assert attacker.get("/pokemon/seasons/999999/draft", follow_redirects=False).status_code == 303
    r = attacker.post("/pokemon/seasons/999999/draft/pick", data={"pokemon_id": "1"}, follow_redirects=False)
    assert r.status_code == 303  # redirected with an error, not a 500


# =====================================================================
# 5. Schedule + match report/confirm/dispute/resolve
# =====================================================================

def test_cannot_generate_or_clear_another_seasons_schedule(attacker):
    season_id, _ = make_commissioner_season()
    from app import db
    from app.pokemon_draft import seasons as pk_seasons
    conn = db.get_connection()
    pk_seasons.add_coach(conn, season_id, query("SELECT user_id FROM users WHERE username = ?",
                                                  (COMMISSIONER,))[0]["user_id"], "Solo Team")
    conn.close()

    r = attacker.post(f"/pokemon/seasons/{season_id}/schedule/generate",
                       data={"num_weeks": "3"}, follow_redirects=False)
    assert r.status_code == 403
    assert query("SELECT count(*) c FROM pokemon_schedule")[0]["c"] == 0

    r = attacker.post(f"/pokemon/seasons/{season_id}/schedule/clear", follow_redirects=False)
    assert r.status_code == 403


def _scheduled_match():
    """Commissioner + attacker as the two coaches, drafted, with a
    generated 1-week schedule -- one unreported match between them.
    Returns (season_id, match_id, commissioner_id, commissioner_coach_id,
    attacker_id, attacker_coach_id)."""
    from app import auth, db
    from app.pokemon_draft import draft as pk_draft
    from app.pokemon_draft import draft_pool as pk_pool
    from app.pokemon_draft import schedule as pk_schedule
    from app.pokemon_draft import seasons as pk_seasons

    conn = db.get_connection()
    # INSERT OR IGNORE: _scheduled_match() may be called more than once in a
    # single test (independent matches for independent scenarios), and this
    # shared static pokemon data only needs to exist once.
    conn.executemany(
        """INSERT OR IGNORE INTO pokemon (pokemon_id, species_id, slug, display_name, national_dex_number,
               generation, type1, base_hp, base_atk, base_def, base_spa, base_spd, base_spe)
           VALUES (?, ?, ?, ?, ?, 1, 'normal', 50, 50, 50, 50, 50, 50)""",
        [(i, i, f"mon{i}", f"Mon{i}", i) for i in range(1, 3)],
    )
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, tier) VALUES (?, ?, ?)",
        (COMMISSIONER, auth.hash_password(GOOD_PASSWORD), "games"))
    commissioner_id = cur.lastrowid
    attacker_id = query("SELECT user_id FROM users WHERE username = ?", (ATTACKER,))[0]["user_id"]

    pk_seasons.create_format(conn, "gen9ou", "Gen 9 OU", "singles", "", 1, 20, True)
    season_id, _ = pk_seasons.create_season(conn, "Match Season", "gen9ou", commissioner_id)
    pk_seasons.add_coach(conn, season_id, commissioner_id, "Commissioner's Team")
    pk_seasons.add_coach(conn, season_id, attacker_id, "Attacker's Team")
    coaches = pk_seasons.list_coaches(conn, season_id)
    commissioner_coach_id = next(c["coach_id"] for c in coaches if c["user_id"] == commissioner_id)
    attacker_coach_id = next(c["coach_id"] for c in coaches if c["user_id"] == attacker_id)
    pk_seasons.set_draft_order(conn, season_id, [commissioner_coach_id, attacker_coach_id])
    pk_pool.add_to_pool(conn, season_id, 1, cost_override=5)
    pk_pool.add_to_pool(conn, season_id, 2, cost_override=5)
    pk_seasons.lock_draft_board(conn, season_id)
    pk_draft.start_draft(conn, season_id)
    pk_draft.make_pick(conn, season_id, commissioner_id, 1)
    pk_draft.make_pick(conn, season_id, attacker_id, 2)
    pk_schedule.generate_schedule(conn, season_id, num_weeks=1)
    row = pk_schedule.overview(conn, season_id)[0]
    conn.close()
    return (season_id, row["match_id"], commissioner_id, commissioner_coach_id,
            attacker_id, attacker_coach_id)


def test_a_non_coach_cannot_report_a_match(attacker):
    """A third account (not either coach in the matchup) tries to report
    a result via a direct POST. `attacker` is unused directly (a separate
    "eve" client is the one attacking) but requesting it is what wires up
    the isolated throwaway database for this test and creates the
    ATTACKER account that _scheduled_match() looks up by username."""
    from app import auth as auth_module
    from app import db
    (season_id, match_id, commissioner_id, commissioner_coach_id,
     attacker_id, attacker_coach_id) = _scheduled_match()

    conn = db.get_connection()
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, tier) VALUES (?, ?, ?)",
        ("eve", auth_module.hash_password(GOOD_PASSWORD), "games"))
    conn.commit()
    conn.close()

    from fastapi.testclient import TestClient
    from app.main import app
    eve = TestClient(app, base_url="https://testserver")
    eve.post("/login", data={"username": "eve", "password": GOOD_PASSWORD}, follow_redirects=False)

    r = eve.post(f"/pokemon/seasons/{season_id}/matches/{match_id}/report",
                 data={"winner_1": "home"}, follow_redirects=False)
    assert "error=" in r.headers["location"]
    assert query("SELECT count(*) c FROM pokemon_match_games")[0]["c"] == 0


def test_only_commissioner_can_resolve_a_disputed_match(attacker):
    from app import db
    from app.pokemon_draft import matches as pk_matches

    (season_id, match_id, commissioner_id, commissioner_coach_id,
     attacker_id, attacker_coach_id) = _scheduled_match()

    conn = db.get_connection()
    pk_matches.report_match(conn, match_id, commissioner_id, [
        {"winner_coach_id": commissioner_coach_id, "stats": []},
        {"winner_coach_id": commissioner_coach_id, "stats": []},
    ])
    pk_matches.dispute_match(conn, match_id, attacker_id, "disagree with this result")
    conn.close()

    r = attacker.post(f"/pokemon/seasons/{season_id}/matches/{match_id}/resolve",
                       data={"winner_1": "away", "winner_2": "away"}, follow_redirects=False)
    assert r.status_code == 403
    row = query("SELECT status FROM pokemon_matches WHERE match_id = ?", (match_id,))[0]
    assert row["status"] == "disputed"


def test_nonexistent_match_does_not_500(attacker):
    assert attacker.get("/pokemon/seasons/1/matches/999999", follow_redirects=False).status_code == 303
    r = attacker.post("/pokemon/seasons/1/matches/999999/confirm", follow_redirects=False)
    assert r.status_code == 303
    assert "error=" in r.headers["location"]


# =====================================================================
# 6. Reporting a game via a Showdown replay link
# =====================================================================

def test_reporting_via_replay_link_populates_stats(attacker, monkeypatch):
    from app.pokemon_draft import replay as pk_replay

    (season_id, match_id, commissioner_id, commissioner_coach_id,
     attacker_id, attacker_coach_id) = _scheduled_match()

    log = """|player|p1|Commissioner's Team|266|1000
|player|p2|Attacker's Team|265|1000
|switch|p1a: Mon1|Mon1, L50|100/100
|switch|p2a: Mon2|Mon2, L50|100/100
|move|p1a: Mon1|Tackle|p2a: Mon2
|-damage|p2a: Mon2|0 fnt
|faint|p2a: Mon2
|win|Commissioner's Team"""
    monkeypatch.setattr(pk_replay, "fetch_replay_json",
                         lambda url: {"log": log, "uploadtime": 42})

    r = attacker.post(f"/pokemon/seasons/{season_id}/matches/{match_id}/report", data={
        "replay_url_1": "https://replay.pokemonshowdown.com/gen9ou-1",
        "replay_home_is_p1_1": "1",
    }, follow_redirects=False)
    assert r.status_code == 303 and "error" not in r.headers["location"]
    row = query("SELECT status, winner_coach_id FROM pokemon_matches WHERE match_id = ?", (match_id,))[0]
    assert row["status"] == "pending_confirmation"
    assert row["winner_coach_id"] == commissioner_coach_id
    game = query("SELECT entry_method, parse_status FROM pokemon_match_games WHERE match_id = ?", (match_id,))[0]
    assert game["entry_method"] == "replay" and game["parse_status"] == "parsed"
    stats = query("SELECT count(*) c FROM pokemon_match_stats")[0]["c"]
    assert stats == 2  # Mon1's kill row + Mon2's death row


def test_a_replay_fetch_failure_writes_nothing(attacker, monkeypatch):
    from app.pokemon_draft import replay as pk_replay

    (season_id, match_id, *_rest) = _scheduled_match()
    monkeypatch.setattr(pk_replay, "fetch_replay_json",
                         lambda url: (_ for _ in ()).throw(pk_replay.ReplayFetchError("timed out")))

    r = attacker.post(f"/pokemon/seasons/{season_id}/matches/{match_id}/report", data={
        "replay_url_1": "https://replay.pokemonshowdown.com/gen9ou-2",
        "replay_home_is_p1_1": "1",
    }, follow_redirects=False)
    assert "error=" in r.headers["location"]
    row = query("SELECT status FROM pokemon_matches WHERE match_id = ?", (match_id,))[0]
    assert row["status"] == "unreported"
    assert query("SELECT count(*) c FROM pokemon_match_games WHERE match_id = ?", (match_id,))[0]["c"] == 0
