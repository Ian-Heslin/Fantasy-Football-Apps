"""Puts webapp/ on sys.path so tests can `from app import ...` the same
way the running app does, whatever directory pytest is invoked from."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
