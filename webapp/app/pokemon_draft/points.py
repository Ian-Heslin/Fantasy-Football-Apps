"""Smogon usage-stat point-cost engine. Fetches a format's monthly usage
stats text file, parses each Pokemon's usage%, and maps that through the
season's configurable pokemon_cost_tiers table into a point cost -- see
schema/sqlite_schema.sql's pokemon_cost_tiers comment. Run once as an
explicit commissioner action at season setup ("fetch point costs" /
"re-fetch"), never on a schedule.

Costs write to pokemon_draft_pool.computed_cost ONLY -- cost_override is
never touched by a fetch, so draft_pool.effective_cost() (COALESCE(
cost_override, computed_cost)) means a commissioner's manual price edit
survives a later re-fetch. Blocked once the draft board locks, same as
every other pool/cost-setup action in draft_pool.py.

Split for testability the same way replay.py splits fetch/parse:
fetch_usage_stats() is thin and mockable, parse_usage_text() and
compute_cost() are pure.
"""
import re

import requests

from app.pokemon_draft import pokedex, seasons

FETCH_TIMEOUT_SECONDS = 8
STATS_BASE_URL = "https://www.smogon.com/stats"

# Smogon usage-stat rows look like " | 1    | Great Tusk    | 41.23480% | ..."
# -- rank, then Pokemon name, then the first usage-percent column. Extra
# trailing columns (Raw/Real counts, weighted %) vary by file and are
# ignored. The header row ("| Rank | Pokemon | Usage % |") and the
# "+ ---- + ------ +" separator rows never match -- neither starts with a
# digit in the first cell.
_ROW_RE = re.compile(r"^\s*\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([\d.]+)%")

# Placeholder usage%->cost boundaries -- there's no historical usage-based
# formula to seed real numbers from (the source league hand-assigned its
# costs), so these exist purely so a season has something to fetch against.
# The commissioner is expected to retune them (set_cost_tiers()) before
# locking the draft board. Ordered highest usage first; the last tier's
# min_usage_percent of 0 is a floor so every matched Pokemon prices to at
# least 1 point rather than going unpriced.
DEFAULT_TIERS = [
    (40, 20), (30, 17), (20, 14), (15, 12), (10, 10),
    (7, 8), (5, 6), (3, 4), (1, 2), (0, 1),
]


class UsageStatsFetchError(Exception):
    pass


def fetch_usage_stats(url):
    """Thin, mockable HTTP fetch -- returns the raw text body, or raises
    UsageStatsFetchError."""
    try:
        resp = requests.get(url, timeout=FETCH_TIMEOUT_SECONDS)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise UsageStatsFetchError(str(e)) from e
    return resp.text


def parse_usage_text(text):
    """[{"name": str, "usage_percent": float}, ...] in the file's own rank
    order. Pure -- no I/O. A malformed/empty file just yields []."""
    out = []
    for line in text.splitlines():
        m = _ROW_RE.match(line)
        if m:
            out.append({"name": m.group(2).strip(), "usage_percent": float(m.group(3))})
    return out


def stats_url(smogon_stats_prefix, month, rating=1500):
    """month: 'YYYY-MM'. Smogon's own URL shape:
    smogon.com/stats/<month>/<formatid>-<rating>.txt"""
    return f"{STATS_BASE_URL}/{month}/{smogon_stats_prefix}-{rating}.txt"


def compute_cost(usage_percent, tiers):
    """tiers: pokemon_cost_tiers rows (or (min_usage_percent, point_cost)
    pairs) for one season, any order. A Pokemon's cost is the point_cost of
    the tier with the HIGHEST min_usage_percent it still clears. None if it
    clears no tier at all -- the commissioner sets cost_override by hand
    for anything that should still be draftable despite that."""
    def min_pct(t):
        return t["min_usage_percent"] if hasattr(t, "keys") else t[0]

    def cost(t):
        return t["point_cost"] if hasattr(t, "keys") else t[1]

    eligible = [t for t in tiers if usage_percent >= min_pct(t)]
    if not eligible:
        return None
    return cost(max(eligible, key=min_pct))


# ---------------------------------------------------------------------
# Cost tier CRUD
# ---------------------------------------------------------------------

def list_cost_tiers(conn, season_id):
    return conn.execute(
        "SELECT * FROM pokemon_cost_tiers WHERE season_id = ? ORDER BY min_usage_percent DESC",
        (season_id,),
    ).fetchall()


def seed_default_tiers(conn, season_id):
    """No-ops if the season already has any tiers -- never clobbers an
    edited table. Called once right after a season is created."""
    if list_cost_tiers(conn, season_id):
        return
    conn.executemany(
        "INSERT INTO pokemon_cost_tiers (season_id, tier_rank, min_usage_percent, point_cost) "
        "VALUES (?, ?, ?, ?)",
        [(season_id, i + 1, min_pct, cost) for i, (min_pct, cost) in enumerate(DEFAULT_TIERS)],
    )
    conn.commit()


def set_cost_tiers(conn, season_id, tiers):
    """Replaces this season's whole tier table. tiers: [(min_usage_percent,
    point_cost), ...], any order, all fed through this at once since
    editing one row at a time can't ever produce a duplicate-percent state
    from the UI. None on success, or an error string -- blocked once the
    draft board is locked, same as the rest of pool/cost setup."""
    season = seasons.get_season(conn, season_id)
    if season is None:
        return "No such season."
    if season["draft_locked_at"]:
        return "The draft board is locked -- cost tiers can no longer be changed."
    if not tiers:
        return "Need at least one tier."
    ordered = sorted(tiers, key=lambda t: -t[0])
    conn.execute("DELETE FROM pokemon_cost_tiers WHERE season_id = ?", (season_id,))
    conn.executemany(
        "INSERT INTO pokemon_cost_tiers (season_id, tier_rank, min_usage_percent, point_cost) "
        "VALUES (?, ?, ?, ?)",
        [(season_id, i + 1, min_pct, cost) for i, (min_pct, cost) in enumerate(ordered)],
    )
    conn.commit()
    return None


# ---------------------------------------------------------------------
# Fetch + apply
# ---------------------------------------------------------------------

def fetch_and_apply(conn, season_id, month, rating=1500):
    """Fetches this season's format's usage stats, matches each row to a
    pokedex entry, and writes usage_percent/computed_cost/stats_fetched_at
    onto every matched pool entry -- cost_override is never touched.
    Returns (matched_count, unmatched_names, None) on success -- where
    unmatched_names is every parsed row that didn't get a cost written,
    either because it isn't in the pokedex under that name or isn't in
    this season's pool -- or (0, [], error string) with nothing written on
    any failure."""
    season = seasons.get_season(conn, season_id)
    if season is None:
        return 0, [], "No such season."
    if season["draft_locked_at"]:
        return 0, [], "The draft board is locked -- costs can no longer be refetched."
    fmt = seasons.get_format(conn, season["format_id"])
    if fmt is None or not fmt["smogon_stats_prefix"]:
        return 0, [], "This season's format has no Smogon stats prefix configured."
    tiers = list_cost_tiers(conn, season_id)
    if not tiers:
        return 0, [], "Set up this season's cost tiers before fetching usage stats."

    url = stats_url(fmt["smogon_stats_prefix"], month, rating)
    try:
        text = fetch_usage_stats(url)
    except UsageStatsFetchError as e:
        return 0, [], f"Couldn't fetch Smogon usage stats: {e}"

    rows = parse_usage_text(text)
    if not rows:
        return 0, [], "Fetched the stats page, but couldn't parse any usage rows from it."

    pool_ids = {r["pokemon_id"] for r in conn.execute(
        "SELECT pokemon_id FROM pokemon_draft_pool WHERE season_id = ?", (season_id,))}

    matched = 0
    unmatched = []
    for row in rows:
        pokemon_id = pokedex.find_by_species_name(conn, row["name"])
        if pokemon_id is None or pokemon_id not in pool_ids:
            unmatched.append(row["name"])
            continue
        cost = compute_cost(row["usage_percent"], tiers)
        conn.execute(
            """UPDATE pokemon_draft_pool SET usage_percent = ?, computed_cost = ?,
                   stats_fetched_at = datetime('now') WHERE season_id = ? AND pokemon_id = ?""",
            (row["usage_percent"], cost, season_id, pokemon_id),
        )
        matched += 1

    conn.execute(
        """INSERT INTO sync_log (table_name, source, last_synced_at, row_count, notes)
               VALUES (?, 'smogon', datetime('now'), ?, ?)
           ON CONFLICT(table_name) DO UPDATE SET
               last_synced_at = datetime('now'), row_count = excluded.row_count, notes = excluded.notes""",
        (f"pokemon_season_{season_id}_usage", matched, url),
    )
    conn.commit()
    return matched, unmatched, None
