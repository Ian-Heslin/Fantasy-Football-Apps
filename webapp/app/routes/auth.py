"""Signup, login, logout. No tier requirement on this router -- these are
the pages you need to be able to reach *without* being logged in yet."""
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import hash_password, verify_password
from app.common import db_missing_response
from app.db import get_connection
from app.templating import templates

router = APIRouter()


@router.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request):
    if request.state.user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "signup.html", {"error": None})


@router.post("/signup", response_class=HTMLResponse)
def signup_submit(request: Request, username: str = Form(...), password: str = Form(...),
                    confirm_password: str = Form(...)):
    username = username.strip()
    if not username or not password:
        return templates.TemplateResponse(
            request, "signup.html", {"error": "Username and password are required."})
    if password != confirm_password:
        return templates.TemplateResponse(
            request, "signup.html", {"error": "Passwords don't match."})

    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        existing = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            return templates.TemplateResponse(
                request, "signup.html", {"error": "That username is already taken."})

        cur = conn.execute(
            "INSERT INTO users (username, password_hash, tier) VALUES (?, ?, 'games')",
            (username, hash_password(password)),
        )
        conn.commit()
        user_id = cur.lastrowid
    finally:
        conn.close()

    request.session["user_id"] = user_id
    return RedirectResponse("/", status_code=303)


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if request.state.user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        row = conn.execute(
            "SELECT user_id, password_hash FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
    finally:
        conn.close()

    if row is None or not verify_password(password, row["password_hash"]):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Incorrect username or password."})

    request.session["user_id"] = row["user_id"]
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
