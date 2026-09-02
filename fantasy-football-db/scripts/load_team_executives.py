#!/usr/bin/env python3
"""
load_team_executives.py -- loads owner + GM (+ a bonus head_coach field)
per team-season into analytics.duckdb's team_executives_season table, for
GM-level attribution alongside analyze_draft_reaches.py's existing HC-
level analysis.

Source: data/team_executives/team_executives_season.csv, Wikipedia-
sourced (each team's per-season article, e.g. "2023 Arizona Cardinals
season") via Claude/Cowork in a browser -- this sandbox can't reach
Wikipedia directly, so this data was fetched outside it and committed
here rather than scraped at load time. Covers 1898-2026, all 32
franchises, keyed on the team's *current* identity regardless of
historical relocations/renames (e.g. every Cardinals season from 1898's
Chicago Cardinals onward is keyed "ARI").

head_coach here is a convenience/cross-check only -- analyze_draft_
reaches.py's HC attribution still comes from coach_table (PFR-sourced,
2001-2025, independently loaded), not duplicated from this file.

Usage:
    python3 scripts/load_team_executives.py
"""
import csv
import os
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUCKDB_PATH = os.path.join(ROOT, "data", "analytics.duckdb")
CSV_PATH = os.path.join(ROOT, "data", "team_executives", "team_executives_season.csv")


def log(msg):
    print(f"[load_team_executives] {msg}")


def main():
    if not os.path.exists(DUCKDB_PATH):
        log("analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    with open(CSV_PATH) as f:
        rows = [
            (int(r["season"]), r["team"], r["owner"] or None, r["general_manager"] or None,
             r["gm_notes"] or None, r["head_coach"] or None)
            for r in csv.DictReader(f)
        ]

    conn = duckdb.connect(DUCKDB_PATH)
    conn.execute("DELETE FROM team_executives_season")
    conn.executemany(
        """INSERT INTO team_executives_season (season, team, owner, general_manager, gm_notes, head_coach)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    years = conn.execute("SELECT min(season), max(season) FROM team_executives_season").fetchone()
    teams = conn.execute("SELECT count(DISTINCT team) FROM team_executives_season").fetchone()[0]
    conn.close()

    log(f"loaded {len(rows)} rows, seasons {years[0]}-{years[1]}, {teams} teams")
    log("done.")


if __name__ == "__main__":
    main()
