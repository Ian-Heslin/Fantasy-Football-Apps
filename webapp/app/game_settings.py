"""Per-user difficulty filter for 501/Imposter's randomized picks --
narrows which years and stat categories can come up, so someone who only
knows recent seasons (or the "big"/more familiar stats) can make the
games easier for themselves without changing anything for anyone else.

Doesn't touch 501's manual (player, year) guesses -- those are always
typed in by the player, so restricting them would just make the game
less flexible rather than easier. It applies to: Imposter's random
category+year picker, and which category cards 501/Imposter show at all.
"""
from app.stat_categories import STAT_CATEGORIES


def get_settings(conn, user_id):
    row = conn.execute("SELECT * FROM game_settings WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return {"min_year": None, "max_year": None, "enabled_categories": None}
    enabled = set(row["enabled_categories"].split(",")) if row["enabled_categories"] else None
    return {"min_year": row["min_year"], "max_year": row["max_year"], "enabled_categories": enabled}


def save_settings(conn, user_id, min_year, max_year, enabled_categories):
    """enabled_categories: list of stat_categories.py keys. Every category
    checked (or none checked) is stored as "no restriction" (NULL) rather
    than a redundant full list."""
    valid = [c for c in (enabled_categories or []) if c in STAT_CATEGORIES]
    enabled_str = ",".join(valid) if valid and len(valid) < len(STAT_CATEGORIES) else None
    conn.execute(
        """INSERT INTO game_settings (user_id, min_year, max_year, enabled_categories) VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
               min_year=excluded.min_year, max_year=excluded.max_year,
               enabled_categories=excluded.enabled_categories""",
        (user_id, min_year, max_year, enabled_str),
    )
    conn.commit()


def allowed_categories(settings):
    return settings["enabled_categories"] or set(STAT_CATEGORIES)


def clamp_year_range(settings, year_min, year_max):
    """Intersect a category's real [year_min, year_max] with the user's
    preferred range. Falls back to the real range if the preference
    doesn't overlap it at all, rather than leaving nothing to pick from."""
    lo = max(year_min, settings["min_year"]) if settings["min_year"] else year_min
    hi = min(year_max, settings["max_year"]) if settings["max_year"] else year_max
    if lo > hi:
        return year_min, year_max
    return lo, hi
