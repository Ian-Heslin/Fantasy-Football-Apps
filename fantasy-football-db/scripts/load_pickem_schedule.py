#!/usr/bin/env python3
"""
load_pickem_schedule.py -- pulls the real NFL schedule, closing spreads,
and (once games are played) final scores from nflverse/nfldata's
games.csv into app.db's pickem_games table.

Regular season only (game_type == 'REG') -- Pick'em doesn't cover preseason
or playoffs. spread_line's sign convention (POSITIVE = home team favored)
was verified empirically against ~2,900 real games' actual results while
building this, not assumed -- see the schema comment on pickem_games.

Safe/expected to re-run periodically during the season: scores and
is_final flip in as games finish, spreads can still move slightly before
lock, so this just re-pulls and upserts every time rather than only
loading once.

Usage:
    python3 scripts/load_pickem_schedule.py
    python3 scripts/load_pickem_schedule.py --season 2025   # backfill an older season
"""
import argparse
import csv
import os
import sqlite3
import subprocess
import sys

from seasons import current_season

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SQLITE_PATH = os.path.join(DATA_DIR, "app.db")
NFLDATA_CLONE_DIR = os.path.join(DATA_DIR, "_nflverse_data", "nfldata")


def log(msg):
    print(f"[load_pickem_schedule] {msg}")


def clone_or_refresh_nfldata():
    # fetch + reset --hard, NOT pull: a shallow clone's "pull" tries to
    # merge/rebase onto the fetched history, which fails outright if
    # nfldata's upstream master was ever force-pushed (confirmed this
    # actually happens -- hit a "divergent branches" error building this).
    # fetch+reset just snaps the local branch to whatever origin/master
    # currently is, which is really what a read-only mirror wants anyway.
    if os.path.isdir(os.path.join(NFLDATA_CLONE_DIR, ".git")):
        log("nflverse/nfldata already cloned, refreshing...")
        subprocess.run(["git", "-C", NFLDATA_CLONE_DIR, "fetch", "--depth", "1", "origin", "master"], check=True)
        subprocess.run(["git", "-C", NFLDATA_CLONE_DIR, "reset", "--hard", "origin/master"], check=True)
    else:
        log("cloning nflverse/nfldata (shallow)...")
        subprocess.run(
            ["git", "clone", "--depth", "1", "https://github.com/nflverse/nfldata.git", NFLDATA_CLONE_DIR],
            check=True,
        )


def load_games(season):
    path = os.path.join(NFLDATA_CLONE_DIR, "data", "games.csv")
    games = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("game_type") != "REG" or int(r["season"]) != season:
                continue
            kickoff_at = r["gameday"]
            if r.get("gametime"):
                kickoff_at = f"{r['gameday']}T{r['gametime']}"
            games.append({
                "game_id": r["game_id"],
                "season": int(r["season"]),
                "week": int(r["week"]),
                "home_team": r["home_team"],
                "away_team": r["away_team"],
                "kickoff_at": kickoff_at,
                "spread_line": float(r["spread_line"]) if r.get("spread_line") else None,
                "home_score": int(r["home_score"]) if r.get("home_score") else None,
                "away_score": int(r["away_score"]) if r.get("away_score") else None,
                "is_final": 1 if r.get("home_score") and r.get("away_score") else 0,
            })
    return games


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=None,
                         help="season to load (default: the current NFL season)")
    args = parser.parse_args()
    season = args.season or current_season()

    if not os.path.exists(SQLITE_PATH):
        log("app.db not found -- run scripts/build_db.py first.")
        sys.exit(1)

    clone_or_refresh_nfldata()
    games = load_games(season)
    if not games:
        # Exit non-zero rather than logging and returning 0. This is the
        # shape a silent failure takes -- nfldata not yet carrying next
        # season, or a --season typo -- and a scheduled run that "passes"
        # while loading nothing leaves Pick'em serving a stale season.
        log(f"ERROR: no {season} regular-season games found in games.csv -- nothing loaded.")
        sys.exit(1)

    conn = sqlite3.connect(SQLITE_PATH)
    for g in games:
        conn.execute(
            """INSERT INTO pickem_games
                   (game_id, season, week, home_team, away_team, kickoff_at,
                    spread_line, home_score, away_score, is_final)
               VALUES (:game_id, :season, :week, :home_team, :away_team, :kickoff_at,
                       :spread_line, :home_score, :away_score, :is_final)
               ON CONFLICT(game_id) DO UPDATE SET
                   kickoff_at=excluded.kickoff_at, spread_line=excluded.spread_line,
                   home_score=excluded.home_score, away_score=excluded.away_score,
                   is_final=excluded.is_final""",
            g,
        )
    conn.execute(
        """INSERT INTO sync_log (table_name, source, last_synced_at, row_count, notes)
           VALUES ('pickem_games', 'nflverse/nfldata', datetime('now'), ?, ?)
           ON CONFLICT(table_name) DO UPDATE SET
               last_synced_at=datetime('now'), row_count=excluded.row_count, notes=excluded.notes""",
        (len(games), f"season {season}, regular season only"),
    )
    conn.commit()
    conn.close()

    n_final = sum(1 for g in games if g["is_final"])
    log(f"loaded {len(games)} games for {season} ({n_final} final)")
    log("done.")


if __name__ == "__main__":
    main()
