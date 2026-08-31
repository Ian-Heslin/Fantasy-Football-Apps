from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import require_tier
from app.common import db_missing_response
from app.db import get_connection
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("games"))])


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    # This dashboard is fantasy-flavored (data freshness for rosters/models);
    # games-tier-only users don't have anything to see here, so send them
    # straight to the section they actually have access to.
    if request.state.user["tier"] == "games":
        return RedirectResponse("/games", status_code=303)

    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        sync_log = conn.execute(
            "SELECT table_name, source, last_synced_at, row_count, notes "
            "FROM sync_log ORDER BY table_name"
        ).fetchall()
        stats = {
            "players": conn.execute("SELECT count(*) FROM players").fetchone()[0],
            "leagues": conn.execute("SELECT count(*) FROM leagues").fetchone()[0],
            "arbitrage_signals": conn.execute("SELECT count(*) FROM arbitrage_signals").fetchone()[0],
            "breakout_predictions": conn.execute(
                "SELECT count(*) FROM model_predictions WHERE model_name = 'breakout'"
            ).fetchone()[0],
            "bounceback_predictions": conn.execute(
                "SELECT count(*) FROM model_predictions WHERE model_name = 'bounceback'"
            ).fetchone()[0],
        }
        leagues = conn.execute(
            "SELECT league_id, platform, name, season, format, status FROM leagues ORDER BY name"
        ).fetchall()

        as_of_1qb = conn.execute(
            "SELECT max(as_of_date) FROM arbitrage_signals WHERE format = '1qb'"
        ).fetchone()[0]
        top_signals = conn.execute(
            """SELECT s.signal, s.gap, p.name, p.position, p.team
               FROM arbitrage_signals s JOIN players p ON p.player_id = s.player_id
               WHERE s.format = '1qb' AND s.as_of_date = ? AND s.signal != 'FAIR'
               ORDER BY abs(s.gap) DESC LIMIT 6""",
            (as_of_1qb,),
        ).fetchall() if as_of_1qb else []
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "home.html",
        {"sync_log": sync_log, "stats": stats, "leagues": leagues, "top_signals": top_signals},
    )
