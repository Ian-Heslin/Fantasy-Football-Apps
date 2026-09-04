"""Keeper predictions + mock-draft routes -- see app/keepers.py for the
round-shift/collision logic, best-available ranking, and all DB access;
these stay thin (parse the request, call into keepers.py, render)."""
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import keepers
from app.auth import require_tier
from app.common import db_missing_response
from app.db import get_connection
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("fantasy"))])


def _load_league(conn, league_id):
    return conn.execute(
        "SELECT league_id, platform, name, season, format, status, my_roster_id "
        "FROM leagues WHERE league_id = ?",
        (league_id,),
    ).fetchone()


def _teams(conn, league_id):
    return conn.execute(
        "SELECT roster_id, owner_name, is_mine FROM rosters WHERE league_id = ? ORDER BY owner_name",
        (league_id,),
    ).fetchall()


def _arb_format(league):
    return "sf" if league["format"] == "SF" else "1qb"


@router.get("/rosters/{league_id}/keepers", response_class=HTMLResponse)
def keepers_index(request: Request, league_id: str):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        league = _load_league(conn, league_id)
        if league is None:
            return templates.TemplateResponse(
                request, "keepers.html",
                {"league": None, "draft_season": None, "keeper_season": None,
                 "teams": [], "eligible": {}, "predictions": {}, "max_keepers": keepers.MAX_KEEPERS},
                status_code=404,
            )

        draft_season = keepers.last_draft_season(conn, league_id)
        keeper_season = league["season"]
        teams = _teams(conn, league_id)
        eligible = keepers.keeper_eligible_players(conn, league_id, draft_season) if draft_season else {}
        predictions = keepers.get_keeper_predictions(conn, user["user_id"], league_id, keeper_season)
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "keepers.html",
        {
            "league": league, "draft_season": draft_season, "keeper_season": keeper_season,
            "teams": teams, "eligible": eligible, "predictions": predictions,
            "max_keepers": keepers.MAX_KEEPERS,
        },
    )


@router.post("/rosters/{league_id}/keepers")
def save_keepers(request: Request, league_id: str, roster_id: str = Form(...),
                  player_ids: List[str] = Form([])):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        league = _load_league(conn, league_id)
        if league is not None:
            keeper_season = league["season"]
            draft_season = keepers.last_draft_season(conn, league_id)

            keepers.save_keeper_predictions(
                conn, user["user_id"], league_id, keeper_season, roster_id, player_ids
            )
            if draft_season:
                board = keepers.compute_keeper_board(
                    conn, league_id, draft_season, keeper_season, user["user_id"]
                )
                keepers.reconcile_mock_draft(conn, user["user_id"], league_id, keeper_season, board)
    finally:
        conn.close()

    return RedirectResponse(f"/rosters/{league_id}/keepers", status_code=303)


def _build_grid(board, existing):
    """{(round, roster_id): {'name','position','team','source','conflict'}}
    -- keeper cells (computed live) take precedence; anything else comes
    from this user's saved manual/auto picks."""
    grid = {}
    for roster_id, team_keepers in board.items():
        for k in team_keepers:
            grid[(k["keeper_round"], roster_id)] = {
                "name": k["name"], "position": k["position"], "team": k["team"],
                "source": "keeper", "conflict": k["conflict"],
            }
    for (round_num, roster_id), pick in existing.items():
        key = (round_num, roster_id)
        if key not in grid:
            grid[key] = {
                "name": pick["name"], "position": pick["position"], "team": pick["team"],
                "source": pick["source"], "conflict": False,
            }
    return grid


@router.get("/rosters/{league_id}/mock-draft", response_class=HTMLResponse)
def mock_draft(request: Request, league_id: str):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        league = _load_league(conn, league_id)
        if league is None:
            return templates.TemplateResponse(
                request, "mock_draft.html",
                {"league": None, "rounds": 0, "round_range": [], "teams": [], "grid": {}},
                status_code=404,
            )

        draft_season = keepers.last_draft_season(conn, league_id)
        keeper_season = league["season"]
        teams = _teams(conn, league_id)

        rounds, grid = 0, {}
        if draft_season:
            rounds = keepers.num_rounds(conn, league_id, draft_season)
            board = keepers.compute_keeper_board(
                conn, league_id, draft_season, keeper_season, user["user_id"]
            )
            existing = keepers.get_mock_draft_picks(conn, user["user_id"], league_id, keeper_season)
            grid = _build_grid(board, existing)
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "mock_draft.html",
        {
            "league": league, "draft_season": draft_season, "keeper_season": keeper_season,
            "rounds": rounds, "round_range": range(1, rounds + 1), "teams": teams, "grid": grid,
            "error": request.query_params.get("error"),
        },
    )


@router.post("/rosters/{league_id}/mock-draft/pick")
def make_pick(request: Request, league_id: str, round: int = Form(...), roster_id: str = Form(...),
              player_name: str = Form(...)):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        league = _load_league(conn, league_id)
        draft_season = keepers.last_draft_season(conn, league_id) if league else None
        error = None
        if league is None or not draft_season:
            error = "No draft history loaded for this league yet."
        else:
            keeper_season = league["season"]
            board = keepers.compute_keeper_board(
                conn, league_id, draft_season, keeper_season, user["user_id"]
            )
            existing = keepers.get_mock_draft_picks(conn, user["user_id"], league_id, keeper_season)
            error = keepers.record_pick_by_name(
                conn, user["user_id"], league_id, keeper_season, round, roster_id,
                _arb_format(league), player_name, board, existing,
            )
    finally:
        conn.close()

    if error:
        return RedirectResponse(f"/rosters/{league_id}/mock-draft?error={quote(error)}", status_code=303)
    return RedirectResponse(f"/rosters/{league_id}/mock-draft", status_code=303)


@router.post("/rosters/{league_id}/mock-draft/clear")
def clear_pick(request: Request, league_id: str, round: int = Form(...), roster_id: str = Form(...)):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        league = _load_league(conn, league_id)
        if league is not None:
            keepers.clear_mock_draft_pick(conn, user["user_id"], league_id, league["season"], round, roster_id)
    finally:
        conn.close()
    return RedirectResponse(f"/rosters/{league_id}/mock-draft", status_code=303)


@router.post("/rosters/{league_id}/mock-draft/auto-fill")
def auto_fill(request: Request, league_id: str):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        league = _load_league(conn, league_id)
        draft_season = keepers.last_draft_season(conn, league_id) if league else None
        if league is not None and draft_season:
            keeper_season = league["season"]
            teams = _teams(conn, league_id)
            rounds = keepers.num_rounds(conn, league_id, draft_season)
            board = keepers.compute_keeper_board(
                conn, league_id, draft_season, keeper_season, user["user_id"]
            )
            existing = keepers.get_mock_draft_picks(conn, user["user_id"], league_id, keeper_season)
            keepers.auto_fill(
                conn, user["user_id"], league_id, keeper_season, rounds,
                [t["roster_id"] for t in teams], _arb_format(league), board, existing,
            )
    finally:
        conn.close()
    return RedirectResponse(f"/rosters/{league_id}/mock-draft", status_code=303)


@router.post("/rosters/{league_id}/mock-draft/reset")
def reset(request: Request, league_id: str):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        league = _load_league(conn, league_id)
        if league is not None:
            keepers.reset_mock_draft(conn, user["user_id"], league_id, league["season"])
    finally:
        conn.close()
    return RedirectResponse(f"/rosters/{league_id}/mock-draft", status_code=303)
