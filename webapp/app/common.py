"""Small constants and helpers shared across route modules."""
import logging

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
