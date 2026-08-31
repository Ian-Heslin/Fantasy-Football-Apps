from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.auth import require_tier
from app.common import SIGNAL_LABELS, db_missing_response
from app.db import get_connection
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("fantasy"))])

# 1-for-1 trades where the two players' values are within this fraction of
# each other count as "fair value" -- see _suggest_trades().
FAIR_TRADE_TOLERANCE = 0.20
MAX_SUGGESTIONS = 15


def _team_players(conn, league_id, roster_id, arb_format, value_col):
    """One team's current roster with its latest trade value + arbitrage
    signal joined in -- shared by roster_detail (one team) and trade_finder
    (two teams at once)."""
    if roster_id is None:
        return []
    return conn.execute(
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


def _resolve_my_roster_id(conn, league, current_user):
    """Which roster in this league is the logged-in user's: prefer their
    linked Sleeper/ESPN owner_id (see /profile) over the league's own
    my_roster_id, which really means "Ian's team" (set by
    load_sleeper.py/load_espn.py) -- that's only the right fallback for
    whoever hasn't linked an account yet."""
    owner_id = (
        current_user.get("sleeper_owner_id") if league["platform"] == "sleeper"
        else current_user.get("espn_owner_id")
    )
    if owner_id:
        row = conn.execute(
            "SELECT roster_id FROM rosters WHERE league_id = ? AND owner_id = ?",
            (league["league_id"], owner_id),
        ).fetchone()
        if row:
            return row["roster_id"]
    return league["my_roster_id"]


def _suggest_trades(mine, theirs, value_col):
    """1-for-1 trade suggestions between two rosters: every (my player,
    their player) pair within FAIR_TRADE_TOLERANCE of each other's value,
    ranked by a mix of value fairness and arbitrage-signal alignment --
    better if you'd be moving a SELL_HIGH player and receiving a BUY_LOW one
    (see /arbitrage for what those mean). Doesn't account for positional
    need (e.g. you already have five WRs) -- just value and signal."""
    candidates = []
    for my_p in mine:
        my_value = my_p[value_col]
        if not my_value:
            continue
        for their_p in theirs:
            their_value = their_p[value_col]
            if not their_value:
                continue
            avg_value = (my_value + their_value) / 2
            gap = abs(my_value - their_value) / avg_value
            if gap > FAIR_TRADE_TOLERANCE:
                continue
            signal_bonus = (my_p["signal"] == "SELL_HIGH") + (their_p["signal"] == "BUY_LOW")
            candidates.append({
                "give": my_p, "get": their_p,
                "value_gap_pct": gap, "signal_bonus": signal_bonus,
            })
    candidates.sort(key=lambda c: (-c["signal_bonus"], c["value_gap_pct"]))
    return candidates[:MAX_SUGGESTIONS]


@router.get("/rosters", response_class=HTMLResponse)
def rosters_index(request: Request):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        leagues = conn.execute(
            "SELECT league_id, platform, name, season, format, status, my_roster_id "
            "FROM leagues ORDER BY name"
        ).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "rosters_index.html", {"leagues": leagues}
    )


@router.get("/rosters/{league_id}", response_class=HTMLResponse)
def roster_detail(request: Request, league_id: str, roster_id: Optional[str] = None):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        league = conn.execute(
            "SELECT league_id, platform, name, season, format, status, my_roster_id "
            "FROM leagues WHERE league_id = ?",
            (league_id,),
        ).fetchone()
        if league is None:
            conn.close()
            return templates.TemplateResponse(
                request, "roster_detail.html",
                {"league": None, "roster_id": None, "players": [], "teams": []},
                status_code=404,
            )

        teams = conn.execute(
            "SELECT roster_id, owner_name, is_mine FROM rosters WHERE league_id = ? ORDER BY owner_name",
            (league_id,),
        ).fetchall()
        team_ids = {t["roster_id"] for t in teams}

        if roster_id not in team_ids:
            roster_id = _resolve_my_roster_id(conn, league, request.state.user)
            if roster_id not in team_ids:
                row = conn.execute(
                    "SELECT roster_id FROM rosters WHERE league_id = ? AND is_mine = 1",
                    (league_id,),
                ).fetchone()
                roster_id = row["roster_id"] if row else None

        players = []
        if roster_id is not None:
            arb_format = "sf" if league["format"] == "SF" else "1qb"
            value_col = "value_2qb" if league["format"] == "SF" else "value_1qb"
            players = _team_players(conn, league_id, roster_id, arb_format, value_col)
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "roster_detail.html",
        {
            "league": league, "roster_id": roster_id, "teams": teams,
            "players": players, "signal_labels": SIGNAL_LABELS,
        },
    )


@router.get("/rosters/{league_id}/trades", response_class=HTMLResponse)
def trade_finder(request: Request, league_id: str, opponent_roster_id: Optional[str] = None):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        league = conn.execute(
            "SELECT league_id, platform, name, season, format, status, my_roster_id "
            "FROM leagues WHERE league_id = ?",
            (league_id,),
        ).fetchone()
        if league is None:
            conn.close()
            return templates.TemplateResponse(
                request, "trade_finder.html",
                {"league": None, "opponents": [], "opponent_roster_id": None, "suggestions": []},
                status_code=404,
            )

        my_roster_id = _resolve_my_roster_id(conn, league, request.state.user)
        if my_roster_id is None:
            row = conn.execute(
                "SELECT roster_id FROM rosters WHERE league_id = ? AND is_mine = 1",
                (league_id,),
            ).fetchone()
            my_roster_id = row["roster_id"] if row else None

        opponents = conn.execute(
            "SELECT roster_id, owner_name FROM rosters "
            "WHERE league_id = ? AND roster_id != ? ORDER BY owner_name",
            (league_id, my_roster_id or ""),
        ).fetchall()
        opponent_ids = {o["roster_id"] for o in opponents}
        if opponent_roster_id not in opponent_ids:
            opponent_roster_id = opponents[0]["roster_id"] if opponents else None

        value_col = "value_2qb" if league["format"] == "SF" else "value_1qb"
        suggestions = []
        if my_roster_id and opponent_roster_id:
            arb_format = "sf" if league["format"] == "SF" else "1qb"
            mine = _team_players(conn, league_id, my_roster_id, arb_format, value_col)
            theirs = _team_players(conn, league_id, opponent_roster_id, arb_format, value_col)
            suggestions = _suggest_trades(mine, theirs, value_col)
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "trade_finder.html",
        {
            "league": league, "my_roster_id": my_roster_id, "opponents": opponents,
            "opponent_roster_id": opponent_roster_id, "suggestions": suggestions,
            "value_col": value_col, "signal_labels": SIGNAL_LABELS,
        },
    )


@router.get("/rosters/{league_id}/history", response_class=HTMLResponse)
def league_history(request: Request, league_id: str):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        league = conn.execute(
            "SELECT league_id, platform, name, season, format, status, my_roster_id "
            "FROM leagues WHERE league_id = ?",
            (league_id,),
        ).fetchone()
        if league is None:
            conn.close()
            return templates.TemplateResponse(
                request, "league_history.html", {"league": None, "rows": []}, status_code=404,
            )

        rows = conn.execute(
            """SELECT season, roster_id, owner_name, wins, losses, ties,
                      points_for, points_against, final_rank
               FROM league_season_standings
               WHERE league_id = ?
               ORDER BY season DESC, final_rank ASC""",
            (league_id,),
        ).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "league_history.html", {"league": league, "rows": rows},
    )
