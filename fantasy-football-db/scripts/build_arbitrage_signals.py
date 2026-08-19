#!/usr/bin/env python3
"""
build_arbitrage_signals.py -- computes the buy-low/sell-high arbitrage
signal (dynasty ECR percentile vs. redraft ECR percentile gap) and writes
it to app.db's arbitrage_signals table.

Method (see docs/sleeper-and-trade-value-pipeline.md): for each player,
compare their FantasyPros dynasty-rankings percentile against their
redraft-rankings percentile, separately for 1QB and superflex (SF) formats.
    percentile = 1 - (ecr - 1) / (pool_size - 1)   -- 1.0 = ranked #1
    gap = dynasty_percentile - redraft_percentile
    gap >= +0.15  -> BUY_LOW  (dynasty market believes in him more than his
                     current-season ranking does)
    gap <= -0.15  -> SELL_HIGH (current production is outrunning his
                     long-term dynasty price)
    else          -> FAIR

This is a lightweight substitute for the full breakout/fall-off model
(see docs/breakout-falloff-methodology.md) -- a real predictive model, not
just a market-pricing gap. Ported from pipeline/build_comparison_model.py
(a prior Cowork session's prototype, which computed the same signal from
the same dynastyprocess ECR snapshot but wrote to a standalone JSON file
rather than app.db).

Known limitation carried over from that prototype: run in the preseason,
before any games are played, dynasty and redraft rankings track closely for
established players -- almost every signal that fires is a rookie/prospect
(real dynasty-vs-redraft uncertainty) or a deep-bench player, not yet a
genuine performance-vs-price gap. Re-run this every few weeks in-season as
redraft rankings start moving on actual results.

Usage:
    python3 scripts/build_arbitrage_signals.py

Safe to re-run: overwrites the row for the resolved as_of_date on conflict
rather than duplicating it, so re-running the same day just refreshes.
"""
import os
import sqlite3
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SQLITE_PATH = os.path.join(DATA_DIR, "app.db")
DUCKDB_PATH = os.path.join(DATA_DIR, "analytics.duckdb")

# (result_key, fp_ecr_history page)
PAGES = {
    "dynasty_1qb": "/nfl/rankings/dynasty-overall.php",
    "dynasty_sf": "/nfl/rankings/dynasty-superflex.php",
    "redraft_1qb": "/nfl/rankings/ppr-cheatsheets.php",
    "redraft_sf": "/nfl/rankings/ppr-superflex-cheatsheets.php",
}
BUY_LOW_THRESHOLD = 0.15
SELL_HIGH_THRESHOLD = -0.15


def log(msg):
    print(f"[build_arbitrage_signals] {msg}")


def load_ecr_by_page(duckdb_conn):
    """One {fp_id: ecr} dict per page, plus each page's pool size (players
    ranked on that page) -- both needed for the percentile formula."""
    by_page = {}
    pool_size = {}
    for key, page in PAGES.items():
        rows = duckdb_conn.execute(
            """SELECT fp_id, ecr FROM fp_ecr_history
               WHERE page = ? AND fp_id IS NOT NULL AND ecr IS NOT NULL""",
            [page],
        ).fetchall()
        by_page[key] = {fp_id: ecr for fp_id, ecr in rows}
        pool_size[key] = len(rows)
    log(f"pool sizes: {pool_size}")
    return by_page, pool_size


def percentile(by_page, pool_size, key, fp_id):
    ecr = by_page[key].get(fp_id)
    if ecr is None:
        return None
    n = pool_size[key]
    if n <= 1:
        return None
    return 1 - (ecr - 1) / (n - 1)


def classify(gap):
    if gap >= BUY_LOW_THRESHOLD:
        return "BUY_LOW"
    if gap <= SELL_HIGH_THRESHOLD:
        return "SELL_HIGH"
    return "FAIR"


def compute_signals(by_page, pool_size):
    """One row per (player_id, format) with a computable gap -- the union
    of every fp_id that appears on any of the 4 ranking pages."""
    all_fp_ids = set()
    for key in PAGES:
        all_fp_ids |= by_page[key].keys()

    rows = []
    for fp_id in all_fp_ids:
        for fmt, dyn_key, red_key in (
            ("1qb", "dynasty_1qb", "redraft_1qb"),
            ("sf", "dynasty_sf", "redraft_sf"),
        ):
            dyn_p = percentile(by_page, pool_size, dyn_key, fp_id)
            red_p = percentile(by_page, pool_size, red_key, fp_id)
            if dyn_p is None or red_p is None:
                continue
            gap = dyn_p - red_p
            rows.append((fp_id, fmt, dyn_p, red_p, gap, classify(gap)))
    return rows


def get_as_of_date(duckdb_conn):
    pages_list = list(PAGES.values())
    placeholders = ",".join("?" * len(pages_list))
    result = duckdb_conn.execute(
        f"SELECT max(scrape_date) FROM fp_ecr_history WHERE page IN ({placeholders})",
        pages_list,
    ).fetchone()
    if not result or result[0] is None:
        log("no scrape_date found in fp_ecr_history -- has build_db.py been run?")
        sys.exit(1)
    return result[0].isoformat()


def write_signals(sqlite_conn, rows, as_of_date):
    sqlite_conn.executemany(
        """INSERT INTO arbitrage_signals
               (player_id, format, as_of_date, dynasty_percentile,
                redraft_percentile, gap, signal)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(player_id, format, as_of_date) DO UPDATE SET
               dynasty_percentile=excluded.dynasty_percentile,
               redraft_percentile=excluded.redraft_percentile,
               gap=excluded.gap, signal=excluded.signal""",
        [(fp_id, fmt, as_of_date, dyn_p, red_p, gap, sig)
         for fp_id, fmt, dyn_p, red_p, gap, sig in rows],
    )
    sqlite_conn.commit()


def update_sync_log(sqlite_conn, row_count, as_of_date):
    sqlite_conn.execute(
        """INSERT INTO sync_log (table_name, source, last_synced_at, row_count, notes)
           VALUES ('arbitrage_signals', 'derived from fp_ecr_history', datetime('now'), ?, ?)
           ON CONFLICT(table_name) DO UPDATE SET
               source=excluded.source, last_synced_at=datetime('now'),
               row_count=excluded.row_count, notes=excluded.notes""",
        (row_count, f"as_of_date {as_of_date}"),
    )
    sqlite_conn.commit()


def main():
    if not os.path.exists(SQLITE_PATH) or not os.path.exists(DUCKDB_PATH):
        log("app.db / analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    duckdb_conn = duckdb.connect(DUCKDB_PATH, read_only=True)
    by_page, pool_size = load_ecr_by_page(duckdb_conn)
    as_of_date = get_as_of_date(duckdb_conn)
    rows = compute_signals(by_page, pool_size)
    duckdb_conn.close()

    n_buy = sum(1 for r in rows if r[5] == "BUY_LOW")
    n_sell = sum(1 for r in rows if r[5] == "SELL_HIGH")
    n_fair = sum(1 for r in rows if r[5] == "FAIR")
    log(f"{len(rows)} player-format signals as of {as_of_date}: "
        f"{n_buy} BUY_LOW, {n_sell} SELL_HIGH, {n_fair} FAIR")

    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    write_signals(sqlite_conn, rows, as_of_date)
    update_sync_log(sqlite_conn, len(rows), as_of_date)
    sqlite_conn.close()

    log("done.")


if __name__ == "__main__":
    main()
