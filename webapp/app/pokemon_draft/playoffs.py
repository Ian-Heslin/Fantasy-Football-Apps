"""Single-elimination playoff bracket. Supports bracket_size 2, 4, or 8
(power-of-2 team counts only -- see BRACKET_STRUCTURE; a non-power-of-2
size would need a bye-seeding scheme this league has no requirement for).

Schema model (see schema/sqlite_schema.sql's pokemon_playoff_bracket
comment): one row per MATCH slot (QF1..QF4, SF1..SF2, F), not per
participant. seed_bracket() seeds round 1 directly from regular-season
standings (via the fixed tiebreaker order) and creates that round's real
pokemon_schedule/pokemon_matches rows immediately, since both
participants are already known. Later rounds' bracket rows exist from
the start (coach_id NULL, "not decided yet") but their pokemon_schedule
row is only created once BOTH of their feeding slots have a recorded
winner -- advance_bracket() does that walk, called after every playoff
match confirms. Standard tournament seeding (1v8, 4v5, 2v7, 3v6 for an
8-team bracket) keeps top seeds apart for as long as possible.
"""
from app.pokemon_draft import seasons, standings

BRACKET_STRUCTURE = {
    2: {
        "F": {"round": "F", "feeds": None, "seeds": (1, 2)},
    },
    4: {
        "SF1": {"round": "SF", "feeds": "F", "seeds": (1, 4)},
        "SF2": {"round": "SF", "feeds": "F", "seeds": (2, 3)},
        "F": {"round": "F", "feeds": None, "seeds": None},
    },
    8: {
        "QF1": {"round": "QF", "feeds": "SF1", "seeds": (1, 8)},
        "QF2": {"round": "QF", "feeds": "SF1", "seeds": (4, 5)},
        "QF3": {"round": "QF", "feeds": "SF2", "seeds": (2, 7)},
        "QF4": {"round": "QF", "feeds": "SF2", "seeds": (3, 6)},
        "SF1": {"round": "SF", "feeds": "F", "seeds": None},
        "SF2": {"round": "SF", "feeds": "F", "seeds": None},
        "F": {"round": "F", "feeds": None, "seeds": None},
    },
}


def is_seeded(conn, season_id):
    return conn.execute(
        "SELECT 1 FROM pokemon_playoff_bracket WHERE season_id = ? LIMIT 1", (season_id,)
    ).fetchone() is not None


def seed_bracket(conn, season_id):
    """None on success, or an error string. Refuses to reseed a bracket
    that already exists -- clear_bracket() first if it's genuinely wrong."""
    season = seasons.get_season(conn, season_id)
    if season is None:
        return "No such season."
    size = season["playoff_bracket_size"]
    structure = BRACKET_STRUCTURE.get(size)
    if structure is None:
        return f"Playoff bracket size must be one of {sorted(BRACKET_STRUCTURE)}, not {size}."
    if is_seeded(conn, season_id):
        return "This season's playoff bracket has already been seeded."

    ranked = standings.standings(conn, season_id)
    if len(ranked) < size:
        return f"Need at least {size} coaches with standings to seed a {size}-team bracket."
    seed_to_coach = {i + 1: r["coach"]["coach_id"] for i, r in enumerate(ranked[:size])}

    for slot, info in structure.items():
        top_seed = info["seeds"][0] if info["seeds"] else None
        conn.execute(
            "INSERT INTO pokemon_playoff_bracket (season_id, slot, round, seed, coach_id, advances_to_slot) "
            "VALUES (?, ?, ?, ?, NULL, ?)",
            (season_id, slot, info["round"], top_seed, info["feeds"]),
        )
        if info["seeds"] is not None:
            home = seed_to_coach[info["seeds"][0]]
            away = seed_to_coach[info["seeds"][1]]
            cur = conn.execute(
                "INSERT INTO pokemon_schedule (season_id, round, coach_id_home, coach_id_away, bracket_slot) "
                "VALUES (?, ?, ?, ?, ?)",
                (season_id, info["round"], home, away, slot),
            )
            conn.execute("INSERT INTO pokemon_matches (schedule_id) VALUES (?)", (cur.lastrowid,))
    conn.commit()
    return None


def clear_bracket(conn, season_id):
    """None on success, or an error string. Refuses once any playoff
    match has a reported result, same guard schedule.clear_schedule()
    uses for the regular season."""
    reported = conn.execute(
        """SELECT count(*) c FROM pokemon_matches m
           JOIN pokemon_schedule s ON s.schedule_id = m.schedule_id
           WHERE s.season_id = ? AND s.round IS NOT NULL AND m.status != 'unreported'""",
        (season_id,),
    ).fetchone()["c"]
    if reported > 0:
        return "Can't clear the bracket -- some playoff matches have already been reported."
    conn.execute(
        "DELETE FROM pokemon_matches WHERE schedule_id IN "
        "(SELECT schedule_id FROM pokemon_schedule WHERE season_id = ? AND round IS NOT NULL)",
        (season_id,))
    conn.execute("DELETE FROM pokemon_schedule WHERE season_id = ? AND round IS NOT NULL", (season_id,))
    conn.execute("DELETE FROM pokemon_playoff_bracket WHERE season_id = ?", (season_id,))
    conn.commit()
    return None


def advance_bracket(conn, season_id):
    """Idempotent -- safe to call after every playoff match confirmation.
    Records each confirmed match's winner in its bracket slot, then
    creates the next round's schedule/match row for any target slot whose
    feeding slots are now ALL decided."""
    confirmed = conn.execute(
        """SELECT s.bracket_slot, m.winner_coach_id FROM pokemon_matches m
           JOIN pokemon_schedule s ON s.schedule_id = m.schedule_id
           WHERE s.season_id = ? AND s.round IS NOT NULL AND m.status = 'confirmed'
             AND s.bracket_slot IS NOT NULL""",
        (season_id,),
    ).fetchall()
    for r in confirmed:
        conn.execute(
            "UPDATE pokemon_playoff_bracket SET coach_id = ? "
            "WHERE season_id = ? AND slot = ? AND coach_id IS NULL",
            (r["winner_coach_id"], season_id, r["bracket_slot"]),
        )
    conn.commit()

    all_slots = conn.execute(
        "SELECT slot, round, coach_id, advances_to_slot FROM pokemon_playoff_bracket WHERE season_id = ?",
        (season_id,),
    ).fetchall()
    by_target = {}
    for s in all_slots:
        if s["advances_to_slot"]:
            by_target.setdefault(s["advances_to_slot"], []).append(s)

    for target_slot, feeders in by_target.items():
        if any(f["coach_id"] is None for f in feeders):
            continue
        already = conn.execute(
            "SELECT 1 FROM pokemon_schedule WHERE season_id = ? AND bracket_slot = ?",
            (season_id, target_slot),
        ).fetchone()
        if already:
            continue
        target = conn.execute(
            "SELECT round FROM pokemon_playoff_bracket WHERE season_id = ? AND slot = ?",
            (season_id, target_slot),
        ).fetchone()
        home, away = feeders[0]["coach_id"], feeders[1]["coach_id"]
        cur = conn.execute(
            "INSERT INTO pokemon_schedule (season_id, round, coach_id_home, coach_id_away, bracket_slot) "
            "VALUES (?, ?, ?, ?, ?)",
            (season_id, target["round"], home, away, target_slot),
        )
        conn.execute("INSERT INTO pokemon_matches (schedule_id) VALUES (?)", (cur.lastrowid,))
    conn.commit()


def bracket_view(conn, season_id):
    """Every bracket slot with its coach/team names and match status, for
    rendering. Ordered so earlier rounds (more slots) come first."""
    return conn.execute(
        """SELECT b.slot, b.round, b.seed, b.coach_id, b.advances_to_slot,
                  c.team_name, s.schedule_id, s.coach_id_home, s.coach_id_away,
                  ch.team_name AS home_team, ca.team_name AS away_team,
                  m.match_id, m.status
           FROM pokemon_playoff_bracket b
           LEFT JOIN pokemon_season_coaches c ON c.coach_id = b.coach_id
           LEFT JOIN pokemon_schedule s ON s.season_id = b.season_id AND s.bracket_slot = b.slot
           LEFT JOIN pokemon_season_coaches ch ON ch.coach_id = s.coach_id_home
           LEFT JOIN pokemon_season_coaches ca ON ca.coach_id = s.coach_id_away
           LEFT JOIN pokemon_matches m ON m.schedule_id = s.schedule_id
           WHERE b.season_id = ?
           ORDER BY b.round = 'F', b.round = 'SF', b.slot""",
        (season_id,),
    ).fetchall()


def champion(conn, season_id):
    """The winning coach_id, or None if the final hasn't been decided."""
    row = conn.execute(
        "SELECT coach_id FROM pokemon_playoff_bracket WHERE season_id = ? AND slot = 'F'",
        (season_id,),
    ).fetchone()
    return row["coach_id"] if row else None
