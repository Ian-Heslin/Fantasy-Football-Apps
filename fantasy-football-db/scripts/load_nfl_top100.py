#!/usr/bin/env python3
"""
load_nfl_top100.py -- loads the NFL Network's fan-voted annual "Top 100
Players" list into analytics.duckdb's nfl_top_100 table, for the "guess
the rank" trivia game (a separate game from Award Winners).

Source: data/trivia/nfl_top100.csv, Wikipedia-sourced (the "NFL Top 100
Players of <year>" articles) via Claude/Cowork in a browser -- this
sandbox can't reach Wikipedia directly, so this data was fetched outside
it and committed here rather than scraped at load time. Covers 2011-2026.
team is NULL for the handful of players who were between teams (free
agents) when that year's list published -- a real edge case in the
source, not missing data.

Usage:
    python3 scripts/load_nfl_top100.py
"""
import csv
import os
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUCKDB_PATH = os.path.join(ROOT, "data", "analytics.duckdb")
CSV_PATH = os.path.join(ROOT, "data", "trivia", "nfl_top100.csv")


def log(msg):
    print(f"[load_nfl_top100] {msg}")


def main():
    if not os.path.exists(DUCKDB_PATH):
        log("analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    with open(CSV_PATH) as f:
        rows = [
            (int(r["year"]), int(r["rank"]), r["player"], r["team"] or None)
            for r in csv.DictReader(f)
        ]

    conn = duckdb.connect(DUCKDB_PATH)
    conn.execute("DELETE FROM nfl_top_100")
    conn.executemany(
        "INSERT INTO nfl_top_100 (year, rank, player, team) VALUES (?, ?, ?, ?)",
        rows,
    )
    years = conn.execute("SELECT min(year), max(year) FROM nfl_top_100").fetchone()
    conn.close()

    log(f"loaded {len(rows)} rows, years {years[0]}-{years[1]}")
    log("done.")


if __name__ == "__main__":
    main()
