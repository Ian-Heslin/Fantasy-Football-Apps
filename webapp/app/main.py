"""
Fantasy Football web app -- FastAPI + server-rendered Jinja2 templates.

Reads app.db (and, for the team/coach pages, analytics.duckdb) directly --
see app/db.py. Run with:
    uvicorn app.main:app --reload
from the webapp/ directory (see webapp/README.md for full setup).

Auth: every page requires a logged-in account except /login, /signup, and
/static -- see app/auth.py for the tier system (games < fantasy < admin)
and how load_current_user/require_tier are wired in as dependencies below.
"""
import os
import secrets

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import Forbidden, NotAuthenticated, load_current_user
from app.routes import (
    admin, arbitrage, auth, coaches, fantasy_draft, home, pickem, predictions, profile, rosters, teams, trivia,
)
from app.templating import templates

HERE = os.path.dirname(os.path.abspath(__file__))

SESSION_SECRET_KEY = os.environ.get("SESSION_SECRET_KEY")
if not SESSION_SECRET_KEY:
    SESSION_SECRET_KEY = secrets.token_hex(32)
    print("[main] WARNING: SESSION_SECRET_KEY not set -- using a random one-time key, "
          "so everyone gets logged out on the next restart. Set SESSION_SECRET_KEY in "
          "your environment (e.g. the systemd service file) for a stable key.")

app = FastAPI(title="Fantasy Football", dependencies=[Depends(load_current_user)])
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")

# Added after AuthMiddleware doesn't exist here -- load_current_user is a
# plain dependency, not middleware, so only SessionMiddleware needs adding;
# it must wrap every route so request.session exists before
# load_current_user (an app-level dependency) reads it.
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET_KEY)


@app.exception_handler(NotAuthenticated)
def handle_not_authenticated(request: Request, exc: NotAuthenticated):
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(Forbidden)
def handle_forbidden(request: Request, exc: Forbidden):
    return templates.TemplateResponse(request, "forbidden.html", {}, status_code=403)


app.include_router(auth.router)
app.include_router(home.router)
app.include_router(rosters.router)
app.include_router(predictions.router)
app.include_router(arbitrage.router)
app.include_router(teams.router)
app.include_router(coaches.router)
app.include_router(profile.router)
app.include_router(admin.router)
app.include_router(pickem.router)
app.include_router(trivia.router)
app.include_router(fantasy_draft.router)
