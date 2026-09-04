"""Keeper-league planning: predicted keepers for an upcoming draft, the
round-shift rule that turns "drafted round" into "keeper round", and a
mock-draft board built from that -- pure functions over DB rows, no
FastAPI/route code (same shape as app/pickem.py and friends).

Keeper rule (a WHMFFL house rule, not something Yahoo enforces or knows
about): a kept player costs the round AFTER where they were drafted last
year, except a 1st-round pick keeps its 1st-round slot (there's nowhere
higher for "+1" to go). If two of one team's keepers compute to the same
round, the less valuable one (the one with the later original draft
round) gets bumped up to (that round - 1), cascading further if that's
also taken -- see assign_team_keepers().

Keeper cells are always computed live from keeper_predictions, never
stored -- same "recompute on every view" approach app/pickem.py uses for
standings. Only manual/auto mock-draft picks are persisted
(mock_draft_picks), and only for rounds a keeper doesn't already occupy.
"""
import difflib

from app.trivia import normalize_name

MAX_KEEPERS = 3


def last_draft_season(conn, league_id):
    """The most recently loaded real draft for this league, or None if
    load_yahoo.py's draft-results pull hasn't been run yet.
    league_draft_picks only has rows for seasons that actually drafted,
    so this is naturally "last season" once the current one is
    pre-draft."""
    row = conn.execute(
        "SELECT max(season) AS season FROM league_draft_picks WHERE league_id = ?",
        (league_id,),
    ).fetchone()
    return row["season"] if row and row["season"] is not None else None


def num_rounds(conn, league_id, draft_season):
    """How many rounds the board needs -- the same as last year's
    roster-spot count, per this league's own rule that this doesn't
    change year to year. Derived from last year's actual draft (its
    highest round number), not the CURRENT roster snapshot, so a
    waiver-wire gap in a live roster right now can't shrink the board."""
    row = conn.execute(
        "SELECT max(round) AS rounds FROM league_draft_picks WHERE league_id = ? AND season = ?",
        (league_id, draft_season),
    ).fetchone()
    return row["rounds"] if row and row["rounds"] is not None else 0


def keeper_eligible_players(conn, league_id, draft_season):
    """{roster_id: [{'player_id','name','position','team','drafted_round'}]}
    -- last year's draftees who are STILL on that same roster right now
    (a player since traded or dropped isn't keeper-eligible here). Joins
    against the latest roster_players snapshot, the same
    max(as_of_date) pattern app/routes/rosters.py uses."""
    rows = conn.execute(
        """
        SELECT ldp.roster_id, ldp.round AS drafted_round,
               p.player_id, p.name, p.position, p.team
        FROM league_draft_picks ldp
        JOIN roster_players rp
          ON rp.league_id = ldp.league_id AND rp.roster_id = ldp.roster_id
         AND rp.player_id = ldp.player_id
         AND rp.as_of_date = (
             SELECT max(as_of_date) FROM roster_players WHERE league_id = ldp.league_id
         )
        JOIN players p ON p.player_id = ldp.player_id
        WHERE ldp.league_id = ? AND ldp.season = ?
        ORDER BY ldp.roster_id, ldp.round
        """,
        (league_id, draft_season),
    ).fetchall()
    by_roster = {}
    for r in rows:
        by_roster.setdefault(r["roster_id"], []).append(r)
    return by_roster


def get_keeper_predictions(conn, user_id, league_id, keeper_season):
    """{roster_id: [player_id, ...]} -- this user's saved guesses at each
    team's keepers for the upcoming draft (keeper_season)."""
    rows = conn.execute(
        "SELECT roster_id, player_id FROM keeper_predictions "
        "WHERE user_id = ? AND league_id = ? AND season = ?",
        (user_id, league_id, keeper_season),
    ).fetchall()
    by_roster = {}
    for r in rows:
        by_roster.setdefault(r["roster_id"], []).append(r["player_id"])
    return by_roster


def save_keeper_predictions(conn, user_id, league_id, keeper_season, roster_id, player_ids):
    """Replaces one team's predicted keepers with `player_ids` (de-duped,
    capped at MAX_KEEPERS -- extra selections are dropped rather than
    erroring, same as a checkbox group that simply can't produce more
    than what's checked)."""
    player_ids = list(dict.fromkeys(player_ids))[:MAX_KEEPERS]
    conn.execute(
        "DELETE FROM keeper_predictions WHERE user_id = ? AND league_id = ? "
        "AND season = ? AND roster_id = ?",
        (user_id, league_id, keeper_season, roster_id),
    )
    for player_id in player_ids:
        conn.execute(
            """INSERT INTO keeper_predictions (user_id, league_id, season, roster_id, player_id)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, league_id, keeper_season, roster_id, player_id),
        )
    conn.commit()


def keeper_round(drafted_round):
    """The un-collided round a single keeper would cost."""
    if drafted_round <= 1:
        return 1
    return drafted_round + 1


def assign_team_keepers(keepers):
    """keepers: [{'player_id', 'drafted_round', ...}, ...] for ONE team.
    Returns the same dicts with 'keeper_round' and 'conflict' added,
    applying the collision rule: the most valuable keeper (lowest
    computed round, ties broken by earlier original draft round) claims
    its round first; a later keeper whose round is already taken moves up
    to (taken - 1), cascading further if that's taken too. Never goes
    below round 1 -- a keeper that would need to (more collisions than
    there are rounds above it, i.e. more than MAX_KEEPERS colliding
    keepers) stays at round 1 and is flagged conflict=True rather than
    silently double-booking a slot."""
    ordered = sorted(keepers, key=lambda k: (keeper_round(k["drafted_round"]), k["drafted_round"]))
    taken = set()
    assigned = []
    for k in ordered:
        round_num = keeper_round(k["drafted_round"])
        while round_num in taken and round_num > 1:
            round_num -= 1
        conflict = round_num in taken
        taken.add(round_num)
        assigned.append({**k, "keeper_round": round_num, "conflict": conflict})
    return assigned


def compute_keeper_board(conn, league_id, draft_season, keeper_season, user_id):
    """{roster_id: [{'player_id','name','position','team','drafted_round',
    'keeper_round','conflict'}, ...]} for every team with at least one
    predicted keeper. Cross-references keeper_eligible_players() (so a
    prediction for a player who's since left the roster is silently
    dropped, not shown as a phantom keeper) against this user's saved
    keeper_predictions."""
    eligible = keeper_eligible_players(conn, league_id, draft_season)
    predictions = get_keeper_predictions(conn, user_id, league_id, keeper_season)

    board = {}
    for roster_id, player_ids in predictions.items():
        pool = {p["player_id"]: p for p in eligible.get(roster_id, [])}
        keepers = [dict(pool[pid]) for pid in player_ids if pid in pool]
        if keepers:
            board[roster_id] = assign_team_keepers(keepers)
    return board


def get_mock_draft_picks(conn, user_id, league_id, keeper_season):
    """{(round, roster_id): row} for this user's saved manual/auto picks.
    Never includes keeper cells -- those are computed live by
    compute_keeper_board(), not stored."""
    rows = conn.execute(
        """SELECT mdp.round, mdp.roster_id, mdp.player_id, mdp.source,
                  p.name, p.position, p.team
           FROM mock_draft_picks mdp
           JOIN players p ON p.player_id = mdp.player_id
           WHERE mdp.user_id = ? AND mdp.league_id = ? AND mdp.season = ?""",
        (user_id, league_id, keeper_season),
    ).fetchall()
    return {(r["round"], r["roster_id"]): r for r in rows}


def reconcile_mock_draft(conn, user_id, league_id, keeper_season, board):
    """Clears any saved manual/auto pick that now sits on a round a
    keeper occupies -- happens when predicted keepers change after some
    picks were already made. Call after save_keeper_predictions()."""
    for roster_id, keepers in board.items():
        for k in keepers:
            conn.execute(
                "DELETE FROM mock_draft_picks WHERE user_id = ? AND league_id = ? "
                "AND season = ? AND round = ? AND roster_id = ?",
                (user_id, league_id, keeper_season, k["keeper_round"], roster_id),
            )
    conn.commit()


def set_mock_draft_pick(conn, user_id, league_id, keeper_season, round_num, roster_id,
                         player_id, source, board, existing_picks):
    """Writes one manual/auto pick, enforcing: not a keeper-locked round
    for that team, and the player isn't already placed anywhere else on
    this board (a real draft can't pick the same player twice). `board`
    is compute_keeper_board()'s result and `existing_picks` is
    get_mock_draft_picks()'s -- passed in so callers that already loaded
    them (every route here does, to render the grid) don't pay for a
    second query. Returns None on success, or a short error string."""
    for k in board.get(roster_id, []):
        if k["keeper_round"] == round_num:
            return "That round is a keeper slot for this team."

    keeper_player_ids = {k["player_id"] for keepers in board.values() for k in keepers}
    if player_id in keeper_player_ids:
        return "That player is already a keeper elsewhere on this board."

    for (r, rid), pick in existing_picks.items():
        if pick["player_id"] == player_id and (r, rid) != (round_num, roster_id):
            return "That player is already picked elsewhere on this board."

    conn.execute(
        """INSERT INTO mock_draft_picks
               (user_id, league_id, season, round, roster_id, player_id, source, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(user_id, league_id, season, round, roster_id) DO UPDATE SET
               player_id=excluded.player_id, source=excluded.source,
               updated_at=datetime('now')""",
        (user_id, league_id, keeper_season, round_num, roster_id, player_id, source),
    )
    conn.commit()
    return None


def clear_mock_draft_pick(conn, user_id, league_id, keeper_season, round_num, roster_id):
    conn.execute(
        "DELETE FROM mock_draft_picks WHERE user_id = ? AND league_id = ? AND season = ? "
        "AND round = ? AND roster_id = ?",
        (user_id, league_id, keeper_season, round_num, roster_id),
    )
    conn.commit()


def reset_mock_draft(conn, user_id, league_id, keeper_season):
    """Clears every manual/auto pick for this user's board. Keeper cells
    are never stored, so they reappear unchanged next time the board is
    computed -- this only undoes hand-entered/auto-filled picks."""
    conn.execute(
        "DELETE FROM mock_draft_picks WHERE user_id = ? AND league_id = ? AND season = ?",
        (user_id, league_id, keeper_season),
    )
    conn.commit()


def best_available(conn, league_id, arb_format, exclude_player_ids, limit=None):
    """Players not in `exclude_player_ids`, ranked by redraft ECR
    percentile (highest first) -- the same redraft_percentile
    app/arbitrage.py already surfaces, see
    fantasy-football-db/scripts/build_arbitrage_signals.py for how it's
    computed. Used both for the player picker and for auto_fill()."""
    query = """
        SELECT p.player_id, p.name, p.position, p.team, asig.redraft_percentile
        FROM players p
        JOIN (
            SELECT player_id, redraft_percentile,
                   ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY as_of_date DESC) rn
            FROM arbitrage_signals WHERE format = ?
        ) asig ON asig.player_id = p.player_id AND asig.rn = 1
    """
    params = [arb_format]
    if exclude_player_ids:
        placeholders = ",".join("?" * len(exclude_player_ids))
        query += f" WHERE p.player_id NOT IN ({placeholders})"
        params += list(exclude_player_ids)
    query += " ORDER BY asig.redraft_percentile DESC"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    return conn.execute(query, params).fetchall()


def find_available_player(conn, league_id, arb_format, exclude_player_ids, name_guess):
    """Best name match among still-available players (see best_available()
    for what "available" excludes), or None. Same typed-name matching as
    app/fantasy_draft.py's find_player()."""
    target = normalize_name(name_guess)
    for row in best_available(conn, league_id, arb_format, exclude_player_ids):
        if normalize_name(row["name"]) == target:
            return row
    return None


def player_suggestions(conn, league_id, arb_format, exclude_player_ids, name_guess, limit=5):
    pool = best_available(conn, league_id, arb_format, exclude_player_ids)
    normalized_to_row = {normalize_name(row["name"]): row for row in pool}
    close = difflib.get_close_matches(
        normalize_name(name_guess), normalized_to_row.keys(), n=limit, cutoff=0.6
    )
    return [normalized_to_row[n]["name"] for n in close]


def record_pick_by_name(conn, user_id, league_id, keeper_season, round_num, roster_id,
                         arb_format, name_guess, board, existing_picks):
    """Resolves a typed player name against who's still available and, on
    a match, writes it via set_mock_draft_pick() as a manual pick.
    Returns an error message, or None on success -- same shape as
    app/five_oh_one.py's make_pick()."""
    if not name_guess or not name_guess.strip():
        return "Enter a player name."

    occupied = {k["player_id"] for keepers in board.values() for k in keepers}
    occupied |= {pick["player_id"] for pick in existing_picks.values()}

    match = find_available_player(conn, league_id, arb_format, occupied, name_guess)
    if match is None:
        hint = player_suggestions(conn, league_id, arb_format, occupied, name_guess)
        return (
            f"No available player named '{name_guess}' found."
            + (f" Did you mean: {', '.join(hint)}?" if hint else "")
        )

    return set_mock_draft_pick(
        conn, user_id, league_id, keeper_season, round_num, roster_id,
        match["player_id"], "manual", board, existing_picks,
    )


def auto_fill(conn, user_id, league_id, keeper_season, rounds, roster_ids, arb_format,
               board, existing_picks):
    """Fills every still-open (non-keeper, not-already-picked) cell with
    the next best-available player by redraft rank, round by round, in
    `roster_ids`' order within each round. Deliberately simple -- no
    positional-need logic, no real snake-order simulation -- since the
    point is a fast starting board to then hand-edit (every auto cell can
    still be overwritten via set_mock_draft_pick), not a realistic draft
    simulator. Returns how many cells were filled."""
    occupied = {k["player_id"] for keepers in board.values() for k in keepers}
    occupied |= {pick["player_id"] for pick in existing_picks.values()}
    pool = iter(best_available(conn, league_id, arb_format, occupied))

    filled = 0
    for round_num in range(1, rounds + 1):
        for roster_id in roster_ids:
            if (round_num, roster_id) in existing_picks:
                continue
            if any(k["keeper_round"] == round_num for k in board.get(roster_id, [])):
                continue
            player = next(pool, None)
            if player is None:
                continue
            conn.execute(
                """INSERT INTO mock_draft_picks
                       (user_id, league_id, season, round, roster_id, player_id, source, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'auto', datetime('now'))
                   ON CONFLICT(user_id, league_id, season, round, roster_id) DO UPDATE SET
                       player_id=excluded.player_id, source='auto', updated_at=datetime('now')""",
                (user_id, league_id, keeper_season, round_num, roster_id, player["player_id"]),
            )
            filled += 1
    conn.commit()
    return filled
