#!/usr/bin/env python3
"""
load_player_stats.py -- loads nflverse's season-level player fantasy stats
and player biographical/draft data into analytics.duckdb. These are the
raw ingredients the breakout/fall-off model (docs/breakout-falloff-
methodology.md) needs on top of player_offense_rank (which already has
PPG/tier per player-season, from a separate Cowork session's export, but
not touches/dropbacks/EPA-per-touch/draft pedigree/birth date).

  player_stats_season   one row per player per season: fantasy_points_ppr,
                        games, carries/targets/attempts (for touches and
                        dropbacks), rushing_epa/receiving_epa/passing_epa
                        (for epa_per_touch). Source: nflverse-data's
                        player_stats release (same file the methodology
                        doc validated its hand-computed PPG against).
  player_bio            one row per player: birth_date (for age), draft_
                        year/round/pick, rookie_season. Source: nflverse-
                        data's players release.

Both are reachable from this sandbox the same way play_by_play is --
github.com release assets, not a platform API.

Usage:
    python3 scripts/load_player_stats.py

Safe to re-run: both tables are full rebuilds each run (CREATE OR REPLACE).
"""
import os
import sys

import duckdb
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
DUCKDB_PATH = os.path.join(DATA_DIR, "analytics.duckdb")
CACHE_DIR = os.path.join(DATA_DIR, "_nflverse_data", "player_stats_cache")

PLAYER_STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats_season.csv.gz"
PLAYERS_URL = "https://github.com/nflverse/nflverse-data/releases/download/players/players.csv"


def log(msg):
    print(f"[load_player_stats] {msg}")


def download(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        log(f"already cached: {os.path.basename(dest)}")
        return dest
    log(f"downloading {url}")
    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    tmp = dest + ".partial"
    with open(tmp, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    os.rename(tmp, dest)
    return dest


def main():
    if not os.path.exists(DUCKDB_PATH):
        log("analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    os.makedirs(CACHE_DIR, exist_ok=True)
    stats_path = download(PLAYER_STATS_URL, os.path.join(CACHE_DIR, "player_stats_season.csv.gz"))
    players_path = download(PLAYERS_URL, os.path.join(CACHE_DIR, "players.csv"))

    conn = duckdb.connect(DUCKDB_PATH)

    conn.execute(f"""
        CREATE OR REPLACE TABLE player_stats_season AS
        SELECT * FROM read_csv_auto('{stats_path}')
        WHERE season_type = 'REG'
    """)
    n_stats = conn.execute("SELECT count(*) FROM player_stats_season").fetchone()[0]
    log(f"player_stats_season: {n_stats} rows (regular season only)")

    conn.execute(f"""
        CREATE OR REPLACE TABLE player_bio AS
        SELECT gsis_id, display_name, position, birth_date, college_name,
               rookie_season, last_season, draft_year, draft_round, draft_pick
        FROM read_csv_auto('{players_path}')
        WHERE gsis_id IS NOT NULL
    """)
    n_bio = conn.execute("SELECT count(*) FROM player_bio").fetchone()[0]
    log(f"player_bio: {n_bio} rows")

    conn.close()
    log("done.")


if __name__ == "__main__":
    main()
