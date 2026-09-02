"""Award Winners / Season Leaders trivia routes -- see app/trivia.py's
module docstring for the async-play design (not the original spreadsheet's
live shared-session format)."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import trivia
from app.auth import require_tier
from app.common import db_missing_response
from app.db import get_connection, get_duckdb_connection
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("games"))])

GAME_LABELS = {
    "award_winners": "Award Winners", "season_leaders": "Season Leaders",
    "weekly_leaders": "Weekly Top Scorers", "nfl_top100": "NFL Top 100",
}
CATEGORIES = {"award_winners": trivia.AWARD_CATEGORIES, "season_leaders": trivia.SEASON_CATEGORIES}


@router.get("/games/trivia", response_class=HTMLResponse)
def trivia_index(request: Request):
    try:
        conn = get_connection()
        duckdb_conn = get_duckdb_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        boards = {
            game_type: {cat: trivia.leaderboard(conn, game_type, cat)[:5] for cat in cats}
            for game_type, cats in CATEGORIES.items()
        }
        latest_season, latest_week = trivia.latest_week(duckdb_conn)
        weekly_category = trivia.weekly_category(latest_season, latest_week) if latest_season else None
        weekly_board = trivia.leaderboard(conn, "weekly_leaders", weekly_category)[:5] if weekly_category else []
        top100_years = trivia.available_top100_years(duckdb_conn)
        top100_boards = {year: trivia.leaderboard(conn, "nfl_top100", str(year))[:5] for year in top100_years}
    finally:
        conn.close()
        duckdb_conn.close()

    return templates.TemplateResponse(
        request, "trivia_index.html",
        {
            "game_labels": GAME_LABELS, "categories": CATEGORIES, "boards": boards,
            "latest_season": latest_season, "latest_week": latest_week,
            "weekly_category": weekly_category, "weekly_board": weekly_board,
            "top100_years": top100_years, "top100_boards": top100_boards,
        },
    )


@router.post("/games/trivia/start")
def start_round(request: Request, game_type: str = Form(...), category: str = Form(...)):
    user = request.state.user
    valid = (
        (game_type in CATEGORIES and category in CATEGORIES[game_type])
        or game_type == "weekly_leaders"
        or (game_type == "nfl_top100" and category.isdigit())
    )
    if not valid:
        return RedirectResponse("/games/trivia", status_code=303)

    try:
        sqlite_conn = get_connection()
        duckdb_conn = get_duckdb_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        round_id = trivia.start_round(sqlite_conn, duckdb_conn, user["user_id"], game_type, category)
    finally:
        sqlite_conn.close()
        duckdb_conn.close()

    if round_id is None:
        return RedirectResponse("/games/trivia", status_code=303)
    return RedirectResponse(f"/games/trivia/round/{round_id}", status_code=303)


@router.get("/games/trivia/round/{round_id}", response_class=HTMLResponse)
def round_page(request: Request, round_id: int):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        round_row, items = trivia.get_round(conn, round_id, user["user_id"])
    finally:
        conn.close()

    if round_row is None:
        return RedirectResponse("/games/trivia", status_code=303)

    return templates.TemplateResponse(
        request, "trivia_round.html",
        {
            "round": round_row, "items": items, "game_label": GAME_LABELS.get(round_row["game_type"]),
            "completed": round_row["completed_at"] is not None,
        },
    )


@router.post("/games/trivia/round/{round_id}")
async def submit_round(request: Request, round_id: int):
    user = request.state.user
    form = await request.form()
    guesses = {
        key[len("guess_"):]: value for key, value in form.items() if key.startswith("guess_")
    }
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        trivia.submit_round(conn, round_id, user["user_id"], guesses)
    finally:
        conn.close()
    return RedirectResponse(f"/games/trivia/round/{round_id}", status_code=303)
