from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.common import db_missing_response
from app.db import duckdb_rows, get_duckdb_connection
from app.templating import templates

router = APIRouter()


MIN_SEASON_OPTIONS = [1, 3, 6]
DEFAULT_MIN_SEASONS = 3


@router.get("/coaches", response_class=HTMLResponse)
def coaches_index(request: Request, min_seasons: int = DEFAULT_MIN_SEASONS):
    if min_seasons not in MIN_SEASON_OPTIONS:
        min_seasons = DEFAULT_MIN_SEASONS

    try:
        conn = get_duckdb_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        # HC/OC only -- these are the roles with actual play-calling
        # responsibility, so "average offense quality under this coach"
        # means something (see docs/breakout-falloff-methodology.md's
        # v14 combined-identity caveat re: defensive-minded HCs).
        # min_seasons defaults to 3 rather than showing everyone: a coach
        # with 1 season can only ever land at the very top or bottom of
        # this list, which is exactly the small-sample noise the page's
        # own caption warns about -- see the doc's v18 section, which
        # uses a >=6-season threshold for its own "consistent" ranking.
        rows = duckdb_rows(conn.execute("""
            SELECT
                c.coach_name,
                count(DISTINCT c.season || '-' || c.team) AS n_seasons,
                avg(t.epa_per_play_pctile) AS avg_epa_pctile,
                min(c.season) AS first_season,
                max(c.season) AS last_season
            FROM coach_table c
            JOIN team_offense_season t ON t.season = c.season AND t.team = c.team
            WHERE c.role IN ('HC', 'OC')
            GROUP BY c.coach_name
            HAVING count(DISTINCT c.season || '-' || c.team) >= ?
            ORDER BY avg_epa_pctile DESC
        """, [min_seasons]))
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "coaches_index.html",
        {"rows": rows, "min_seasons": min_seasons, "min_season_options": MIN_SEASON_OPTIONS},
    )


@router.get("/coaches/{coach_name}", response_class=HTMLResponse)
def coach_detail(request: Request, coach_name: str):
    try:
        conn = get_duckdb_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        rows = duckdb_rows(conn.execute("""
            SELECT c.season, c.team, c.role, t.ppg, t.epa_per_play,
                   t.epa_rank, t.epa_per_play_pctile
            FROM coach_table c
            LEFT JOIN team_offense_season t ON t.season = c.season AND t.team = c.team
            WHERE c.coach_name = ?
            ORDER BY c.season, c.role
        """, [coach_name]))
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "coach_detail.html", {"coach_name": coach_name, "rows": rows},
        status_code=200 if rows else 404,
    )
