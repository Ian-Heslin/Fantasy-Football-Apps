"""Shared Jinja2Templates instance, so every route module renders from the
same templates/ directory and filter set without re-instantiating it."""
import os

from fastapi.templating import Jinja2Templates

from app.team_colors import TEAMS

HERE = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))

# A Jinja global (not per-route context) since base.html's top-bar team
# picker renders on every page, not just /profile.
templates.env.globals["teams"] = TEAMS
