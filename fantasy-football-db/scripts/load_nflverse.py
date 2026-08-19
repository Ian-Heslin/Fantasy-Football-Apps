#!/usr/bin/env python3
"""
load_nflverse.py -- populates analytics.duckdb's historical tables from
nflverse's public, no-auth data:

  play_by_play         raw nflverse play-by-play, one CSV.gz per season,
                        downloaded from nflverse-data's GitHub release
                        assets and unioned into a single table.
  team_offense_season   derived from play_by_play (EPA/play) + nfldata's
                        games.csv (points, so PPG is exact final scores
                        rather than reconstructed from play-level state).
  vegas_odds            nfldata's win_totals.csv (preseason win total line)
                        joined to standings.csv (actual wins). No Super Bowl
                        odds source was available from this sandbox's
                        network -- sb_odds stays NULL until one is.
  coach_table           derived from nfldata's games.csv home_coach/
                        away_coach columns. This only gives head coaches
                        (role='HC') -- games.csv has no OC/DC/position-coach
                        data, so those rows still need a separate source.

adp_history is NOT populated by this script: its sources (footballguys.com,
FantasyPros) are ordinary websites, not GitHub-hosted, and are blocked by
this sandbox's egress policy the same way api.sleeper.app is. Everything
above uses github.com/raw.githubusercontent.com, which this sandbox can
reach.

Usage:
    python3 scripts/load_nflverse.py                  # seasons 1999-2025
    python3 scripts/load_nflverse.py --start 2015      # 2015-2025
    python3 scripts/load_nflverse.py --start 2020 --end 2023

Safe to re-run: play_by_play/team_offense_season/vegas_odds are full
rebuilds each run (CREATE OR REPLACE / DELETE+INSERT), and downloaded
season files are cached locally and skipped if already present.
"""
import argparse
import os
import sqlite3
import subprocess
import sys

import duckdb
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SQLITE_PATH = os.path.join(DATA_DIR, "app.db")
DUCKDB_PATH = os.path.join(DATA_DIR, "analytics.duckdb")
NFLVERSE_DIR = os.path.join(DATA_DIR, "_nflverse_data")
PBP_CACHE_DIR = os.path.join(NFLVERSE_DIR, "pbp_cache")
NFLDATA_CLONE_DIR = os.path.join(NFLVERSE_DIR, "nfldata")

PBP_RELEASE_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz"
EARLIEST_SEASON = 1999


def log(msg):
    print(f"[load_nflverse] {msg}")


def ensure_dirs():
    os.makedirs(PBP_CACHE_DIR, exist_ok=True)


def download_play_by_play(seasons):
    """Download each season's play-by-play CSV.gz from nflverse-data's
    GitHub release assets, skipping any already cached locally."""
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


def clone_or_refresh_nfldata():
    """Shallow-clone nflverse/nfldata (games.csv, win_totals.csv,
    standings.csv), or pull if it's already cloned."""
    if os.path.isdir(os.path.join(NFLDATA_CLONE_DIR, ".git")):
        log("nflverse/nfldata already cloned, pulling latest...")
        subprocess.run(
            ["git", "-C", NFLDATA_CLONE_DIR, "pull", "--depth", "1"],
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


def derive_team_offense_season(duckdb_conn, min_season, max_season):
    """PPG comes from nfldata's games.csv final scores (exact and simple);
    YPG and EPA/play come from play_by_play itself. Regular season only --
    playoff sample sizes are small and uneven across teams."""
    games_csv = os.path.join(NFLDATA_CLONE_DIR, "data", "games.csv")
    duckdb_conn.execute(f"""
        CREATE OR REPLACE TEMP TABLE _team_games AS
        SELECT season, home_team AS team, home_score AS points_for, game_id
        FROM read_csv_auto('{games_csv}')
        WHERE game_type = 'REG' AND home_score IS NOT NULL
              AND season BETWEEN {min_season} AND {max_season}
        UNION ALL
        SELECT season, away_team AS team, away_score AS points_for, game_id
        FROM read_csv_auto('{games_csv}')
        WHERE game_type = 'REG' AND away_score IS NOT NULL
              AND season BETWEEN {min_season} AND {max_season}
    """)

    duckdb_conn.execute(f"""
        CREATE OR REPLACE TEMP TABLE _team_yards AS
        SELECT season, posteam AS team, game_id, sum(yards_gained) AS yards
        FROM play_by_play
        WHERE season_type = 'REG' AND posteam IS NOT NULL
              AND play_type IN ('pass', 'run')
              AND season BETWEEN {min_season} AND {max_season}
        GROUP BY season, posteam, game_id
    """)

    duckdb_conn.execute(f"""
        CREATE OR REPLACE TEMP TABLE _team_epa AS
        SELECT season, posteam AS team, avg(epa) AS epa_per_play
        FROM play_by_play
        WHERE season_type = 'REG' AND posteam IS NOT NULL
              AND play_type IN ('pass', 'run') AND epa IS NOT NULL
              AND season BETWEEN {min_season} AND {max_season}
        GROUP BY season, posteam
    """)

    duckdb_conn.execute("DELETE FROM team_offense_season")
    duckdb_conn.execute("""
        INSERT INTO team_offense_season
            (season, team, ppg, ypg, epa_per_play, rank_ppg, rank_ypg, rank_epa)
        WITH base AS (
            SELECT
                g.season, g.team,
                avg(g.points_for) AS ppg,
                (SELECT avg(y.yards) FROM _team_yards y
                 WHERE y.season = g.season AND y.team = g.team) AS ypg,
                (SELECT e.epa_per_play FROM _team_epa e
                 WHERE e.season = g.season AND e.team = g.team) AS epa_per_play
            FROM _team_games g
            GROUP BY g.season, g.team
        )
        SELECT
            season, team, ppg, ypg, epa_per_play,
            rank() OVER (PARTITION BY season ORDER BY ppg DESC) AS rank_ppg,
            rank() OVER (PARTITION BY season ORDER BY ypg DESC) AS rank_ypg,
            rank() OVER (PARTITION BY season ORDER BY epa_per_play DESC) AS rank_epa
        FROM base
    """)
    count = duckdb_conn.execute("SELECT count(*) FROM team_offense_season").fetchone()[0]
    log(f"team_offense_season: {count} team-season rows")
    return count


def load_vegas_odds(duckdb_conn, min_season, max_season):
    """win_totals.csv has the preseason win-total line; standings.csv has
    actual wins. No Super Bowl odds source reachable here -- sb_odds is
    left NULL rather than guessed. NOTE: nfldata's win_totals.csv only goes
    up to the 2020 season as of this writing -- seasons after that will
    come back with 0 rows until nflverse (or another reachable source)
    publishes newer win totals."""
    win_totals_csv = os.path.join(NFLDATA_CLONE_DIR, "data", "win_totals.csv")
    standings_csv = os.path.join(NFLDATA_CLONE_DIR, "data", "standings.csv")

    duckdb_conn.execute("DELETE FROM vegas_odds")
    duckdb_conn.execute(f"""
        INSERT INTO vegas_odds (season, team, win_total_line, sb_odds, actual_wins)
        SELECT
            w.season, w.team, w.line AS win_total_line,
            NULL AS sb_odds,
            s.wins AS actual_wins
        FROM read_csv_auto('{win_totals_csv}') w
        LEFT JOIN read_csv_auto('{standings_csv}') s
            ON s.season = w.season AND s.team = w.team
        WHERE w.season BETWEEN {min_season} AND {max_season}
    """)
    count = duckdb_conn.execute("SELECT count(*) FROM vegas_odds").fetchone()[0]
    log(f"vegas_odds: {count} team-season rows (sb_odds not sourced -- left NULL)")
    return count


def load_coach_table(duckdb_conn, min_season, max_season):
    """games.csv only carries head coach per game -- take the coach who
    appears in the most games for that team-season as the season's HC,
    which handles an in-season interim-coach change reasonably (majority
    of games decide it). Ties (e.g. a coach fired exactly at midseason)
    break on coach_name so exactly one row comes out per team-season.
    OC/DC/position coaches aren't in this source."""
    games_csv = os.path.join(NFLDATA_CLONE_DIR, "data", "games.csv")

    duckdb_conn.execute("DELETE FROM coach_table WHERE role = 'HC'")
    duckdb_conn.execute(f"""
        INSERT INTO coach_table (season, team, role, coach_name)
        WITH team_games AS (
            SELECT season, home_team AS team, home_coach AS coach_name
            FROM read_csv_auto('{games_csv}')
            WHERE home_coach IS NOT NULL
                  AND season BETWEEN {min_season} AND {max_season}
            UNION ALL
            SELECT season, away_team AS team, away_coach AS coach_name
            FROM read_csv_auto('{games_csv}')
            WHERE away_coach IS NOT NULL
                  AND season BETWEEN {min_season} AND {max_season}
        ),
        counted AS (
            SELECT season, team, coach_name, count(*) AS n
            FROM team_games
            GROUP BY season, team, coach_name
        ),
        ranked AS (
            SELECT *, row_number() OVER (
                PARTITION BY season, team ORDER BY n DESC, coach_name
            ) AS rnk
            FROM counted
        )
        SELECT season, team, 'HC' AS role, coach_name
        FROM ranked
        WHERE rnk = 1
    """)
    count = duckdb_conn.execute(
        "SELECT count(*) FROM coach_table WHERE role = 'HC'"
    ).fetchone()[0]
    log(f"coach_table: {count} team-season HC rows (OC/DC/position coaches not sourced here)")
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
                         help="last season to load (default: current year - 1, "
                              "i.e. the most recently completed season)")
    args = parser.parse_args()
    end = args.end or 2025
    seasons = list(range(args.start, end + 1))

    if not os.path.exists(SQLITE_PATH) or not os.path.exists(DUCKDB_PATH):
        log("app.db / analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    ensure_dirs()
    duckdb_conn = duckdb.connect(DUCKDB_PATH)

    log(f"loading seasons {seasons[0]}-{seasons[-1]}")
    cached_paths = download_play_by_play(seasons)
    n_pbp = load_play_by_play(duckdb_conn, cached_paths)

    clone_or_refresh_nfldata()
    n_offense = derive_team_offense_season(duckdb_conn, args.start, end)
    n_odds = load_vegas_odds(duckdb_conn, args.start, end)
    n_coach = load_coach_table(duckdb_conn, args.start, end)

    duckdb_conn.close()

    update_sync_log("play_by_play", "nflverse-data (GitHub release, pbp tag)", n_pbp,
                     notes=f"seasons {seasons[0]}-{seasons[-1]}")
    update_sync_log("team_offense_season", "derived from play_by_play + nfldata/games.csv",
                     n_offense)
    update_sync_log("vegas_odds", "nfldata/win_totals.csv + standings.csv", n_odds,
                     notes="sb_odds not sourced -- left NULL")
    update_sync_log("coach_table", "nfldata/games.csv (home_coach/away_coach)", n_coach,
                     notes="HC only -- OC/DC/position coaches not sourced")

    log("done.")


if __name__ == "__main__":
    main()
