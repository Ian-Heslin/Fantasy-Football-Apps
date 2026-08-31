#!/usr/bin/env python3
"""
backfill_vegas_actual_wins.py -- fills in actual_wins/actual_losses/
actual_ties/over_under_result for any vegas_odds row that has a win_total_
line (preseason data, known before the season) but no actual result yet
(because the season hadn't finished when that data was compiled).

Source: nflverse/nfldata's standings.csv, the same nflverse ecosystem
already used elsewhere in this project (team abbreviations match
vegas_odds/team_offense_season exactly -- no crosswalk needed).

Only backfills rows where actual_wins IS NULL -- never overwrites the
existing PFR-sourced historical results already loaded by
load_coaching_and_offense.py. Safe to re-run any time a season wraps up
and nfldata's standings.csv picks up the final results.

Usage:
    python3 scripts/backfill_vegas_actual_wins.py
"""
import csv
import os
import subprocess
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
DUCKDB_PATH = os.path.join(DATA_DIR, "analytics.duckdb")
NFLDATA_CLONE_DIR = os.path.join(DATA_DIR, "_nflverse_data", "nfldata")


def log(msg):
    print(f"[backfill_vegas_actual_wins] {msg}")


def clone_or_refresh_nfldata():
    # fetch + reset --hard, NOT pull: a shallow clone's "pull" tries to
    # merge/rebase onto the fetched history, which fails outright if
    # nfldata's upstream master was ever force-pushed (confirmed this
    # actually happens, while building scripts/load_pickem_schedule.py).
    # fetch+reset just snaps the local branch to whatever origin/master
    # currently is, which is really what a read-only mirror wants anyway.
    # nfldata's default branch is "master", not "main" (a mismatch that
    # broke an even earlier version of this script).
    if os.path.isdir(os.path.join(NFLDATA_CLONE_DIR, ".git")):
        log("nflverse/nfldata already cloned, refreshing...")
        subprocess.run(
            ["git", "-C", NFLDATA_CLONE_DIR, "fetch", "--depth", "1", "origin", "master"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", NFLDATA_CLONE_DIR, "reset", "--hard", "origin/master"],
            check=True,
        )
    else:
        log("cloning nflverse/nfldata (shallow)...")
        subprocess.run(
            [
                "git", "clone", "--depth", "1",
                "https://github.com/nflverse/nfldata.git",
                NFLDATA_CLONE_DIR,
            ],
            check=True,
        )


def load_standings():
    path = os.path.join(NFLDATA_CLONE_DIR, "data", "standings.csv")
    standings = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                season = int(r["season"])
                wins, losses, ties = float(r["wins"]), float(r["losses"]), float(r["ties"])
            except (ValueError, KeyError):
                continue
            standings[(season, r["team"])] = (wins, losses, ties)
    return standings


def main():
    if not os.path.exists(DUCKDB_PATH):
        log("analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    conn = duckdb.connect(DUCKDB_PATH)

    missing = conn.execute(
        "SELECT season, team, win_total_line FROM vegas_odds WHERE actual_wins IS NULL"
    ).fetchall()
    if not missing:
        log("nothing to backfill -- every vegas_odds row already has actual_wins.")
        conn.close()
        return

    seasons_needed = sorted({season for season, _, _ in missing})
    log(f"{len(missing)} rows missing actual_wins, seasons {seasons_needed}")

    clone_or_refresh_nfldata()
    standings = load_standings()

    updated = 0
    still_missing = []
    for season, team, win_total_line in missing:
        result = standings.get((season, team))
        if result is None:
            still_missing.append((season, team))
            continue
        wins, losses, ties = result
        if win_total_line is None:
            over_under = None
        elif wins > win_total_line:
            over_under = "over"
        elif wins < win_total_line:
            over_under = "under"
        else:
            over_under = "push"
        conn.execute(
            """UPDATE vegas_odds
               SET actual_wins = ?, actual_losses = ?, actual_ties = ?, over_under_result = ?
               WHERE season = ? AND team = ?""",
            (wins, losses, ties, over_under, season, team),
        )
        updated += 1

    log(f"backfilled {updated} rows")
    if still_missing:
        log(f"WARNING: {len(still_missing)} rows still have no standings match "
            f"(season not yet in nfldata's standings.csv): {still_missing}")

    conn.close()
    log("done.")


if __name__ == "__main__":
    main()
