#!/usr/bin/env python3
"""
rb_touches_falloff.py -- does an RB's next-season production fall off more
(as a percentage) after a ~300-touch season than after a 200-250-touch
season, and are they more likely to miss significant time the following
year? An ad-hoc research question, not part of the regular data pipeline.

Data:
  - touches (carries + receptions, NOT targets -- the user's own
    definition: "combined rushing attempts and catches") from
    player_stats_season, season N
  - ppg/fantasy_points_ppr/games_played from player_offense_rank, season N
    and season N+1, for the same player_id

Season N ranges 2001-2024 (player_offense_rank starts 2001; touches data
needs season N+1 to exist in player_offense_rank too, which tops out at
2025, so season N can go up to 2024).

Important methodological note: a player with NO row at all in
player_offense_rank for season N+1 (the table only includes players with
>=4 games played) is NOT dropped from this analysis -- that would be
survivorship bias, silently excluding the worst outcomes (the exact
"Uncategorized season" trap docs/breakout-falloff-methodology.md's v6
section already ran into once with Achilles tears). Those seasons are
counted as 0 PPG / 0 games for the production-drop-off numbers, and
separately as their own "vanished" rate for the injury-proxy question.

Usage:
    python3 analysis/rb_touches_falloff.py
"""
import os

import duckdb
import numpy as np
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUCKDB_PATH = os.path.join(ROOT, "data", "analytics.duckdb")

BUCKETS = [
    ("<150", 0, 149),
    ("150-199", 150, 199),
    ("200-249", 200, 249),
    ("250-299", 250, 299),
    ("300-349", 300, 349),
    ("350+", 350, 10_000),
]


def bucket_for(touches):
    for label, lo, hi in BUCKETS:
        if lo <= touches <= hi:
            return label
    return None


def main():
    conn = duckdb.connect(DUCKDB_PATH, read_only=True)

    rows = conn.execute("""
        WITH touches AS (
            SELECT season, player_id, carries + receptions AS touches
            FROM player_stats_season
            WHERE position = 'RB' AND season BETWEEN 2001 AND 2024
        )
        SELECT
            t.season, t.player_id, t.touches,
            cur.display_name, cur.ppg AS ppg_current, cur.fantasy_points_ppr AS pts_current,
            cur.games_played AS games_current, cur.tier_score AS tier_current,
            nxt.ppg AS ppg_next, nxt.fantasy_points_ppr AS pts_next,
            nxt.games_played AS games_next, nxt.tier_score AS tier_next,
            bio.birth_date
        FROM touches t
        JOIN player_offense_rank cur ON cur.season = t.season AND cur.player_id = t.player_id
        LEFT JOIN player_offense_rank nxt ON nxt.season = t.season + 1 AND nxt.player_id = t.player_id
        LEFT JOIN player_bio bio ON bio.gsis_id = t.player_id
    """).fetchall()
    conn.close()

    cols = ["season", "player_id", "touches", "display_name", "ppg_current", "pts_current",
            "games_current", "tier_current", "ppg_next", "pts_next", "games_next", "tier_next",
            "birth_date"]
    data = [dict(zip(cols, r)) for r in rows]
    print(f"[rb_touches_falloff] {len(data)} RB player-seasons, 2001-2024, with a next-season lookup")

    for d in data:
        d["bucket"] = bucket_for(d["touches"])
        d["vanished"] = d["ppg_next"] is None
        d["ppg_next_eff"] = d["ppg_next"] if d["ppg_next"] is not None else 0.0
        d["pts_next_eff"] = d["pts_next"] if d["pts_next"] is not None else 0.0
        d["games_next_eff"] = d["games_next"] if d["games_next"] is not None else 0
        if d["birth_date"] is not None:
            d["age"] = d["season"] - d["birth_date"].year
        else:
            d["age"] = None

    print("\n=== By touch bucket ===")
    print(f"{'Bucket':<10}{'n':>5}{'AvgAge':>8}{'GmsCur':>8}{'PPGcur':>8}{'PPGnxt':>8}"
          f"{'PPG Δ%':>9}{'Pts Δ%':>9}{'GmsNxt':>8}{'Van%':>7}{'<=9gm%':>8}")

    bucket_rows = {}
    for label, lo, hi in BUCKETS:
        rows_b = [d for d in data if d["bucket"] == label]
        bucket_rows[label] = rows_b
        n = len(rows_b)
        if n == 0:
            continue
        ages = [d["age"] for d in rows_b if d["age"] is not None]
        ppg_cur = np.array([d["ppg_current"] for d in rows_b])
        ppg_nxt_eff = np.array([d["ppg_next_eff"] for d in rows_b])
        pts_cur = np.array([d["pts_current"] for d in rows_b])
        pts_nxt_eff = np.array([d["pts_next_eff"] for d in rows_b])
        games_nxt_eff = np.array([d["games_next_eff"] for d in rows_b])
        vanished_rate = np.mean([d["vanished"] for d in rows_b]) * 100
        le9_rate = np.mean(games_nxt_eff <= 9) * 100

        ppg_pct_change = (ppg_nxt_eff - ppg_cur) / ppg_cur * 100
        pts_pct_change = (pts_nxt_eff - pts_cur) / pts_cur * 100

        print(f"{label:<10}{n:>5}{np.mean(ages) if ages else 0:>8.1f}"
              f"{np.mean([d['games_current'] for d in rows_b]):>8.1f}"
              f"{np.mean(ppg_cur):>8.1f}{np.mean(ppg_nxt_eff):>8.1f}"
              f"{np.mean(ppg_pct_change):>+8.1f}%{np.mean(pts_pct_change):>+8.1f}%"
              f"{np.mean(games_nxt_eff):>8.1f}{vanished_rate:>6.1f}%{le9_rate:>7.1f}%")

    # Head-to-head: 300+ touches (merging 300-349 and 350+) vs 200-249
    heavy = bucket_rows["300-349"] + bucket_rows["350+"]
    mid = bucket_rows["200-249"]

    def pct_changes(rows_b, key_cur, key_nxt_eff):
        cur = np.array([d[key_cur] for d in rows_b])
        nxt = np.array([d[key_nxt_eff] for d in rows_b])
        return (nxt - cur) / cur * 100

    heavy_ppg_pct = pct_changes(heavy, "ppg_current", "ppg_next_eff")
    mid_ppg_pct = pct_changes(mid, "ppg_current", "ppg_next_eff")
    heavy_pts_pct = pct_changes(heavy, "pts_current", "pts_next_eff")
    mid_pts_pct = pct_changes(mid, "pts_current", "pts_next_eff")

    print(f"\n=== 300+ touches (n={len(heavy)}) vs. 200-249 touches (n={len(mid)}) ===")
    print(f"PPG %% change:   300+ mean {heavy_ppg_pct.mean():+.1f}%% (median {np.median(heavy_ppg_pct):+.1f}%%)  "
          f"vs 200-249 mean {mid_ppg_pct.mean():+.1f}%% (median {np.median(mid_ppg_pct):+.1f}%%)")
    t_ppg, p_ppg = stats.ttest_ind(heavy_ppg_pct, mid_ppg_pct, equal_var=False)
    u_ppg, pu_ppg = stats.mannwhitneyu(heavy_ppg_pct, mid_ppg_pct)
    print(f"  Welch t-test p={p_ppg:.4f}   Mann-Whitney p={pu_ppg:.4f}")

    print(f"\nTotal-points %% change: 300+ mean {heavy_pts_pct.mean():+.1f}%% (median {np.median(heavy_pts_pct):+.1f}%%)  "
          f"vs 200-249 mean {mid_pts_pct.mean():+.1f}%% (median {np.median(mid_pts_pct):+.1f}%%)")
    t_pts, p_pts = stats.ttest_ind(heavy_pts_pct, mid_pts_pct, equal_var=False)
    u_pts, pu_pts = stats.mannwhitneyu(heavy_pts_pct, mid_pts_pct)
    print(f"  Welch t-test p={p_pts:.4f}   Mann-Whitney p={pu_pts:.4f}")

    # Injury-proxy: rate of missing significant time the following season
    heavy_games_next = np.array([d["games_next_eff"] for d in heavy])
    mid_games_next = np.array([d["games_next_eff"] for d in mid])
    for thresh in (9, 12):
        heavy_rate = np.mean(heavy_games_next <= thresh)
        mid_rate = np.mean(mid_games_next <= thresh)
        count = np.array([np.sum(heavy_games_next <= thresh), np.sum(mid_games_next <= thresh)])
        nobs = np.array([len(heavy_games_next), len(mid_games_next)])
        from statsmodels.stats.proportion import proportions_ztest
        z, p = proportions_ztest(count, nobs)
        print(f"\n<= {thresh} games played next season: 300+ {heavy_rate:.1%} (n={nobs[0]}) "
              f"vs 200-249 {mid_rate:.1%} (n={nobs[1]})   proportions z-test p={p:.4f}")

    heavy_vanish = np.mean([d["vanished"] for d in heavy])
    mid_vanish = np.mean([d["vanished"] for d in mid])
    print(f"\nFully vanished from player_offense_rank next season "
          f"(<4 games played or out of the league): 300+ {heavy_vanish:.1%} vs 200-249 {mid_vanish:.1%}")

    print(f"\nAvg age -- 300+: {np.mean([d['age'] for d in heavy if d['age'] is not None]):.1f}  "
          f"200-249: {np.mean([d['age'] for d in mid if d['age'] is not None]):.1f}")

    # Save the row-level dataset for a chart / further slicing
    import csv
    out_path = os.path.join(ROOT, "analysis", "rb_touches_falloff_rows.csv")
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["season", "player_id", "display_name", "touches", "bucket", "age",
                    "games_current", "ppg_current", "pts_current",
                    "games_next_eff", "ppg_next_eff", "pts_next_eff", "vanished"])
        for d in data:
            w.writerow([d["season"], d["player_id"], d["display_name"], d["touches"], d["bucket"],
                        d["age"], d["games_current"], d["ppg_current"], d["pts_current"],
                        d["games_next_eff"], d["ppg_next_eff"], d["pts_next_eff"], d["vanished"]])
    print(f"\nRow-level dataset written to {out_path}")


if __name__ == "__main__":
    main()
