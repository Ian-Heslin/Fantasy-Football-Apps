#!/usr/bin/env python3
"""
load_nflverse.py -- populates analytics.duckdb's play_by_play table from
nflverse-data's public GitHub release assets: one CSV.gz per season,
downloaded and unioned into a single table.

Reachable from this sandbox even though api.sleeper.app and ordinary
websites (footballguys, FantasyPros, pro-football-reference) aren't --
everything here comes from github.com/raw.githubusercontent.com.

NOTE: team_offense_season, vegas_odds, and coach_table used to be derived
here too (from play_by_play + nflverse/nfldata's games.csv). That's been
superseded by scripts/load_coaching_and_offense.py, which loads a richer,
Pro-Football-Reference-sourced version of all three (plus team_primary_qb,
player_offense_rank, and coach_tenure_segments) from a separate Cowork
session's v13-v18 coaching/offense research -- see
data/coaching_and_offense/ and docs/breakout-falloff-methodology.md. Run
that script after this one.

adp_history is NOT populated by this script: its sources (footballguys.com,
FantasyPros) are ordinary websites, not GitHub-hosted, and are blocked by
this sandbox's egress policy the same way api.sleeper.app is.

Usage:
    python3 scripts/load_nflverse.py                  # seasons 1999-2025
    python3 scripts/load_nflverse.py --start 2015      # 2015-2025
    python3 scripts/load_nflverse.py --start 2020 --end 2023

Safe to re-run: play_by_play is a full rebuild each run (CREATE OR REPLACE),
and downloaded season files are cached locally and skipped if already
present.
"""
import argparse
import os
import sqlite3
import sys

import duckdb
import requests

from seasons import EARLIEST_PBP_SEASON, current_season

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SQLITE_PATH = os.path.join(DATA_DIR, "app.db")
DUCKDB_PATH = os.path.join(DATA_DIR, "analytics.duckdb")
PBP_CACHE_DIR = os.path.join(DATA_DIR, "_nflverse_data", "pbp_cache")

PBP_RELEASE_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz"
EARLIEST_SEASON = EARLIEST_PBP_SEASON
# Derived, not pinned: a hardcoded LATEST_SEASON silently stops pulling
# new play-by-play the moment the calendar rolls past it, and everything
# downstream (fantasy points, the Weekly Top Scorers trivia game) just
# stops moving forward with no error. --season-max overrides it.
LATEST_SEASON = current_season()


def log(msg):
    print(f"[load_nflverse] {msg}")


def download_play_by_play(seasons):
    """Download each season's play-by-play CSV.gz from nflverse-data's
    GitHub release assets, skipping any already cached locally."""
    os.makedirs(PBP_CACHE_DIR, exist_ok=True)
    paths = []
    for season in seasons:
        dest = os.path.join(PBP_CACHE_DIR, f"play_by_play_{season}.csv.gz")
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            log(f"{season}: already cached, skipping download")
            paths.append(dest)
            continue
        url = PBP_RELEASE_URL.format(season=season)
        log(f"{season}: downloading {url}")
        resp = requests.get(url, timeout=120, stream=True)
        if resp.status_code == 404:
            log(f"{season}: no play-by-play release for this season, skipping")
            resp.close()
            continue
        resp.raise_for_status()
        tmp = dest + ".partial"
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        os.rename(tmp, dest)
        paths.append(dest)
    return paths


def load_play_by_play(duckdb_conn, cached_paths):
    """Union all cached season files into one table. union_by_name handles
    the column set changing slightly release to release (nflverse adds
    columns over time) by aligning on column name and filling NULL where a
    given season's file doesn't have a column another season does."""
    if not cached_paths:
        log("no play_by_play files downloaded, skipping table build")
        return 0
    glob = os.path.join(PBP_CACHE_DIR, "play_by_play_*.csv.gz")
    duckdb_conn.execute(f"""
        CREATE OR REPLACE TABLE play_by_play AS
        SELECT * FROM read_csv_auto('{glob}', union_by_name=true)
    """)
    count = duckdb_conn.execute("SELECT count(*) FROM play_by_play").fetchone()[0]
    seasons = duckdb_conn.execute(
        "SELECT min(season), max(season) FROM play_by_play"
    ).fetchone()
    log(f"play_by_play: {count} rows, seasons {seasons[0]}-{seasons[1]}")
    return count


def update_sync_log(table_name, source, row_count, notes=""):
    conn = sqlite3.connect(SQLITE_PATH)
    conn.execute(
        """INSERT INTO sync_log (table_name, source, last_synced_at, row_count, notes)
           VALUES (?, ?, datetime('now'), ?, ?)
           ON CONFLICT(table_name) DO UPDATE SET
               source=excluded.source, last_synced_at=datetime('now'),
               row_count=excluded.row_count, notes=excluded.notes""",
        (table_name, source, row_count, notes),
    )
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=EARLIEST_SEASON,
                         help=f"first season to load (default {EARLIEST_SEASON}, "
                              f"the earliest nflverse has)")
    parser.add_argument("--end", type=int, default=None,
                         help=f"last season to load (default {LATEST_SEASON}, "
                              f"the most recently completed season)")
    args = parser.parse_args()
    end = args.end or LATEST_SEASON
    seasons = list(range(args.start, end + 1))

    if not os.path.exists(SQLITE_PATH) or not os.path.exists(DUCKDB_PATH):
        log("app.db / analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    duckdb_conn = duckdb.connect(DUCKDB_PATH)

    log(f"loading seasons {seasons[0]}-{seasons[-1]}")
    cached_paths = download_play_by_play(seasons)
    n_pbp = load_play_by_play(duckdb_conn, cached_paths)

    duckdb_conn.close()

    update_sync_log("play_by_play", "nflverse-data (GitHub release, pbp tag)", n_pbp,
                     notes=f"seasons {seasons[0]}-{seasons[-1]}")

    log("done.")


if __name__ == "__main__":
    main()
