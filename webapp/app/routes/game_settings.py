"""Game Settings routes -- a per-user difficulty filter for 501/Imposter's
randomized picks. See app/game_settings.py."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import game_settings
from app.auth import require_tier
from app.common import db_missing_response
from app.db import get_connection, get_duckdb_connection
from app.stat_categories import STAT_CATEGORIES, available_years
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("games"))])


@router.get("/games/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    user = request.state.user
    try:
        conn = get_connection()
        duckdb_conn = get_duckdb_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        settings = game_settings.get_settings(conn, user["user_id"])
        all_ranges = [available_years(duckdb_conn, key) for key in STAT_CATEGORIES]
        year_min = min(lo for lo, hi in all_ranges)
        year_max = max(hi for lo, hi in all_ranges)
    finally:
        conn.close()
        duckdb_conn.close()

    return templates.TemplateResponse(
        request, "games_settings.html",
        {
            "settings": settings, "categories": STAT_CATEGORIES,
            "enabled": game_settings.allowed_categories(settings),
            "year_min": year_min, "year_max": year_max,
        },
    )


@router.post("/games/settings")
async def save_settings(request: Request):
    user = request.state.user
    form = await request.form()
    min_year = form.get("min_year")
    max_year = form.get("max_year")
    enabled = form.getlist("category")
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        game_settings.save_settings(
            conn, user["user_id"],
            int(min_year) if min_year else None, int(max_year) if max_year else None, enabled,
        )
    finally:
        conn.close()
    return RedirectResponse("/games/settings", status_code=303)
