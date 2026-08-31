"""Admin-only: promote/demote user tiers. See auth.py's TIER_RANK and
schema/sqlite_schema.sql's users table comment for the bootstrap problem
this doesn't solve -- the very first admin has to be promoted by hand
(scripts/promote_user.py) since there's no admin yet to use this page."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import TIER_RANK, require_tier
from app.common import db_missing_response
from app.db import get_connection
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("admin"))])

TIERS = list(TIER_RANK.keys())


@router.get("/admin/users", response_class=HTMLResponse)
def list_users(request: Request):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        users = conn.execute(
            "SELECT user_id, username, tier, sleeper_owner_id, espn_owner_id, created_at "
            "FROM users ORDER BY username"
        ).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "admin_users.html", {"users": users, "tiers": TIERS},
    )


@router.post("/admin/users/{user_id}/tier")
def update_tier(request: Request, user_id: int, tier: str = Form(...)):
    if tier not in TIER_RANK:
        return RedirectResponse("/admin/users", status_code=303)

    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        conn.execute("UPDATE users SET tier = ? WHERE user_id = ?", (tier, user_id))
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse("/admin/users", status_code=303)
