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
import re
import secrets
import threading
import time
from collections import defaultdict, deque

import bcrypt
from fastapi import Depends, Request

from app import team_colors
from app.db import get_connection

TIER_RANK = {"games": 1, "fantasy": 2, "admin": 3}

# Signup rules. There's no password-reset flow on this site, so the floor
# is a real minimum rather than a nudge -- but it's a length floor only,
# no character-class rules, which push people toward "Password1!" and
# away from the long passphrase that actually helps.
MIN_PASSWORD_LENGTH = 12
# bcrypt hashes at most the first 72 BYTES and ignores the rest, so
# anything past that is security theatre; reject it plainly instead of
# silently truncating (and note bytes, not characters -- a passphrase
# with emoji or accents hits 72 sooner than it looks).
MAX_PASSWORD_BYTES = 72
MIN_USERNAME_LENGTH = 2
MAX_USERNAME_LENGTH = 32
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

# A bcrypt hash of a value nobody can enter, used to spend the same ~100ms
# verifying a login for a username that doesn't exist as for one that
# does -- otherwise the response time says which usernames are real.
_DUMMY_HASH = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt()).decode()


def validate_username(username):
    """None if the username is acceptable, else the reason it isn't."""
    if not MIN_USERNAME_LENGTH <= len(username) <= MAX_USERNAME_LENGTH:
        return (f"Usernames need to be {MIN_USERNAME_LENGTH}-{MAX_USERNAME_LENGTH} "
                "characters long.")
    if not USERNAME_RE.match(username):
        return "Usernames can use letters, numbers, dots, dashes and underscores."
    return None


def validate_password(password):
    """None if the password is acceptable, else the reason it isn't."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Passwords need to be at least {MIN_PASSWORD_LENGTH} characters long."
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        return f"Passwords can be at most {MAX_PASSWORD_BYTES} bytes long."
    return None


class NotAuthenticated(Exception):
    """Raised by require_tier when there's no logged-in user -- handled in
    main.py by redirecting to /login."""


class Forbidden(Exception):
    """Raised by require_tier when the logged-in user's tier is too low --
    handled in main.py by rendering a 403 page."""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        # Malformed/truncated hash in the DB -- treat as a failed login
        # rather than a 500, so one bad row can't take out the login page.
        return False


def verify_password_or_dummy(password: str, password_hash) -> bool:
    """Same as verify_password, but when there's no such user (hash is
    None) it still runs a real bcrypt check against a throwaway hash and
    returns False. Without that, "no such user" returns in microseconds
    while a real username takes ~100ms, which quietly tells an attacker
    which usernames exist."""
    if password_hash is None:
        bcrypt.checkpw(password.encode(), _DUMMY_HASH.encode())
        return False
    return verify_password(password, password_hash)


# ---------------------------------------------------------------------
# Login throttle
# ---------------------------------------------------------------------
# Deliberately in-process and per-username rather than per-IP: everyone
# arrives through the Cloudflare tunnel, so without --proxy-headers every
# request looks like it came from the same address and a per-IP limit
# would lock out the whole site at once. Per-username can't do that -- at
# worst one account is briefly unloggable, which is also exactly what
# you want while someone is guessing at it.
#
# State lives in memory, so a restart clears it. That's an accepted
# limit: it costs an attacker a restart's worth of waiting and it keeps
# the login path from needing a write to app.db on every failed attempt.
MAX_FAILED_LOGINS = 8
LOGIN_WINDOW_SECONDS = 15 * 60

_login_failures = defaultdict(deque)
_login_lock = threading.Lock()


def _prune(attempts, now):
    while attempts and attempts[0] <= now - LOGIN_WINDOW_SECONDS:
        attempts.popleft()


def login_is_throttled(username: str) -> bool:
    now = time.monotonic()
    with _login_lock:
        attempts = _login_failures[username]
        _prune(attempts, now)
        return len(attempts) >= MAX_FAILED_LOGINS


def record_login_failure(username: str) -> None:
    now = time.monotonic()
    with _login_lock:
        attempts = _login_failures[username]
        _prune(attempts, now)
        attempts.append(now)


def clear_login_failures(username: str) -> None:
    with _login_lock:
        _login_failures.pop(username, None)


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
