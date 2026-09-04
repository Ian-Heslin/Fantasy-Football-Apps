"""Pokemon Draft League: draft pool management + the live draft room. See
app/pokemon_draft/{draft_pool,draft}.py for the underlying logic."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import require_tier
from app.common import db_missing_response
from app.db import get_connection
from app.pokemon_draft import draft as pk_draft
from app.pokemon_draft import draft_pool as pk_pool
from app.pokemon_draft import pokedex as pk_pokedex
from app.pokemon_draft import roster as pk_roster
from app.pokemon_draft import seasons as pk_seasons
from app.pokemon_draft.permissions import require_commissioner
from app.templating import templates

router = APIRouter(prefix="/pokemon", dependencies=[Depends(require_tier("games"))])


# ---------------------------------------------------------------------
# Pool management
# ---------------------------------------------------------------------

@router.get("/seasons/{season_id}/pool", response_class=HTMLResponse)
def pool_page(request: Request, season_id: int):
    query = request.query_params.get("q") or None
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        season = pk_seasons.get_season(conn, season_id)
        if season is None:
            return RedirectResponse("/pokemon/seasons", status_code=303)
        is_commissioner = user["tier"] == "admin" or user["user_id"] == season["commissioner_user_id"]
        pool = pk_pool.list_pool(conn, season_id)
        search_results = pk_pokedex.search(conn, query=query)[0] if query else []
        generations = pk_pokedex.generations(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "pokemon/pool.html",
        {
            "season": season, "is_commissioner": is_commissioner, "pool": pool,
            "query": query or "", "search_results": search_results, "generations": generations,
            "error": None,
        },
    )


@router.post("/seasons/{season_id}/pool/add", dependencies=[Depends(require_commissioner)])
async def add_to_pool(request: Request, season_id: int):
    form = await request.form()
    pokemon_id = form.get("pokemon_id")
    cost = form.get("cost")
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        pk_pool.add_to_pool(
            conn, season_id, int(pokemon_id), int(cost) if cost else None)
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}/pool", status_code=303)


@router.post("/seasons/{season_id}/pool/add-generation", dependencies=[Depends(require_commissioner)])
async def add_generation(request: Request, season_id: int):
    form = await request.form()
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        pk_pool.add_generation_to_pool(
            conn, season_id, int(form.get("generation")), int(form.get("default_cost", 1) or 1))
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}/pool", status_code=303)


@router.post("/seasons/{season_id}/pool/{pokemon_id}/ban", dependencies=[Depends(require_commissioner)])
async def set_ban(request: Request, season_id: int, pokemon_id: int):
    form = await request.form()
    banned = form.get("banned") == "1"
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        pk_pool.set_ban(conn, season_id, pokemon_id, banned)
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}/pool", status_code=303)


@router.post("/seasons/{season_id}/pool/{pokemon_id}/cost", dependencies=[Depends(require_commissioner)])
def set_cost(request: Request, season_id: int, pokemon_id: int, cost: int = Form(...)):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        pk_pool.set_cost_override(conn, season_id, pokemon_id, cost)
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}/pool", status_code=303)


@router.post("/seasons/{season_id}/pool/{pokemon_id}/remove", dependencies=[Depends(require_commissioner)])
def remove_from_pool(request: Request, season_id: int, pokemon_id: int):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        pk_pool.remove_from_pool(conn, season_id, pokemon_id)
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}/pool", status_code=303)


@router.post("/seasons/{season_id}/lock", dependencies=[Depends(require_commissioner)])
def lock_draft_board(request: Request, season_id: int):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        pk_seasons.lock_draft_board(conn, season_id)
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}/pool", status_code=303)


@router.post("/seasons/{season_id}/draft/start", dependencies=[Depends(require_commissioner)])
def start_draft(request: Request, season_id: int):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        pk_draft.start_draft(conn, season_id)
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}/draft", status_code=303)


# ---------------------------------------------------------------------
# The live draft room
# ---------------------------------------------------------------------

@router.get("/seasons/{season_id}/draft", response_class=HTMLResponse)
def draft_room(request: Request, season_id: int):
    user = request.state.user
    query = request.query_params.get("q") or None
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        season = pk_seasons.get_season(conn, season_id)
        if season is None:
            return RedirectResponse("/pokemon/seasons", status_code=303)
        session = pk_draft.get_session(conn, season_id)
        turn = pk_draft.whose_turn(conn, season_id)
        my_seat = pk_seasons.coach_seat_for(conn, season_id, user["user_id"])
        is_my_turn = turn is not None and turn["coach"]["user_id"] == user["user_id"]
        available = pk_pool.undrafted(conn, season_id, query=query) if turn is not None else []
        turn_roster_count = turn_roster_spent = None
        if turn is not None:
            turn_roster_count, turn_roster_spent = pk_roster.roster_summary(
                conn, season_id, turn["coach"]["coach_id"])
        picks = pk_draft.board(conn, season_id)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "pokemon/draft_room.html",
        {
            "season": season, "session": session, "turn": turn, "my_seat": my_seat,
            "is_my_turn": is_my_turn, "available": available, "query": query or "",
            "turn_roster_count": turn_roster_count, "turn_roster_spent": turn_roster_spent,
            "picks": picks, "error": request.query_params.get("error"),
        },
    )


@router.post("/seasons/{season_id}/draft/pick")
def make_pick(request: Request, season_id: int, pokemon_id: int = Form(...)):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        error = pk_draft.make_pick(conn, season_id, user["user_id"], pokemon_id)
    finally:
        conn.close()
    if error:
        from urllib.parse import quote
        return RedirectResponse(f"/pokemon/seasons/{season_id}/draft?error={quote(error)}", status_code=303)
    return RedirectResponse(f"/pokemon/seasons/{season_id}/draft", status_code=303)
