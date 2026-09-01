#!/usr/bin/env python3
"""
load_trivia_data.py -- loads the trivia games' reference/answer data into
analytics.duckdb, from the committed CSVs under data/trivia/. Those CSVs
are a one-time export from a personal spreadsheet of games Ian's played
with friends (award-winner-by-year, all-time-leader-by-rank, and a
"draft any player from any year" redraft game) -- there's no live source
to re-fetch this from, unlike everything else this project loads, so the
extracted data is committed directly and this script just loads it.

Usage:
    python3 scripts/load_trivia_data.py
"""
import csv
import os
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUCKDB_PATH = os.path.join(ROOT, "data", "analytics.duckdb")
DATA_DIR = os.path.join(ROOT, "data", "trivia")


def log(msg):
    print(f"[load_trivia_data] {msg}")


def _int_or_none(v):
    return int(float(v)) if v not in (None, "") else None


def _float_or_none(v):
    return float(v) if v not in (None, "") else None


def load_award_winners(conn):
    with open(os.path.join(DATA_DIR, "award_winners.csv")) as f:
        rows = [
            (r["category"], int(r["year"]), r["position"] or None, r["player"], r["team"] or None)
            for r in csv.DictReader(f)
        ]
    conn.execute("DELETE FROM trivia_award_winners")
    conn.executemany(
        "INSERT INTO trivia_award_winners (category, year, position, player, team) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    log(f"trivia_award_winners: loaded {len(rows)} rows")


def load_season_leaders(conn):
    with open(os.path.join(DATA_DIR, "season_leaders.csv")) as f:
        rows = [
            (r["category"], int(r["rank"]), r["player"], _float_or_none(r["stat_value"]),
             r["years_active"] or None, r["team_clue"] or None)
            for r in csv.DictReader(f)
        ]
    conn.execute("DELETE FROM trivia_season_leaders")
    conn.executemany(
        """INSERT INTO trivia_season_leaders (category, rank, player, stat_value, years_active, team_clue)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    log(f"trivia_season_leaders: loaded {len(rows)} rows")


def load_fantasy_draft_stats(conn):
    with open(os.path.join(DATA_DIR, "fantasy_draft_stats.csv")) as f:
        rows = [
            (int(r["year"]), r["player"], r["team"] or None, r["position"],
             _int_or_none(r["games"]), _float_or_none(r["fant_pt"]), _float_or_none(r["ppr_pt"]))
            for r in csv.DictReader(f)
        ]
    conn.execute("DELETE FROM fantasy_draft_stats")
    conn.executemany(
        """INSERT INTO fantasy_draft_stats (year, player, team, position, games, fant_pt, ppr_pt)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    years = conn.execute("SELECT min(year), max(year) FROM fantasy_draft_stats").fetchone()
    log(f"fantasy_draft_stats: loaded {len(rows)} rows, years {years[0]}-{years[1]}")


def main():
    if not os.path.exists(DUCKDB_PATH):
        log("analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    conn = duckdb.connect(DUCKDB_PATH)
    load_award_winners(conn)
    load_season_leaders(conn)
    load_fantasy_draft_stats(conn)
    conn.close()
    log("done.")


if __name__ == "__main__":
    main()
