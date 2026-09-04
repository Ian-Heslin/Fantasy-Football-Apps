"""Award Winners / Season Leaders trivia routes -- see app/trivia.py's
module docstring for the async-play design (not the original spreadsheet's
live shared-session format)."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import trivia
from app.auth import require_tier
from app.common import db_missing_response
from app.db import close_all, get_connection, open_both
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
        conn, duckdb_conn = open_both()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        boards = {
            game_type: {cat: trivia.leaderboard(conn, game_type, cat)[:5] for cat in cats}
            for game_type, cats in CATEGORIES.items()
        }
        top100_years = trivia.available_top100_years(duckdb_conn)
        top100_boards = {year: trivia.leaderboard(conn, "nfl_top100", str(year))[:5] for year in top100_years}
    finally:
        close_all(conn, duckdb_conn)

    return templates.TemplateResponse(
        request, "trivia_index.html",
        {
            "game_labels": GAME_LABELS, "categories": CATEGORIES, "boards": boards,
            "top100_years": top100_years, "top100_boards": top100_boards,
            "top100_hint_labels": trivia.TOP100_HINT_LABELS,
        },
    )


@router.post("/games/trivia/start")
async def start_round(request: Request, game_type: str = Form(...), category: str = Form(...)):
    user = request.state.user
    # One shared validator (see trivia.is_valid_category) rather than a
    # per-route expression -- the Group entry point had drifted from this
    # one, and both let categories through that later raised.
    if not trivia.is_valid_category(game_type, category):
        return RedirectResponse("/games/trivia", status_code=303)

    hints = None
    if game_type == "nfl_top100":
        form = await request.form()
        hints = set(form.getlist("hint")) & set(trivia.TOP100_HINT_LABELS)

    try:
        sqlite_conn, duckdb_conn = open_both()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        round_id = trivia.start_round(sqlite_conn, duckdb_conn, user["user_id"], game_type, category, hints)
    finally:
        close_all(sqlite_conn, duckdb_conn)

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
            "round": round_row, "answered": [i for i in items if i["guess"] is not None],
            "current_item": trivia.current_item(items), "game_label": GAME_LABELS.get(round_row["game_type"]),
            "completed": round_row["completed_at"] is not None,
        },
    )


@router.post("/games/trivia/round/{round_id}/guess")
async def submit_guess(request: Request, round_id: int, item_key: str = Form(...), guess: str = Form("")):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        trivia.submit_guess(conn, round_id, user["user_id"], item_key, guess)
    finally:
        conn.close()
    return RedirectResponse(f"/games/trivia/round/{round_id}", status_code=303)
