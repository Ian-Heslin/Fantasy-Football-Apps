"""Pokemon Draft League: Smogon usage-stat cost engine tests.

parse_usage_text()/compute_cost() are pure (no network, no DB) -- literal
fixture strings, same pattern as test_pokemon_replay.py. fetch_usage_stats()
itself (the one bit of network I/O) is exercised here via a monkeypatched
fetch, mirroring how test_pokemon_tier_security.py exercises replay.py's
fetch_replay_json().

Run with:  python3 -m pytest tests/ -q     (from webapp/)
"""
import sqlite3

from conftest import SQLITE_SCHEMA

from app.pokemon_draft import draft_pool, points, seasons

SAMPLE_STATS_TEXT = """ Total battles: 24868
 Avg. weight/team: 0.398382
 + ---- + ------------------------ + --------- +
 | Rank | Pokemon                  | Usage %   |
 + ---- + ------------------------ + --------- +
 | 1    | Great Tusk               | 41.23480% |
 | 2    | Kingambit                | 30.10200% |
 | 3    | Landorus-Therian         | 18.55000% |
 | 4    | Gholdengo                | 6.40000%  |
 | 5    | Some Rarely Used Mon     | 0.50000%  |
 + ---- + ------------------------ + --------- +
"""


# ---------------------------------------------------------------------
# Pure parsing
# ---------------------------------------------------------------------

def test_parse_usage_text_extracts_rank_ordered_rows():
    rows = points.parse_usage_text(SAMPLE_STATS_TEXT)
    assert [r["name"] for r in rows] == [
        "Great Tusk", "Kingambit", "Landorus-Therian", "Gholdengo", "Some Rarely Used Mon"]
    assert rows[0]["usage_percent"] == 41.2348
    assert rows[4]["usage_percent"] == 0.5


def test_parse_usage_text_ignores_header_and_separator_lines():
    rows = points.parse_usage_text(SAMPLE_STATS_TEXT)
    names = [r["name"] for r in rows]
    assert "Rank" not in names and "Pokemon" not in names


def test_parse_usage_text_on_garbage_returns_empty():
    assert points.parse_usage_text("not a stats file at all\njust some text") == []


def test_stats_url_matches_smogons_own_shape():
    assert points.stats_url("gen9ou", "2025-01", 1500) == \
        "https://www.smogon.com/stats/2025-01/gen9ou-1500.txt"


# ---------------------------------------------------------------------
# compute_cost
# ---------------------------------------------------------------------

TIERS = [(40, 20), (30, 17), (20, 14), (10, 10), (0, 1)]


def test_compute_cost_picks_the_highest_tier_cleared():
    assert points.compute_cost(45.0, TIERS) == 20
    assert points.compute_cost(40.0, TIERS) == 20  # exactly at the boundary counts
    assert points.compute_cost(35.0, TIERS) == 17
    assert points.compute_cost(0.1, TIERS) == 1


def test_compute_cost_none_when_no_tier_is_cleared():
    tiers_without_floor = [(40, 20), (30, 17)]
    assert points.compute_cost(5.0, tiers_without_floor) is None


def test_compute_cost_works_with_sqlite_rows_not_just_tuples():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open(SQLITE_SCHEMA) as f:
        conn.executescript(f.read())
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, tier) VALUES (1, 'u', 'x', 'games')")
    seasons.create_format(conn, "gen9ou", "Gen 9 OU", "singles", "", 10, 100, True)
    season_id, _ = seasons.create_season(conn, "S", "gen9ou", 1)
    points.set_cost_tiers(conn, season_id, TIERS)
    rows = points.list_cost_tiers(conn, season_id)
    assert points.compute_cost(35.0, rows) == 17


# ---------------------------------------------------------------------
# Cost tier CRUD
# ---------------------------------------------------------------------

def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with open(SQLITE_SCHEMA) as f:
        conn.executescript(f.read())
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, tier) VALUES (1, 'u', 'x', 'games')")
    seasons.create_format(conn, "gen9ou", "Gen 9 OU", "singles", "", 10, 100, True,
                           smogon_stats_prefix="gen9ou")
    season_id, _ = seasons.create_season(conn, "S", "gen9ou", 1)
    return conn, season_id


def test_seed_default_tiers_populates_a_fresh_season():
    conn, season_id = make_db()
    points.seed_default_tiers(conn, season_id)
    tiers = points.list_cost_tiers(conn, season_id)
    assert len(tiers) == len(points.DEFAULT_TIERS)
    assert tiers[0]["min_usage_percent"] == max(p for p, _ in points.DEFAULT_TIERS)


def test_seed_default_tiers_never_clobbers_an_existing_table():
    conn, season_id = make_db()
    points.set_cost_tiers(conn, season_id, [(50, 25)])
    points.seed_default_tiers(conn, season_id)
    tiers = points.list_cost_tiers(conn, season_id)
    assert len(tiers) == 1 and tiers[0]["point_cost"] == 25


def test_set_cost_tiers_orders_by_usage_descending_regardless_of_input_order():
    conn, season_id = make_db()
    error = points.set_cost_tiers(conn, season_id, [(10, 5), (40, 20), (25, 12)])
    assert error is None
    tiers = points.list_cost_tiers(conn, season_id)
    assert [t["min_usage_percent"] for t in tiers] == [40, 25, 10]


def test_set_cost_tiers_rejects_an_empty_table():
    conn, season_id = make_db()
    error = points.set_cost_tiers(conn, season_id, [])
    assert error is not None and "at least one tier" in error


def test_set_cost_tiers_refuses_once_the_draft_board_is_locked():
    conn, season_id = make_db()
    points.set_cost_tiers(conn, season_id, TIERS)
    seasons.lock_draft_board(conn, season_id)
    error = points.set_cost_tiers(conn, season_id, [(1, 1)])
    assert error is not None and "locked" in error
    assert len(points.list_cost_tiers(conn, season_id)) == len(TIERS)  # unchanged


# ---------------------------------------------------------------------
# fetch_and_apply
# ---------------------------------------------------------------------

def _pool_pokemon(conn, pokemon_id, slug, display_name):
    conn.execute(
        """INSERT INTO pokemon (pokemon_id, species_id, slug, display_name, national_dex_number,
               generation, type1, base_hp, base_atk, base_def, base_spa, base_spd, base_spe)
           VALUES (?, ?, ?, ?, ?, 9, 'normal', 50, 50, 50, 50, 50, 50)""",
        (pokemon_id, pokemon_id, slug, display_name, pokemon_id),
    )


def test_fetch_and_apply_writes_computed_cost_without_touching_override(monkeypatch):
    conn, season_id = make_db()
    _pool_pokemon(conn, 1, "great-tusk", "Great Tusk")
    _pool_pokemon(conn, 2, "kingambit", "Kingambit")
    draft_pool.add_to_pool(conn, season_id, 1)  # no override
    draft_pool.add_to_pool(conn, season_id, 2, cost_override=99)  # commissioner already priced this
    points.set_cost_tiers(conn, season_id, TIERS)

    monkeypatch.setattr(points, "fetch_usage_stats", lambda url: SAMPLE_STATS_TEXT)
    matched, unmatched, error = points.fetch_and_apply(conn, season_id, "2025-01")
    assert error is None
    assert matched == 2  # Great Tusk (41.2%) and Kingambit (30.1%) both in this pool

    great_tusk = draft_pool.get_pool_entry(conn, season_id, 1)
    assert great_tusk["computed_cost"] == 20  # 41.2% clears the 40 tier
    assert great_tusk["usage_percent"] == 41.2348
    assert great_tusk["stats_fetched_at"] is not None
    assert draft_pool.effective_cost(great_tusk) == 20  # visible -- no override shadowing it

    kingambit = draft_pool.get_pool_entry(conn, season_id, 2)
    assert kingambit["computed_cost"] == 17  # 30.1% clears the 30 tier
    assert kingambit["cost_override"] == 99  # never touched
    assert draft_pool.effective_cost(kingambit) == 99  # override still wins


def test_pool_added_with_no_cost_can_actually_be_priced_by_a_later_fetch(monkeypatch):
    """Regression test: add_generation_to_pool()'s bulk-add path (and
    add_to_pool()'s single-add path) used to always write a placeholder
    into cost_override -- even when the commissioner left "cost" blank --
    which permanently shadowed computed_cost via effective_cost()'s
    COALESCE and made a later Smogon fetch a complete no-op. Both now
    default to leaving cost_override NULL when no cost is given."""
    conn, season_id = make_db()
    _pool_pokemon(conn, 1, "great-tusk", "Great Tusk")
    _pool_pokemon(conn, 2, "kingambit", "Kingambit")
    count, error = draft_pool.add_generation_to_pool(conn, season_id, 9)  # no default_cost
    assert error is None and count == 2
    for pokemon_id in (1, 2):
        entry = draft_pool.get_pool_entry(conn, season_id, pokemon_id)
        assert entry["cost_override"] is None
        assert draft_pool.effective_cost(entry) is None  # genuinely unpriced, not just "0"

    points.set_cost_tiers(conn, season_id, TIERS)
    monkeypatch.setattr(points, "fetch_usage_stats", lambda url: SAMPLE_STATS_TEXT)
    matched, unmatched, error = points.fetch_and_apply(conn, season_id, "2025-01")
    assert error is None and matched == 2

    great_tusk = draft_pool.get_pool_entry(conn, season_id, 1)
    assert draft_pool.effective_cost(great_tusk) == 20  # the fetch actually took effect


def test_set_cost_override_none_clears_it_back_to_computed_cost(monkeypatch):
    """Regression test: previously there was no way to undo a manually-set
    cost_override short of removing and re-adding the pool entry."""
    conn, season_id = make_db()
    _pool_pokemon(conn, 1, "great-tusk", "Great Tusk")
    draft_pool.add_to_pool(conn, season_id, 1, cost_override=1)
    points.set_cost_tiers(conn, season_id, TIERS)
    monkeypatch.setattr(points, "fetch_usage_stats", lambda url: SAMPLE_STATS_TEXT)
    points.fetch_and_apply(conn, season_id, "2025-01")

    entry = draft_pool.get_pool_entry(conn, season_id, 1)
    assert draft_pool.effective_cost(entry) == 1  # override still shadowing the fetched cost

    draft_pool.set_cost_override(conn, season_id, 1, None)
    entry = draft_pool.get_pool_entry(conn, season_id, 1)
    assert entry["cost_override"] is None
    assert draft_pool.effective_cost(entry) == 20  # computed_cost now visible


def test_fetch_and_apply_reports_rows_it_cant_apply_a_cost_to(monkeypatch):
    conn, season_id = make_db()
    _pool_pokemon(conn, 1, "great-tusk", "Great Tusk")
    draft_pool.add_to_pool(conn, season_id, 1)
    points.set_cost_tiers(conn, season_id, TIERS)

    monkeypatch.setattr(points, "fetch_usage_stats", lambda url: SAMPLE_STATS_TEXT)
    matched, unmatched, error = points.fetch_and_apply(conn, season_id, "2025-01")
    assert error is None
    assert matched == 1
    # Kingambit, Landorus-Therian, Gholdengo, and the rare mon are all
    # parsed from the file but never entered this season's pool.
    assert set(unmatched) == {"Kingambit", "Landorus-Therian", "Gholdengo", "Some Rarely Used Mon"}


def test_fetch_and_apply_requires_cost_tiers_first():
    conn, season_id = make_db()
    matched, unmatched, error = points.fetch_and_apply(conn, season_id, "2025-01")
    assert error is not None and "cost tiers" in error
    assert matched == 0 and unmatched == []


def test_fetch_and_apply_requires_a_smogon_stats_prefix():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with open(SQLITE_SCHEMA) as f:
        conn.executescript(f.read())
    conn.execute(
        "INSERT INTO users (user_id, username, password_hash, tier) VALUES (1, 'u', 'x', 'games')")
    seasons.create_format(conn, "homebrew", "Homebrew Format", "singles", "", 10, 100, True)
    season_id, _ = seasons.create_season(conn, "S", "homebrew", 1)
    points.set_cost_tiers(conn, season_id, TIERS)

    matched, unmatched, error = points.fetch_and_apply(conn, season_id, "2025-01")
    assert error is not None and "Smogon stats" in error


def test_fetch_and_apply_writes_nothing_on_a_fetch_failure(monkeypatch):
    conn, season_id = make_db()
    _pool_pokemon(conn, 1, "great-tusk", "Great Tusk")
    draft_pool.add_to_pool(conn, season_id, 1)
    points.set_cost_tiers(conn, season_id, TIERS)

    def boom(url):
        raise points.UsageStatsFetchError("timed out")
    monkeypatch.setattr(points, "fetch_usage_stats", boom)

    matched, unmatched, error = points.fetch_and_apply(conn, season_id, "2025-01")
    assert error is not None and "timed out" in error
    entry = draft_pool.get_pool_entry(conn, season_id, 1)
    assert entry["computed_cost"] is None and entry["stats_fetched_at"] is None


def test_fetch_and_apply_refuses_once_the_draft_board_is_locked(monkeypatch):
    conn, season_id = make_db()
    points.set_cost_tiers(conn, season_id, TIERS)
    seasons.lock_draft_board(conn, season_id)

    monkeypatch.setattr(points, "fetch_usage_stats", lambda url: SAMPLE_STATS_TEXT)
    matched, unmatched, error = points.fetch_and_apply(conn, season_id, "2025-01")
    assert error is not None and "locked" in error
