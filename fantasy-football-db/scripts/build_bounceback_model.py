#!/usr/bin/env python3
"""
build_bounceback_model.py -- rebuilds the v7 bounce-back model from
docs/breakout-falloff-methodology.md: predicts whether a player who fell
off from Star-or-higher tier returns to Star+ the very next season.

Tier data comes from player_offense_rank (loaded by
scripts/load_coaching_and_offense.py -- a separate Cowork session's
research export, already covering 2001-2025 with the exact fixed PPG
cutoffs recovered from data/final_workbooks/Fantasy_Football_PPG_Tiers_
2001-2025.xlsx's "Tier Cutoffs" sheet). Age comes from player_bio (loaded
by scripts/load_player_stats.py).

Known deviations from the original v7 methodology (documented honestly,
not hidden):
  - The original definition folds in 20 additional "confirmed-injury
    fall-off" events (Star+ then <4 games the next season, verified >=40%
    injury-attributed) that a plain tier-adjacency walk can't see, since
    <4-game seasons don't appear in player_offense_rank at all. This
    rebuild only uses standard adjacent-season fall-offs. Expect somewhat
    fewer training events (~547 vs. the original's 567).
  - `years_star_streak` here only counts consecutive rows THAT EXIST in
    player_offense_rank -- a season missing from the table (e.g. <4 games,
    which breaks streak continuity in our data even though a healthy
    Star+ player wouldn't have had such a season) could undercount a
    streak in rare cases. Not expected to matter much given how few
    Star+ players miss most of a season.
  - Coefficients/AUC will differ somewhat from the original (different
    exact player pool via a different but equivalent tier source), but
    should be directionally consistent: age and ppg_drop negative,
    prior_ppg_above_star and years_star_streak positive, RB/TE/WR all
    well below QB.

Usage:
    python3 scripts/build_bounceback_model.py

Safe to re-run: model_predictions/model_feature_pool rows for this
model_name/model_version are deleted and rewritten each run.
"""
import json
import os
import sqlite3
import sys

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.metrics import roc_auc_score

from seasons import last_complete_season

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SQLITE_PATH = os.path.join(DATA_DIR, "app.db")
DUCKDB_PATH = os.path.join(DATA_DIR, "analytics.duckdb")

MODEL_NAME = "bounceback"
MODEL_VERSION = "v7"

# From data/final_workbooks/Fantasy_Football_PPG_Tiers_2001-2025.xlsx,
# "Tier Cutoffs" sheet -- fixed PPG thresholds, not re-derived per season.
STAR_PPG_CUTOFF = {"QB": 17.65, "RB": 13.24, "WR": 14.71, "TE": 10.29}
# Derived: training on a season that is still being played skews every
# fitted coefficient toward whoever started fast, and a pinned year
# quietly stops advancing. See scripts/seasons.py.
LAST_COMPLETE_SEASON = last_complete_season()

FEATURES = ["age", "ppg_drop", "prior_ppg_above_star", "years_star_streak",
            "pos_RB", "pos_TE", "pos_WR"]


def log(msg):
    print(f"[build_bounceback_model] {msg}")


def load_tier_timeline(duckdb_conn):
    df = duckdb_conn.execute("""
        SELECT o.season, o.player_id, o.display_name, o.position, o.ppg,
               o.tier_score, o.games_played, b.birth_date
        FROM player_offense_rank o
        LEFT JOIN player_bio b ON b.gsis_id = o.player_id
        WHERE o.position IN ('QB', 'RB', 'WR', 'TE')
    """).fetchdf()
    df["birth_date"] = pd.to_datetime(df["birth_date"], errors="coerce")
    return df


def age_at_season(birth_date, season):
    if pd.isna(birth_date):
        return None
    # Age as of Sept 1 of the season -- close enough to "age during the
    # season" for a feature; the original doc doesn't specify a stricter
    # convention.
    season_start = pd.Timestamp(year=season, month=9, day=1)
    return (season_start - birth_date).days / 365.25


def build_star_streak(row_by_player_season, player_id, season):
    """Count consecutive seasons ending at `season` (inclusive) where the
    player was Star+ (tier_score>=3), walking backward one season at a time
    through whatever rows exist in the timeline."""
    streak = 0
    s = season
    while True:
        row = row_by_player_season.get((player_id, s))
        if row is None or row.tier_score < 3:
            break
        streak += 1
        s -= 1
    return streak


def build_falloff_events(timeline):
    by_player_season = {
        (r.player_id, r.season): r for r in timeline.itertuples()
    }
    events = []
    for r in timeline.itertuples():
        prior_season = r.season
        if r.tier_score < 3:
            continue  # not a Star+ season, can't be the "prior" side of a fall-off
        falloff_row = by_player_season.get((r.player_id, prior_season + 1))
        if falloff_row is None or falloff_row.tier_score >= 3:
            continue  # no next season on record, or didn't actually fall off

        falloff_season = prior_season + 1
        age = age_at_season(r.birth_date, falloff_season)
        if age is None:
            continue

        streak = build_star_streak(by_player_season, r.player_id, prior_season)
        star_cutoff = STAR_PPG_CUTOFF[r.position]

        bounce_row = by_player_season.get((r.player_id, falloff_season + 1))
        resolvable = (falloff_season + 1) <= LAST_COMPLETE_SEASON
        bounce_back = None
        if resolvable:
            bounce_back = 1 if (bounce_row is not None and bounce_row.tier_score >= 3) else 0

        events.append({
            "player_id": r.player_id, "display_name": r.display_name,
            "position": r.position, "falloff_season": falloff_season,
            "age": age,
            "ppg_drop": r.ppg - falloff_row.ppg,
            "prior_ppg_above_star": r.ppg - star_cutoff,
            "years_star_streak": streak,
            "pos_RB": 1 if r.position == "RB" else 0,
            "pos_TE": 1 if r.position == "TE" else 0,
            "pos_WR": 1 if r.position == "WR" else 0,
            "resolvable": resolvable,
            "bounce_back": bounce_back,
        })
    return pd.DataFrame(events)


def fit_and_report(train_df):
    X = sm.add_constant(train_df[FEATURES].astype(float))
    y = train_df["bounce_back"].astype(float)
    model = sm.Logit(y, X).fit(disp=0)
    log("coefficients:")
    for name, coef, p in zip(model.params.index, model.params.values, model.pvalues.values):
        log(f"  {name:24s} {coef:+.3f}  p={p:.4f}")
    return model


def backtest(model, resolved_df, test_season):
    test = resolved_df[resolved_df["falloff_season"] == test_season]
    if test.empty:
        return
    X = sm.add_constant(test[FEATURES].astype(float), has_constant="add")
    X = X.reindex(columns=model.params.index, fill_value=0.0)
    preds = model.predict(X)
    y = test["bounce_back"].astype(float)
    if y.nunique() < 2:
        log(f"{test_season} fall-offs (n={len(test)}): only one outcome class present, AUC undefined")
        return
    auc = roc_auc_score(y, preds)
    log(f"{test_season} fall-offs (n={len(test)}, actual bounce-back rate "
        f"{y.mean():.1%}): AUC {auc:.3f}")


def gsis_to_canonical(sqlite_conn):
    """model_predictions/model_feature_pool use app.db's canonical player_id
    (fantasypros_id when available, matching players/trade_values/
    arbitrage_signals) -- NOT nflverse's gsis_id, which is what
    player_offense_rank/player_bio use. Unmatched gsis ids fall back to a
    'gsis:<id>' pseudo-id, the same pattern players.player_id already uses
    for sleeper-only players ('sleeper:<id>')."""
    rows = sqlite_conn.execute(
        "SELECT gsis_id, player_id FROM players WHERE gsis_id IS NOT NULL"
    ).fetchall()
    return {gsis_id: player_id for gsis_id, player_id in rows}


def write_outputs(sqlite_conn, all_events, full_model, train_seasons_max):
    """Score every fall-off event (resolved and forward-looking) with the
    final model (fit on all resolved events through train_seasons_max) and
    write to model_predictions + model_feature_pool."""
    X = sm.add_constant(all_events[FEATURES].astype(float), has_constant="add")
    X = X.reindex(columns=full_model.params.index, fill_value=0.0)
    all_events = all_events.copy()
    all_events["predicted_probability"] = full_model.predict(X)

    crosswalk = gsis_to_canonical(sqlite_conn)
    pred_rows = []
    feature_rows = []
    for r in all_events.itertuples():
        canonical_id = crosswalk.get(r.player_id, f"gsis:{r.player_id}")
        season_predicted_for = r.falloff_season + 1
        pred_rows.append((
            canonical_id, MODEL_NAME, MODEL_VERSION, season_predicted_for,
            float(r.predicted_probability),
            int(r.bounce_back) if r.resolvable else None,
        ))
        features = {
            "age": r.age, "ppg_drop": r.ppg_drop,
            "prior_ppg_above_star": r.prior_ppg_above_star,
            "years_star_streak": r.years_star_streak, "position": r.position,
        }
        feature_rows.append((
            canonical_id, r.falloff_season, "falloff", MODEL_VERSION,
            json.dumps(features),
            int(r.bounce_back) if r.resolvable else None,
        ))

    sqlite_conn.execute(
        "DELETE FROM model_predictions WHERE model_name = ? AND model_version = ?",
        (MODEL_NAME, MODEL_VERSION),
    )
    sqlite_conn.executemany(
        """INSERT INTO model_predictions
               (player_id, model_name, model_version, season,
                predicted_probability, actual_outcome)
           VALUES (?, ?, ?, ?, ?, ?)""",
        pred_rows,
    )

    duck_conn = duckdb.connect(DUCKDB_PATH)
    duck_conn.execute(
        "DELETE FROM model_feature_pool WHERE model_version = ? AND event_type = 'falloff'",
        [MODEL_VERSION],
    )
    duck_conn.executemany(
        """INSERT INTO model_feature_pool
               (player_id, season, event_type, model_version, features, outcome)
           VALUES (?, ?, ?, ?, ?, ?)""",
        feature_rows,
    )
    duck_conn.close()
    sqlite_conn.commit()
    log(f"wrote {len(pred_rows)} rows to model_predictions, "
        f"{len(feature_rows)} rows to model_feature_pool")


def update_sync_log(sqlite_conn, row_count):
    sqlite_conn.execute(
        """INSERT INTO sync_log (table_name, source, last_synced_at, row_count, notes)
           VALUES ('model_predictions', 'build_bounceback_model.py', datetime('now'), ?, ?)
           ON CONFLICT(table_name) DO UPDATE SET
               source=excluded.source, last_synced_at=datetime('now'),
               row_count=excluded.row_count, notes=excluded.notes""",
        (row_count, f"bounceback {MODEL_VERSION} predictions (see model_name column)"),
    )
    sqlite_conn.commit()


def main():
    if not os.path.exists(SQLITE_PATH) or not os.path.exists(DUCKDB_PATH):
        log("app.db / analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    duckdb_conn = duckdb.connect(DUCKDB_PATH)
    tables = {r[0] for r in duckdb_conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
    ).fetchall()}
    if "player_bio" not in tables:
        log("player_bio not found -- run scripts/load_player_stats.py first.")
        sys.exit(1)

    timeline = load_tier_timeline(duckdb_conn)
    duckdb_conn.close()
    log(f"tier timeline: {len(timeline)} player-seasons, {timeline['season'].min()}-{timeline['season'].max()}")

    events = build_falloff_events(timeline)
    resolved = events[events["resolvable"]].dropna(subset=FEATURES)
    forward = events[~events["resolvable"]].dropna(subset=FEATURES)
    log(f"fall-off events: {len(events)} total ({len(resolved)} resolved, {len(forward)} forward-looking)")

    train = resolved[resolved["falloff_season"] <= 2022]
    log(f"training on {len(train)} fall-off events (season <= 2022)")
    model = fit_and_report(train)

    log("walk-forward backtest (held out of training):")
    backtest(model, resolved, 2023)
    backtest(model, resolved, 2024)

    log(f"refitting on all {len(resolved)} resolved events for final predictions")
    full_model = fit_and_report(resolved)

    if not forward.empty:
        X = sm.add_constant(forward[FEATURES].astype(float), has_constant="add")
        X = X.reindex(columns=full_model.params.index, fill_value=0.0)
        forward = forward.copy()
        forward["predicted_probability"] = full_model.predict(X)
        top5 = forward.sort_values("predicted_probability", ascending=False).head(5)
        log(f"top 5 forward-looking predictions (fall-off season {forward['falloff_season'].iloc[0]}, "
            f"bounce-back season {forward['falloff_season'].iloc[0] + 1}):")
        for r in top5.itertuples():
            log(f"  {r.display_name:24s} {r.position}  {r.predicted_probability:.1%}")

    all_events = pd.concat([resolved, forward], ignore_index=True)
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    write_outputs(sqlite_conn, all_events, full_model, 2022)
    update_sync_log(sqlite_conn, len(all_events))
    sqlite_conn.close()

    log("done.")


if __name__ == "__main__":
    main()
