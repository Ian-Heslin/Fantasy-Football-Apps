from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.common import SIGNAL_LABELS, db_missing_response
from app.db import get_connection
from app.templating import templates

router = APIRouter()


@router.get("/rosters", response_class=HTMLResponse)
def rosters_index(request: Request):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        leagues = conn.execute(
            "SELECT league_id, name, season, format, status, my_roster_id "
            "FROM leagues ORDER BY name"
        ).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "rosters_index.html", {"leagues": leagues}
    )


@router.get("/rosters/{league_id}", response_class=HTMLResponse)
def roster_detail(request: Request, league_id: str):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        league = conn.execute(
            "SELECT league_id, name, season, format, status, my_roster_id "
            "FROM leagues WHERE league_id = ?",
            (league_id,),
        ).fetchone()
        if league is None:
            conn.close()
            return templates.TemplateResponse(
                request, "roster_detail.html",
                {"league": None, "roster_id": None, "players": []},
                status_code=404,
            )

        roster_id = league["my_roster_id"]
        if roster_id is None:
            row = conn.execute(
                "SELECT roster_id FROM rosters WHERE league_id = ? AND is_mine = 1",
                (league_id,),
            ).fetchone()
            roster_id = row["roster_id"] if row else None

        players = []
        if roster_id is not None:
            arb_format = "sf" if league["format"] == "SF" else "1qb"
            value_col = "value_2qb" if league["format"] == "SF" else "value_1qb"
            players = conn.execute(
                f"""
                SELECT
                    p.player_id, p.name, p.position, p.team,
                    tv.value_1qb, tv.value_2qb,
                    asig.gap, asig.signal
                FROM roster_players rp
                JOIN players p ON p.player_id = rp.player_id
                LEFT JOIN (
                    SELECT player_id, value_1qb, value_2qb,
                           ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY value_date DESC) rn
                    FROM trade_values WHERE is_pick = 0
                ) tv ON tv.player_id = p.player_id AND tv.rn = 1
                LEFT JOIN (
                    SELECT player_id, format, gap, signal,
                           ROW_NUMBER() OVER (PARTITION BY player_id, format ORDER BY as_of_date DESC) rn
                    FROM arbitrage_signals
                ) asig ON asig.player_id = p.player_id AND asig.format = ? AND asig.rn = 1
                WHERE rp.league_id = ? AND rp.roster_id = ? AND rp.as_of_date = (
                    SELECT max(as_of_date) FROM roster_players
                    WHERE league_id = ? AND roster_id = ?
                )
                ORDER BY {value_col} DESC
                """,
                (arb_format, league_id, roster_id, league_id, roster_id),
            ).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "roster_detail.html",
        {
            "league": league, "roster_id": roster_id,
            "players": players, "signal_labels": SIGNAL_LABELS,
        },
    )
