"""Group mode routes -- shared-screen, host-run live sessions. See
app/group_games.py (reveal-style trivia) and app/group_draft.py (live
Fantasy Draft) for the actual game logic."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import fantasy_draft, group_draft, group_games, trivia
from app.auth import require_tier
from app.common import db_missing_response
from app.db import get_connection, get_duckdb_connection
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("games"))])

REVEAL_CATEGORIES = {"award_winners": trivia.AWARD_CATEGORIES, "season_leaders": trivia.SEASON_CATEGORIES}


def _draft_context(session, turn, picks, standings, year_min, year_max, error):
    turn_participant, open_slots = turn if turn else (None, None)
    return {
        "session": session, "turn": turn, "turn_participant": turn_participant, "open_slots": open_slots,
        "picks": picks, "standings": standings, "year_min": year_min, "year_max": year_max, "error": error,
    }


@router.get("/games/group", response_class=HTMLResponse)
def group_hub(request: Request):
    user = request.state.user
    try:
        conn = get_connection()
        duckdb_conn = get_duckdb_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        reveal_sessions = group_games.active_sessions(conn, user["user_id"])
        draft_sessions = group_draft.active_sessions(conn, user["user_id"])
        top100_years = trivia.available_top100_years(duckdb_conn)
    finally:
        conn.close()
        duckdb_conn.close()

    return templates.TemplateResponse(
        request, "games_group.html",
        {
            "reveal_sessions": reveal_sessions, "draft_sessions": draft_sessions,
            "game_labels": group_games.GAME_LABELS, "reveal_categories": REVEAL_CATEGORIES,
            "top100_years": top100_years,
        },
    )


@router.post("/games/group/new")
async def new_session(request: Request):
    user = request.state.user
    form = await request.form()
    game_type = form.get("game_type")
    names = [n.strip() for n in form.get("participants", "").split(",") if n.strip()]

    if len(names) < 2:
        return RedirectResponse("/games/group", status_code=303)

    try:
        conn = get_connection()
        duckdb_conn = get_duckdb_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        if game_type == "fantasy_draft":
            session_id = group_draft.start_session(conn, user["user_id"], names)
            dest = f"/games/group/draft/{session_id}"
        elif game_type in REVEAL_CATEGORIES or game_type == "nfl_top100":
            category = form.get("category")
            valid_category = (
                category in REVEAL_CATEGORIES.get(game_type, [])
                or (game_type == "nfl_top100" and (category or "").isdigit())
            )
            if not valid_category:
                return RedirectResponse("/games/group", status_code=303)
            session_id = group_games.start_session(conn, duckdb_conn, user["user_id"], game_type, category, names)
            if session_id is None:
                return RedirectResponse("/games/group", status_code=303)
            dest = f"/games/group/session/{session_id}"
        else:
            return RedirectResponse("/games/group", status_code=303)
    finally:
        conn.close()
        duckdb_conn.close()

    return RedirectResponse(dest, status_code=303)


@router.get("/games/group/session/{session_id}", response_class=HTMLResponse)
def reveal_session_page(request: Request, session_id: int):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        session = group_games.get_session(conn, session_id, user["user_id"])
        if session is None:
            conn.close()
            return RedirectResponse("/games/group", status_code=303)
        participants = group_games.get_participants(conn, session_id)
        item = group_games.current_item(conn, session_id)
        standings = group_games.standings(conn, session_id)
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "group_session.html",
        {
            "session": session, "participants": participants, "item": item, "standings": standings,
            "game_label": group_games.GAME_LABELS.get(session["game_type"]),
        },
    )


@router.post("/games/group/session/{session_id}/reveal")
async def reveal_item(request: Request, session_id: int):
    user = request.state.user
    form = await request.form()
    item_key = form.get("item_key")

    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        session = group_games.get_session(conn, session_id, user["user_id"])
        if session is not None and item_key:
            correct_ids = {int(v) for k, v in form.items() if k.startswith("correct_")}
            group_games.mark_and_reveal(conn, session_id, item_key, correct_ids)
    finally:
        conn.close()
    return RedirectResponse(f"/games/group/session/{session_id}", status_code=303)


@router.get("/games/group/draft/{session_id}", response_class=HTMLResponse)
def draft_session_page(request: Request, session_id: int):
    user = request.state.user
    try:
        conn = get_connection()
        duckdb_conn = get_duckdb_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        session = group_draft.get_session(conn, session_id, user["user_id"])
        if session is None:
            return RedirectResponse("/games/group", status_code=303)
        turn = group_draft.whose_turn(conn, session_id)
        picks = group_draft.get_picks(conn, session_id)
        standings = group_draft.standings(conn, session_id)
        year_min, year_max = fantasy_draft.year_range(duckdb_conn)
    finally:
        conn.close()
        duckdb_conn.close()

    return templates.TemplateResponse(
        request, "group_draft.html", _draft_context(session, turn, picks, standings, year_min, year_max, None),
    )


@router.post("/games/group/draft/{session_id}/pick")
async def make_draft_pick(request: Request, session_id: int, slot: str = Form(...),
                           year: str = Form(...), player: str = Form(...)):
    user = request.state.user
    try:
        conn = get_connection()
        duckdb_conn = get_duckdb_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        session = group_draft.get_session(conn, session_id, user["user_id"])
        if session is None:
            return RedirectResponse("/games/group", status_code=303)
        error = group_draft.make_pick(conn, duckdb_conn, session_id, slot, year, player)
        if error:
            turn = group_draft.whose_turn(conn, session_id)
            picks = group_draft.get_picks(conn, session_id)
            standings = group_draft.standings(conn, session_id)
            year_min, year_max = fantasy_draft.year_range(duckdb_conn)
            return templates.TemplateResponse(
                request, "group_draft.html",
                _draft_context(session, turn, picks, standings, year_min, year_max, error),
            )
    finally:
        conn.close()
        duckdb_conn.close()

    return RedirectResponse(f"/games/group/draft/{session_id}", status_code=303)
