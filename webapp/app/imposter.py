"""Imposter -- a random year+stat category shows 10 names: 9 real players
from that season's actual top 10 in the stat (one real top-10 player is
left out, to keep the shown count at 10) and 1 "imposter" from that same
season's rank 11-20. Click names one at a time, trying to click all 9 real
ones without ever clicking the imposter -- click all 9 and you win; click
the imposter and you lose, with your score being however many you'd
correctly clicked first.

Uses app.stat_categories.top_n() for the same per-category/per-year
rankings 501 and the NFL Top 100 hints already rely on, so "top 10" here
means the same thing everywhere in the app.
"""
import random

from app.stat_categories import top_n

WIN_THRESHOLD = 9


def start_round(conn, duckdb_conn, user_id, category, year):
    """Returns the new round_id, or None if this (category, year) doesn't
    have at least 11 qualifying players (can't build a real top-10 +
    11-20 split)."""
    pool = top_n(duckdb_conn, category, year, n=20)
    if len(pool) < 11:
        return None

    top10 = pool[:10]
    rest = pool[10:20]
    shown_top10 = random.sample(top10, k=9)
    imposter_name, _ = random.choice(rest)

    names = [(name, True) for name, _ in shown_top10] + [(imposter_name, False)]
    random.shuffle(names)

    cur = conn.execute(
        "INSERT INTO imposter_rounds (user_id, year, category, imposter_name) VALUES (?, ?, ?, ?)",
        (user_id, year, category, imposter_name),
    )
    round_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO imposter_round_names (round_id, name, is_top10, display_order) VALUES (?, ?, ?, ?)",
        [(round_id, name, int(is_top10), i) for i, (name, is_top10) in enumerate(names)],
    )
    conn.commit()
    return round_id


def get_round(conn, round_id, user_id):
    return conn.execute(
        "SELECT * FROM imposter_rounds WHERE round_id = ? AND user_id = ?", (round_id, user_id)
    ).fetchone()


def get_names(conn, round_id):
    return conn.execute(
        "SELECT * FROM imposter_round_names WHERE round_id = ? ORDER BY display_order", (round_id,)
    ).fetchall()


def click_name(conn, round_id, name):
    """Returns 'won'/'lost'/'active' (the round's status after this click),
    or None if the round is already finished or name was already clicked."""
    round_row = conn.execute("SELECT * FROM imposter_rounds WHERE round_id = ?", (round_id,)).fetchone()
    if round_row is None or round_row["status"] != "active":
        return None
    row = conn.execute(
        "SELECT * FROM imposter_round_names WHERE round_id = ? AND name = ?", (round_id, name)
    ).fetchone()
    if row is None or row["clicked"]:
        return None

    conn.execute(
        "UPDATE imposter_round_names SET clicked = 1 WHERE round_id = ? AND name = ?", (round_id, name)
    )

    if not row["is_top10"]:
        conn.execute(
            "UPDATE imposter_rounds SET status = 'lost', completed_at = datetime('now') WHERE round_id = ?",
            (round_id,),
        )
        conn.commit()
        return "lost"

    correct_count = round_row["correct_count"] + 1
    won = correct_count >= WIN_THRESHOLD
    conn.execute(
        """UPDATE imposter_rounds SET correct_count = ?,
               status = CASE WHEN ? THEN 'won' ELSE status END,
               completed_at = CASE WHEN ? THEN datetime('now') ELSE completed_at END
           WHERE round_id = ?""",
        (correct_count, won, won, round_id),
    )
    conn.commit()
    return "won" if won else "active"


def leaderboard(conn, category=None):
    """Best (highest correct_count) finished round per user -- a 'won'
    round is always correct_count=9; a 'lost' one is however many were
    clicked correctly before the fatal click."""
    where = "status IN ('won', 'lost')"
    params = []
    if category is not None:
        where += " AND category = ?"
        params.append(category)

    rows = conn.execute(
        f"""SELECT r.user_id, u.username, r.category, r.correct_count, r.status
            FROM imposter_rounds r JOIN users u ON u.user_id = r.user_id
            WHERE {where}""",
        params,
    ).fetchall()

    best = {}
    for r in rows:
        key = r["user_id"]
        if key not in best or r["correct_count"] > best[key]["correct_count"]:
            best[key] = {
                "user_id": r["user_id"], "username": r["username"], "category": r["category"],
                "correct_count": r["correct_count"], "status": r["status"],
            }
    results = sorted(best.values(), key=lambda r: r["correct_count"], reverse=True)
    for i, r in enumerate(results, start=1):
        r["rank"] = i
    return results
