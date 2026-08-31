from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.auth import require_tier
from app.common import db_missing_response
from app.db import duckdb_rows, get_duckdb_connection
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("fantasy"))])

TEAM_SEASON_COLUMNS = """
    t.season, t.team, t.games, t.ppg, t.yards_per_game, t.epa_per_play,
    t.epa_rank, t.ppg_rank, t.ypg_rank,
    q.primary_qb_name,
    (SELECT coach_name FROM coach_table c
     WHERE c.season = t.season AND c.team = t.team AND c.role = 'HC'
     ORDER BY coach_name LIMIT 1) AS head_coach,
    v.win_total_line, v.actual_wins
"""


@router.get("/teams", response_class=HTMLResponse)
def teams_index(request: Request, season: Optional[int] = None):
    try:
        conn = get_duckdb_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        seasons = [r[0] for r in conn.execute(
            "SELECT DISTINCT season FROM team_offense_season ORDER BY season DESC"
        ).fetchall()]
        selected_season = season if season in seasons else (seasons[0] if seasons else None)

        rows = []
        if selected_season is not None:
            rows = duckdb_rows(conn.execute(f"""
                SELECT {TEAM_SEASON_COLUMNS}
                FROM team_offense_season t
                LEFT JOIN team_primary_qb q ON q.season = t.season AND q.team = t.team
                LEFT JOIN vegas_odds v ON v.season = t.season AND v.team = t.team
                WHERE t.season = ?
                ORDER BY t.epa_rank
            """, [selected_season]))
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "teams_index.html",
        {"rows": rows, "seasons": seasons, "selected_season": selected_season},
    )


@router.get("/teams/{team}", response_class=HTMLResponse)
def team_detail(request: Request, team: str):
    try:
        conn = get_duckdb_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        rows = duckdb_rows(conn.execute(f"""
            SELECT {TEAM_SEASON_COLUMNS}
            FROM team_offense_season t
            LEFT JOIN team_primary_qb q ON q.season = t.season AND q.team = t.team
            LEFT JOIN vegas_odds v ON v.season = t.season AND v.team = t.team
            WHERE t.team = ?
            ORDER BY t.season DESC
        """, [team.upper()]))
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "team_detail.html", {"team": team.upper(), "rows": rows},
        status_code=200 if rows else 404,
    )
