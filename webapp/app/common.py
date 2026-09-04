"""Small constants and helpers shared across route modules."""
import logging
from urllib.parse import urlparse

from fastapi import Request

from app.templating import templates

log = logging.getLogger(__name__)

POSITIONS = ["QB", "RB", "WR", "TE"]
SIGNAL_LABELS = {
    "BUY_LOW": "Buy Low",
    "SELL_HIGH": "Sell High",
    "FAIR": "Fair",
}
COACH_ROLES = ["HC", "OC", "DC", "QB", "RB", "WR", "TE", "OL"]


def safe_redirect_path(candidate, default="/"):
    """A same-site path taken from user input, or `default`.

    `candidate.startswith("/")` is NOT sufficient on its own, which is
    what this replaces. A browser reads `//evil.example.com` as a
    protocol-relative URL -- scheme inherited, host `evil.example.com` --
    so a value passing that check sends the logged-in user straight off
    the site. `/\\evil.example.com` is treated the same way by several
    browsers, which is why backslashes are rejected outright rather than
    normalised.

    Anything with a scheme, a host, a backslash, or a CR/LF (header
    splitting) falls back to `default`."""
    if not candidate or not isinstance(candidate, str):
        return default
    if not candidate.startswith("/"):
        return default
    if "\\" in candidate or "\r" in candidate or "\n" in candidate:
        return default
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return default
    return candidate


def db_missing_response(request: Request, error: FileNotFoundError):
    """503 page for "the database file isn't there".

    The exception message names the absolute path of the missing file and
    the script that builds it -- genuinely useful while setting the site
    up, and not something to hand a logged-out stranger, since /login
    reaches this handler before authentication. So it's logged for the
    operator either way and shown in the page only to an admin."""
    log.error("database unavailable serving %s: %s", request.url.path, error)
    user = getattr(request.state, "user", None)
    detail = str(error) if user and user.get("tier") == "admin" else None
    return templates.TemplateResponse(
        request, "db_missing.html", {"error": detail}, status_code=503
    )
