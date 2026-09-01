"""Real NFL Pick'em scoring -- operates on DB rows (pickem_games,
pickem_picks, pickem_settings), unlike the original mockup's in-memory
dataclasses. Standings are computed live from picks + settings every time
they're requested rather than stored, so toggling settings recomputes
every standings view immediately.

spread_line convention: POSITIVE means the home team is favored -- verified
empirically against ~2,900 real games (see schema/sqlite_schema.sql's
pickem_games comment). Don't flip the signs below without re-checking that.
"""
from datetime import datetime

TEAM_NAMES = {
    "BUF": "Bills", "MIA": "Dolphins", "NE": "Patriots", "NYJ": "Jets",
    "BAL": "Ravens", "CIN": "Bengals", "CLE": "Browns", "PIT": "Steelers",
    "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "TEN": "Titans",
    "DEN": "Broncos", "KC": "Chiefs", "LV": "Raiders", "LAC": "Chargers",
    "DAL": "Cowboys", "NYG": "Giants", "PHI": "Eagles", "WAS": "Commanders",
    "CHI": "Bears", "DET": "Lions", "GB": "Packers", "MIN": "Vikings",
    "ATL": "Falcons", "CAR": "Panthers", "NO": "Saints", "TB": "Buccaneers",
    "ARI": "Cardinals", "LAR": "Rams", "SF": "49ers", "SEA": "Seahawks",
}


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


def compute_display_confidence(games, existing):
    """Confidence value to show for every game this week, whether picked
    yet or not -- always a full 1..len(games) permutation. Games with an
    already-stored confidence (existing[game_id]['confidence']) keep it;
    everything else gets whatever numbers are left over, largest first, in
    `games`' order (kickoff order, same as the table). Doesn't write
    anything -- callers persist by way of the normal picks/confidence
    submit paths, at which point a real team pick exists for the row."""
    n = len(games)
    used = {
        r["confidence"] for r in existing.values()
        if r["confidence"] is not None and 1 <= r["confidence"] <= n
    }
    remaining = [v for v in range(n, 0, -1) if v not in used]
    result = {}
    it = iter(remaining)
    for g in games:
        row = existing.get(g["game_id"])
        if row is not None and row["confidence"] is not None and row["confidence"] in used:
            result[g["game_id"]] = row["confidence"]
        else:
            result[g["game_id"]] = next(it)
    return result


def reorder_confidence(conn, user_id, season, week, game_id, new_confidence):
    """Sets one game's confidence for this user, shifting every other
    already-picked game for the same week to keep a valid 1..n_games
    permutation -- the standard "move to rank N, close the gap" reorder:
    moving a pick to a HIGHER number shifts everything strictly above its
    old spot and at-or-below the new one DOWN by one; moving it to a LOWER
    number shifts everything at-or-above the new spot and below the old
    one UP by one. Only touches games the user has already picked a team
    for (confidence can't be stored without a picked_team row to attach
    to -- schema requires it) -- a not-yet-picked game's displayed
    confidence is just recomputed fresh next render, see
    compute_display_confidence. No-ops if game_id has no existing pick."""
    n_games = conn.execute(
        "SELECT count(*) FROM pickem_games WHERE season = ? AND week = ?", (season, week)
    ).fetchone()[0]
    new_confidence = max(1, min(n_games, new_confidence))

    current = conn.execute(
        """SELECT game_id, confidence FROM pickem_picks
           WHERE user_id = ? AND game_id IN
               (SELECT game_id FROM pickem_games WHERE season = ? AND week = ?)""",
        (user_id, season, week),
    ).fetchall()
    by_game = {r["game_id"]: r["confidence"] for r in current}

    if game_id not in by_game:
        return  # no team picked for this game yet -- nothing to reorder

    old_confidence = by_game[game_id] or new_confidence
    if old_confidence == new_confidence:
        conn.execute(
            "UPDATE pickem_picks SET confidence = ? WHERE user_id = ? AND game_id = ?",
            (new_confidence, user_id, game_id),
        )
        conn.commit()
        return

    for other_id, conf in by_game.items():
        if other_id == game_id or conf is None:
            continue
        if new_confidence > old_confidence and old_confidence < conf <= new_confidence:
            conn.execute(
                "UPDATE pickem_picks SET confidence = ? WHERE user_id = ? AND game_id = ?",
                (conf - 1, user_id, other_id),
            )
        elif new_confidence < old_confidence and new_confidence <= conf < old_confidence:
            conn.execute(
                "UPDATE pickem_picks SET confidence = ? WHERE user_id = ? AND game_id = ?",
                (conf + 1, user_id, other_id),
            )
    conn.execute(
        "UPDATE pickem_picks SET confidence = ? WHERE user_id = ? AND game_id = ?",
        (new_confidence, user_id, game_id),
    )
    conn.commit()


def is_locked(game):
    """True once a game has started (or finished) -- picks for it can no
    longer be made or changed. kickoff_at has no timezone info (nfldata
    gives local kickoff time, assumed ET), compared against the server's
    local clock -- approximate by a few hours depending on server timezone,
    good enough to block picking after a game's already well underway."""
    if game["is_final"]:
        return True
    if not game["kickoff_at"]:
        return False
    try:
        kickoff = datetime.fromisoformat(game["kickoff_at"])
    except ValueError:
        return False
    return datetime.now() >= kickoff


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
