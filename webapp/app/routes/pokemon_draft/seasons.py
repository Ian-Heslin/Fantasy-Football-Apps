"""Pokemon Draft League: season/format/coach management routes. See
app/pokemon_draft/seasons.py for the underlying logic -- routes here stay
thin (parse the request, open/close a connection, call into that module,
render a template), same shape as every other route file in this app."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import require_tier
from app.common import db_missing_response
from app.db import get_connection
from app.pokemon_draft import seasons as pk_seasons
from app.pokemon_draft.permissions import require_commissioner
from app.templating import templates

router = APIRouter(prefix="/pokemon", dependencies=[Depends(require_tier("games"))])


def _viewer_context(conn, season_id, user):
    """is_commissioner/my_seat -- computed the same way on every page that
    shows a season, so a commissioner always sees their admin controls and
    a coach always sees their own seat highlighted."""
    season = pk_seasons.get_season(conn, season_id)
    if season is None:
        return None, None, None
    is_commissioner = user["tier"] == "admin" or user["user_id"] == season["commissioner_user_id"]
    my_seat = pk_seasons.coach_seat_for(conn, season_id, user["user_id"])
    return season, is_commissioner, my_seat


@router.get("", response_class=HTMLResponse)
def hub(request: Request):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        active = pk_seasons.active_season(conn)
    finally:
        conn.close()
    if active is not None:
        return RedirectResponse(f"/pokemon/seasons/{active['season_id']}", status_code=303)
    return RedirectResponse("/pokemon/seasons", status_code=303)


@router.get("/seasons", response_class=HTMLResponse)
def season_list(request: Request):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        all_seasons = pk_seasons.list_seasons(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "pokemon/seasons_list.html", {"seasons": all_seasons})


@router.get("/seasons/new", response_class=HTMLResponse)
def new_season_form(request: Request):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        formats = pk_seasons.list_formats(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "pokemon/season_new.html", {"formats": formats, "error": None})


@router.post("/seasons")
def create_season(request: Request, name: str = Form(...), format_id: str = Form(...)):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        season_id, error = pk_seasons.create_season(conn, name, format_id, user["user_id"])
        if error:
            formats = pk_seasons.list_formats(conn)
            return templates.TemplateResponse(
                request, "pokemon/season_new.html",
                {"formats": formats, "error": error}, status_code=400)
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}", status_code=303)


@router.get("/seasons/{season_id}", response_class=HTMLResponse)
def season_detail(request: Request, season_id: int):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        season, is_commissioner, my_seat = _viewer_context(conn, season_id, request.state.user)
        if season is None:
            return RedirectResponse("/pokemon/seasons", status_code=303)
        coaches = pk_seasons.list_coaches(conn, season_id)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "pokemon/season_detail.html",
        {"season": season, "coaches": coaches, "is_commissioner": is_commissioner,
         "my_seat": my_seat, "coach_error": None},
    )


@router.post("/seasons/{season_id}/ruleset", dependencies=[Depends(require_commissioner)])
async def edit_ruleset(request: Request, season_id: int):
    form = await request.form()

    def to_int(key, default=None):
        v = form.get(key)
        return int(v) if v not in (None, "") else default

    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        pk_seasons.update_ruleset(
            conn, season_id,
            to_int("roster_size_cap"), to_int("point_budget"),
            "species_clause_enabled" in form,
            to_int("fa_transactions_allowed", 0),
            to_int("roster_freeze_week"),
            to_int("playoff_bracket_size", 4),
        )
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}", status_code=303)


@router.post("/seasons/{season_id}/activate", dependencies=[Depends(require_commissioner)])
def activate(request: Request, season_id: int):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        pk_seasons.activate_season(conn, season_id)
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}", status_code=303)


@router.post("/seasons/{season_id}/archive", dependencies=[Depends(require_commissioner)])
def archive(request: Request, season_id: int):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        pk_seasons.archive_season(conn, season_id)
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}", status_code=303)


@router.post("/seasons/{season_id}/coaches", dependencies=[Depends(require_commissioner)])
def add_coach(request: Request, season_id: int, username: str = Form(...), team_name: str = Form(...)):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        target = conn.execute(
            "SELECT user_id FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
        error = ("No account with that username." if target is None else
                 pk_seasons.add_coach(conn, season_id, target["user_id"], team_name))
        if error:
            season, is_commissioner, my_seat = _viewer_context(conn, season_id, request.state.user)
            coaches = pk_seasons.list_coaches(conn, season_id)
            return templates.TemplateResponse(
                request, "pokemon/season_detail.html",
                {"season": season, "coaches": coaches, "is_commissioner": is_commissioner,
                 "my_seat": my_seat, "coach_error": error},
                status_code=400,
            )
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}", status_code=303)


@router.post("/seasons/{season_id}/coaches/{coach_id}/delete", dependencies=[Depends(require_commissioner)])
def remove_coach(request: Request, season_id: int, coach_id: int):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        pk_seasons.remove_coach(conn, season_id, coach_id)
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}", status_code=303)


@router.post("/seasons/{season_id}/coaches/order", dependencies=[Depends(require_commissioner)])
async def set_draft_order(request: Request, season_id: int):
    # No JS drag-and-drop in this app -- the form instead has one "position"
    # dropdown (1..N) per coach; this sorts coach_ids by chosen position
    # rather than relying on submission order.
    form = await request.form()
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        coaches = pk_seasons.list_coaches(conn, season_id)
        positioned = []
        for i, c in enumerate(coaches):
            raw = form.get(f"position_{c['coach_id']}")
            position = int(raw) if raw else i + 1
            positioned.append((position, i, c["coach_id"]))
        positioned.sort()
        pk_seasons.set_draft_order(conn, season_id, [coach_id for _, _, coach_id in positioned])
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}", status_code=303)


@router.get("/formats/new", response_class=HTMLResponse)
def new_format_form(request: Request):
    return templates.TemplateResponse(request, "pokemon/format_new.html", {"error": None})


@router.post("/formats")
async def create_format(request: Request):
    form = await request.form()

    def to_int(key, default):
        v = form.get(key)
        return int(v) if v not in (None, "") else default

    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        error = pk_seasons.create_format(
            conn, form.get("format_id", ""), form.get("display_name", ""),
            form.get("battle_style", ""), form.get("rules_text", ""),
            to_int("default_roster_size", 10), to_int("default_point_budget", 100),
            "default_species_clause" in form,
        )
        if error:
            return templates.TemplateResponse(
                request, "pokemon/format_new.html", {"error": error}, status_code=400)
    finally:
        conn.close()
    return RedirectResponse("/pokemon/seasons/new", status_code=303)
