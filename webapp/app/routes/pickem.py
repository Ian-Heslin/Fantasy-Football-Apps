"""NFL Pick'em -- the first game in the /games area (play with friends).

Mock/in-memory only for now -- see app/pickem_data.py for why (this is a
demo of the concept, not backed by app.db). Settings toggle straight-up
vs against-the-spread picks, and confidence points on/off; standings
recompute live against whichever settings are currently selected.
"""
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import pickem_data as data
from app.templating import templates

router = APIRouter()


@router.get("/games", response_class=HTMLResponse)
def games_index(request: Request):
    return templates.TemplateResponse(request, "games_index.html", {})


@router.get("/games/pickem", response_class=HTMLResponse)
def pickem_home(request: Request):
    open_week = data.get_week(data.OPEN_WEEK)
    standings = data.season_standings()
    return templates.TemplateResponse(
        request, "pickem_index.html",
        {
            "settings": data.SETTINGS,
            "friends": data.FRIENDS,
            "open_week_num": data.OPEN_WEEK,
            "open_week": open_week,
            "standings": standings,
            "team_names": data.TEAM_NAMES,
        },
    )


@router.post("/games/pickem/settings")
def update_settings(pick_mode: str = Form(...), confidence_enabled: bool = Form(False)):
    data.SETTINGS["pick_mode"] = pick_mode if pick_mode in ("straight_up", "spread") else "straight_up"
    data.SETTINGS["confidence_enabled"] = confidence_enabled
    return RedirectResponse(url="/games/pickem", status_code=303)


@router.get("/games/pickem/picks", response_class=HTMLResponse)
def picks_form(request: Request, friend: str = None, week: int = None):
    week = week if week in data.WEEKS else data.OPEN_WEEK
    friend = friend if friend in data.FRIENDS else data.FRIENDS[0]
    week_data = data.get_week(week)
    games = week_data["games"]
    existing = data.get_picks(week, friend)
    n_games = len(games)

    return templates.TemplateResponse(
        request, "pickem_picks.html",
        {
            "settings": data.SETTINGS,
            "friends": data.FRIENDS,
            "friend": friend,
            "week": week,
            "week_data": week_data,
            "games": games,
            "n_games": n_games,
            "existing": existing,
            "team_names": data.TEAM_NAMES,
            "saved": request.query_params.get("saved") == "1",
        },
    )


@router.post("/games/pickem/picks")
async def submit_picks(request: Request):
    form = await request.form()
    friend = form.get("friend")
    week = int(form.get("week"))
    if friend not in data.FRIENDS:
        return RedirectResponse(url="/games/pickem", status_code=303)

    games = data.get_week(week)["games"]
    picks = {}
    for g in games:
        team = form.get(f"pick_{g.id}")
        confidence = form.get(f"confidence_{g.id}")
        picks[g.id] = {
            "team": team or None,
            "confidence": int(confidence) if confidence else None,
        }
    data.save_picks(week, friend, picks)
    return RedirectResponse(url=f"/games/pickem/picks?friend={friend}&week={week}&saved=1", status_code=303)


@router.get("/games/pickem/standings", response_class=HTMLResponse)
def standings(request: Request):
    weeks = []
    for week_num in data.CLOSED_WEEKS:
        week_data = data.get_week(week_num)
        results = data.week_results(week_num)
        weeks.append({"num": week_num, "label": week_data["label"], "results": results})

    return templates.TemplateResponse(
        request, "pickem_standings.html",
        {
            "settings": data.SETTINGS,
            "standings": data.season_standings(),
            "weeks": weeks,
        },
    )
