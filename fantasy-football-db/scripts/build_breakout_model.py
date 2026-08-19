#!/usr/bin/env python3
"""
build_breakout_model.py -- rebuilds the v11 breakout model from
docs/breakout-falloff-methodology.md: four independent per-position
logistic regressions predicting whether a below-Star player reaches
Star-or-higher tier the following season.

v11 rather than the doc's final v12: v12 adds `log_adp`, built from
footballguys.com/FantasyPros ADP scrapes -- both ordinary websites this
sandbox's egress policy blocks (same wall as api.sleeper.app; see
docs/local-webapp-and-database-architecture.md and README.md's adp_history
section). v11 (age + ppg-above-starter + position-specific extras, no ADP)
is the doc's own documented fallback for exactly this situation: "the
original v11 walk-forward backtest... kept as the baseline/full-coverage
view since ~30% of candidates have no ADP match" (v12 section). If ADP
ever becomes available, log_adp can be added the same way `docs/...`
describes without changing anything else here.

Feature sets (v11, per position):
  QB: age, ppg_above_starter, position_share, candidate_streak, no_other_star_on_team
  RB: age, ppg_above_starter, epa_per_touch, position_share, log_draft_pick
  WR: age, ppg_above_starter, top10_pick, day3_or_undrafted
  TE: age, ppg_above_starter, reached_starter_by_climbing, log_draft_pick

Candidate pool: player-seasons below Star tier, >=8 games played, meaningful
volume (QB >=100 dropbacks; RB/WR/TE >=30 touches) -- same thresholds as the
original. Undrafted players are filled to round 8 / pick 300 (same
convention as the original, so going undrafted is a meaningful signal
rather than missing data).

Known deviations (documented, not hidden): no ADP (see above); touches/
dropbacks/EPA come from nflverse's player_stats_season rather than raw
play-by-play (same underlying numbers, just pre-aggregated -- simpler and
sufficient for a per-touch rate stat); candidate pool sizes and exact
coefficients will differ somewhat from the original's reported numbers as
a result, but should be directionally consistent.

Usage:
    python3 scripts/build_breakout_model.py
"""
import json
import math
import os
import sqlite3
import sys

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.metrics import roc_auc_score

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SQLITE_PATH = os.path.join(DATA_DIR, "app.db")
DUCKDB_PATH = os.path.join(DATA_DIR, "analytics.duckdb")

MODEL_NAME = "breakout"
MODEL_VERSION = "v11"

STARTER_PPG_CUTOFF = {"QB": 15.0, "RB": 11.0, "WR": 11.0, "TE": 8.0}
LAST_COMPLETE_SEASON = 2025
UNDRAFTED_PICK = 300
UNDRAFTED_ROUND = 8

POSITION_FEATURES = {
    "QB": ["age", "ppg_above_starter", "position_share", "candidate_streak", "no_other_star_on_team"],
    "RB": ["age", "ppg_above_starter", "epa_per_touch", "position_share", "log_draft_pick"],
    "WR": ["age", "ppg_above_starter", "top10_pick", "day3_or_undrafted"],
    "TE": ["age", "ppg_above_starter", "reached_starter_by_climbing", "log_draft_pick"],
}


def log(msg):
    print(f"[build_breakout_model] {msg}")


def load_stats_from_play_by_play(duckdb_conn, seasons):
    """nflverse's player_stats release currently lags play_by_play by about
    a season (as of this run, player_stats_season tops out at 2024 while
    play_by_play already has 2025) -- rather than lose a whole season of
    candidates/forward-looking predictions to that gap, derive the same
    counting stats directly from play_by_play for whichever seasons
    player_stats_season doesn't cover yet. Same underlying nflverse data,
    just aggregated here instead of upstream."""
    if not seasons:
        return pd.DataFrame(columns=["season", "player_id", "carries", "targets",
                                      "attempts", "sacks", "rushing_epa", "receiving_epa"])
    placeholders = ",".join("?" * len(seasons))
    return duckdb_conn.execute(f"""
        WITH rushing AS (
            SELECT season, rusher_player_id AS player_id,
                   count(*) AS carries, sum(epa) AS rushing_epa
            FROM play_by_play
            WHERE season_type = 'REG' AND play_type = 'run'
                  AND rusher_player_id IS NOT NULL AND season IN ({placeholders})
            GROUP BY season, rusher_player_id
        ),
        receiving AS (
            SELECT season, receiver_player_id AS player_id,
                   count(*) AS targets, sum(epa) AS receiving_epa
            FROM play_by_play
            WHERE season_type = 'REG' AND play_type = 'pass'
                  AND receiver_player_id IS NOT NULL AND season IN ({placeholders})
            GROUP BY season, receiver_player_id
        ),
        passing AS (
            SELECT season, passer_player_id AS player_id,
                   count(*) FILTER (WHERE play_type = 'pass') AS attempts,
                   count(*) FILTER (WHERE sack = 1) AS sacks
            FROM play_by_play
            WHERE season_type = 'REG' AND passer_player_id IS NOT NULL
                  AND season IN ({placeholders})
            GROUP BY season, passer_player_id
        )
        SELECT
            coalesce(r.season, c.season, p.season) AS season,
            coalesce(r.player_id, c.player_id, p.player_id) AS player_id,
            r.carries, c.targets, p.attempts, p.sacks,
            r.rushing_epa, c.receiving_epa
        FROM rushing r
        FULL OUTER JOIN receiving c USING (season, player_id)
        FULL OUTER JOIN passing p USING (season, player_id)
    """, seasons * 3).fetchdf()


def load_base_data(duckdb_conn):
    rank = duckdb_conn.execute("""
        SELECT season, player_id, display_name, position, team, ppg,
               tier_score, games_played
        FROM player_offense_rank
        WHERE position IN ('QB', 'RB', 'WR', 'TE')
    """).fetchdf()

    stats = duckdb_conn.execute("""
        SELECT season, player_id, carries, targets, attempts, sacks,
               rushing_epa, receiving_epa
        FROM player_stats_season
    """).fetchdf()

    max_stats_season = duckdb_conn.execute("SELECT max(season) FROM player_stats_season").fetchone()[0]
    missing_seasons = sorted(int(s) for s in rank["season"].unique() if s > max_stats_season)
    if missing_seasons:
        log(f"player_stats_season doesn't cover season(s) {missing_seasons} yet "
            f"(nflverse hasn't published them there) -- deriving from play_by_play instead")
        backfill = load_stats_from_play_by_play(duckdb_conn, missing_seasons)
        stats = pd.concat([stats, backfill], ignore_index=True)

    stats = stats.merge(rank[["season", "player_id", "position"]], on=["season", "player_id"], how="inner")
    stats["touches"] = stats["carries"].fillna(0) + stats["targets"].fillna(0)
    stats["dropbacks"] = stats["attempts"].fillna(0) + stats["sacks"].fillna(0)
    stats["volume"] = np.where(stats["position"] == "QB", stats["dropbacks"], stats["touches"])
    stats["touch_epa"] = stats["rushing_epa"].fillna(0) + stats["receiving_epa"].fillna(0)

    bio = duckdb_conn.execute("""
        SELECT gsis_id AS player_id, birth_date, draft_round, draft_pick
        FROM player_bio
    """).fetchdf()
    bio["birth_date"] = pd.to_datetime(bio["birth_date"], errors="coerce")
    bio["draft_round"] = bio["draft_round"].fillna(UNDRAFTED_ROUND)
    bio["draft_pick"] = bio["draft_pick"].fillna(UNDRAFTED_PICK)

    df = rank.merge(stats[["season", "player_id", "touches", "dropbacks", "volume", "touch_epa"]],
                     on=["season", "player_id"], how="left")
    df = df.merge(bio, on="player_id", how="left")
    return df


def age_at_season(birth_date, season):
    if pd.isna(birth_date):
        return None
    season_start = pd.Timestamp(year=int(season), month=9, day=1)
    return (season_start - birth_date).days / 365.25


def build_candidate_flags(df):
    """Every player-season that qualifies for the candidate pool, regardless
    of whether it ends up used in the final model (candidate_streak needs
    the full flag history to walk backward through)."""
    volume_ok = np.where(df["position"] == "QB", df["volume"] >= 100, df["volume"] >= 30)
    df["is_candidate"] = (df["tier_score"] < 3) & (df["games_played"] >= 8) & volume_ok
    return df


def build_position_share(df):
    team_totals = df.groupby(["season", "team", "position"])["volume"].transform("sum")
    df["position_share"] = df["volume"] / team_totals.replace(0, np.nan)
    return df


def build_pool(df):
    by_player_season = {(r.player_id, r.season): r for r in df.itertuples()}
    team_has_star = (
        df[df["tier_score"] >= 3].groupby(["season", "team"]).size() > 0
    )

    rows = []
    for r in df.itertuples():
        if not r.is_candidate:
            continue
        season = r.season
        age = age_at_season(r.birth_date, season)
        if age is None:
            continue

        star_row = by_player_season.get((r.player_id, season + 1))
        resolvable = season <= (LAST_COMPLETE_SEASON - 1)
        broke_out = None
        if resolvable:
            broke_out = 1 if (star_row is not None and star_row.tier_score >= 3) else 0

        # candidate_streak: consecutive PRIOR seasons also flagged as a candidate
        streak = 0
        s = season - 1
        while True:
            prev = by_player_season.get((r.player_id, s))
            if prev is None or not prev.is_candidate:
                break
            streak += 1
            s -= 1

        prior_row = by_player_season.get((r.player_id, season - 1))
        reached_starter_by_climbing = None
        if prior_row is not None:
            reached_starter_by_climbing = 1 if (prior_row.tier_score < 2 and r.tier_score >= 2) else 0

        other_star_on_team = False
        if (season, r.team) in team_has_star.index:
            # at least one Star+ row exists on this team-season -- check it isn't only this player
            teammates = df[(df["season"] == season) & (df["team"] == r.team) &
                           (df["player_id"] != r.player_id) & (df["tier_score"] >= 3)]
            other_star_on_team = len(teammates) > 0
        no_other_star_on_team = 0 if other_star_on_team else 1

        touch_epa = r.touch_epa if pd.notna(r.touch_epa) else 0.0
        epa_per_touch = touch_epa / r.volume if r.volume else 0.0

        draft_pick = r.draft_pick if pd.notna(r.draft_pick) else UNDRAFTED_PICK
        draft_round = r.draft_round if pd.notna(r.draft_round) else UNDRAFTED_ROUND

        rows.append({
            "player_id": r.player_id, "display_name": r.display_name,
            "position": r.position, "candidate_season": season,
            "age": age,
            "ppg_above_starter": r.ppg - STARTER_PPG_CUTOFF[r.position],
            "position_share": r.position_share if pd.notna(r.position_share) else 0.0,
            "epa_per_touch": epa_per_touch,
            "log_draft_pick": math.log(max(draft_pick, 1)),
            "top10_pick": 1 if draft_pick <= 10 else 0,
            "day3_or_undrafted": 1 if (draft_round >= 4) else 0,
            "candidate_streak": streak,
            "no_other_star_on_team": no_other_star_on_team,
            "reached_starter_by_climbing": reached_starter_by_climbing,
            "resolvable": resolvable,
            "broke_out": broke_out,
        })
    return pd.DataFrame(rows)


def fit_position_model(position, train_df):
    features = POSITION_FEATURES[position]
    fit_df = train_df.dropna(subset=features)
    X = sm.add_constant(fit_df[features].astype(float))
    y = fit_df["broke_out"].astype(float)
    model = sm.Logit(y, X).fit(disp=0)
    log(f"{position} coefficients (n={len(fit_df)}):")
    for name, coef, p in zip(model.params.index, model.params.values, model.pvalues.values):
        log(f"    {name:28s} {coef:+.3f}  p={p:.4f}")
    return model


def backtest(position, model, resolved_df, test_season):
    features = POSITION_FEATURES[position]
    test = resolved_df[(resolved_df["position"] == position) &
                        (resolved_df["candidate_season"] == test_season)].dropna(subset=features)
    if test.empty:
        return
    X = sm.add_constant(test[features].astype(float), has_constant="add")
    X = X.reindex(columns=model.params.index, fill_value=0.0)
    preds = model.predict(X)
    y = test["broke_out"].astype(float)
    if y.nunique() < 2:
        log(f"  {position} {test_season} candidates (n={len(test)}): single outcome class, AUC undefined")
        return
    auc = roc_auc_score(y, preds)
    log(f"  {position} {test_season} candidates (n={len(test)}, breakout rate {y.mean():.1%}): AUC {auc:.3f}")


def score_all(position, model, pool_df):
    features = POSITION_FEATURES[position]
    scoreable = pool_df[pool_df["position"] == position].dropna(subset=features).copy()
    X = sm.add_constant(scoreable[features].astype(float), has_constant="add")
    X = X.reindex(columns=model.params.index, fill_value=0.0)
    scoreable["predicted_probability"] = model.predict(X)
    return scoreable


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


def write_outputs(sqlite_conn, scored_by_position):
    crosswalk = gsis_to_canonical(sqlite_conn)
    pred_rows = []
    feature_rows = []
    for position, scored in scored_by_position.items():
        features = POSITION_FEATURES[position]
        for r in scored.itertuples():
            canonical_id = crosswalk.get(r.player_id, f"gsis:{r.player_id}")
            season_predicted_for = r.candidate_season + 1
            pred_rows.append((
                canonical_id, MODEL_NAME, MODEL_VERSION, season_predicted_for,
                float(r.predicted_probability),
                int(r.broke_out) if r.resolvable else None,
            ))
            feat_dict = {name: getattr(r, name) for name in features}
            feat_dict["position"] = position
            feature_rows.append((
                canonical_id, r.candidate_season, "breakout_candidate", MODEL_VERSION,
                json.dumps(feat_dict, default=str),
                int(r.broke_out) if r.resolvable else None,
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
    sqlite_conn.commit()

    duck_conn = duckdb.connect(DUCKDB_PATH)
    duck_conn.execute(
        "DELETE FROM model_feature_pool WHERE model_version = ? AND event_type = 'breakout_candidate'",
        [MODEL_VERSION],
    )
    duck_conn.executemany(
        """INSERT INTO model_feature_pool
               (player_id, season, event_type, model_version, features, outcome)
           VALUES (?, ?, ?, ?, ?, ?)""",
        feature_rows,
    )
    duck_conn.close()
    log(f"wrote {len(pred_rows)} rows to model_predictions, {len(feature_rows)} rows to model_feature_pool")


def update_sync_log(sqlite_conn, row_count):
    total = sqlite_conn.execute("SELECT count(*) FROM model_predictions").fetchone()[0]
    sqlite_conn.execute(
        """INSERT INTO sync_log (table_name, source, last_synced_at, row_count, notes)
           VALUES ('model_predictions', 'build_bounceback_model.py + build_breakout_model.py',
                   datetime('now'), ?, ?)
           ON CONFLICT(table_name) DO UPDATE SET
               source=excluded.source, last_synced_at=datetime('now'),
               row_count=excluded.row_count, notes=excluded.notes""",
        (total, f"breakout {MODEL_VERSION}: {row_count} rows (total across both models: {total})"),
    )
    sqlite_conn.commit()


def main():
    if not os.path.exists(SQLITE_PATH) or not os.path.exists(DUCKDB_PATH):
        log("app.db / analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    duckdb_conn = duckdb.connect(DUCKDB_PATH)
    df = load_base_data(duckdb_conn)
    duckdb_conn.close()

    df = build_candidate_flags(df)
    df = build_position_share(df)
    pool = build_pool(df)
    log(f"candidate pool: {len(pool)} rows -- " +
        ", ".join(f"{p} {(pool['position'] == p).sum()}" for p in POSITION_FEATURES))

    resolved = pool[pool["resolvable"]]
    forward = pool[~pool["resolvable"]]

    scored_by_position = {}
    for position, features in POSITION_FEATURES.items():
        pos_resolved = resolved[resolved["position"] == position]
        train = pos_resolved[pos_resolved["candidate_season"] <= 2022]
        log(f"--- {position} ({len(train)} training rows) ---")
        model = fit_position_model(position, train)

        log(f"  walk-forward backtest:")
        backtest(position, model, pos_resolved, 2023)
        backtest(position, model, pos_resolved, 2024)

        full_model = fit_position_model(position, pos_resolved)
        scored_resolved = score_all(position, full_model, pos_resolved)
        scored_forward = score_all(position, full_model, forward)
        scored_by_position[position] = pd.concat([scored_resolved, scored_forward], ignore_index=True)

        top5 = scored_forward.sort_values("predicted_probability", ascending=False).head(5)
        if not top5.empty:
            forward_season = int(scored_forward["candidate_season"].iloc[0]) + 1
            log(f"  top 5 forward-looking {position} predictions (breakout season {forward_season}):")
            for r in top5.itertuples():
                log(f"    {r.display_name:24s} {r.predicted_probability:.1%}")

    total_rows = sum(len(v) for v in scored_by_position.values())
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    write_outputs(sqlite_conn, scored_by_position)
    update_sync_log(sqlite_conn, total_rows)
    sqlite_conn.close()

    log("done.")


if __name__ == "__main__":
    main()
