"""Link a site account to "my team" on Sleeper/ESPN -- see users.
sleeper_owner_id/espn_owner_id in schema/sqlite_schema.sql. Available
choices are just whatever owner_ids have already shown up in `rosters`
(from load_sleeper.py/load_espn.py) -- there's no live lookup here, you're
picking "which of these teams I already see is mine."""
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import require_tier
from app.common import db_missing_response
from app.db import get_connection
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("games"))])


def _owner_options(conn, platform):
    return conn.execute(
        """SELECT DISTINCT r.owner_id, r.owner_name
           FROM rosters r JOIN leagues l ON l.league_id = r.league_id
           WHERE l.platform = ? AND r.owner_id IS NOT NULL
           ORDER BY r.owner_name""",
        (platform,),
    ).fetchall()


@router.get("/profile", response_class=HTMLResponse)
def profile(request: Request):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        sleeper_options = _owner_options(conn, "sleeper")
        espn_options = _owner_options(conn, "espn")
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "profile.html",
        {"sleeper_options": sleeper_options, "espn_options": espn_options, "saved": False},
    )


@router.post("/profile", response_class=HTMLResponse)
def profile_update(request: Request, sleeper_owner_id: Optional[str] = Form(None),
                     espn_owner_id: Optional[str] = Form(None)):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        conn.execute(
            "UPDATE users SET sleeper_owner_id = ?, espn_owner_id = ? WHERE user_id = ?",
            (sleeper_owner_id or None, espn_owner_id or None, user["user_id"]),
        )
        conn.commit()
        sleeper_options = _owner_options(conn, "sleeper")
        espn_options = _owner_options(conn, "espn")
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "profile.html",
        {"sleeper_options": sleeper_options, "espn_options": espn_options, "saved": True},
    )
