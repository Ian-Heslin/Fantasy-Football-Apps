"""Fantasy Draft routes -- see app/fantasy_draft.py's module docstring."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import fantasy_draft
from app.auth import require_tier
from app.common import db_missing_response
from app.db import close_all, open_both
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("games"))])


@router.get("/games/fantasy-draft", response_class=HTMLResponse)
def draft_home(request: Request):
    user = request.state.user
    try:
        conn, duckdb_conn = open_both()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        entries = fantasy_draft.get_entries(conn, user["user_id"])
        total_points = sum(e["points"] or 0 for e in entries.values())
        board = fantasy_draft.leaderboard(conn)
        year_min, year_max = fantasy_draft.year_range(duckdb_conn)
    finally:
        close_all(conn, duckdb_conn)

    return templates.TemplateResponse(
        request, "fantasy_draft.html",
        {
            "slots": fantasy_draft.SLOTS, "slot_positions": fantasy_draft.SLOT_POSITIONS,
            "entries": entries, "total_points": total_points, "board": board,
            "year_min": year_min, "year_max": year_max, "errors": {},
            "saved": request.query_params.get("saved") == "1",
        },
    )


@router.post("/games/fantasy-draft")
async def save_draft(request: Request):
    user = request.state.user
    form = await request.form()
    try:
        conn, duckdb_conn = open_both()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        errors = fantasy_draft.save_picks(conn, duckdb_conn, user["user_id"], form)
        if errors:
            entries = fantasy_draft.get_entries(conn, user["user_id"])
            total_points = sum(e["points"] or 0 for e in entries.values())
            board = fantasy_draft.leaderboard(conn)
            year_min, year_max = fantasy_draft.year_range(duckdb_conn)
            return templates.TemplateResponse(
                request, "fantasy_draft.html",
                {
                    "slots": fantasy_draft.SLOTS, "slot_positions": fantasy_draft.SLOT_POSITIONS,
                    "entries": entries, "total_points": total_points, "board": board,
                    "year_min": year_min, "year_max": year_max, "errors": errors, "saved": False,
                },
            )
    finally:
        close_all(conn, duckdb_conn)

    return RedirectResponse("/games/fantasy-draft?saved=1", status_code=303)
