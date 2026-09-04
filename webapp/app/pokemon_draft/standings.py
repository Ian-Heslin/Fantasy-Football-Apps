"""Live standings and the league-wide Pokemon leaderboard -- computed
fresh from confirmed matches every time, never stored (matches
app/pickem.py's compute-don't-cache philosophy).

Tiebreaker order is FIXED, not configurable (confirmed requirement):
Series Wins > Game Wins > Differential > Head-to-Head > Strength of
Schedule. The first three are a plain multi-key sort; head-to-head and
strength-of-schedule only apply *within* a group of coaches still tied
after those three, which needs a second pass -- see standings() below.
Head-to-head is computed only from series results among the tied group
itself (not the whole season), and can't perfectly resolve every possible
3+-way non-transitive cycle (e.g. A beat B, B beat C, C beat A) -- falls
through to strength of schedule for whatever a group's internal record
alone can't separate, which is the same limitation most real fantasy
platforms accept rather than trying to solve exactly.
"""
from collections import defaultdict

from app.pokemon_draft import seasons


def _confirmed_matches(conn, season_id):
    return conn.execute(
        """SELECT m.match_id, m.winner_coach_id, s.coach_id_home, s.coach_id_away
           FROM pokemon_matches m
           JOIN pokemon_schedule s ON s.schedule_id = m.schedule_id
           WHERE s.season_id = ? AND m.status = 'confirmed' AND s.coach_id_away IS NOT NULL""",
        (season_id,),
    ).fetchall()


def standings(conn, season_id):
    coaches = seasons.list_coaches(conn, season_id)
    if not coaches:
        return []
    stats = {
        c["coach_id"]: {"coach": c, "series_w": 0, "series_l": 0, "game_w": 0, "game_l": 0}
        for c in coaches
    }
    matches_ = _confirmed_matches(conn, season_id)

    h2h_wins = defaultdict(lambda: defaultdict(int))  # h2h_wins[winner][loser] += 1
    opponents = defaultdict(list)  # coach_id -> [opponent_coach_id, ...] played this season

    for m in matches_:
        home, away, winner = m["coach_id_home"], m["coach_id_away"], m["winner_coach_id"]
        if winner is None:
            continue
        loser = away if winner == home else home
        if winner in stats:
            stats[winner]["series_w"] += 1
        if loser in stats:
            stats[loser]["series_l"] += 1
        h2h_wins[winner][loser] += 1
        opponents[home].append(away)
        opponents[away].append(home)

        games = conn.execute(
            "SELECT winner_coach_id FROM pokemon_match_games WHERE match_id = ?", (m["match_id"],)
        ).fetchall()
        for g in games:
            gwinner = g["winner_coach_id"]
            if gwinner is None:
                continue
            gloser = away if gwinner == home else home
            if gwinner in stats:
                stats[gwinner]["game_w"] += 1
            if gloser in stats:
                stats[gloser]["game_l"] += 1

    def win_pct(coach_id):
        s = stats.get(coach_id)
        if not s:
            return 0.0
        total = s["series_w"] + s["series_l"]
        return s["series_w"] / total if total else 0.0

    rows = list(stats.values())
    for r in rows:
        r["differential"] = r["game_w"] - r["game_l"]
        opp = opponents.get(r["coach"]["coach_id"], [])
        r["sos"] = (sum(win_pct(o) for o in opp) / len(opp)) if opp else 0.0

    def primary_key(r):
        return (r["series_w"], r["game_w"], r["differential"])

    rows.sort(key=primary_key, reverse=True)

    result = []
    i = 0
    while i < len(rows):
        j = i
        while j < len(rows) and primary_key(rows[j]) == primary_key(rows[i]):
            j += 1
        group = rows[i:j]
        if len(group) > 1:
            group_ids = {r["coach"]["coach_id"] for r in group}

            def h2h_record(cid):
                w = sum(h2h_wins[cid][o] for o in group_ids if o != cid)
                loss = sum(h2h_wins[o][cid] for o in group_ids if o != cid)
                return w - loss

            group.sort(key=lambda r: (h2h_record(r["coach"]["coach_id"]), r["sos"]), reverse=True)
        result.extend(group)
        i = j

    for idx, r in enumerate(result, start=1):
        r["rank"] = idx
    return result


def pokemon_leaderboard(conn, season_id):
    """League-wide per-Pokemon K/D across confirmed games, ranked by
    differential (kills minus deaths)."""
    return conn.execute(
        """SELECT ms.pokemon_id, p.display_name, p.sprite_url, c.team_name,
                  SUM(ms.kills) AS kills, SUM(ms.deaths) AS deaths,
                  SUM(ms.kills) - SUM(ms.deaths) AS differential,
                  COUNT(*) AS games_played
           FROM pokemon_match_stats ms
           JOIN pokemon_match_games g ON g.game_id = ms.game_id
           JOIN pokemon_matches m ON m.match_id = g.match_id
           JOIN pokemon_schedule s ON s.schedule_id = m.schedule_id
           JOIN pokemon p ON p.pokemon_id = ms.pokemon_id
           JOIN pokemon_season_coaches c ON c.coach_id = ms.coach_id
           WHERE s.season_id = ? AND m.status = 'confirmed'
           GROUP BY ms.pokemon_id, ms.coach_id
           ORDER BY differential DESC, kills DESC""",
        (season_id,),
    ).fetchall()
