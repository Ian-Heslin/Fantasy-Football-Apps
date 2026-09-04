"""Pokemon Draft League: static Pokedex browse/search page. See
app/pokemon_draft/pokedex.py for the underlying lookups."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.auth import require_tier
from app.common import db_missing_response
from app.db import get_connection
from app.pokemon_draft import pokedex as pk_pokedex
from app.templating import templates

router = APIRouter(prefix="/pokemon", dependencies=[Depends(require_tier("games"))])


@router.get("/pokedex", response_class=HTMLResponse)
def browse(request: Request):
    query = request.query_params.get("q") or None
    generation = request.query_params.get("generation")
    generation = int(generation) if generation else None
    page = max(int(request.query_params.get("page", 1) or 1), 1)

    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)
    try:
        rows, total = pk_pokedex.search(conn, query=query, generation=generation, page=page)
        all_generations = pk_pokedex.generations(conn)
    finally:
        conn.close()

    return templates.TemplateResponse(
        request, "pokemon/pokedex.html",
        {
            "pokemon": rows, "total": total, "page": page,
            "page_size": pk_pokedex.PAGE_SIZE, "query": query or "",
            "generation": generation, "generations": all_generations,
            "has_next": page * pk_pokedex.PAGE_SIZE < total,
        },
    )
