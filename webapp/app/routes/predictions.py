from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.common import POSITIONS, db_missing_response
from app.db import get_connection
from app.templating import templates

router = APIRouter()


@router.get("/predictions", response_class=HTMLResponse)
def predictions(request: Request, model: str = "breakout", season: Optional[int] = None,
                 position: Optional[str] = None):
    if model not in ("breakout", "bounceback"):
        model = "breakout"

    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        seasons = [r[0] for r in conn.execute(
            "SELECT DISTINCT season FROM model_predictions WHERE model_name = ? ORDER BY season DESC",
            (model,),
        ).fetchall()]
        selected_season = season if season in seasons else (seasons[0] if seasons else None)

        query = """
            SELECT mp.player_id, mp.season, mp.predicted_probability, mp.actual_outcome,
                   p.name, p.position, p.team
            FROM model_predictions mp
            LEFT JOIN players p ON p.player_id = mp.player_id
            WHERE mp.model_name = ?
        """
        params = [model]
        if selected_season is not None:
            query += " AND mp.season = ?"
            params.append(selected_season)
        if position in POSITIONS:
            query += " AND p.position = ?"
            params.append(position)
        query += " ORDER BY mp.predicted_probability DESC"

        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "predictions.html",
        {
            "model": model, "rows": rows,
            "seasons": seasons, "selected_season": selected_season,
            "positions": POSITIONS, "selected_position": position,
        },
    )
