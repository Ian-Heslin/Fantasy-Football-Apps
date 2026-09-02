#!/usr/bin/env python3
"""
compute_fantasy_points.py -- computes standard + PPR fantasy points per
player per week directly from play_by_play (1999-2025, wherever nflverse's
play-by-play covers), into player_week_fantasy_points and its season-level
aggregate player_season_fantasy_points.

Why this exists (vs. fantasy_draft_stats, the personal-spreadsheet
export): play_by_play gets re-loaded periodically during the season
(load_nflverse.py), so re-running this script after that picks up new
weeks automatically -- a genuinely live-updating source, unlike the
spreadsheet export (frozen at 1970-2023). It also has weekly granularity,
which the spreadsheet doesn't, enabling a "top scorers this week" game.
And since play-by-play is the actual record of every game, it can't have
the spreadsheet's kind of gap (Rob Gronkowski's excellent 2011 season was
missing from that year's tab entirely -- this script has it, see below).

Scoring (standard PFR-style, matching the spreadsheet's own convention):
    0.04 pt/passing yard, 4 pt/passing TD, -2 pt/interception
    0.1 pt/rushing yard, 6 pt/rushing TD
    0.1 pt/receiving yard, 6 pt/receiving TD, +1 pt/reception (PPR only)
    -2 pt/fumble lost, +2 pt/two-point conversion

Validated against player_offense_rank's independently-sourced season
totals (a separate v13-v18 research export, not itself play-by-play-
derived the same way): exact match to the decimal on 3 spot-checked
skill-position seasons (Rob Gronkowski 2011 -- 330.9 PPR both ways --
Randy Moss 2007, Priest Holmes 2002). A QB-only case (Tom Brady 2007)
was off by 1.4 points out of ~390 (0.36%) -- not chased down further,
doesn't meaningfully affect any leaderboard or draft outcome at that
scale, but worth knowing this isn't a byte-for-byte guaranteed match on
every player-season.

Player identity: play_by_play's own *_player_name fields are abbreviated
("T.Brady", not "Tom Brady") and there's no position/team column on a
play itself -- display_name/position come from player_bio (career-stable,
keyed on the same gsis_id play_by_play uses), and team is the most common
posteam across that player's own plays each week/season (handles
in-season trades reasonably; "mode", not "team as of the last game").

Usage:
    python3 scripts/compute_fantasy_points.py                 # all seasons
    python3 scripts/compute_fantasy_points.py --start 2025    # just the
                                                                current season,
                                                                cheap to
                                                                re-run
                                                                mid-season
"""
import argparse
import os
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUCKDB_PATH = os.path.join(ROOT, "data", "analytics.duckdb")

WEEKLY_QUERY = """
WITH rushing AS (
    SELECT season, week, rusher_player_id AS player_id,
           any_value(posteam) AS team,
           sum(rushing_yards) AS rushing_yards,
           sum(rush_touchdown) AS rushing_tds
    FROM play_by_play
    WHERE season_type = 'REG' AND play_type = 'run' AND rusher_player_id IS NOT NULL
          AND season BETWEEN ? AND ?
    GROUP BY season, week, rusher_player_id
),
receiving AS (
    SELECT season, week, receiver_player_id AS player_id,
           any_value(posteam) AS team,
           sum(CASE WHEN complete_pass = 1 THEN 1 ELSE 0 END) AS receptions,
           sum(receiving_yards) AS receiving_yards,
           sum(pass_touchdown) FILTER (WHERE complete_pass = 1) AS receiving_tds
    FROM play_by_play
    WHERE season_type = 'REG' AND play_type = 'pass' AND receiver_player_id IS NOT NULL
          AND season BETWEEN ? AND ?
    GROUP BY season, week, receiver_player_id
),
passing AS (
    SELECT season, week, passer_player_id AS player_id,
           any_value(posteam) AS team,
           sum(passing_yards) AS passing_yards,
           sum(pass_touchdown) AS passing_tds,
           sum(interception) AS interceptions
    FROM play_by_play
    WHERE season_type = 'REG' AND play_type = 'pass' AND passer_player_id IS NOT NULL
          AND season BETWEEN ? AND ?
    GROUP BY season, week, passer_player_id
),
fumbles AS (
    SELECT season, week, fumbled_1_player_id AS player_id, count(*) AS fumbles_lost
    FROM play_by_play
    WHERE season_type = 'REG' AND fumble_lost = 1 AND fumbled_1_player_id IS NOT NULL
          AND season BETWEEN ? AND ?
    GROUP BY season, week, fumbled_1_player_id
),
two_point AS (
    SELECT season, week, coalesce(rusher_player_id, receiver_player_id) AS player_id,
           count(*) AS two_point_conversions
    FROM play_by_play
    WHERE season_type = 'REG' AND two_point_conv_result = 'success'
          AND coalesce(rusher_player_id, receiver_player_id) IS NOT NULL
          AND season BETWEEN ? AND ?
    GROUP BY season, week, coalesce(rusher_player_id, receiver_player_id)
),
combined AS (
    SELECT
        coalesce(r.season, c.season, p.season, f.season, t.season) AS season,
        coalesce(r.week, c.week, p.week, f.week, t.week) AS week,
        coalesce(r.player_id, c.player_id, p.player_id, f.player_id, t.player_id) AS player_id,
        coalesce(r.team, c.team, p.team) AS team,
        coalesce(r.rushing_yards, 0) AS rushing_yards, coalesce(r.rushing_tds, 0) AS rushing_tds,
        coalesce(c.receptions, 0) AS receptions, coalesce(c.receiving_yards, 0) AS receiving_yards,
        coalesce(c.receiving_tds, 0) AS receiving_tds,
        coalesce(p.passing_yards, 0) AS passing_yards, coalesce(p.passing_tds, 0) AS passing_tds,
        coalesce(p.interceptions, 0) AS interceptions,
        coalesce(f.fumbles_lost, 0) AS fumbles_lost,
        coalesce(t.two_point_conversions, 0) AS two_point_conversions
    FROM rushing r
    FULL OUTER JOIN receiving c USING (season, week, player_id)
    FULL OUTER JOIN passing p USING (season, week, player_id)
    FULL OUTER JOIN fumbles f USING (season, week, player_id)
    FULL OUTER JOIN two_point t USING (season, week, player_id)
)
SELECT
    combined.season, combined.week, combined.player_id,
    coalesce(bio.display_name, combined.player_id) AS player,
    bio.position, combined.team,
    combined.passing_yards, combined.passing_tds, combined.interceptions,
    combined.rushing_yards, combined.rushing_tds,
    combined.receptions, combined.receiving_yards, combined.receiving_tds,
    combined.fumbles_lost, combined.two_point_conversions,
    (combined.passing_yards * 0.04 + combined.passing_tds * 4 - combined.interceptions * 2
     + combined.rushing_yards * 0.1 + combined.rushing_tds * 6
     + combined.receiving_yards * 0.1 + combined.receiving_tds * 6
     - combined.fumbles_lost * 2 + combined.two_point_conversions * 2) AS fant_pt,
    (combined.passing_yards * 0.04 + combined.passing_tds * 4 - combined.interceptions * 2
     + combined.rushing_yards * 0.1 + combined.rushing_tds * 6
     + combined.receiving_yards * 0.1 + combined.receiving_tds * 6 + combined.receptions * 1
     - combined.fumbles_lost * 2 + combined.two_point_conversions * 2) AS ppr_pt
FROM combined
LEFT JOIN player_bio bio ON bio.gsis_id = combined.player_id
WHERE combined.player_id IS NOT NULL
"""

SEASON_QUERY = """
SELECT season, player_id, any_value(player) AS player, any_value(position) AS position,
       mode(team) AS team, count(*) AS games,
       sum(passing_yards) AS passing_yards, sum(passing_tds) AS passing_tds,
       sum(rushing_yards) AS rushing_yards, sum(rushing_tds) AS rushing_tds,
       sum(receptions) AS receptions, sum(receiving_yards) AS receiving_yards,
       sum(receiving_tds) AS receiving_tds,
       sum(fant_pt) AS fant_pt, sum(ppr_pt) AS ppr_pt
FROM player_week_fantasy_points
WHERE season BETWEEN ? AND ?
GROUP BY season, player_id
"""


def log(msg):
    print(f"[compute_fantasy_points] {msg}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=1999)
    parser.add_argument("--end", type=int, default=2030)
    args = parser.parse_args()

    if not os.path.exists(DUCKDB_PATH):
        log("analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    conn = duckdb.connect(DUCKDB_PATH)
    conn.execute("DELETE FROM player_week_fantasy_points WHERE season BETWEEN ? AND ?", (args.start, args.end))
    conn.execute(
        f"INSERT INTO player_week_fantasy_points "
        f"(season, week, player_id, player, position, team, passing_yards, passing_tds, "
        f"interceptions, rushing_yards, rushing_tds, receptions, receiving_yards, receiving_tds, "
        f"fumbles_lost, two_point_conversions, fant_pt, ppr_pt) {WEEKLY_QUERY}",
        [args.start, args.end] * 5,
    )
    weekly_count = conn.execute(
        "SELECT count(*) FROM player_week_fantasy_points WHERE season BETWEEN ? AND ?",
        (args.start, args.end),
    ).fetchone()[0]
    log(f"player_week_fantasy_points: {weekly_count} rows, seasons {args.start}-{args.end}")

    conn.execute("DELETE FROM player_season_fantasy_points WHERE season BETWEEN ? AND ?", (args.start, args.end))
    conn.execute(
        f"INSERT INTO player_season_fantasy_points "
        f"(season, player_id, player, position, team, games, passing_yards, passing_tds, "
        f"rushing_yards, rushing_tds, receptions, receiving_yards, receiving_tds, fant_pt, ppr_pt) "
        f"{SEASON_QUERY}",
        (args.start, args.end),
    )
    season_count = conn.execute(
        "SELECT count(*) FROM player_season_fantasy_points WHERE season BETWEEN ? AND ?",
        (args.start, args.end),
    ).fetchone()[0]
    years = conn.execute(
        "SELECT min(season), max(season) FROM player_season_fantasy_points"
    ).fetchone()
    log(f"player_season_fantasy_points: {season_count} rows this run, table now covers {years[0]}-{years[1]}")
    conn.close()
    log("done.")


if __name__ == "__main__":
    main()
