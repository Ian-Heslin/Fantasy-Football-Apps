"""
Fantasy Football web app -- FastAPI + server-rendered Jinja2 templates.

Reads app.db (and, for the team/coach pages, analytics.duckdb) directly --
see app/db.py. Run with:
    uvicorn app.main:app --reload
from the webapp/ directory (see webapp/README.md for full setup).
"""
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import arbitrage, coaches, home, pickem, predictions, rosters, teams

HERE = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Fantasy Football")
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")

app.include_router(home.router)
app.include_router(rosters.router)
app.include_router(predictions.router)
app.include_router(arbitrage.router)
app.include_router(teams.router)
app.include_router(coaches.router)
app.include_router(pickem.router)
