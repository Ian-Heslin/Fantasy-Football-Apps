"""Shared Jinja2Templates instance, so every route module renders from the
same templates/ directory and filter set without re-instantiating it."""
import os

from fastapi.templating import Jinja2Templates

from app.team_colors import TEAMS, logo_for

HERE = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))

# Jinja globals (not per-route context) since base.html's top-bar team
# picker renders on every page, not just /profile, and logo_for() is handy
# from any template that shows a team abbreviation (Pick'em, standings).
templates.env.globals["teams"] = TEAMS
templates.env.globals["logo_for"] = logo_for
