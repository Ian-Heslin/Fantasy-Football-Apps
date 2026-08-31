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
