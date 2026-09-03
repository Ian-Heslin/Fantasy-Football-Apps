"""501 routes -- see app/five_oh_one.py for the game logic."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import five_oh_one, game_settings
from app.auth import require_tier
from app.common import db_missing_response
from app.db import get_connection, get_duckdb_connection
from app.stat_categories import STAT_CATEGORIES
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("games"))])


@router.get("/games/501", response_class=HTMLResponse)
def hub(request: Request):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        active_games = conn.execute(
            "SELECT * FROM five_oh_one_games WHERE user_id = ? AND completed_at IS NULL ORDER BY created_at DESC",
            (user["user_id"],),
        ).fetchall()
        settings = game_settings.get_settings(conn, user["user_id"])
        allowed = game_settings.allowed_categories(settings)
        categories = {k: v for k, v in STAT_CATEGORIES.items() if k in allowed}
        boards = {key: five_oh_one.leaderboard(conn, key)[:5] for key in categories}
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "games_501.html",
        {
            "categories": categories, "all_categories": STAT_CATEGORIES,
            "active_games": active_games, "boards": boards,
        },
    )


@router.post("/games/501/start")
def start_game(request: Request, category: str = Form(...)):
    user = request.state.user
    if category not in STAT_CATEGORIES:
        return RedirectResponse("/games/501", status_code=303)
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        game_id = five_oh_one.start_game(conn, user["user_id"], category)
    finally:
        conn.close()
    return RedirectResponse(f"/games/501/game/{game_id}", status_code=303)


def _game_context(game, picks, error):
    remaining_slots = five_oh_one.PICK_COUNT - game["picks_made"]
    return {
        "game": game, "picks": picks, "error": error,
        "category_label": STAT_CATEGORIES[game["category"]]["label"],
        "completed": game["completed_at"] is not None, "remaining_slots": remaining_slots,
    }


@router.get("/games/501/game/{game_id}", response_class=HTMLResponse)
def game_page(request: Request, game_id: int):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        game = five_oh_one.get_game(conn, game_id, user["user_id"])
        if game is None:
            return RedirectResponse("/games/501", status_code=303)
        picks = five_oh_one.get_picks(conn, game_id)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "five_oh_one_game.html", _game_context(game, picks, None))


@router.post("/games/501/game/{game_id}/pick")
def make_pick(request: Request, game_id: int, year: str = Form(...), player: str = Form(...)):
    user = request.state.user
    try:
        conn = get_connection()
        duckdb_conn = get_duckdb_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        game = five_oh_one.get_game(conn, game_id, user["user_id"])
        if game is None:
            return RedirectResponse("/games/501", status_code=303)
        error = five_oh_one.make_pick(conn, duckdb_conn, game_id, year, player)
        if error:
            picks = five_oh_one.get_picks(conn, game_id)
            game = five_oh_one.get_game(conn, game_id, user["user_id"])
            return templates.TemplateResponse(request, "five_oh_one_game.html", _game_context(game, picks, error))
    finally:
        conn.close()
        duckdb_conn.close()
    return RedirectResponse(f"/games/501/game/{game_id}", status_code=303)
