#!/usr/bin/env python3
"""
rb_carries_superstar_falloff.py -- follow-up to rb_touches_falloff.py,
three refinements requested directly:

  1. A tighter 250-299 vs. 300+ bucket comparison (narrower than the
     original 200-249 vs. 300+ touches comparison).
  2. Run twice: once across all RB seasons, once restricted to seasons
     where the RB was ALREADY Superstar-tier or better that year
     (tier_score >= 4) -- does the "reaching a heavy workload is itself a
     filter for a good situation" explanation from the original report
     still hold once we're only looking at backs who were already elite,
     or does conditioning on elite production wash the effect out?
  3. Run under BOTH workload definitions -- rushing CARRIES only (isolates
     leg-wear from receiving work) and total TOUCHES (carries +
     receptions, the original report's definition) -- so the two are
     directly comparable side by side.

Same survivorship-bias handling as rb_touches_falloff.py: a player absent
from player_offense_rank the next season (<4 games played, or out of the
league) is scored at 0 PPG/points/games for the decline metrics, not
dropped, and tracked separately as a "vanished" rate.

Usage:
    python3 analysis/rb_carries_superstar_falloff.py
"""
import csv
import os

import duckdb
import numpy as np
from scipy import stats
from statsmodels.stats.proportion import proportions_ztest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUCKDB_PATH = os.path.join(ROOT, "data", "analytics.duckdb")

SUPERSTAR_TIER_SCORE = 4  # Superstar=4, League Winner=5 (see docs/breakout-falloff-methodology.md)

METRICS = {
    "carries": "s.carries",
    "touches": "s.carries + s.receptions",
}


def load_data(conn, metric_expr):
    rows = conn.execute(f"""
        SELECT
            s.season, s.player_id, {metric_expr} AS workload,
            cur.display_name, cur.ppg AS ppg_current, cur.fantasy_points_ppr AS pts_current,
            cur.games_played AS games_current, cur.tier AS tier_current, cur.tier_score AS tier_score_current,
            nxt.ppg AS ppg_next, nxt.fantasy_points_ppr AS pts_next,
            nxt.games_played AS games_next
        FROM player_stats_season s
        JOIN player_offense_rank cur ON cur.season = s.season AND cur.player_id = s.player_id
        LEFT JOIN player_offense_rank nxt ON nxt.season = s.season + 1 AND nxt.player_id = s.player_id
        WHERE s.position = 'RB' AND s.season BETWEEN 2001 AND 2024 AND {metric_expr} >= 250
    """).fetchall()
    cols = ["season", "player_id", "workload", "display_name", "ppg_current", "pts_current",
            "games_current", "tier_current", "tier_score_current", "ppg_next", "pts_next", "games_next"]
    data = [dict(zip(cols, r)) for r in rows]
    for d in data:
        d["bucket"] = "300+" if d["workload"] >= 300 else "250-299"
        d["vanished"] = d["ppg_next"] is None
        d["ppg_next_eff"] = d["ppg_next"] if d["ppg_next"] is not None else 0.0
        d["pts_next_eff"] = d["pts_next"] if d["pts_next"] is not None else 0.0
        d["games_next_eff"] = d["games_next"] if d["games_next"] is not None else 0
    return data


def pct_change(rows_b, key_cur, key_nxt_eff):
    cur = np.array([d[key_cur] for d in rows_b])
    nxt = np.array([d[key_nxt_eff] for d in rows_b])
    return (nxt - cur) / cur * 100


def report(unit, title, heavy, mid):
    print(f"\n=== {title}: 300+ {unit} (n={len(heavy)}) vs. 250-299 {unit} (n={len(mid)}) ===")
    if not heavy or not mid:
        print("  not enough rows in one bucket to compare")
        return

    heavy_ppg = pct_change(heavy, "ppg_current", "ppg_next_eff")
    mid_ppg = pct_change(mid, "ppg_current", "ppg_next_eff")
    t, p = stats.ttest_ind(heavy_ppg, mid_ppg, equal_var=False)
    u, pu = stats.mannwhitneyu(heavy_ppg, mid_ppg)
    print(f"PPG % change:   300+ mean {heavy_ppg.mean():+.1f}% (median {np.median(heavy_ppg):+.1f}%)  "
          f"vs 250-299 mean {mid_ppg.mean():+.1f}% (median {np.median(mid_ppg):+.1f}%)")
    print(f"  Welch t-test p={p:.4f}   Mann-Whitney p={pu:.4f}")

    heavy_pts = pct_change(heavy, "pts_current", "pts_next_eff")
    mid_pts = pct_change(mid, "pts_current", "pts_next_eff")
    t2, p2 = stats.ttest_ind(heavy_pts, mid_pts, equal_var=False)
    u2, pu2 = stats.mannwhitneyu(heavy_pts, mid_pts)
    print(f"Total pts % change: 300+ mean {heavy_pts.mean():+.1f}% (median {np.median(heavy_pts):+.1f}%)  "
          f"vs 250-299 mean {mid_pts.mean():+.1f}% (median {np.median(mid_pts):+.1f}%)")
    print(f"  Welch t-test p={p2:.4f}   Mann-Whitney p={pu2:.4f}")

    heavy_games = np.array([d["games_next_eff"] for d in heavy])
    mid_games = np.array([d["games_next_eff"] for d in mid])
    for thresh in (9, 12):
        heavy_rate = np.mean(heavy_games <= thresh)
        mid_rate = np.mean(mid_games <= thresh)
        count = np.array([np.sum(heavy_games <= thresh), np.sum(mid_games <= thresh)])
        nobs = np.array([len(heavy_games), len(mid_games)])
        z, pz = proportions_ztest(count, nobs)
        print(f"<= {thresh} games next season: 300+ {heavy_rate:.1%} vs 250-299 {mid_rate:.1%}   "
              f"proportions z-test p={pz:.4f}")

    heavy_vanish = np.mean([d["vanished"] for d in heavy])
    mid_vanish = np.mean([d["vanished"] for d in mid])
    print(f"Vanished next season: 300+ {heavy_vanish:.1%} vs 250-299 {mid_vanish:.1%}")

    print(f"Avg current-season games played: 300+ {np.mean([d['games_current'] for d in heavy]):.1f}  "
          f"250-299 {np.mean([d['games_current'] for d in mid]):.1f}")


def run_metric(conn, metric_name, metric_expr):
    print(f"\n{'#' * 70}\n# WORKLOAD METRIC: {metric_name.upper()}\n{'#' * 70}")
    data = load_data(conn, metric_expr)
    print(f"[rb_carries_superstar_falloff] {len(data)} RB player-seasons with 250+ {metric_name}, 2001-2024")

    all_heavy = [d for d in data if d["bucket"] == "300+"]
    all_mid = [d for d in data if d["bucket"] == "250-299"]
    report(metric_name, "All RB seasons", all_heavy, all_mid)

    ss_heavy = [d for d in all_heavy if d["tier_score_current"] >= SUPERSTAR_TIER_SCORE]
    ss_mid = [d for d in all_mid if d["tier_score_current"] >= SUPERSTAR_TIER_SCORE]
    report(metric_name, "Superstar-tier-or-better seasons only", ss_heavy, ss_mid)

    print(f"\n--- Superstar+ 300+ {metric_name}: every season (sorted by {metric_name}) ---")
    for d in sorted(ss_heavy, key=lambda d: -d["workload"]):
        outcome = "vanished" if d["vanished"] else f"{d['ppg_next_eff']:.1f} ppg / {d['games_next_eff']:.0f} gm"
        print(f"  {d['season']} {d['display_name']:<22} {d['workload']:>3} {metric_name[:3]}  "
              f"{d['ppg_current']:.1f} ppg ({d['tier_current']})  ->  {outcome}")

    print(f"\n--- Superstar+ 250-299 {metric_name}: every season (sorted by {metric_name}) ---")
    for d in sorted(ss_mid, key=lambda d: -d["workload"]):
        outcome = "vanished" if d["vanished"] else f"{d['ppg_next_eff']:.1f} ppg / {d['games_next_eff']:.0f} gm"
        print(f"  {d['season']} {d['display_name']:<22} {d['workload']:>3} {metric_name[:3]}  "
              f"{d['ppg_current']:.1f} ppg ({d['tier_current']})  ->  {outcome}")

    out_path = os.path.join(ROOT, "analysis", f"rb_{metric_name}_superstar_falloff_rows.csv")
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["season", "player_id", "display_name", metric_name, "bucket",
                     "tier_current", "tier_score_current", "games_current", "ppg_current", "pts_current",
                     "games_next_eff", "ppg_next_eff", "pts_next_eff", "vanished"])
        for d in data:
            w.writerow([d["season"], d["player_id"], d["display_name"], d["workload"], d["bucket"],
                        d["tier_current"], d["tier_score_current"], d["games_current"], d["ppg_current"],
                        d["pts_current"], d["games_next_eff"], d["ppg_next_eff"], d["pts_next_eff"], d["vanished"]])
    print(f"\nRow-level dataset written to {out_path}")


def main():
    conn = duckdb.connect(DUCKDB_PATH, read_only=True)
    for metric_name, metric_expr in METRICS.items():
        run_metric(conn, metric_name, metric_expr)
    conn.close()


if __name__ == "__main__":
    main()
