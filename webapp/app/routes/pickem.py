"""NFL Pick'em -- the first real game in the /games area. Replaces the
earlier in-memory mockup (branch claude/nfl-pickem-mockup-qk4abr) with
real persistence (pickem_games/pickem_picks/pickem_settings in app.db)
and real data (schedule/spreads/scores from
scripts/load_pickem_schedule.py). "Picking as" is now just whoever's
logged in -- no more friend dropdown."""
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import pickem
from app.auth import require_tier
from app.common import db_missing_response
from app.db import get_connection
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("games"))])


@router.get("/games", response_class=HTMLResponse)
def games_index(request: Request):
    return templates.TemplateResponse(request, "games_index.html", {})


@router.get("/games/pickem", response_class=HTMLResponse)
def pickem_home(request: Request):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        season = pickem.current_season(conn)
        if season is None:
            conn.close()
            return templates.TemplateResponse(request, "pickem_index.html", {"season": None})

        week = pickem.current_week(conn, season)
        games = conn.execute(
            "SELECT * FROM pickem_games WHERE season = ? AND week = ? ORDER BY kickoff_at",
            (season, week),
        ).fetchall()
        settings = pickem.get_settings(conn)
        season_standings = pickem.standings(conn, season)
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "pickem_index.html",
        {
            "season": season, "week": week, "games": games, "settings": settings,
            "standings": season_standings[:5], "team_names": pickem.TEAM_NAMES,
        },
    )


@router.post("/games/pickem/settings")
def update_settings(request: Request, pick_mode: str = Form(...),
                     confidence_enabled: bool = Form(False),
                     admin_user=Depends(require_tier("admin"))):
    # Admin-only -- this is a shared, league-wide setting, not a per-user
    # preference, so letting any games-tier user flip it would change
    # everyone's scoring at once.
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        pickem.save_settings(conn, pick_mode if pick_mode in ("straight_up", "spread") else "straight_up",
                              confidence_enabled)
    finally:
        conn.close()
    return RedirectResponse("/games/pickem", status_code=303)


@router.get("/games/pickem/picks", response_class=HTMLResponse)
def picks_form(request: Request, week: Optional[int] = None):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        season = pickem.current_season(conn)
        if season is None:
            conn.close()
            return templates.TemplateResponse(request, "pickem_picks.html", {"season": None})

        week = week or pickem.current_week(conn, season)
        games = conn.execute(
            "SELECT * FROM pickem_games WHERE season = ? AND week = ? ORDER BY kickoff_at",
            (season, week),
        ).fetchall()
        existing_rows = conn.execute(
            """SELECT * FROM pickem_picks WHERE user_id = ? AND game_id IN
               (SELECT game_id FROM pickem_games WHERE season = ? AND week = ?)""",
            (user["user_id"], season, week),
        ).fetchall()
        existing = {r["game_id"]: r for r in existing_rows}
        settings = pickem.get_settings(conn)
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "pickem_picks.html",
        {
            "season": season, "week": week, "games": games, "existing": existing,
            "settings": settings, "team_names": pickem.TEAM_NAMES,
            "n_games": len(games), "is_locked": pickem.is_locked,
            "favorite_team": pickem.favorite_team,
            "saved": request.query_params.get("saved") == "1",
        },
    )


@router.post("/games/pickem/picks")
async def submit_picks(request: Request):
    user = request.state.user
    form = await request.form()
    season = int(form.get("season"))
    week = int(form.get("week"))

    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        games = conn.execute(
            "SELECT * FROM pickem_games WHERE season = ? AND week = ?", (season, week)
        ).fetchall()
        for g in games:
            if pickem.is_locked(g):
                continue  # already started/final -- server-side lock, not just UI
            team = form.get(f"pick_{g['game_id']}")
            if not team or team not in (g["home_team"], g["away_team"]):
                continue
            confidence = form.get(f"confidence_{g['game_id']}")
            conn.execute(
                """INSERT INTO pickem_picks (user_id, game_id, picked_team, confidence, submitted_at)
                   VALUES (?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(user_id, game_id) DO UPDATE SET
                       picked_team=excluded.picked_team, confidence=excluded.confidence,
                       submitted_at=datetime('now')""",
                (user["user_id"], g["game_id"], team, int(confidence) if confidence else None),
            )
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(f"/games/pickem/picks?week={week}&saved=1", status_code=303)


@router.get("/games/pickem/standings", response_class=HTMLResponse)
def standings_page(request: Request):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        season = pickem.current_season(conn)
        if season is None:
            conn.close()
            return templates.TemplateResponse(request, "pickem_standings.html", {"season": None})

        settings = pickem.get_settings(conn)
        season_standings = pickem.standings(conn, season)
        weeks = [
            {"num": w, "results": pickem.standings(conn, season, week=w)}
            for w in pickem.weeks_with_results(conn, season)
        ]
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "pickem_standings.html",
        {"season": season, "settings": settings, "standings": season_standings, "weeks": weeks},
    )
