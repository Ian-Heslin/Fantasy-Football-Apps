"""Shared Jinja2Templates instance, so every route module renders from the
same templates/ directory and filter set without re-instantiating it."""
import os

from fastapi.templating import Jinja2Templates

HERE = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))
