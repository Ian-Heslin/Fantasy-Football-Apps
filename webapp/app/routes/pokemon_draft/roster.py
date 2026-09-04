"""Pokemon Draft League: team roster, free agency, and trades. See
app/pokemon_draft/roster.py for the underlying logic."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import require_tier
from app.common import db_missing_response
from app.db import get_connection
from app.pokemon_draft import roster as pk_roster
from app.pokemon_draft import seasons as pk_seasons
from app.templating import templates

router = APIRouter(prefix="/pokemon", dependencies=[Depends(require_tier("games"))])


@router.get("/seasons/{season_id}/roster/{coach_id}", response_class=HTMLResponse)
def roster_detail(request: Request, season_id: int, coach_id: int):
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
        coaches = pk_seasons.list_coaches(conn, season_id)
        coach = next((c for c in coaches if c["coach_id"] == coach_id), None)
        if coach is None:
            return RedirectResponse(f"/pokemon/seasons/{season_id}", status_code=303)
        is_own_team = coach["user_id"] == user["user_id"]
        team_roster = pk_roster.current_roster(conn, season_id, coach_id)
        team_roster_display = pk_roster.current_roster_with_pokemon(conn, season_id, coach_id)
        cost_by_id = {r["pokemon_id"]: r["cost"] for r in team_roster}
        count, spent = pk_roster.roster_summary(conn, season_id, coach_id)
        fa_used = pk_roster.fa_transactions_used(conn, season_id, coach_id)
        fa_search = pk_roster.available_for_fa(conn, season_id, query=query) if (is_own_team and query) else []
        pending_trades = pk_roster.list_pending_trades(conn, season_id, coach_id)
        other_coaches = [c for c in coaches if c["coach_id"] != coach_id]
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "pokemon/roster_detail.html",
        {
            "season": season, "coach": coach, "is_own_team": is_own_team,
            "team_roster": team_roster_display, "cost_by_id": cost_by_id,
            "count": count, "spent": spent, "fa_used": fa_used, "query": query or "",
            "fa_search": fa_search, "pending_trades": pending_trades,
            "other_coaches": other_coaches, "error": request.query_params.get("error"),
        },
    )


@router.post("/seasons/{season_id}/roster/{coach_id}/fa-add")
def fa_add(request: Request, season_id: int, coach_id: int, pokemon_id: int = Form(...)):
    user = request.state.user
    dest = f"/pokemon/seasons/{season_id}/roster/{coach_id}"
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        coach = conn.execute(
            "SELECT user_id FROM pokemon_season_coaches WHERE coach_id = ? AND season_id = ?",
            (coach_id, season_id),
        ).fetchone()
        if coach is None or coach["user_id"] != user["user_id"]:
            error = "You can only manage your own roster."
        else:
            error = pk_roster.fa_add(conn, season_id, coach_id, pokemon_id)
    finally:
        conn.close()
    return RedirectResponse(f"{dest}?error={quote(error)}" if error else dest, status_code=303)


@router.post("/seasons/{season_id}/roster/{coach_id}/fa-drop")
def fa_drop(request: Request, season_id: int, coach_id: int, pokemon_id: int = Form(...)):
    user = request.state.user
    dest = f"/pokemon/seasons/{season_id}/roster/{coach_id}"
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        coach = conn.execute(
            "SELECT user_id FROM pokemon_season_coaches WHERE coach_id = ? AND season_id = ?",
            (coach_id, season_id),
        ).fetchone()
        if coach is None or coach["user_id"] != user["user_id"]:
            error = "You can only manage your own roster."
        else:
            error = pk_roster.fa_drop(conn, season_id, coach_id, pokemon_id)
    finally:
        conn.close()
    return RedirectResponse(f"{dest}?error={quote(error)}" if error else dest, status_code=303)


@router.get("/seasons/{season_id}/roster/{coach_id}/trade/new", response_class=HTMLResponse)
def trade_new(request: Request, season_id: int, coach_id: int):
    user = request.state.user
    with_coach_id = request.query_params.get("with_coach_id")
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        season = pk_seasons.get_season(conn, season_id)
        coach = pk_seasons.coach_seat_for(conn, season_id, user["user_id"])
        if season is None or coach is None or coach["coach_id"] != coach_id:
            return RedirectResponse(f"/pokemon/seasons/{season_id}", status_code=303)
        my_roster = pk_roster.current_roster_with_pokemon(conn, season_id, coach_id)
        other_coaches = [c for c in pk_seasons.list_coaches(conn, season_id) if c["coach_id"] != coach_id]
        their_roster, their_coach = [], None
        if with_coach_id:
            their_coach = next((c for c in other_coaches if c["coach_id"] == int(with_coach_id)), None)
            if their_coach is not None:
                their_roster = pk_roster.current_roster_with_pokemon(conn, season_id, their_coach["coach_id"])
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "pokemon/trade_new.html",
        {
            "season": season, "coach": coach, "my_roster": my_roster,
            "other_coaches": other_coaches, "their_coach": their_coach,
            "their_roster": their_roster, "error": None,
        },
    )


@router.post("/seasons/{season_id}/roster/{coach_id}/trade/new")
async def propose_trade(request: Request, season_id: int, coach_id: int):
    user = request.state.user
    form = await request.form()
    # "target_coach_id", not "their_coach_id" -- deliberately avoids the
    # "their_" prefix used below for per-Pokemon checkboxes, which would
    # otherwise swallow this field too and crash on int("coach_id").
    target_coach_id = form.get("target_coach_id")
    dest = f"/pokemon/seasons/{season_id}/roster/{coach_id}"
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        coach = pk_seasons.coach_seat_for(conn, season_id, user["user_id"])
        if coach is None or coach["coach_id"] != coach_id or not target_coach_id:
            error = "Invalid trade proposal."
        else:
            target_coach_id = int(target_coach_id)
            items = []
            for key, value in form.items():
                if key.startswith("my_") and value in ("trade", "drop"):
                    items.append({"pokemon_id": int(key[3:]), "from_coach_id": coach_id, "action": value})
                elif key.startswith("their_") and value == "1":
                    items.append({"pokemon_id": int(key[6:]), "from_coach_id": target_coach_id, "action": "trade"})
            _trade_id, error = pk_roster.propose_trade(conn, season_id, coach_id, target_coach_id, items)
    finally:
        conn.close()
    return RedirectResponse(f"{dest}?error={quote(error)}" if error else dest, status_code=303)


@router.post("/seasons/{season_id}/trades/{trade_id}/accept")
def accept_trade(request: Request, season_id: int, trade_id: int):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        error = pk_roster.accept_trade(conn, trade_id, user["user_id"])
        offer = conn.execute("SELECT receiving_coach_id FROM pokemon_trade_offers WHERE trade_id = ?",
                              (trade_id,)).fetchone()
    finally:
        conn.close()
    dest = f"/pokemon/seasons/{season_id}/roster/{offer['receiving_coach_id']}" if offer else f"/pokemon/seasons/{season_id}"
    return RedirectResponse(f"{dest}?error={quote(error)}" if error else dest, status_code=303)


@router.post("/seasons/{season_id}/trades/{trade_id}/respond")
def respond_to_trade(request: Request, season_id: int, trade_id: int):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        offer = conn.execute("SELECT proposing_coach_id FROM pokemon_trade_offers WHERE trade_id = ?",
                              (trade_id,)).fetchone()
        error = pk_roster.respond_to_trade(conn, trade_id, user["user_id"])
    finally:
        conn.close()
    dest = f"/pokemon/seasons/{season_id}/roster/{offer['proposing_coach_id']}" if offer else f"/pokemon/seasons/{season_id}"
    return RedirectResponse(f"{dest}?error={quote(error)}" if error else dest, status_code=303)
