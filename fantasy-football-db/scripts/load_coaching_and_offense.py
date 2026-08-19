#!/usr/bin/env python3
"""
load_coaching_and_offense.py -- loads coach_table, team_offense_season,
vegas_odds, team_primary_qb, player_offense_rank, and coach_tenure_segments
into analytics.duckdb from the CSVs in data/coaching_and_offense/.

That data is the output of a separate Claude Cowork session's v13-v18
coaching-effects and offense-quality research (see docs/breakout-falloff-
methodology.md) -- it replaced an earlier, thinner version of team_offense_
season/vegas_odds/coach_table that scripts/load_nflverse.py derived directly
from nflverse/nfldata, once this richer, PFR-sourced export arrived.

Usage:
    python3 scripts/load_coaching_and_offense.py

Safe to re-run: each table is deleted and reloaded from the CSVs every time,
so these CSVs are the source of truth for these 6 tables, not a one-time
import. Requires schema/duckdb_schema.sql to already be applied (run
scripts/build_db.py first if analytics.duckdb doesn't exist yet).
"""
import os
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
DUCKDB_PATH = os.path.join(DATA_DIR, "analytics.duckdb")
COACHING_DATA_DIR = os.path.join(DATA_DIR, "coaching_and_offense")

# (table_name, csv_path relative to data/coaching_and_offense/)
TABLES = [
    ("coach_table", "coach_effects/coach_table.csv"),
    ("team_offense_season", "offense_analysis/team_offense_ranked.csv"),
    ("vegas_odds", "offense_analysis/vegas_vs_offense.csv"),
    ("team_primary_qb", "offense_analysis/team_primary_qb_id.csv"),
    ("player_offense_rank", "offense_analysis/player_season_with_offense_rank.csv"),
    ("coach_tenure_segments", "offense_analysis/all_coach_tenure_segments.csv"),
]


def log(msg):
    print(f"[load_coaching_and_offense] {msg}")


def main():
    if not os.path.exists(DUCKDB_PATH):
        log("analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    conn = duckdb.connect(DUCKDB_PATH)

    for table, rel_csv in TABLES:
        csv_path = os.path.join(COACHING_DATA_DIR, rel_csv)
        if not os.path.exists(csv_path):
            log(f"SKIP {table}: {csv_path} not found")
            continue
        # Select only the columns the schema defines, in schema order, so an
        # extra or differently-ordered column in the source CSV can't break
        # the load (team_offense_ranked.csv and vegas_vs_offense.csv share
        # most of their columns with each other, for instance).
        col_names = [
            row[0] for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position",
                [table],
            ).fetchall()
        ]
        col_list = ", ".join(f'"{c}"' for c in col_names)
        conn.execute(f"DELETE FROM {table}")
        conn.execute(
            f"INSERT INTO {table} SELECT {col_list} "
            f"FROM read_csv_auto('{csv_path}', HEADER=TRUE)"
        )
        n = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        log(f"loaded {table}: {n} rows from {rel_csv}")

    conn.close()
    log("done.")


if __name__ == "__main__":
    main()
