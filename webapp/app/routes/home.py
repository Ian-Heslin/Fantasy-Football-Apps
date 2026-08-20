from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.common import db_missing_response
from app.db import get_connection
from app.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
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
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "home.html", {"sync_log": sync_log, "stats": stats}
    )
