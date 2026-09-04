"""Season-scoped commissioner permission, layered on top of the site's
tier system (see app/auth.py) rather than a new tier -- see
schema/sqlite_schema.sql's pokemon_seasons.commissioner_user_id comment.

Routes get this the same way they get require_tier: as a per-route
Depends(require_commissioner) on top of the router-level
Depends(require_tier("games")) every pokemon_draft router already has.
"""
from fastapi import HTTPException, Request

from app.auth import Forbidden
from app.db import get_connection
from app.pokemon_draft import seasons


def require_commissioner(season_id: int, request: Request):
    """FastAPI resolves season_id from the path parameter of the same
    name. Site admin tier also acts as a cross-season override -- an
    escape hatch if a commissioner goes AWOL mid-dispute."""
    user = request.state.user
    conn = get_connection()
    try:
        season = seasons.get_season(conn, season_id)
    finally:
        conn.close()
    if season is None:
        raise HTTPException(status_code=404)
    if user["tier"] == "admin":
        return user
    if user["user_id"] != season["commissioner_user_id"]:
        raise Forbidden()
    return user
