"""
Fantasy Football web app -- FastAPI + server-rendered Jinja2 templates.

Reads app.db directly (see app/db.py). Run with:
    uvicorn app.main:app --reload
from the webapp/ directory (see webapp/README.md for full setup).
"""
import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import get_connection

HERE = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Fantasy Football")
app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))

POSITIONS = ["QB", "RB", "WR", "TE"]
SIGNAL_LABELS = {
    "BUY_LOW": "Buy Low",
    "SELL_HIGH": "Sell High",
    "FAIR": "Fair",
}


def db_missing_response(request: Request, error: FileNotFoundError):
    return templates.TemplateResponse(
        request, "db_missing.html", {"error": str(error)}, status_code=503
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        sync_log = conn.execute(
            "SELECT table_name, source, last_synced_at, row_count, notes "
            "FROM sync_log ORDER BY table_name"
        ).fetchall()
        stats = {
            "players": conn.execute("SELECT count(*) FROM players").fetchone()[0],
            "leagues": conn.execute("SELECT count(*) FROM leagues").fetchone()[0],
            "arbitrage_signals": conn.execute("SELECT count(*) FROM arbitrage_signals").fetchone()[0],
            "breakout_predictions": conn.execute(
                "SELECT count(*) FROM model_predictions WHERE model_name = 'breakout'"
            ).fetchone()[0],
            "bounceback_predictions": conn.execute(
                "SELECT count(*) FROM model_predictions WHERE model_name = 'bounceback'"
            ).fetchone()[0],
        }
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "home.html", {"sync_log": sync_log, "stats": stats}
    )


@app.get("/rosters", response_class=HTMLResponse)
def rosters_index(request: Request):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        leagues = conn.execute(
            "SELECT league_id, name, season, format, status, my_roster_id "
            "FROM leagues ORDER BY name"
        ).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "rosters_index.html", {"leagues": leagues}
    )


@app.get("/rosters/{league_id}", response_class=HTMLResponse)
def roster_detail(request: Request, league_id: str):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        league = conn.execute(
            "SELECT league_id, name, season, format, status, my_roster_id "
            "FROM leagues WHERE league_id = ?",
            (league_id,),
        ).fetchone()
        if league is None:
            conn.close()
            return templates.TemplateResponse(
                request, "roster_detail.html",
                {"league": None, "roster_id": None, "players": []},
                status_code=404,
            )

        roster_id = league["my_roster_id"]
        if roster_id is None:
            row = conn.execute(
                "SELECT roster_id FROM rosters WHERE league_id = ? AND is_mine = 1",
                (league_id,),
            ).fetchone()
            roster_id = row["roster_id"] if row else None

        players = []
        if roster_id is not None:
            arb_format = "sf" if league["format"] == "SF" else "1qb"
            value_col = "value_2qb" if league["format"] == "SF" else "value_1qb"
            players = conn.execute(
                f"""
                SELECT
                    p.player_id, p.name, p.position, p.team,
                    tv.value_1qb, tv.value_2qb,
                    asig.gap, asig.signal
                FROM roster_players rp
                JOIN players p ON p.player_id = rp.player_id
                LEFT JOIN (
                    SELECT player_id, value_1qb, value_2qb,
                           ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY value_date DESC) rn
                    FROM trade_values WHERE is_pick = 0
                ) tv ON tv.player_id = p.player_id AND tv.rn = 1
                LEFT JOIN (
                    SELECT player_id, format, gap, signal,
                           ROW_NUMBER() OVER (PARTITION BY player_id, format ORDER BY as_of_date DESC) rn
                    FROM arbitrage_signals
                ) asig ON asig.player_id = p.player_id AND asig.format = ? AND asig.rn = 1
                WHERE rp.league_id = ? AND rp.roster_id = ? AND rp.as_of_date = (
                    SELECT max(as_of_date) FROM roster_players
                    WHERE league_id = ? AND roster_id = ?
                )
                ORDER BY {value_col} DESC
                """,
                (arb_format, league_id, roster_id, league_id, roster_id),
            ).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "roster_detail.html",
        {
            "league": league, "roster_id": roster_id,
            "players": players, "signal_labels": SIGNAL_LABELS,
        },
    )


@app.get("/predictions", response_class=HTMLResponse)
def predictions(request: Request, model: str = "breakout", season: int | None = None,
                 position: str | None = None):
    if model not in ("breakout", "bounceback"):
        model = "breakout"

    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        seasons = [r[0] for r in conn.execute(
            "SELECT DISTINCT season FROM model_predictions WHERE model_name = ? ORDER BY season DESC",
            (model,),
        ).fetchall()]
        selected_season = season if season in seasons else (seasons[0] if seasons else None)

        query = """
            SELECT mp.player_id, mp.season, mp.predicted_probability, mp.actual_outcome,
                   p.name, p.position, p.team
            FROM model_predictions mp
            LEFT JOIN players p ON p.player_id = mp.player_id
            WHERE mp.model_name = ?
        """
        params = [model]
        if selected_season is not None:
            query += " AND mp.season = ?"
            params.append(selected_season)
        if position in POSITIONS:
            query += " AND p.position = ?"
            params.append(position)
        query += " ORDER BY mp.predicted_probability DESC"

        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "predictions.html",
        {
            "model": model, "rows": rows,
            "seasons": seasons, "selected_season": selected_season,
            "positions": POSITIONS, "selected_position": position,
        },
    )
