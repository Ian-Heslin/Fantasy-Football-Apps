# NFL Pick'em mockup

A working mockup of a new "play games with friends" area, added to the
existing FastAPI/Jinja2 web app. NFL Pick'em is the first game in that
area -- pick the winner of every NFL matchup each week, with a settings
toggle for two common strategy variants.

## What it does

- **Straight-up or against-the-spread picks.** A league setting decides
  whether picking the outright winner is enough, or whether you have to
  pick whoever covers the Vegas spread that was live when picks were made.
- **Confidence points (optional).** Instead of 1 point per correct pick,
  each pick is assigned a unique value from 1 to *N* (N = games that week,
  since bye weeks change the count). Your most confident pick is worth N
  points if right, your least confident is worth 1. Wrong picks score 0.
- **Live-recomputing standings.** Toggling the settings recomputes
  standings immediately against whichever mode is currently selected, so
  you can see how the same picks would have scored under a different
  strategy.

## Routes

| Route | Purpose |
|---|---|
| `GET /games` | Games landing page (lists available games; just Pick'em for now) |
| `GET /games/pickem` | League home: settings form, this week's games, standings summary |
| `POST /games/pickem/settings` | Update `pick_mode` / `confidence_enabled` |
| `GET /games/pickem/picks?friend=&week=` | Picks form for one friend/week |
| `POST /games/pickem/picks` | Save picks |
| `GET /games/pickem/standings` | Season + week-by-week leaderboard |

## Data (mock, in-memory)

Everything lives in `app/pickem_data.py` as module-level state -- it is
**not** backed by `app.db` or `analytics.duckdb`, and resets whenever the
app restarts. This mirrors the rest of the app's routes/templates
structure, but the rest of the app is read-only against real data; this
feature needs writes (picks), which the app doesn't support yet.

- `TEAM_NAMES` -- all 32 NFL team abbreviations/names.
- `FRIENDS` -- 4 mock players (`Ian`, `Jake`, `Maria`, `Chris`).
- `WEEKS` -- two sample weeks:
  - **Week 1** (16 games, marked final with mock scores) -- pre-seeded
    picks per friend so standings have something real to show.
  - **Week 2** (14 games, open) -- has spreads but no results yet; this is
    the week you can actually submit picks for.
- `PICKS[week][friend][game_id]` -- `{"team": ..., "confidence": ...}`.
- `SETTINGS` -- `pick_mode` (`"straight_up"` | `"spread"`) and
  `confidence_enabled` (bool), global across the whole game.

Scoring (`score_pick` in `pickem_data.py`): for a finished game, compare
the pick against either the actual winner or the team that covered the
spread (depending on `pick_mode`); award 1 point, or the assigned
confidence value, if correct.

## Files touched/added

```
webapp/app/pickem_data.py                 -- mock data + scoring (new)
webapp/app/routes/pickem.py               -- routes (new)
webapp/app/templates/games_index.html     -- (new)
webapp/app/templates/pickem_index.html    -- (new)
webapp/app/templates/pickem_picks.html    -- (new)
webapp/app/templates/pickem_standings.html -- (new)
webapp/app/main.py                        -- registers the new router
webapp/app/templates/base.html            -- adds "Games" nav link
webapp/app/static/style.css               -- buttons, pick radios,
                                              confidence input, game cards
webapp/requirements.txt                   -- adds python-multipart
                                              (needed for HTML form posts)
```

## Running it

```bash
cd webapp
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000/games`.

## What's mocked vs. real

- Matchups, spreads, and scores are invented sample data, not the real
  NFL schedule or live Vegas lines.
- Picks and settings are process memory, not persisted to disk -- fine
  for demoing the UX, not for actually running a league.
- No auth/accounts -- "picking as" a friend is just a dropdown, anyone can
  pick for anyone.

## Natural next steps

- Persist games/picks/settings in a real store (a small SQLite db, or new
  tables in `app.db`) instead of module globals.
- Pull real weekly matchups + live spreads (odds API) instead of hardcoded
  mock games.
- Lock each game's picks at its own kickoff time rather than only gating
  by week.
- Basic auth so friends can only edit their own picks.
- A second game in the `/games` area once Pick'em is real (survivor pool,
  squares, etc.).
