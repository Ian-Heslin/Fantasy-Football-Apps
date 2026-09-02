"""Signup, login, logout. No tier requirement on this router -- these are
the pages you need to be able to reach *without* being logged in yet."""
import sqlite3

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth import (
    clear_login_failures, hash_password, login_is_throttled, record_login_failure,
    validate_password, validate_username, verify_password_or_dummy,
)
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
    problem = validate_username(username) or validate_password(password)
    if problem:
        return templates.TemplateResponse(request, "signup.html", {"error": problem})

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

        try:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, tier) VALUES (?, ?, 'games')",
                (username, hash_password(password)),
            )
        except sqlite3.IntegrityError:
            # The SELECT above catches this in every normal case; this is
            # the two-simultaneous-signups race, where users.username's
            # UNIQUE constraint is the real guard. Show the same message
            # instead of a 500.
            return templates.TemplateResponse(
                request, "signup.html", {"error": "That username is already taken."})
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
    username = username.strip()

    if login_is_throttled(username):
        # Same wording whether or not the account exists, so the throttle
        # itself doesn't become a way to enumerate usernames.
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Too many failed sign-in attempts. Try again in a few minutes."},
            status_code=429)

    try:
        conn = get_connection()
    except FileNotFoundError as e:
        return db_missing_response(request, e)

    try:
        row = conn.execute(
            "SELECT user_id, password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
    finally:
        conn.close()

    # verify_password_or_dummy runs a real bcrypt check even when there's
    # no such user, so a wrong username and a wrong password take the
    # same time to come back.
    if not verify_password_or_dummy(password, row["password_hash"] if row else None):
        record_login_failure(username)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Incorrect username or password."},
            status_code=401)

    clear_login_failures(username)
    request.session["user_id"] = row["user_id"]
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
