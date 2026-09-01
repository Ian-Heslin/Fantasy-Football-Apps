"""Fantasy Draft -- "draft any player from any NFL season since 1970,
build a roster, whoever's roster scored the most PPR fantasy points that
season wins." Async/individual, like Pick'em and the trivia games: each
user builds their own roster independently (not a shared draft board, so
two users can pick the same year+player -- see schema/sqlite_schema.sql's
fantasy_draft_entries comment for why that's the deliberate choice here).

Reference data comes from two sources in analytics.duckdb, chosen per
year: `player_season_fantasy_points` (computed directly from play_by_play,
see scripts/compute_fantasy_points.py) for any season it covers -- 1999
onward, live-updating as play_by_play gets re-loaded during the season --
and `fantasy_draft_stats` (a one-time personal-spreadsheet export, see
scripts/load_trivia_data.py) only for 1970-1998, before nflverse's
play-by-play coverage starts. The computed source is preferred wherever
both exist, since it's the one that stays current and doesn't have the
spreadsheet's known gaps (e.g. Rob Gronkowski's 2011 season, missing from
that year's spreadsheet tab entirely, is present here).

A pick's points are snapshotted into fantasy_draft_entries at pick time,
so a roster's score doesn't shift under someone if the reference data is
ever reloaded/corrected.

Player lookup is a typed name (no live search-as-you-type datalist here,
to keep this server-rendered/JS-free like the rest of the app) matched
loosely via app.trivia.normalize_name; an unmatched guess gets a handful
of close-spelling suggestions from that year+slot's real player pool
rather than just failing silently.
"""
import difflib

from app.trivia import normalize_name

SLOTS = ["QB", "WR1", "WR2", "RB1", "RB2", "TE", "FLEX1", "FLEX2", "SUPERFLEX"]

SLOT_POSITIONS = {
    "QB": ["QB"],
    "WR1": ["WR"], "WR2": ["WR"],
    "RB1": ["RB"], "RB2": ["RB"],
    "TE": ["TE"],
    "FLEX1": ["RB", "WR", "TE"], "FLEX2": ["RB", "WR", "TE"],
    "SUPERFLEX": ["QB", "RB", "WR", "TE"],
}

# player_season_fantasy_points (computed from play_by_play) covers this
# year and later; fantasy_draft_stats (the spreadsheet) is the only source
# before it.
COMPUTED_SOURCE_START_YEAR = 1999


def year_range(duckdb_conn):
    spreadsheet_min = duckdb_conn.execute("SELECT min(year) FROM fantasy_draft_stats").fetchone()[0]
    computed_max = duckdb_conn.execute("SELECT max(season) FROM player_season_fantasy_points").fetchone()[0]
    return spreadsheet_min, max(computed_max, COMPUTED_SOURCE_START_YEAR - 1)


def _position_pool(duckdb_conn, year, positions):
    placeholders = ",".join("?" for _ in positions)
    if year >= COMPUTED_SOURCE_START_YEAR:
        return duckdb_conn.execute(
            f"SELECT player, team, position, games, ppr_pt FROM player_season_fantasy_points "
            f"WHERE season = ? AND position IN ({placeholders})",
            [year] + positions,
        ).fetchall()
    return duckdb_conn.execute(
        f"SELECT player, team, position, games, ppr_pt FROM fantasy_draft_stats "
        f"WHERE year = ? AND position IN ({placeholders})",
        [year] + positions,
    ).fetchall()


def find_player(duckdb_conn, year, name_guess, positions):
    """Best (player, team, position, games, ppr_pt) match for a typed
    guess within that year+slot's eligible positions, or None."""
    target = normalize_name(name_guess)
    for row in _position_pool(duckdb_conn, year, positions):
        if normalize_name(row[0]) == target:
            return row
    return None


def suggestions(duckdb_conn, year, name_guess, positions, limit=5):
    pool = _position_pool(duckdb_conn, year, positions)
    names = [row[0] for row in pool]
    normalized_to_real = {normalize_name(n): n for n in names}
    close = difflib.get_close_matches(normalize_name(name_guess), normalized_to_real.keys(), n=limit, cutoff=0.6)
    return [normalized_to_real[n] for n in close]


def get_entries(conn, user_id):
    rows = conn.execute("SELECT * FROM fantasy_draft_entries WHERE user_id = ?", (user_id,)).fetchall()
    return {r["slot"]: r for r in rows}


def save_picks(conn, duckdb_conn, user_id, form):
    """form: {f'year_{slot}': ..., f'player_{slot}': ...} for whichever
    slots were submitted with both fields filled in. Returns {slot: error
    message} for anything that didn't match -- those slots are left
    untouched rather than saved wrong or blanked."""
    errors = {}
    for slot in SLOTS:
        year_raw = form.get(f"year_{slot}")
        player_raw = form.get(f"player_{slot}")
        if not year_raw or not player_raw:
            continue
        try:
            year = int(year_raw)
        except ValueError:
            errors[slot] = f"'{year_raw}' isn't a year."
            continue

        match = find_player(duckdb_conn, year, player_raw, SLOT_POSITIONS[slot])
        if match is None:
            hint = suggestions(duckdb_conn, year, player_raw, SLOT_POSITIONS[slot])
            errors[slot] = (
                f"No {'/'.join(SLOT_POSITIONS[slot])} named '{player_raw}' found in {year}."
                + (f" Did you mean: {', '.join(hint)}?" if hint else "")
            )
            continue

        player, team, position, games, ppr_pt = match
        conn.execute(
            """INSERT INTO fantasy_draft_entries (user_id, slot, year, player, points)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id, slot) DO UPDATE SET
                   year=excluded.year, player=excluded.player, points=excluded.points""",
            (user_id, slot, year, player, ppr_pt),
        )
    conn.commit()
    return errors


def leaderboard(conn):
    rows = conn.execute(
        """SELECT u.user_id, u.username, sum(e.points) AS total_points, count(e.slot) AS slots_filled
           FROM users u JOIN fantasy_draft_entries e ON e.user_id = u.user_id
           GROUP BY u.user_id, u.username"""
    ).fetchall()
    results = [
        {"user_id": r["user_id"], "username": r["username"],
         "total_points": r["total_points"] or 0, "slots_filled": r["slots_filled"]}
        for r in rows
    ]
    results.sort(key=lambda r: r["total_points"], reverse=True)
    for i, r in enumerate(results, start=1):
        r["rank"] = i
    return results
