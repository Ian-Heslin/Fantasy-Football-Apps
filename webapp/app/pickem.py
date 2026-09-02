"""Real NFL Pick'em scoring -- operates on DB rows (pickem_games,
pickem_picks, pickem_settings), unlike the original mockup's in-memory
dataclasses. Standings are computed live from picks + settings every time
they're requested rather than stored, so toggling settings recomputes
every standings view immediately.

spread_line convention: POSITIVE means the home team is favored -- verified
empirically against ~2,900 real games (see schema/sqlite_schema.sql's
pickem_games comment). Don't flip the signs below without re-checking that.

Confidence points: see confidence_layout() for the one rule everything
else here depends on -- once a game kicks off its number is frozen, and
only the games still to come renumber among themselves.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TEAM_NAMES = {
    "BUF": "Bills", "MIA": "Dolphins", "NE": "Patriots", "NYJ": "Jets",
    "BAL": "Ravens", "CIN": "Bengals", "CLE": "Browns", "PIT": "Steelers",
    "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "TEN": "Titans",
    "DEN": "Broncos", "KC": "Chiefs", "LV": "Raiders", "LAC": "Chargers",
    "DAL": "Cowboys", "NYG": "Giants", "PHI": "Eagles", "WAS": "Commanders",
    "CHI": "Bears", "DET": "Lions", "GB": "Packers", "MIN": "Vikings",
    "ATL": "Falcons", "CAR": "Panthers", "NO": "Saints", "TB": "Buccaneers",
    "ARI": "Cardinals", "LA": "Rams", "SF": "49ers", "SEA": "Seahawks",
}

# pickem_games.kickoff_at is stored naive, in the stadium's local time,
# which nfldata reports as Eastern for every game (including the ones
# played abroad). See is_locked().
KICKOFF_TZ = ZoneInfo("America/New_York")


def get_settings(conn):
    row = conn.execute(
        "SELECT pick_mode, confidence_enabled FROM pickem_settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return {"pick_mode": "straight_up", "confidence_enabled": False}
    return {"pick_mode": row["pick_mode"], "confidence_enabled": bool(row["confidence_enabled"])}


def save_settings(conn, pick_mode, confidence_enabled):
    conn.execute(
        """INSERT INTO pickem_settings (id, pick_mode, confidence_enabled) VALUES (1, ?, ?)
           ON CONFLICT(id) DO UPDATE SET pick_mode=excluded.pick_mode,
               confidence_enabled=excluded.confidence_enabled""",
        (pick_mode, int(confidence_enabled)),
    )
    conn.commit()


def winner_side(game):
    """'home' | 'away' | 'push' | None (game not final yet)."""
    if not game["is_final"]:
        return None
    if game["home_score"] == game["away_score"]:
        return "push"
    return "home" if game["home_score"] > game["away_score"] else "away"


def cover_side(game):
    """Which side covered the spread -- 'home' | 'away' | 'push' | None."""
    if not game["is_final"] or game["spread_line"] is None:
        return None
    margin = (game["home_score"] - game["away_score"]) - game["spread_line"]
    if margin > 0:
        return "home"
    if margin < 0:
        return "away"
    return "push"


def favorite_team(game):
    """Team abbreviation favored by the spread, or None (pick'em game /
    no line). Positive spread_line = home favored."""
    if game["spread_line"] is None or game["spread_line"] == 0:
        return None
    return game["home_team"] if game["spread_line"] > 0 else game["away_team"]


def score_pick(game, pick_row, settings):
    """Points for one pick, or None if the game isn't final or there's no
    pick recorded. pick_row: a pickem_picks row (or None)."""
    if not game["is_final"] or pick_row is None:
        return None
    target_side = cover_side(game) if settings["pick_mode"] == "spread" else winner_side(game)
    if target_side == "push":
        return 0
    target_team = game["home_team"] if target_side == "home" else game["away_team"]
    if pick_row["picked_team"] != target_team:
        return 0
    if settings["confidence_enabled"]:
        return pick_row["confidence"] or 0
    return 1


def confidence_layout(games, existing, now=None):
    """The whole week's confidence picture in one pass.

    Returns (assignment, frozen_ids, free_values):
      assignment   {game_id: confidence} -- always a full 1..len(games)
                   permutation, so every game shows a number whether it's
                   been picked or not.
      frozen_ids   game_ids whose number can no longer move (kicked off
                   or final), whether or not a team was ever picked.
      free_values  sorted confidence values still in play -- exactly the
                   numbers held by the games that haven't kicked off, and
                   the only values reorder_confidence will accept.

    The rule that makes this correct: **a game that kicks off holds its
    number, picked or not.** A kicked-off game with no pick scores
    nothing (score_pick returns None without a pick row), but it still
    burns its confidence value, so the games that are still open
    renumber among free_values only. Without that, an unplayed game's
    number could be handed to a game whose result is already known.

    Numbers are handed out in three passes: real stored picks keep what
    they have; kicked-off games with nothing stored take the LOWEST
    values left (a missed pick burns the cheapest number rather than the
    most valuable one); everything still open takes the rest, largest
    first in kickoff order. That ordering is also what keeps a
    kicked-off game's number stable as other games get picked -- the
    open games only ever draw from values above the burned ones.

    Pure: writes nothing. A pick's number is persisted by the normal
    submit paths, at which point a real team pick exists to hang it on.
    An open game with no pick has no row to store a number in, so its
    displayed number is recomputed each render and can move as its
    neighbours get picked -- it's a preview, not a commitment."""
    n = len(games)

    # Pass 1: stored picks keep their number. Defensive against
    # duplicates and out-of-range values (a week whose game count shrank
    # after a postponement) -- anything invalid falls through to be
    # reassigned below rather than corrupting the permutation.
    assignment, used = {}, set()
    for g in games:
        row = existing.get(g["game_id"])
        if row is None or row["confidence"] is None:
            continue
        value = row["confidence"]
        if not 1 <= value <= n or value in used:
            continue
        assignment[g["game_id"]] = value
        used.add(value)

    pool = [v for v in range(1, n + 1) if v not in used]

    # Pass 2: kicked off, nothing stored -- burn the lowest values left.
    burned = 0
    for g in games:
        if g["game_id"] in assignment or not is_locked(g, now):
            continue
        assignment[g["game_id"]] = pool[burned]
        burned += 1

    # Pass 3: still open -- share out what's left, largest first.
    remaining = sorted(pool[burned:], reverse=True)
    for g, value in zip((g for g in games if g["game_id"] not in assignment), remaining):
        assignment[g["game_id"]] = value

    frozen_ids = {g["game_id"] for g in games if is_locked(g, now)}
    free_values = sorted(v for gid, v in assignment.items() if gid not in frozen_ids)
    return assignment, frozen_ids, free_values


def week_picks(conn, user_id, season, week):
    """This user's picks for one week, keyed by game_id."""
    rows = conn.execute(
        """SELECT * FROM pickem_picks WHERE user_id = ? AND game_id IN
               (SELECT game_id FROM pickem_games WHERE season = ? AND week = ?)""",
        (user_id, season, week),
    ).fetchall()
    return {r["game_id"]: r for r in rows}


def week_games(conn, season, week):
    return conn.execute(
        "SELECT * FROM pickem_games WHERE season = ? AND week = ? ORDER BY kickoff_at",
        (season, week),
    ).fetchall()


def reorder_confidence(conn, user_id, season, week, game_id, new_confidence, now=None):
    """Sets one game's confidence for this user, shifting the other games
    that are still open to keep a valid 1..n_games permutation. Returns
    True if anything was written.

    The shift is the standard "move to rank N, close the gap" reorder,
    but it runs over confidence_layout's free_values rather than over
    1..n: moving a pick to a HIGHER number shifts everything strictly
    above its old spot and at-or-below the new one DOWN one free slot;
    moving it LOWER shifts everything at-or-above the new spot and below
    the old one UP one free slot. Because it walks free_values by index
    rather than doing conf +/- 1 arithmetic, it steps *over* the numbers
    frozen games are holding instead of stealing them.

    Refuses outright when the target game has kicked off, or when the
    requested number belongs to a game that has. That guard is the point
    of this function: it used to shift every picked game in the week by
    raw value, so changing an upcoming game's number silently rewrote
    the number on a game that was already final and already scored --
    and a direct POST could set a finished game's confidence once its
    result was known.

    Only writes rows that exist: an open game with no team picked yet has
    nothing to store a number against (the schema requires picked_team),
    so it keeps getting its number from confidence_layout each render."""
    games = week_games(conn, season, week)
    if not games:
        return False
    target = next((g for g in games if g["game_id"] == game_id), None)
    if target is None or is_locked(target, now):
        return False  # kicked off -- its number is locked in place

    existing = week_picks(conn, user_id, season, week)
    if game_id not in existing:
        return False  # no team picked for this game yet -- nothing to reorder

    assignment, frozen_ids, free_values = confidence_layout(games, existing, now)
    if new_confidence not in free_values:
        return False  # that number belongs to a game that's already kicked off

    slot = {value: i for i, value in enumerate(free_values)}
    old_i, new_i = slot[assignment[game_id]], slot[new_confidence]

    if old_i != new_i:
        for other_id, value in assignment.items():
            if other_id == game_id or other_id in frozen_ids or other_id not in existing:
                continue
            i = slot[value]
            if new_i > old_i and old_i < i <= new_i:
                _set_confidence(conn, user_id, other_id, free_values[i - 1])
            elif new_i < old_i and new_i <= i < old_i:
                _set_confidence(conn, user_id, other_id, free_values[i + 1])

    _set_confidence(conn, user_id, game_id, new_confidence)
    conn.commit()
    return True


def _set_confidence(conn, user_id, game_id, value):
    conn.execute(
        "UPDATE pickem_picks SET confidence = ? WHERE user_id = ? AND game_id = ?",
        (value, user_id, game_id),
    )


def is_locked(game, now=None):
    """True once a game has started (or finished) -- picks for it can no
    longer be made or changed, and its confidence number is frozen.

    kickoff_at carries no timezone (nfldata gives local kickoff time,
    which is Eastern), so it's *interpreted* as ET here rather than
    compared against a naive server clock. That comparison used to be
    naive-vs-naive, which silently inherited whatever timezone the host
    happened to run in -- on a UTC host (Debian's default) every game
    locked 4-5 hours early, closing picks most of a morning before
    kickoff with no error anywhere. Explicit zones both sides now, so
    the host's timezone can't change the answer.

    now: injectable for tests; defaults to the real current instant."""
    if game["is_final"]:
        return True
    if not game["kickoff_at"]:
        return False
    try:
        kickoff = datetime.fromisoformat(game["kickoff_at"])
    except (TypeError, ValueError):
        return False
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=KICKOFF_TZ)
    return (now or datetime.now(timezone.utc)) >= kickoff


def current_season(conn):
    row = conn.execute("SELECT max(season) FROM pickem_games").fetchone()
    return row[0] if row and row[0] is not None else None


def current_week(conn, season):
    """First week with a not-yet-final game, or the last week if the
    season's fully wrapped, or 1 if nothing's loaded at all."""
    row = conn.execute(
        "SELECT min(week) FROM pickem_games WHERE season = ? AND is_final = 0", (season,)
    ).fetchone()
    if row and row[0] is not None:
        return row[0]
    row = conn.execute("SELECT max(week) FROM pickem_games WHERE season = ?", (season,)).fetchone()
    return row[0] if row and row[0] is not None else 1


def weeks_with_results(conn, season):
    rows = conn.execute(
        "SELECT DISTINCT week FROM pickem_games WHERE season = ? AND is_final = 1 ORDER BY week",
        (season,),
    ).fetchall()
    return [r[0] for r in rows]


def standings(conn, season, week=None):
    """Every user's points/correct/total for one week (week=<int>) or the
    whole season (week=None), ranked by points descending."""
    settings = get_settings(conn)
    if week is not None:
        games = conn.execute(
            "SELECT * FROM pickem_games WHERE season = ? AND week = ?", (season, week)
        ).fetchall()
    else:
        games = conn.execute("SELECT * FROM pickem_games WHERE season = ?", (season,)).fetchall()
    if not games:
        return []

    game_ids = [g["game_id"] for g in games]
    placeholders = ",".join("?" for _ in game_ids)
    picks = conn.execute(
        f"SELECT * FROM pickem_picks WHERE game_id IN ({placeholders})", game_ids
    ).fetchall()
    picks_by_user_game = {(p["user_id"], p["game_id"]): p for p in picks}

    users = conn.execute("SELECT user_id, username FROM users ORDER BY username").fetchall()
    results = []
    for u in users:
        points = correct = total = 0
        for g in games:
            if not g["is_final"]:
                continue
            total += 1
            pts = score_pick(g, picks_by_user_game.get((u["user_id"], g["game_id"])), settings)
            if pts:
                points += pts
                correct += 1
        results.append({
            "user_id": u["user_id"], "username": u["username"],
            "points": points, "correct": correct, "total": total,
        })
    results.sort(key=lambda r: r["points"], reverse=True)
    for i, r in enumerate(results, start=1):
        r["rank"] = i
    return results
