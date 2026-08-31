from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.auth import require_tier
from app.common import POSITIONS, SIGNAL_LABELS, db_missing_response
from app.db import get_connection
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("fantasy"))])

SIGNALS = ["BUY_LOW", "SELL_HIGH", "FAIR"]


@router.get("/arbitrage", response_class=HTMLResponse)
def arbitrage_board(request: Request, format: str = "1qb", signal: Optional[str] = None,
                      position: Optional[str] = None):
    if format not in ("1qb", "sf"):
        format = "1qb"

    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        as_of_date = conn.execute(
            "SELECT max(as_of_date) FROM arbitrage_signals WHERE format = ?", (format,)
        ).fetchone()[0]

        query = """
            SELECT s.player_id, s.dynasty_percentile, s.redraft_percentile, s.gap, s.signal,
                   p.name, p.position, p.team
            FROM arbitrage_signals s
            LEFT JOIN players p ON p.player_id = s.player_id
            WHERE s.format = ? AND s.as_of_date = ?
        """
        params = [format, as_of_date]
        if signal in SIGNALS:
            query += " AND s.signal = ?"
            params.append(signal)
        if position in POSITIONS:
            query += " AND p.position = ?"
            params.append(position)
        query += " ORDER BY s.gap DESC"

        rows = conn.execute(query, params).fetchall() if as_of_date else []
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "arbitrage.html",
        {
            "rows": rows, "as_of_date": as_of_date, "format": format,
            "signal": signal, "signals": SIGNALS, "signal_labels": SIGNAL_LABELS,
            "positions": POSITIONS, "selected_position": position,
        },
    )
