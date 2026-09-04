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
    admin, arbitrage, auth, coaches, fantasy_draft, five_oh_one, game_settings, games_hub, group, home,
    imposter, pickem, predictions, profile, rosters, teams, trivia,
)
from app.routes.pokemon_draft import (
    draft as pokemon_draft, pokedex as pokemon_pokedex, roster as pokemon_roster,
    schedule as pokemon_schedule, seasons as pokemon_seasons,
)
from app.templating import templates

HERE = os.path.dirname(os.path.abspath(__file__))

# 30 days: long enough that nobody on the Pi's little friends-and-family
# site gets logged out mid-season, short enough that an old cookie dies.
SESSION_MAX_AGE = 30 * 24 * 60 * 60

# The session cookie is Secure by default, so a browser will only send it
# back over HTTPS -- which is all the deployed site ever serves. Plain
# `uvicorn app.main:app --reload` on http://127.0.0.1:8000 is the one
# case where that would silently break login (the browser accepts the
# Set-Cookie and then never sends it), so local dev can opt out:
#
#     SESSION_INSECURE_COOKIE=1 uvicorn app.main:app --reload
#
# Never set this on the Pi.
SESSION_HTTPS_ONLY = os.environ.get("SESSION_INSECURE_COOKIE", "").lower() not in (
    "1", "true", "yes")
if not SESSION_HTTPS_ONLY:
    print("[main] WARNING: SESSION_INSECURE_COOKIE is set -- the session cookie is NOT "
          "marked Secure. For local http:// development only; never set this in "
          "the systemd service file.")

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
#
# Cookie flags are set explicitly rather than inherited from Starlette's
# defaults, because two of them are load-bearing here:
#   https_only -- the deployed site is only ever served over HTTPS
#     (Cloudflare named tunnel), and this cookie is the whole of the auth
#     story, so there's no reason to let a browser put it on the wire in
#     clear. Starlette's default for this is False.
#   same_site="lax" -- the app has no CSRF tokens; this is what stops a
#     cross-site form post from arriving with the session attached. It
#     still allows ordinary top-level GET navigation (a link from a text
#     message to /games/pickem keeps you logged in).
# SESSION_MAX_AGE bounds how long a stolen cookie stays useful.
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    https_only=SESSION_HTTPS_ONLY,
    same_site="lax",
    max_age=SESSION_MAX_AGE,
)


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
app.include_router(games_hub.router)
app.include_router(group.router)
app.include_router(fantasy_draft.router)
app.include_router(five_oh_one.router)
app.include_router(imposter.router)
app.include_router(game_settings.router)
app.include_router(pokemon_seasons.router)
app.include_router(pokemon_pokedex.router)
app.include_router(pokemon_draft.router)
app.include_router(pokemon_schedule.router)
app.include_router(pokemon_roster.router)
