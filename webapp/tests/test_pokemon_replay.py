"""Pokemon Draft League: Showdown replay parser tests.

parse_battle_log() is pure (no network, no DB) -- these are literal
protocol-log fixture strings, same pattern as test_pickem.py's hand-built
fixtures. fetch_replay_json() itself (the one bit of network I/O) is
exercised at the route level in test_pokemon_tier_security.py via a
monkeypatched fetch, not here.

Run with:  python3 -m pytest tests/ -q     (from webapp/)
"""
from app.pokemon_draft import replay


def test_direct_hit_kill_is_attributed_to_the_attacker():
    log = """|player|p1|Alice|266|1000
|player|p2|Bob|265|1000
|switch|p1a: Garchomp|Garchomp, L50, M|100/100
|switch|p2a: Ferrothorn|Ferrothorn, L50|100/100
|move|p1a: Garchomp|Earthquake|p2a: Ferrothorn
|-damage|p2a: Ferrothorn|0 fnt
|faint|p2a: Ferrothorn
|win|Alice"""
    result = replay.parse_battle_log(log, "singles")
    assert result["winner_side"] == "p1"
    assert result["p1"]["Garchomp"] == {"kills": 1, "deaths": 0}
    assert result["p2"]["Ferrothorn"] == {"kills": 0, "deaths": 1}


def test_switching_updates_which_species_occupies_a_slot():
    """The slot that faints should be credited to whatever's CURRENTLY
    there, not whichever Pokemon originally held that slot."""
    log = """|player|p1|Alice|266|1000
|player|p2|Bob|265|1000
|switch|p1a: Garchomp|Garchomp, L50, M|100/100
|switch|p2a: Ferrothorn|Ferrothorn, L50|100/100
|move|p1a: Garchomp|Earthquake|p2a: Ferrothorn
|-damage|p2a: Ferrothorn|0 fnt
|faint|p2a: Ferrothorn
|switch|p2a: Landorus|Landorus-Therian, L50|100/100
|move|p1a: Garchomp|Earthquake|p2a: Landorus
|-damage|p2a: Landorus|0 fnt
|faint|p2a: Landorus
|win|Alice"""
    result = replay.parse_battle_log(log, "singles")
    assert result["p1"]["Garchomp"]["kills"] == 2
    assert result["p2"]["Ferrothorn"] == {"kills": 0, "deaths": 1}
    assert result["p2"]["Landorus-Therian"] == {"kills": 0, "deaths": 1}


def test_indirect_damage_credits_no_attacker():
    """A faint whose last damage instance carries a [from] tag (status,
    weather, hazards, recoil, item damage) is a death with no kill
    credited anywhere -- matches how these leagues already score by hand."""
    log = """|player|p1|Alice|266|1000
|player|p2|Bob|265|1000
|switch|p1a: Garchomp|Garchomp, L50, M|100/100
|switch|p2a: Ferrothorn|Ferrothorn, L50|1/100
|-damage|p2a: Ferrothorn|0 fnt|[from] psn
|faint|p2a: Ferrothorn
|win|Alice"""
    result = replay.parse_battle_log(log, "singles")
    assert result["p2"]["Ferrothorn"] == {"kills": 0, "deaths": 1}
    assert result["p1"] == {}  # Garchomp never did anything -- no row at all


def test_the_last_damage_instance_before_a_faint_is_what_counts():
    """A direct hit that doesn't finish the target, followed by an
    indirect tick that does, credits no one -- even though the direct hit
    did most of the work. This is the documented, accepted simplification
    (see replay.py's module docstring), not a bug to "fix" by attributing
    partial credit."""
    log = """|player|p1|Alice|266|1000
|player|p2|Bob|265|1000
|switch|p1a: Garchomp|Garchomp, L50, M|100/100
|switch|p2a: Ferrothorn|Ferrothorn, L50|100/100
|move|p1a: Garchomp|Earthquake|p2a: Ferrothorn
|-damage|p2a: Ferrothorn|5/100
|-damage|p2a: Ferrothorn|0 fnt|[from] psn
|faint|p2a: Ferrothorn
|win|Alice"""
    result = replay.parse_battle_log(log, "singles")
    assert result["p1"] == {}  # Garchomp neither fainted nor scored a kill -- no row at all
    assert result["p2"]["Ferrothorn"] == {"kills": 0, "deaths": 1}


def test_doubles_spread_move_credits_the_attacker_for_both_targets():
    log = """|player|p1|Alice|266|1000
|player|p2|Bob|265|1000
|switch|p1a: Garchomp|Garchomp, L50, M|100/100
|switch|p1b: Amoonguss|Amoonguss, L50|100/100
|switch|p2a: Ferrothorn|Ferrothorn, L50|1/100
|switch|p2b: Rotom|Rotom-Wash, L50|1/100
|move|p1a: Garchomp|Earthquake||[spread] p2a,p2b
|-damage|p2a: Ferrothorn|0 fnt
|-damage|p2b: Rotom|0 fnt
|faint|p2a: Ferrothorn
|faint|p2b: Rotom
|win|Alice"""
    result = replay.parse_battle_log(log, "doubles")
    assert result["p1"]["Garchomp"]["kills"] == 2
    assert result["p2"]["Ferrothorn"]["deaths"] == 1
    assert result["p2"]["Rotom-Wash"]["deaths"] == 1


def test_winner_side_resolved_from_player_and_win_lines():
    log = """|player|p1|Alice|266|1000
|player|p2|Bob|265|1000
|win|Bob"""
    assert replay.parse_battle_log(log)["winner_side"] == "p2"


def test_no_win_line_leaves_winner_side_none():
    log = """|player|p1|Alice|266|1000
|player|p2|Bob|265|1000
|switch|p1a: Garchomp|Garchomp, L50, M|100/100"""
    assert replay.parse_battle_log(log)["winner_side"] is None


def test_malformed_or_empty_logs_never_raise():
    for bad in ["", "not a battle log at all", "|garbage|||||", "|move|", "|faint|p1a:",
                "|switch|p1a: X", "|-damage|", "|player|p1"]:
        result = replay.parse_battle_log(bad, "singles")
        assert result["winner_side"] is None
        assert result["p1"] == {} and result["p2"] == {}


def test_build_game_from_replay_reports_a_fetch_failure_without_writing_anything(monkeypatch):
    def boom(url):
        raise replay.ReplayFetchError("connection refused")
    monkeypatch.setattr(replay, "fetch_replay_json", boom)
    game, error = replay.build_game_from_replay(None, "https://replay.pokemonshowdown.com/x", 1, 2, True)
    assert game is None
    assert "connection refused" in error


def test_build_game_from_replay_reports_missing_winner(monkeypatch):
    monkeypatch.setattr(replay, "fetch_replay_json", lambda url: {"log": "|player|p1|Alice|1|1"})
    game, error = replay.build_game_from_replay(None, "https://replay.pokemonshowdown.com/x", 1, 2, True)
    assert game is None
    assert "winner" in error.lower()


def test_build_game_from_replay_maps_p1_p2_onto_home_away(monkeypatch):
    import sqlite3
    from conftest import SQLITE_SCHEMA

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open(SQLITE_SCHEMA) as f:
        conn.executescript(f.read())
    conn.execute(
        """INSERT INTO pokemon (pokemon_id, species_id, slug, display_name, national_dex_number,
               generation, type1, base_hp, base_atk, base_def, base_spa, base_spd, base_spe)
           VALUES (1, 1, 'garchomp', 'Garchomp', 1, 1, 'normal', 50, 50, 50, 50, 50, 50)""")
    conn.commit()

    log = """|player|p1|Alice|266|1000
|player|p2|Bob|265|1000
|switch|p1a: Garchomp|Garchomp, L50, M|100/100
|win|Alice"""
    monkeypatch.setattr(replay, "fetch_replay_json",
                         lambda url: {"log": log, "uploadtime": 111})

    HOME, AWAY = 10, 20
    # home_is_p1=True: p1 (winner) maps to HOME
    game, error = replay.build_game_from_replay(conn, "https://x", HOME, AWAY, True)
    assert error is None
    assert game["winner_coach_id"] == HOME
    assert game["entry_method"] == "replay"
    assert game["parse_status"] == "parsed"

    # home_is_p1=False: p1 (winner) maps to AWAY instead
    game2, error2 = replay.build_game_from_replay(conn, "https://x", HOME, AWAY, False)
    assert error2 is None
    assert game2["winner_coach_id"] == AWAY
