"""Accounts, sessions, and tier-based access control.

Three tiers, strictly nested (see schema/sqlite_schema.sql's users table
comment): 'games' < 'fantasy' < 'admin'. A page requires a *minimum* tier
via require_tier() as a router-level dependency -- see app/routes/*.py's
`router = APIRouter(dependencies=[Depends(require_tier("fantasy"))])`.

load_current_user runs as a global app dependency (see main.py) on every
request, logged in or not, so request.state.user is always populated (to
a dict, or None) before any route-specific auth check runs. It also
resolves request.state.colors (see app/team_colors.py) from that same
user, since every page's <head> needs it regardless of tier.
"""
import bcrypt
from fastapi import Depends, Request

from app import team_colors
from app.db import get_connection

TIER_RANK = {"games": 1, "fantasy": 2, "admin": 3}


class NotAuthenticated(Exception):
    """Raised by require_tier when there's no logged-in user -- handled in
    main.py by redirecting to /login."""


class Forbidden(Exception):
    """Raised by require_tier when the logged-in user's tier is too low --
    handled in main.py by rendering a 403 page."""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def load_current_user(request: Request) -> None:
    """Populates request.state.user from the session cookie. Doesn't
    reject anything -- that's require_tier's job -- so this can run
    unconditionally for every request, including /login and /signup
    themselves (which need to know "already logged in?" too)."""
    user_id = request.session.get("user_id")
    request.state.user = None
    if user_id:
        try:
            conn = get_connection()
        except FileNotFoundError:
            conn = None
        if conn is not None:
            try:
                row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            finally:
                conn.close()
            request.state.user = dict(row) if row else None

    request.state.colors = team_colors.resolve(request.state.user)


def require_tier(min_tier: str):
    """Router-level dependency: Depends(require_tier("fantasy")) rejects
    anyone not logged in (-> /login) or below that tier (-> 403), and
    hands back the user dict for routes that want to know who's logged in
    without a second request.state.user lookup."""
    def dependency(request: Request):
        user = request.state.user
        if user is None:
            raise NotAuthenticated()
        if TIER_RANK[user["tier"]] < TIER_RANK[min_tier]:
            raise Forbidden()
        return user
    return dependency


CurrentUser = Depends(require_tier("games"))
