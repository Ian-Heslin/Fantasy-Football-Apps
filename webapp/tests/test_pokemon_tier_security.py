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
