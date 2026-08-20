"""Small constants and helpers shared across route modules."""
from fastapi import Request

from app.templating import templates

POSITIONS = ["QB", "RB", "WR", "TE"]
SIGNAL_LABELS = {
    "BUY_LOW": "Buy Low",
    "SELL_HIGH": "Sell High",
    "FAIR": "Fair",
}
COACH_ROLES = ["HC", "OC", "DC", "QB", "RB", "WR", "TE", "OL"]


def db_missing_response(request: Request, error: FileNotFoundError):
    return templates.TemplateResponse(
        request, "db_missing.html", {"error": str(error)}, status_code=503
    )
