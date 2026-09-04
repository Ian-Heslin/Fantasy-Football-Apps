"""Pokemon Draft League: schedule, match report/confirm/dispute, and
standings/leaderboard routes. See app/pokemon_draft/{schedule,matches,
standings}.py for the underlying logic."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import require_tier
from app.common import db_missing_response
from app.db import get_connection
from app.pokemon_draft import matches as pk_matches
from app.pokemon_draft import playoffs as pk_playoffs
from app.pokemon_draft import replay as pk_replay
from app.pokemon_draft import roster as pk_roster
from app.pokemon_draft import schedule as pk_schedule
from app.pokemon_draft import seasons as pk_seasons
from app.pokemon_draft import standings as pk_standings
from app.pokemon_draft.permissions import require_commissioner
from app.templating import templates

router = APIRouter(prefix="/pokemon", dependencies=[Depends(require_tier("games"))])


# ---------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------

@router.get("/seasons/{season_id}/schedule", response_class=HTMLResponse)
def schedule_page(request: Request, season_id: int):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        season = pk_seasons.get_season(conn, season_id)
        if season is None:
            return RedirectResponse("/pokemon/seasons", status_code=303)
        is_commissioner = user["tier"] == "admin" or user["user_id"] == season["commissioner_user_id"]
        rows = pk_schedule.overview(conn, season_id)
    finally:
        conn.close()

    weeks = {}
    for r in rows:
        weeks.setdefault(r["week"], []).append(r)

    return templates.TemplateResponse(
        request, "pokemon/schedule.html",
        {"season": season, "is_commissioner": is_commissioner, "weeks": weeks, "error": None},
    )


@router.post("/seasons/{season_id}/schedule/generate", dependencies=[Depends(require_commissioner)])
def generate_schedule(request: Request, season_id: int, num_weeks: int = Form(...)):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        pk_schedule.generate_schedule(conn, season_id, num_weeks)
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}/schedule", status_code=303)


@router.post("/seasons/{season_id}/schedule/clear", dependencies=[Depends(require_commissioner)])
def clear_schedule(request: Request, season_id: int):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        pk_schedule.clear_schedule(conn, season_id)
    finally:
        conn.close()
    return RedirectResponse(f"/pokemon/seasons/{season_id}/schedule", status_code=303)


# ---------------------------------------------------------------------
# Match report / confirm / dispute / resolve
# ---------------------------------------------------------------------

def _parse_games_from_form(conn, form, match, home_roster, away_roster):
    """(games, None) on success or (None, error string) on failure --
    reads game 1..3's input in one of two ways, checked in order:

    1. A "replay_url_{g}" field, if filled -- fetched and parsed via
       app/pokemon_draft/replay.py, using "replay_home_is_p1_{g}" (a "1"
       checkbox value) to map Showdown's p1/p2 sides onto our home/away
       coaches. A fetch/parse failure here aborts the WHOLE report with
       that error, before anything is written -- same "nothing saved on
       error" contract report_match()/resolve_dispute() already have.
    2. Otherwise, the manual entry fields: winner_{g} (home/away) plus
       kills_/deaths_{g}_{coach_id}_{pokemon_id} per roster row. A row
       with both kills and deaths left blank is treated as "didn't play"
       -- no stats row, not a zero row (matches the schema's convention)."""
    games = []
    for g in (1, 2, 3):
        replay_url = (form.get(f"replay_url_{g}") or "").strip()
        if replay_url:
            home_is_p1 = form.get(f"replay_home_is_p1_{g}") == "1"
            game, error = pk_replay.build_game_from_replay(
                conn, replay_url, match["coach_id_home"], match["coach_id_away"], home_is_p1)
            if error:
                return None, f"Game {g} replay: {error}"
            games.append(game)
            continue

        winner_side = form.get(f"winner_{g}")
        if winner_side not in ("home", "away"):
            continue
        winner_coach_id = match["coach_id_home"] if winner_side == "home" else match["coach_id_away"]
        stats = []
        for side_roster, coach_id in ((home_roster, match["coach_id_home"]),
                                       (away_roster, match["coach_id_away"])):
            for r in side_roster:
                pid = r["pokemon_id"]
                k = (form.get(f"kills_{g}_{coach_id}_{pid}") or "").strip()
                d = (form.get(f"deaths_{g}_{coach_id}_{pid}") or "").strip()
                if not k and not d:
                    continue
                stats.append({
                    "coach_id": coach_id, "pokemon_id": pid,
                    "kills": int(k) if k else 0, "deaths": int(d) if d else 0,
                })
        games.append({"winner_coach_id": winner_coach_id, "stats": stats})
    return games, None


@router.get("/seasons/{season_id}/matches/{match_id}", response_class=HTMLResponse)
def match_detail(request: Request, season_id: int, match_id: int):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        match = pk_matches.get_match(conn, match_id)
        if match is None or match["season_id"] != season_id:
            return RedirectResponse(f"/pokemon/seasons/{season_id}/schedule", status_code=303)
        season = pk_seasons.get_season(conn, season_id)
        is_commissioner = user["tier"] == "admin" or user["user_id"] == season["commissioner_user_id"]
        is_my_matchup = pk_matches.coach_in_match(match, user["user_id"]) is not None
        is_reporter = match["reported_by_user_id"] == user["user_id"]
        home_roster = pk_roster.current_roster_with_pokemon(conn, season_id, match["coach_id_home"])
        away_roster = pk_roster.current_roster_with_pokemon(conn, season_id, match["coach_id_away"])
        games = pk_matches.get_games(conn, match_id)
        games_with_stats = [(g, pk_matches.get_stats(conn, g["game_id"])) for g in games]
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "pokemon/match_detail.html",
        {
            "season_id": season_id, "match": match, "is_commissioner": is_commissioner,
            "is_my_matchup": is_my_matchup, "is_reporter": is_reporter,
            "home_roster": home_roster, "away_roster": away_roster,
            "games_with_stats": games_with_stats, "error": request.query_params.get("error"),
        },
    )


@router.post("/seasons/{season_id}/matches/{match_id}/report")
async def report_match(request: Request, season_id: int, match_id: int):
    user = request.state.user
    form = await request.form()
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        match = pk_matches.get_match(conn, match_id)
        if match is None:
            return RedirectResponse(f"/pokemon/seasons/{season_id}/schedule", status_code=303)
        home_roster = pk_roster.current_roster_with_pokemon(conn, season_id, match["coach_id_home"])
        away_roster = pk_roster.current_roster_with_pokemon(conn, season_id, match["coach_id_away"])
        games, error = _parse_games_from_form(conn, form, match, home_roster, away_roster)
        if error is None:
            error = pk_matches.report_match(conn, match_id, user["user_id"], games)
    finally:
        conn.close()
    dest = f"/pokemon/seasons/{season_id}/matches/{match_id}"
    return RedirectResponse(f"{dest}?error={quote(error)}" if error else dest, status_code=303)


@router.post("/seasons/{season_id}/matches/{match_id}/confirm")
def confirm_match(request: Request, season_id: int, match_id: int):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        error = pk_matches.confirm_match(conn, match_id, user["user_id"])
        if error is None:
            # Harmless no-op for a non-playoff match or a season with no
            # bracket yet -- only walks the bracket forward when this
            # match's schedule row actually has a bracket_slot set.
            pk_playoffs.advance_bracket(conn, season_id)
    finally:
        conn.close()
    dest = f"/pokemon/seasons/{season_id}/matches/{match_id}"
    return RedirectResponse(f"{dest}?error={quote(error)}" if error else dest, status_code=303)


@router.post("/seasons/{season_id}/matches/{match_id}/dispute")
async def dispute_match(request: Request, season_id: int, match_id: int):
    user = request.state.user
    form = await request.form()
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        error = pk_matches.dispute_match(conn, match_id, user["user_id"], form.get("reason", ""))
    finally:
        conn.close()
    dest = f"/pokemon/seasons/{season_id}/matches/{match_id}"
    return RedirectResponse(f"{dest}?error={quote(error)}" if error else dest, status_code=303)


@router.post("/seasons/{season_id}/matches/{match_id}/resolve", dependencies=[Depends(require_commissioner)])
async def resolve_dispute(request: Request, season_id: int, match_id: int):
    user = request.state.user
    form = await request.form()
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        match = pk_matches.get_match(conn, match_id)
        if match is None:
            return RedirectResponse(f"/pokemon/seasons/{season_id}/schedule", status_code=303)
        home_roster = pk_roster.current_roster_with_pokemon(conn, season_id, match["coach_id_home"])
        away_roster = pk_roster.current_roster_with_pokemon(conn, season_id, match["coach_id_away"])
        games, error = _parse_games_from_form(conn, form, match, home_roster, away_roster)
        if error is None:
            error = pk_matches.resolve_dispute(conn, match_id, user["user_id"], form.get("note", ""), games)
        if error is None:
            pk_playoffs.advance_bracket(conn, season_id)
    finally:
        conn.close()
    dest = f"/pokemon/seasons/{season_id}/matches/{match_id}"
    return RedirectResponse(f"{dest}?error={quote(error)}" if error else dest, status_code=303)


# ---------------------------------------------------------------------
# Standings / leaderboard
# ---------------------------------------------------------------------

@router.get("/seasons/{season_id}/standings", response_class=HTMLResponse)
def standings_page(request: Request, season_id: int):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        season = pk_seasons.get_season(conn, season_id)
        if season is None:
            return RedirectResponse("/pokemon/seasons", status_code=303)
        rows = pk_standings.standings(conn, season_id)
        leaderboard = pk_standings.pokemon_leaderboard(conn, season_id)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "pokemon/standings.html",
        {"season": season, "standings": rows, "leaderboard": leaderboard},
    )


# ---------------------------------------------------------------------
# Playoffs
# ---------------------------------------------------------------------

@router.get("/seasons/{season_id}/playoffs", response_class=HTMLResponse)
def playoffs_page(request: Request, season_id: int):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        season = pk_seasons.get_season(conn, season_id)
        if season is None:
            return RedirectResponse("/pokemon/seasons", status_code=303)
        is_commissioner = user["tier"] == "admin" or user["user_id"] == season["commissioner_user_id"]
        seeded = pk_playoffs.is_seeded(conn, season_id)
        bracket = pk_playoffs.bracket_view(conn, season_id) if seeded else []
        champion_coach_id = pk_playoffs.champion(conn, season_id) if seeded else None
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "pokemon/playoffs.html",
        {
            "season": season, "is_commissioner": is_commissioner, "seeded": seeded,
            "bracket": bracket, "champion_coach_id": champion_coach_id, "error": None,
        },
    )


@router.post("/seasons/{season_id}/playoffs/seed", dependencies=[Depends(require_commissioner)])
def seed_playoffs(request: Request, season_id: int):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        error = pk_playoffs.seed_bracket(conn, season_id)
    finally:
        conn.close()
    dest = f"/pokemon/seasons/{season_id}/playoffs"
    return RedirectResponse(f"{dest}?error={quote(error)}" if error else dest, status_code=303)


@router.post("/seasons/{season_id}/playoffs/clear", dependencies=[Depends(require_commissioner)])
def clear_playoffs(request: Request, season_id: int):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        error = pk_playoffs.clear_bracket(conn, season_id)
    finally:
        conn.close()
    dest = f"/pokemon/seasons/{season_id}/playoffs"
    return RedirectResponse(f"{dest}?error={quote(error)}" if error else dest, status_code=303)
