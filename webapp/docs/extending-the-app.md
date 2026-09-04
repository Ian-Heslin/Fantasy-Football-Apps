# Adding functionality to the Fantasy Football web app

A guide for anyone (human or AI) picking up a feature request against this
site who isn't already steeped in the codebase. It answers the first
question up front, then walks through the shape a new feature needs to
take to fit in cleanly.

## What language/framework do I write this in?

**Python 3, using FastAPI, with server-rendered Jinja2 HTML templates.**

There is no separate frontend project, no JS framework (React/Vue/etc.),
and no build step. A "page" is a Python route function that queries a
database and returns rendered HTML directly. The only JavaScript in the
app is small inline `<script>` blocks for things like a click-to-select
toggle -- there's no bundler, no `package.json`, no npm install. If your
feature can be expressed as "a route handler that reads some data and
renders a template," that's exactly the shape this app wants; if it
genuinely needs a rich client-side UI, that would be new territory for
this codebase and worth flagging before you start.

Stack, concretely:

- **FastAPI** for routing, request handling, and dependency injection
  (`app/main.py`, `app/routes/*.py`)
- **Jinja2** for templates, via a single shared `Jinja2Templates` instance
  (`app/templating.py`) -- one `.html` file per page under
  `app/templates/`, each extending `base.html`
- **SQLite** (`app.db`) for operational/small data, **DuckDB**
  (`analytics.duckdb`) for large historical/analytical data -- see
  "Which database do I use?" below
- **Plain hand-written CSS** (`app/static/style.css`), no framework, no
  preprocessor
- **pytest** for tests (`tests/`), run against throwaway in-memory /
  `tmp_path` databases -- never a real `app.db`

## The request/response shape

Every route follows the same pattern: open a connection, do the work in a
plain (non-FastAPI) helper module, close the connection, render a
template.

```python
# app/routes/my_feature.py
"""My Feature routes -- see app/my_feature.py for the game/feature logic."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import my_feature
from app.auth import require_tier
from app.common import db_missing_response
from app.db import get_connection
from app.templating import templates

router = APIRouter(dependencies=[Depends(require_tier("games"))])


@router.get("/games/my-feature", response_class=HTMLResponse)
def hub(request: Request):
    user = request.state.user
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        data = my_feature.load_for_user(conn, user["user_id"])
    finally:
        conn.close()
    return templates.TemplateResponse(request, "my_feature.html", {"data": data})
```

Then wire it into the app once, in `app/main.py`:

```python
from app.routes import my_feature
...
app.include_router(my_feature.router)
```

Points worth internalizing from that example:

- **Business logic lives in a plain module (`app/my_feature.py`), not in
  the route file.** Route files (`app/routes/*.py`) stay thin: parse the
  request, open/close the DB connection, call into the logic module,
  render a template. The logic module's functions take a DB connection
  and plain arguments and return plain data structures -- no FastAPI
  imports, no `Request` object -- so they're trivial to unit test without
  spinning up the app (see `tests/test_pickem.py` for the pattern).
- **Access control is one line per router, not per route.**
  `APIRouter(dependencies=[Depends(require_tier("games"))])` protects
  every route in that file at once. Tiers are `games < fantasy < admin`,
  strictly nested (`app/auth.py`); pick whichever a new feature needs.
  `games` is what every self-signed-up account gets, so it's the right
  default for a new game/feature aimed at all users.
- **`request.state.user`** is already populated (or `None`) on every
  request by a global dependency -- no extra lookup needed to know who's
  logged in.
- **Handle the "database file doesn't exist yet" case.** `get_connection()`
  / `get_duckdb_connection()` raise `FileNotFoundError` if the DB hasn't
  been built; catch it and return `db_missing_response(request, e)` rather
  than letting it 500.
- **Always close connections in a `finally`.** If a route needs both
  databases, use `app.db.open_both()` / `close_all()` rather than two
  separate try/finally blocks (see `app/db.py`'s own docstring for why).

## Which database do I use?

- **`app.db` (SQLite, `get_connection()`)** -- operational/current-state
  data: users, accounts, league/roster data, game state for anything a
  user interacts with (picks, scores, leaderboards). This is what almost
  every new interactive feature will read and write.
- **`analytics.duckdb` (DuckDB, `get_duckdb_connection()`)** -- large
  historical/reference data: play-by-play, season stats, coaching
  history. Opened read-only from the app; nothing writes to it at
  request time.
- Never `ATTACH` one to the other inside a request -- pick whichever
  connection a route needs, or open both independently with `open_both()`.
- DuckDB cursors return plain tuples, not dict-like rows. Use
  `app.db.duckdb_rows(cursor)` to get the same `row["col_name"]` access
  templates expect from SQLite's `sqlite3.Row`.

## Templates and the design system

- One `.html` file per page in `app/templates/`, extending `base.html`.
- The site's look ("Solaris / Dynasty Desk") is driven entirely by CSS
  custom properties in `app/static/style.css` -- use the existing
  components (cards, badges, status dots, tables, buttons, the toggle
  switch) rather than one-off styling, and colors via `var(--yellow)`,
  `var(--green)`, `var(--sky)`, etc. so the site's dynamic "Team Colors"
  re-theming keeps working automatically. Full spec:
  `docs/solaris-design-spec.md`.
- If a new feature adds a table, make it responsive on phones (breakpoint
  720px): wrap read-only tables in `.table-scroll`, or use `.table-stack`
  (with `data-label` on every `<td>`) for tables with inputs or tappable
  cells. See the README's "Phones" section for the two utilities and the
  gotchas around 16px form controls and `.tab-settings`' margin.
- If the new page belongs under the games hub, add it to the relevant tab
  and reuse `_macros.html`'s `game_tabs(active)` macro for the shared nav
  rather than hand-rolling tab markup.
- Guessing/quiz-style games in this app are answered **row by row** -- one
  guess submitted and scored at a time -- not one big form submitted all
  at once. Follow that pattern if you're adding another one.

## Testing

```bash
pip install -r requirements.txt -r requirements-dev.txt
python3 -m pytest tests/ -q
```

- Test the pure logic module directly (no FastAPI involved) for scoring,
  validation, and edge-case rules -- that's most of the value, and it's
  fast. See `tests/test_pickem.py` for the pattern.
- Use `tests/test_routes.py`'s approach (a real ASGI app, real schema,
  real templates, throwaway `tmp_path` DB) if you need to test the
  end-to-end request/response path, auth, or tier boundaries.
- Never point a test at a real `app.db`. Tests build their own schema in
  an in-memory or `tmp_path` SQLite file.

## Checklist for a new feature/page

1. Decide the minimum account tier it needs (`games` unless there's a
   specific reason for more).
2. Write the logic as plain functions in a new `app/<feature>.py` module,
   taking a DB connection + arguments, returning plain data. Unit test
   these directly.
3. Add `app/routes/<feature>.py` with an `APIRouter(dependencies=[Depends(require_tier(...))])`,
   thin route functions that open/close a connection and call into the
   logic module.
4. Add `app/templates/<feature>.html` extending `base.html`, using
   existing design-system components; wrap/tag any tables for mobile.
5. Register the router in `app/main.py` (`app.include_router(...)`).
6. If it's part of the games hub, link it from `_macros.html`'s
   `game_tabs` nav or the relevant hub page.
7. Run `pytest tests/ -q` and manually exercise the page locally
   (`uvicorn app.main:app --reload`, with `SESSION_INSECURE_COOKIE=1` for
   local http://).

## What this app is not

- No JS framework, no bundler/build step, no separate frontend repo --
  don't introduce one for a single feature; render server-side HTML.
- No ORM -- routes/logic modules use raw SQL via `sqlite3`/`duckdb`
  connections and dict-style row access.
- No real-time/websocket layer -- "live" multi-user features (like Group
  mode) work by one host device driving state and everyone else reading
  it on reload/refresh, not push updates.
