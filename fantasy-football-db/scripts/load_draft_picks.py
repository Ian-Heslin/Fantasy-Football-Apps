#!/usr/bin/env python3
"""
load_draft_picks.py -- loads actual draft results + career outcomes into
analytics.duckdb's draft_picks table, from nflverse-data's richer
draft_picks release (not nfldata's thinner data/draft_picks.csv mirror --
this one has approximate value and Pro Bowl/All-Pro counts, needed to
test whether reaches actually underperform).

Reachable from this sandbox (github.com release asset, same as
play_by_play elsewhere in this project).

Usage:
    python3 scripts/load_draft_picks.py
"""
import csv
import io
import os
import sys

import duckdb
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUCKDB_PATH = os.path.join(ROOT, "data", "analytics.duckdb")
SOURCE_URL = "https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv"


def log(msg):
    print(f"[load_draft_picks] {msg}")


def _int_or_none(v):
    return int(float(v)) if v else None


def _float_or_none(v):
    return float(v) if v else None


def main():
    if not os.path.exists(DUCKDB_PATH):
        log("analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    log(f"downloading {SOURCE_URL}")
    resp = requests.get(SOURCE_URL, timeout=60)
    resp.raise_for_status()

    rows = []
    for r in csv.DictReader(io.StringIO(resp.text)):
        if not r.get("season") or not r.get("pick"):
            continue
        rows.append((
            int(r["season"]),
            _int_or_none(r.get("round")),
            int(r["pick"]),
            r["team"] or None,
            r.get("gsis_id") or None,
            r.get("pfr_player_id") or None,
            r["pfr_player_name"],
            r.get("position") or None,
            r.get("college") or None,
            _float_or_none(r.get("age")),
            _int_or_none(r.get("games")),
            _int_or_none(r.get("allpro")),
            _int_or_none(r.get("probowls")),
            _int_or_none(r.get("seasons_started")),
            _float_or_none(r.get("w_av")),
        ))

    conn = duckdb.connect(DUCKDB_PATH)
    conn.execute("DELETE FROM draft_picks")
    conn.executemany(
        """INSERT INTO draft_picks
               (season, round, pick, team, gsis_id, pfr_player_id, player_name, position,
                college, age, games, allpro, probowls, seasons_started, w_av)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    n = conn.execute("SELECT count(*) FROM draft_picks").fetchone()[0]
    years = conn.execute("SELECT min(season), max(season) FROM draft_picks").fetchone()
    conn.close()

    log(f"loaded {n} rows, seasons {years[0]}-{years[1]}")
    log("done.")


if __name__ == "__main__":
    main()
