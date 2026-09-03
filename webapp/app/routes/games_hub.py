"""The Solo and Daily tabs' hub pages, plus the Daily Stat Pad game
itself. Leagues (/games, in routes/pickem.py) and Group (routes/group.py)
live in their own modules; this one's just small enough to share.
"""
import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import daily_challenge, trivia
from app.auth import require_tier
from app.common import db_missing_response
from app.db import close_all, open_both
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("games"))])


@router.get("/games/solo", response_class=HTMLResponse)
def solo_hub(request: Request):
    return templates.TemplateResponse(request, "games_solo.html", {})


@router.get("/games/daily", response_class=HTMLResponse)
def daily_hub(request: Request):
    user = request.state.user
    try:
        conn, duckdb_conn = open_both()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        latest_season, latest_week = trivia.latest_week(duckdb_conn)
        weekly_category = trivia.weekly_category(latest_season, latest_week) if latest_season else None
        weekly_board = trivia.leaderboard(conn, "weekly_leaders", weekly_category)[:5] if weekly_category else []

        today = datetime.date.today()
        category = daily_challenge.todays_category(today)
        year_min, year_max = daily_challenge.MIN_YEAR, duckdb_conn.execute(
            "SELECT max(season) FROM player_season_fantasy_points"
        ).fetchone()[0]
        picks = daily_challenge.get_picks(conn, user["user_id"], today.isoformat())
        next_pick = daily_challenge.next_pick_num(conn, user["user_id"], today.isoformat())
        board = daily_challenge.leaderboard(conn, today.isoformat())
    finally:
        close_all(conn, duckdb_conn)

    return templates.TemplateResponse(
        request, "games_daily.html",
        {
            "weekly_category": weekly_category, "weekly_board": weekly_board,
            "today": today.isoformat(), "category": category,
            "pick_count": daily_challenge.PICK_COUNT, "year_min": year_min, "year_max": year_max,
            "picks": picks, "next_pick": next_pick, "board": board, "error": None,
        },
    )


@router.post("/games/daily/stat-pad")
async def submit_stat_pad(request: Request):
    user = request.state.user
    form = await request.form()
    today = datetime.date.today()
    try:
        conn, duckdb_conn = open_both()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        category = daily_challenge.todays_category(today)
        pick_num = int(form.get("pick_num"))
        error = daily_challenge.save_one_pick(
            conn, duckdb_conn, user["user_id"], today.isoformat(), category,
            pick_num, form.get("year"), form.get("player"),
        )
        if error is None:
            return RedirectResponse("/games/daily", status_code=303)

        latest_season, latest_week = trivia.latest_week(duckdb_conn)
        weekly_category = trivia.weekly_category(latest_season, latest_week) if latest_season else None
        weekly_board = trivia.leaderboard(conn, "weekly_leaders", weekly_category)[:5] if weekly_category else []
        year_min, year_max = daily_challenge.MIN_YEAR, duckdb_conn.execute(
            "SELECT max(season) FROM player_season_fantasy_points"
        ).fetchone()[0]
        picks = daily_challenge.get_picks(conn, user["user_id"], today.isoformat())
        board = daily_challenge.leaderboard(conn, today.isoformat())
    finally:
        close_all(conn, duckdb_conn)

    return templates.TemplateResponse(
        request, "games_daily.html",
        {
            "weekly_category": weekly_category, "weekly_board": weekly_board,
            "today": today.isoformat(), "category": category,
            "pick_count": daily_challenge.PICK_COUNT, "year_min": year_min, "year_max": year_max,
            "picks": picks, "next_pick": pick_num, "board": board, "error": error,
        },
    )
