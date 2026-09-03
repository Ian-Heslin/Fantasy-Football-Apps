"""Imposter routes -- see app/imposter.py for the game logic."""
import random

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import game_settings, imposter
from app.auth import require_tier
from app.common import db_missing_response
from app.db import get_connection, get_duckdb_connection
from app.stat_categories import STAT_CATEGORIES, available_years
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("games"))])


@router.get("/games/imposter", response_class=HTMLResponse)
def hub(request: Request):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        active_rounds = conn.execute(
            "SELECT * FROM imposter_rounds WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC",
            (user["user_id"],),
        ).fetchall()
        settings = game_settings.get_settings(conn, user["user_id"])
        allowed = game_settings.allowed_categories(settings)
        categories = {k: v for k, v in STAT_CATEGORIES.items() if k in allowed}
        boards = {key: imposter.leaderboard(conn, key)[:5] for key in categories}
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "games_imposter.html",
        {
            "categories": categories, "all_categories": STAT_CATEGORIES,
            "active_rounds": active_rounds, "boards": boards,
        },
    )


@router.post("/games/imposter/start")
def start(request: Request, category: str = Form("")):
    user = request.state.user
    try:
        conn = get_connection()
        duckdb_conn = get_duckdb_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        settings = game_settings.get_settings(conn, user["user_id"])
        if category not in STAT_CATEGORIES:
            category = random.choice(list(game_settings.allowed_categories(settings)))
        year_min, year_max = available_years(duckdb_conn, category)
        if year_min is None:
            return RedirectResponse("/games/imposter", status_code=303)
        year_min, year_max = game_settings.clamp_year_range(settings, year_min, year_max)
        year = random.randint(year_min, year_max)
        round_id = imposter.start_round(conn, duckdb_conn, user["user_id"], category, year)
        if round_id is None:
            return RedirectResponse("/games/imposter", status_code=303)
    finally:
        conn.close()
        duckdb_conn.close()
    return RedirectResponse(f"/games/imposter/round/{round_id}", status_code=303)


@router.get("/games/imposter/round/{round_id}", response_class=HTMLResponse)
def round_page(request: Request, round_id: int):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        round_row = imposter.get_round(conn, round_id, user["user_id"])
        if round_row is None:
            return RedirectResponse("/games/imposter", status_code=303)
        names = imposter.get_names(conn, round_id)
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "imposter_round.html",
        {
            "round": round_row, "names": names,
            "category_label": STAT_CATEGORIES[round_row["category"]]["label"],
        },
    )


@router.post("/games/imposter/round/{round_id}/click")
def click(request: Request, round_id: int, name: str = Form(...)):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        round_row = imposter.get_round(conn, round_id, user["user_id"])
        if round_row is not None:
            imposter.click_name(conn, round_id, name)
    finally:
        conn.close()
    return RedirectResponse(f"/games/imposter/round/{round_id}", status_code=303)
