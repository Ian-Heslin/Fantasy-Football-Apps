"""Current-roster computation, free-agent add/drop, and coach-to-coach
trades. Reads the append-only pokemon_roster_moves ledger via a window
function rather than a stored "current roster" table, matching
app/pickem.py's compute-don't-cache philosophy -- see
schema/sqlite_schema.sql's pokemon_roster_moves comment for why.

The window function partitions by pokemon_id ONLY (not also coach_id) --
a pokemon's most recent move might be a 'trade_out' recorded under its
OLD coach, so filtering to one coach's own rows before ranking would miss
that it already left them. coach_id is filtered in the outer query
instead, once ownership is correctly resolved.

FA transactions: only 'fa_add' rows count toward a season's
fa_transactions_allowed cap -- drops (including ones bundled into a
trade) are free, per the confirmed requirement. roster_freeze_week blocks
every roster-changing action (FA add/drop and trade accept alike) once
the season reaches that week -- inferred from match-confirmation progress
via current_week(), since this app has no explicit calendar/date concept
for "weeks."

Trades (see schema/sqlite_schema.sql's pokemon_trade_offers/
pokemon_trade_offer_items comments): a trade offer bundles both the
Pokemon changing hands AND any drops needed to stay under budget/roster
cap into ONE atomic accept -- accept_trade() re-prices every incoming
Pokemon at its CURRENT effective_cost (not what the previous owner paid)
and rejects the whole offer, writing nothing, if either side's resulting
roster would exceed the season's point budget or roster cap.
"""
from app.pokemon_draft import draft_pool, seasons


def current_roster(conn, season_id, coach_id=None):
    """Every currently-held (coach_id, pokemon_id, cost) row this season,
    or just one coach's if coach_id is given."""
    sql = """
        WITH latest AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY pokemon_id ORDER BY move_id DESC
            ) AS rn
            FROM pokemon_roster_moves WHERE season_id = ?
        )
        SELECT coach_id, pokemon_id, cost FROM latest
        WHERE rn = 1 AND move_type IN ('draft', 'fa_add', 'trade_in')
    """
    params = [season_id]
    if coach_id is not None:
        sql += " AND coach_id = ?"
        params.append(coach_id)
    return conn.execute(sql, params).fetchall()


def roster_summary(conn, season_id, coach_id):
    """(pokemon_count, points_spent) for one coach's current roster."""
    rows = current_roster(conn, season_id, coach_id)
    return len(rows), sum(r["cost"] or 0 for r in rows)


def current_roster_with_pokemon(conn, season_id, coach_id):
    """Like current_roster(), but joined with the pokemon table for
    display purposes (name, sprite, types) -- kept separate from
    current_roster() so the hot paths that only need pokemon_id/cost
    (make_pick's budget check, match reporting's roster validation) don't
    pay for a join they don't use."""
    ids = {r["pokemon_id"] for r in current_roster(conn, season_id, coach_id)}
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return conn.execute(
        f"""SELECT pokemon_id, display_name, sprite_url, type1, type2
            FROM pokemon WHERE pokemon_id IN ({placeholders})
            ORDER BY display_name""",
        list(ids),
    ).fetchall()


def available_for_fa(conn, season_id, query=None):
    """Pool entries not banned and not currently on ANY roster -- unlike
    app/pokemon_draft/draft_pool.py's undrafted() (which checks the
    permanent draft-pick history table), this checks the live roster
    ledger, so a Pokemon someone drops becomes available again for
    another coach to pick up via free agency."""
    held_ids = {r["pokemon_id"] for r in current_roster(conn, season_id)}
    sql, params = draft_pool.pool_base_query(season_id, query)
    sql += " ORDER BY effective_cost DESC, p.national_dex_number"
    return [r for r in conn.execute(sql, params).fetchall() if r["pokemon_id"] not in held_ids]


def _rostered_species_ids(conn, season_id):
    """species_id set for every Pokemon currently on ANY roster this
    season -- used for the league-wide species clause check on FA adds
    (a coach can't pick up via free agency what the clause already
    blocked at the draft)."""
    held = current_roster(conn, season_id)
    if not held:
        return set()
    placeholders = ",".join("?" for _ in held)
    rows = conn.execute(
        f"SELECT DISTINCT species_id FROM pokemon WHERE pokemon_id IN ({placeholders})",
        [r["pokemon_id"] for r in held],
    ).fetchall()
    return {r["species_id"] for r in rows}


def current_week(conn, season_id):
    """The season's current week for roster-freeze purposes: the
    earliest scheduled week that isn't fully confirmed yet, or the last
    scheduled week if the season's wrapped, or None if no schedule
    exists yet.

    INNER JOINs to pokemon_matches -- not LEFT JOINs -- so a bye row
    (coach_id_away IS NULL, and per schedule.generate_schedule() no
    pokemon_matches row is ever created for one) is excluded entirely
    rather than counting as perpetually "unconfirmed". A LEFT JOIN here
    previously left every bye week's m.status NULL forever, which pinned
    MIN(week) on the season's very first bye week even after every real
    match in every later week was confirmed -- silently disabling
    roster_freeze_week for any season with an odd number of coaches."""
    row = conn.execute(
        """SELECT MIN(s.week) AS w FROM pokemon_schedule s
           JOIN pokemon_matches m ON m.schedule_id = s.schedule_id
           WHERE s.season_id = ? AND s.week IS NOT NULL AND m.status != 'confirmed'""",
        (season_id,),
    ).fetchone()
    if row["w"] is not None:
        return row["w"]
    row2 = conn.execute(
        "SELECT MAX(week) AS w FROM pokemon_schedule WHERE season_id = ? AND week IS NOT NULL",
        (season_id,),
    ).fetchone()
    return row2["w"]


def fa_transactions_used(conn, season_id, coach_id):
    return conn.execute(
        """SELECT count(*) c FROM pokemon_roster_moves
           WHERE season_id = ? AND coach_id = ? AND counts_toward_fa_cap = 1""",
        (season_id, coach_id),
    ).fetchone()["c"]


def _roster_freeze_error(conn, season_id, season):
    if season["roster_freeze_week"] is None:
        return None
    week = current_week(conn, season_id)
    if week is not None and week >= season["roster_freeze_week"]:
        return f"Rosters are frozen starting week {season['roster_freeze_week']}."
    return None


def fa_add(conn, season_id, coach_id, pokemon_id):
    """None on success, or an error string."""
    season = seasons.get_season(conn, season_id)
    if season is None:
        return "No such season."
    error = _roster_freeze_error(conn, season_id, season)
    if error:
        return error

    pool_entry = draft_pool.get_pool_entry(conn, season_id, pokemon_id)
    if pool_entry is None or pool_entry["is_banned"]:
        return "That Pokemon isn't available in this season's pool."
    cost = draft_pool.effective_cost(pool_entry)
    if cost is None:
        return "That Pokemon doesn't have a point cost set yet."

    if pokemon_id in {r["pokemon_id"] for r in current_roster(conn, season_id)}:
        return "That Pokemon is already on a roster."

    if season["species_clause_enabled"]:
        species = conn.execute(
            "SELECT species_id FROM pokemon WHERE pokemon_id = ?", (pokemon_id,)
        ).fetchone()["species_id"]
        if species in _rostered_species_ids(conn, season_id):
            return "Species clause: a different form of that Pokemon is already on a roster."

    count, spent = roster_summary(conn, season_id, coach_id)
    if count >= season["roster_size_cap"]:
        return "Your roster is already full."
    if spent + cost > season["point_budget"]:
        return f"Not enough budget: {cost} points would put you over the {season['point_budget']}-point cap."

    used = fa_transactions_used(conn, season_id, coach_id)
    if used >= season["fa_transactions_allowed"]:
        return f"You've already used all {season['fa_transactions_allowed']} free agent transactions this season."

    conn.execute(
        """INSERT INTO pokemon_roster_moves
               (season_id, coach_id, pokemon_id, move_type, cost, counts_toward_fa_cap, week)
           VALUES (?, ?, ?, 'fa_add', ?, 1, ?)""",
        (season_id, coach_id, pokemon_id, cost, current_week(conn, season_id)),
    )
    conn.commit()
    return None


def fa_drop(conn, season_id, coach_id, pokemon_id):
    """None on success, or an error string. Drops are free -- they never
    count toward the FA cap (confirmed requirement)."""
    season = seasons.get_season(conn, season_id)
    if season is None:
        return "No such season."
    error = _roster_freeze_error(conn, season_id, season)
    if error:
        return error
    held = {r["pokemon_id"] for r in current_roster(conn, season_id, coach_id)}
    if pokemon_id not in held:
        return "That Pokemon isn't on your roster."
    conn.execute(
        """INSERT INTO pokemon_roster_moves
               (season_id, coach_id, pokemon_id, move_type, cost, counts_toward_fa_cap, week)
           VALUES (?, ?, ?, 'drop', NULL, 0, ?)""",
        (season_id, coach_id, pokemon_id, current_week(conn, season_id)),
    )
    conn.commit()
    return None


# ---------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------

def propose_trade(conn, season_id, proposing_coach_id, receiving_coach_id, items):
    """items: [{"pokemon_id", "from_coach_id", "action"}, ...] -- action
    is 'trade' (moves to the other coach) or 'drop' (leaves from_coach_id's
    roster entirely, bundled in specifically to keep the trade legal under
    budget/roster-cap). Returns (trade_id, None) on success or
    (None, error string)."""
    season = seasons.get_season(conn, season_id)
    if season is None:
        return None, "No such season."
    error = _roster_freeze_error(conn, season_id, season)
    if error:
        return None, error
    if proposing_coach_id == receiving_coach_id:
        return None, "Can't trade with yourself."
    if not items:
        return None, "A trade needs at least one Pokemon."

    valid_coaches = {proposing_coach_id, receiving_coach_id}
    has_trade_item = False
    for item in items:
        if item["from_coach_id"] not in valid_coaches:
            return None, "A trade item must belong to one of the two coaches in the offer."
        if item["action"] not in ("trade", "drop"):
            return None, "Invalid trade item action."
        if item["action"] == "trade":
            has_trade_item = True
        held = {r["pokemon_id"] for r in current_roster(conn, season_id, item["from_coach_id"])}
        if item["pokemon_id"] not in held:
            return None, "A trade item isn't on that coach's current roster."
    if not has_trade_item:
        return None, "A trade needs at least one Pokemon actually changing hands."

    cur = conn.execute(
        "INSERT INTO pokemon_trade_offers (season_id, proposing_coach_id, receiving_coach_id) VALUES (?, ?, ?)",
        (season_id, proposing_coach_id, receiving_coach_id),
    )
    trade_id = cur.lastrowid
    for item in items:
        conn.execute(
            "INSERT INTO pokemon_trade_offer_items (trade_id, pokemon_id, from_coach_id, action) "
            "VALUES (?, ?, ?, ?)",
            (trade_id, item["pokemon_id"], item["from_coach_id"], item["action"]),
        )
    conn.commit()
    return trade_id, None


def get_trade_offer(conn, trade_id):
    """(offer_row, items) or None."""
    offer = conn.execute("SELECT * FROM pokemon_trade_offers WHERE trade_id = ?", (trade_id,)).fetchone()
    if offer is None:
        return None
    items = conn.execute(
        "SELECT * FROM pokemon_trade_offer_items WHERE trade_id = ?", (trade_id,)
    ).fetchall()
    return offer, items


def list_pending_trades(conn, season_id, coach_id):
    return conn.execute(
        """SELECT * FROM pokemon_trade_offers WHERE season_id = ? AND status = 'pending'
           AND (proposing_coach_id = ? OR receiving_coach_id = ?)
           ORDER BY created_at DESC""",
        (season_id, coach_id, coach_id),
    ).fetchall()


def accept_trade(conn, trade_id, accepting_user_id):
    """None on success, or an error string -- nothing is written on error.
    Only the RECEIVING coach can accept (the proposer already agreed to
    the offer by creating it)."""
    result = get_trade_offer(conn, trade_id)
    if result is None:
        return "No such trade offer."
    offer, items = result
    if offer["status"] != "pending":
        return "This trade is no longer pending."

    season = seasons.get_season(conn, offer["season_id"])
    error = _roster_freeze_error(conn, offer["season_id"], season)
    if error:
        return error

    receiving_coach = conn.execute(
        "SELECT user_id FROM pokemon_season_coaches WHERE coach_id = ?", (offer["receiving_coach_id"],)
    ).fetchone()
    if receiving_coach is None or receiving_coach["user_id"] != accepting_user_id:
        return "Only the receiving coach can accept this trade."

    # Rosters can drift between proposal and acceptance -- re-check every
    # item is still where the offer says it is.
    for item in items:
        held = {r["pokemon_id"] for r in current_roster(conn, offer["season_id"], item["from_coach_id"])}
        if item["pokemon_id"] not in held:
            return "This trade is no longer valid -- a Pokemon in it has already left that roster."

    proposing_id, receiving_id = offer["proposing_coach_id"], offer["receiving_coach_id"]
    giving_up = {proposing_id: set(), receiving_id: set()}
    incoming = {proposing_id: [], receiving_id: []}
    for item in items:
        giving_up[item["from_coach_id"]].add(item["pokemon_id"])
        if item["action"] == "trade":
            other = receiving_id if item["from_coach_id"] == proposing_id else proposing_id
            incoming[other].append(item["pokemon_id"])

    incoming_costs = {}
    for coach_id in (proposing_id, receiving_id):
        current = current_roster(conn, offer["season_id"], coach_id)
        kept = [r for r in current if r["pokemon_id"] not in giving_up[coach_id]]
        kept_cost = sum(r["cost"] or 0 for r in kept)

        total_incoming_cost = 0
        for pid in incoming[coach_id]:
            pool_entry = draft_pool.get_pool_entry(conn, offer["season_id"], pid)
            cost = draft_pool.effective_cost(pool_entry) if pool_entry else None
            if cost is None:
                return "A traded Pokemon no longer has a valid point cost."
            incoming_costs[pid] = cost
            total_incoming_cost += cost

        new_count = len(kept) + len(incoming[coach_id])
        new_spent = kept_cost + total_incoming_cost
        if new_count > season["roster_size_cap"]:
            return (f"This trade would leave a roster with {new_count} Pokemon, over the "
                    f"{season['roster_size_cap']}-Pokemon cap.")
        if new_spent > season["point_budget"]:
            return (f"This trade would leave a roster at {new_spent} points, over the "
                    f"{season['point_budget']}-point cap.")

        if season["species_clause_enabled"]:
            final_ids = [r["pokemon_id"] for r in kept] + incoming[coach_id]
            if final_ids:
                placeholders = ",".join("?" for _ in final_ids)
                species_ids = [r["species_id"] for r in conn.execute(
                    f"SELECT species_id FROM pokemon WHERE pokemon_id IN ({placeholders})",
                    final_ids,
                ).fetchall()]
                if len(species_ids) != len(set(species_ids)):
                    return ("Species clause: this trade would leave a roster with two forms of "
                            "the same species.")

    week = current_week(conn, offer["season_id"])
    for item in items:
        if item["action"] == "drop":
            conn.execute(
                """INSERT INTO pokemon_roster_moves
                       (season_id, coach_id, pokemon_id, move_type, cost, trade_group_id,
                        counts_toward_fa_cap, week)
                   VALUES (?, ?, ?, 'drop', NULL, ?, 0, ?)""",
                (offer["season_id"], item["from_coach_id"], item["pokemon_id"], str(trade_id), week),
            )
        else:
            other = receiving_id if item["from_coach_id"] == proposing_id else proposing_id
            conn.execute(
                """INSERT INTO pokemon_roster_moves
                       (season_id, coach_id, pokemon_id, move_type, cost, trade_group_id,
                        counts_toward_fa_cap, week)
                   VALUES (?, ?, ?, 'trade_out', NULL, ?, 0, ?)""",
                (offer["season_id"], item["from_coach_id"], item["pokemon_id"], str(trade_id), week),
            )
            conn.execute(
                """INSERT INTO pokemon_roster_moves
                       (season_id, coach_id, pokemon_id, move_type, cost, trade_group_id,
                        counts_toward_fa_cap, week)
                   VALUES (?, ?, ?, 'trade_in', ?, ?, 0, ?)""",
                (offer["season_id"], other, item["pokemon_id"], incoming_costs[item["pokemon_id"]],
                 str(trade_id), week),
            )
    conn.execute(
        "UPDATE pokemon_trade_offers SET status = 'accepted', resolved_at = datetime('now') WHERE trade_id = ?",
        (trade_id,),
    )
    conn.commit()
    return None


def respond_to_trade(conn, trade_id, responding_user_id):
    """Reject (receiving coach) or cancel (proposing coach) a pending
    offer. None on success, or an error string."""
    result = get_trade_offer(conn, trade_id)
    if result is None:
        return "No such trade offer."
    offer, _items = result
    if offer["status"] != "pending":
        return "This trade is no longer pending."

    proposing_user = conn.execute(
        "SELECT user_id FROM pokemon_season_coaches WHERE coach_id = ?", (offer["proposing_coach_id"],)
    ).fetchone()["user_id"]
    receiving_user = conn.execute(
        "SELECT user_id FROM pokemon_season_coaches WHERE coach_id = ?", (offer["receiving_coach_id"],)
    ).fetchone()["user_id"]
    if responding_user_id not in (proposing_user, receiving_user):
        return "You're not part of this trade."

    new_status = "cancelled" if responding_user_id == proposing_user else "rejected"
    conn.execute(
        "UPDATE pokemon_trade_offers SET status = ?, resolved_at = datetime('now') WHERE trade_id = ?",
        (new_status, trade_id),
    )
    conn.commit()
    return None
