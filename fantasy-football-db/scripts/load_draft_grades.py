#!/usr/bin/env python3
"""
load_draft_grades.py -- loads pre-draft evaluation data into
analytics.duckdb's draft_prospect_grades table.

NOT a multi-analyst "consensus big board" -- no clean historical version
of that was found to be freely reachable (NFL Mock Draft Database runs
one, but it's an ordinary website blocked from this project's sandbox,
and full export needs a paid tier anyway). This is NFL.com's own
prospect grade + Next Gen Stats' draft grade for every combine invitee,
2006-2025 (2021 has zero rows -- no combine grading that cycle), from
github.com/array-carpenter/nfl-draft-data -- a single, methodologically
consistent pre-draft evaluation across 20 seasons, which is arguably a
cleaner basis for "drafted higher than the evaluation implied" than
stitching together incomparable analyst boards year to year would be.

Reachable from this sandbox (github.com/raw.githubusercontent.com, same
as everywhere else in this project).

Usage:
    python3 scripts/load_draft_grades.py
"""
import csv
import io
import os
import sys

import duckdb
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUCKDB_PATH = os.path.join(ROOT, "data", "analytics.duckdb")
SOURCE_URL = "https://raw.githubusercontent.com/array-carpenter/nfl-draft-data/master/data/combine_official.csv"


def log(msg):
    print(f"[load_draft_grades] {msg}")


def main():
    if not os.path.exists(DUCKDB_PATH):
        log("analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    log(f"downloading {SOURCE_URL}")
    resp = requests.get(SOURCE_URL, timeout=60)
    resp.raise_for_status()

    rows = []
    for r in csv.DictReader(io.StringIO(resp.text)):
        rows.append((
            int(r["year"]),
            r["player"],
            r["college"] or None,
            r["position"] or None,
            float(r["grade"]) if r.get("grade") else None,
            float(r["draft_grade"]) if r.get("draft_grade") else None,
            r["draft_projection"] or None,
        ))

    conn = duckdb.connect(DUCKDB_PATH)
    conn.execute("DELETE FROM draft_prospect_grades")
    conn.executemany(
        """INSERT INTO draft_prospect_grades
               (year, player_name, college, position, nfl_grade, ngs_draft_grade, draft_projection)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    n = conn.execute("SELECT count(*) FROM draft_prospect_grades").fetchone()[0]
    years = conn.execute("SELECT min(year), max(year) FROM draft_prospect_grades").fetchone()
    conn.close()

    log(f"loaded {n} rows, years {years[0]}-{years[1]}")
    log("done.")


if __name__ == "__main__":
    main()
