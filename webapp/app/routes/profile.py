"""Link a site account to "my team" on Sleeper/ESPN -- see users.
sleeper_owner_id/espn_owner_id in schema/sqlite_schema.sql. Available
choices are just whatever owner_ids have already shown up in `rosters`
(from load_sleeper.py/load_espn.py) -- there's no live lookup here, you're
picking "which of these teams I already see is mine."

Also handles the Team Colors feature's favorite_team/team_colors_enabled
(see app/team_colors.py) -- both the full picker on /profile and the
quick top-bar toggle+select every page's nav renders (POST /preferences/
team-colors, which redirects back to wherever it was submitted from)."""
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import team_colors
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
        {
            "sleeper_options": sleeper_options, "espn_options": espn_options, "saved": False,
            "teams": team_colors.TEAMS,
        },
    )


@router.post("/profile", response_class=HTMLResponse)
def profile_update(request: Request, sleeper_owner_id: Optional[str] = Form(None),
                     espn_owner_id: Optional[str] = Form(None),
                     favorite_team: Optional[str] = Form(None),
                     team_colors_enabled: bool = Form(False)):
    user = request.state.user
    if favorite_team and favorite_team not in team_colors.TEAMS_BY_ID:
        favorite_team = None

    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        conn.execute(
            """UPDATE users SET sleeper_owner_id = ?, espn_owner_id = ?,
                   favorite_team = ?, team_colors_enabled = ? WHERE user_id = ?""",
            (sleeper_owner_id or None, espn_owner_id or None,
             favorite_team, int(team_colors_enabled), user["user_id"]),
        )
        conn.commit()
        sleeper_options = _owner_options(conn, "sleeper")
        espn_options = _owner_options(conn, "espn")
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "profile.html",
        {
            "sleeper_options": sleeper_options, "espn_options": espn_options, "saved": True,
            "teams": team_colors.TEAMS,
        },
    )


@router.post("/preferences/team-colors")
def update_team_colors_quick(request: Request, next: str = Form("/"),
                               favorite_team: Optional[str] = Form(None),
                               team_colors_enabled: bool = Form(False)):
    """The top-bar toggle+picker every page's nav renders -- same fields
    as /profile's form, but redirects back to wherever it was submitted
    from instead of always landing on /profile."""
    user = request.state.user
    if favorite_team and favorite_team not in team_colors.TEAMS_BY_ID:
        favorite_team = None

    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        conn.execute(
            "UPDATE users SET favorite_team = ?, team_colors_enabled = ? WHERE user_id = ?",
            (favorite_team, int(team_colors_enabled), user["user_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    safe_next = next if next.startswith("/") else "/"
    return RedirectResponse(safe_next, status_code=303)
