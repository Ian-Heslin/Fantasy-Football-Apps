#!/usr/bin/env python3
"""
load_yahoo.py -- pulls Ian's Yahoo league, rosters, and roster/player
membership into app.db, the same way load_sleeper.py/load_espn.py do for
their platforms.

Yahoo's OFFICIAL Fantasy Sports API needs an approved OAuth app (see
docs/sleeper-and-trade-value-pipeline.md's Yahoo section -- Ian applied,
still pending, no published turnaround time). This script uses a
DIFFERENT, unofficial route found by capturing the actual requests Yahoo's
own web frontend makes: `pub-api-rw.fantasysports.yahoo.com` mirrors the
same `/fantasy/v2/...` JSON shape as the real documented API, but accepts
plain browser LOGIN COOKIES instead of an OAuth bearer token -- confirmed
2026-09 pulling real league/team/roster data this way. This is reverse
engineered, not documented by Yahoo, and could break if Yahoo changes how
their frontend authenticates -- if this script starts failing across the
board, that's the first thing to suspect (re-capture a fresh request from
the browser Network tab the same way, per this project's chat history).

Auth: set YAHOO_COOKIE to the value of the browser's `Cookie` request
header for a request to pub-api-rw.fantasysports.yahoo.com (DevTools ->
Network -> Fetch/XHR -> click a request to that host -> Headers -> copy
the whole `cookie` line's value verbatim). This is Ian's live Yahoo login
session -- never hardcode it here, never commit it, treat it like a
password (same guidance as SWID/ESPN_S2 and the FantasyPros API key).
Unlike ESPN's public leagues, Ian's Yahoo league is PRIVATE, so there's no
no-auth fallback here at all -- YAHOO_COOKIE is required, not optional.

Yahoo mints a new numeric league_id AND a new numeric "game_key" (its
per-season/per-sport id, e.g. 470 = 2026 NFL) every season, then chains
them via a `renew`/`renewed` pair on the league object -- `renew` on the
CURRENT season points backward to last season as "{game_key}_{league_id}"
(confirmed live comparing Ian's 2026 and 2025 league objects: 2026's
renew was "461_121909", exactly 2025's game_key/league_id). This is the
same shape of problem as Sleeper's previous_league_id chain, just spelled
differently -- see load_season_history() below.

YAHOO_LEAGUE_ID/YAHOO_GAME_KEY below need a manual bump once a year, same
as ESPN's SEASON constant -- there's no reliable no-lookup way to avoid
this without risking an unverified "nfl" game-code alias. To find next
year's values: open the league in a browser, DevTools -> Network ->
Fetch/XHR, load any league page, and look at a pub-api-rw request's URL --
it starts with `/fantasy/v2/league/{game_key}.l.{league_id}/...`.

NOTE: like load_sleeper.py/load_espn.py, this can't reach Yahoo's API from
this sandbox (egress to fantasysports.yahoo.com domains is blocked here).
Run this on your own machine, or from wherever the web app actually runs.

Usage:
    python3 scripts/load_yahoo.py            # current season only
    python3 scripts/load_yahoo.py --history  # also walk the renew chain
                                              # back through every past
                                              # season's final standings
"""
import argparse
import os
import sqlite3
import sys
from datetime import date

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQLITE_PATH = os.path.join(ROOT, "data", "app.db")
TODAY = date.today().isoformat()
BASE = "https://pub-api-rw.fantasysports.yahoo.com/fantasy/v2"

YAHOO_COOKIE = os.environ.get("YAHOO_COOKIE")

# Ian's Yahoo league ("WHMFFL") -- current season's game_key/league_id, and
# his manager guid (STABLE across seasons even though team_id and league_id
# both change every year -- confirmed 2026 vs 2025, same guid both times).
YAHOO_GAME_KEY = "470"
YAHOO_LEAGUE_ID = "3157"
MY_MANAGER_GUID = "YEHVGA7JAHA4MKR52LSDYS2SEM"
# WHMFFL is superflex, confirmed by Ian (not yet derived from real Yahoo
# league settings data -- no captured example of that resource). Update
# this if that ever changes, or replace with a real settings lookup if a
# usable resource capture turns up.
YAHOO_FORMAT = "SF"


def yahoo_get(resource_path, extra_params=None):
    """resource_path already contains any Yahoo `;modifier=value` segments
    (Yahoo's API puts resource modifiers like `;out=standings` in the PATH,
    not the query string) -- this just adds format=json and auth."""
    if not YAHOO_COOKIE:
        raise RuntimeError("YAHOO_COOKIE not set")
    params = {"format": "json"}
    if extra_params:
        params.update(extra_params)
    resp = requests.get(
        f"{BASE}{resource_path}",
        params=params,
        headers={"Cookie": YAHOO_COOKIE, "Accept": "*/*"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _merge_fields(items):
    """Yahoo represents most 'team' and 'player' fields as a list of
    single-key dicts -- with bare [] entries as fillers for whichever
    optional fields are absent on a given player/team -- instead of one
    flat dict. Merges them into one flat dict."""
    merged = {}
    for item in items:
        if isinstance(item, dict):
            merged.update(item)
    return merged


def _collection_items(node):
    """Yahoo's list-like collections (teams, players) often arrive as
    {'0': {...}, '1': {...}, 'count': N} instead of a real JSON array.
    Normalizes either shape to a plain list of the value dicts."""
    if isinstance(node, list):
        return node
    if isinstance(node, dict):
        return [v for k, v in node.items() if k != "count"]
    return []


def parse_team(team_node):
    """team_node is the value of a 'team' key: [list_of_field_dicts,
    {sub_resource_key: ...}, ...] -- e.g. the second element is
    team_standings for a `teams;out=standings` call, or roster for a
    `team/.../roster` call. Returns (flat_fields, flat_sub_resources)."""
    field_list, *rest = team_node
    return _merge_fields(field_list), _merge_fields(rest)


def parse_player(player_node):
    """Same shape as parse_team, for player_node = the value of a
    'player' key: [list_of_field_dicts, {selected_position...}, ...]."""
    field_list, *rest = player_node
    return _merge_fields(field_list), _merge_fields(rest)


def get_league_teams(game_key, league_id):
    """Returns (flat_league_fields, [flat_team_fields, ...]) for one
    league-season, teams merged with their team_standings."""
    data = yahoo_get(f"/league/{game_key}.l.{league_id}/teams;out=standings")
    league_node = (data.get("fantasy_content") or {}).get("league")
    # 'league' turns out to use the same list-of-single-key-dicts shape as
    # 'team'/'player' (confirmed live 2026-09 -- a plain .get("teams") on it
    # raised AttributeError: 'list' object has no attribute 'get'), just
    # without team/player's extra wrapping level, since 'teams' is simply
    # one more field in that same list rather than a separate sub-resource.
    league = _merge_fields(league_node) if isinstance(league_node, list) else (league_node or {})
    teams = []
    for team_wrapper in _collection_items(league.get("teams") or {}):
        fields, extra = parse_team(team_wrapper["team"])
        fields.update(extra)
        teams.append(fields)
    return league, teams


def get_draft_results(game_key, league_id):
    """Returns a list of {'pick', 'round', 'team_key', 'player_key'} dicts,
    one per pick, for one league-season's actual draft -- empty before the
    draft has happened (see load_league()'s draft_status check) or if
    Yahoo has no history for that season. Same 'draft_results' field
    directly on the merged league dict as 'teams' in get_league_teams()
    (see that function's comment on the shape)."""
    data = yahoo_get(f"/league/{game_key}.l.{league_id}/draftresults")
    league_node = (data.get("fantasy_content") or {}).get("league")
    league = _merge_fields(league_node) if isinstance(league_node, list) else (league_node or {})
    picks = []
    for wrapper in _collection_items(league.get("draft_results") or {}):
        result = wrapper.get("draft_result") if isinstance(wrapper, dict) else None
        if result is None:
            continue
        # draft_result is a flat dict in every capture seen so far;
        # _merge_fields is a no-op on one and normalizes it if Yahoo ever
        # sends it list-wrapped like team/player instead.
        fields = _merge_fields(result) if isinstance(result, list) else result
        if fields.get("pick") is not None:
            picks.append(fields)
    return picks


def load_draft_results(conn, anchor_league_id, season, teams, picks):
    """Inserts one season's real draft into league_draft_picks. `teams` is
    get_league_teams()'s team list (for team_key -> roster_id); `picks` is
    get_draft_results()'s return. No-op if the draft hasn't happened yet
    (picks is empty) -- callers don't need to check draft_status
    themselves. Returns how many picks were written."""
    if not picks:
        return 0
    team_key_to_roster_id = {t.get("team_key"): str(t.get("team_id")) for t in teams}
    n = 0
    for p in picks:
        roster_id = team_key_to_roster_id.get(p.get("team_key"))
        player_key = p.get("player_key")
        round_num, overall_pick = p.get("round"), p.get("pick")
        if roster_id is None or player_key is None or round_num is None or overall_pick is None:
            continue
        # player_key is '{game_key}.p.{player_id}' -- the same id space as
        # get_team_roster_player_ids()'s 'player_id' field, just composite
        # here since draft_result doesn't also give the bare id.
        yahoo_player_id = player_key.rsplit(".p.", 1)[-1]
        conn.execute(
            """INSERT INTO league_draft_picks
                   (league_id, season, round, overall_pick, roster_id, player_id)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(league_id, season, overall_pick) DO UPDATE SET
                   round=excluded.round, roster_id=excluded.roster_id,
                   player_id=excluded.player_id""",
            (anchor_league_id, season, int(round_num), int(overall_pick),
             roster_id, f"yahoo:{yahoo_player_id}"),
        )
        n += 1
    conn.commit()
    return n


def get_team_roster_player_ids(team_key):
    """Returns the list of yahoo player_ids on one team's current roster
    (whatever week Yahoo defaults to -- observed as the current week for
    an in-progress season, or the final week for a completed one)."""
    data = yahoo_get(f"/team/{team_key}/roster")
    team_node = (data.get("fantasy_content") or {}).get("team")
    if not team_node:
        return []
    _, extra = parse_team(team_node)
    roster = extra.get("roster") or {}

    players_node = None
    for value in roster.values():
        if isinstance(value, dict) and "players" in value:
            players_node = value["players"]
            break

    ids = []
    for player_wrapper in _collection_items(players_node or {}):
        fields, _ = parse_player(player_wrapper["player"])
        player_id = fields.get("player_id")
        if player_id is not None:
            ids.append(player_id)
    return ids


def _team_manager(team):
    managers = team.get("managers") or []
    if not managers:
        return {}
    return managers[0].get("manager") or {}


def load_league(conn, game_key, league_id):
    league, teams = get_league_teams(game_key, league_id)
    if not league:
        print(f"[load_yahoo] WARNING: no data for league {game_key}.{league_id}, skipping")
        return None

    anchor_league_id = league.get("league_id")
    name = league.get("name")
    season = int(league["season"]) if league.get("season") else None
    is_finished = str(league.get("is_finished")) == "1"
    status = (
        "complete" if is_finished
        else "pre_draft" if league.get("draft_status") == "predraft"
        else "in_season"
    )

    conn.execute(
        """INSERT INTO leagues (league_id, platform, name, season, format, status, updated_at)
           VALUES (?, 'yahoo', ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(league_id) DO UPDATE SET
               name=excluded.name, season=excluded.season, format=excluded.format,
               status=excluded.status, updated_at=datetime('now')""",
        (anchor_league_id, name, season, YAHOO_FORMAT, status),
    )

    my_roster_id = None
    for team in teams:
        roster_id = str(team.get("team_id"))
        manager = _team_manager(team)
        owner_id = manager.get("guid")
        owner_name = manager.get("nickname") or team.get("name")
        is_mine = 1 if owner_id == MY_MANAGER_GUID else 0
        if is_mine:
            my_roster_id = roster_id

        conn.execute(
            """INSERT INTO rosters (league_id, roster_id, owner_id, owner_name, is_mine, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(league_id, roster_id) DO UPDATE SET
                   owner_id=excluded.owner_id, owner_name=excluded.owner_name,
                   is_mine=excluded.is_mine, updated_at=datetime('now')""",
            (anchor_league_id, roster_id, owner_id, owner_name, is_mine),
        )

        team_key = team.get("team_key")
        for yahoo_player_id in get_team_roster_player_ids(team_key):
            conn.execute(
                """INSERT INTO roster_players (league_id, roster_id, player_id, as_of_date)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT DO NOTHING""",
                (anchor_league_id, roster_id, f"yahoo:{yahoo_player_id}", TODAY),
            )

    if my_roster_id:
        conn.execute(
            "UPDATE leagues SET my_roster_id = ? WHERE league_id = ?",
            (my_roster_id, anchor_league_id),
        )

    conn.commit()
    print(f"[load_yahoo] loaded league '{name}' ({anchor_league_id}): {len(teams)} teams")

    try:
        picks = get_draft_results(game_key, league_id)
    except requests.RequestException as e:
        print(f"[load_yahoo] WARNING: failed to load draft results for {game_key}.{league_id}: {e}")
        picks = []
    n_picks = load_draft_results(conn, anchor_league_id, season, teams, picks)
    if n_picks:
        print(f"[load_yahoo] loaded {n_picks} draft picks for league '{name}' season {season}")

    return league


def resolve_yahoo_player_ids(conn):
    """roster_players and league_draft_picks store raw yahoo ids as
    'yahoo:<id>' -- if a player also has a fantasypros_id in the players
    table (loaded by build_db.py), repoint both at that canonical id so
    they join cleanly against trade_values/arbitrage_signals/
    model_predictions. Players with no fantasypros match keep the
    yahoo: id."""
    rows = conn.execute(
        "SELECT player_id, yahoo_id FROM players WHERE yahoo_id IS NOT NULL"
    ).fetchall()
    remap = {f"yahoo:{yahoo_id}": canonical_id for canonical_id, yahoo_id in rows}

    updated = 0
    draft_updated = 0
    for raw_id, canonical_id in remap.items():
        if raw_id == canonical_id:
            continue
        cur = conn.execute(
            "UPDATE OR IGNORE roster_players SET player_id = ? WHERE player_id = ?",
            (canonical_id, raw_id),
        )
        updated += cur.rowcount
        cur = conn.execute(
            "UPDATE OR IGNORE league_draft_picks SET player_id = ? WHERE player_id = ?",
            (canonical_id, raw_id),
        )
        draft_updated += cur.rowcount
    conn.commit()
    print(f"[load_yahoo] remapped {updated} roster_players rows and {draft_updated} "
          f"league_draft_picks rows to canonical player_id")


def load_season_history(conn, anchor_league_id, current_league):
    """Walks backward through Yahoo's renew chain (see module docstring).
    Stops as soon as a league object has no 'renew' field -- unlike
    ESPN's ambiguous silent failures, this is Yahoo's own explicit
    end-of-chain signal, no failure-counting heuristic needed. Returns how
    many past seasons were found."""
    seasons_loaded = 0
    renew = current_league.get("renew")

    while renew and "_" in renew:
        game_key, league_id = renew.split("_", 1)
        try:
            league, teams = get_league_teams(game_key, league_id)
        except requests.RequestException as e:
            print(f"[load_yahoo] history: request failed for {game_key}.{league_id}: {e}")
            break
        if not teams:
            print(f"[load_yahoo] history: no teams for {game_key}.{league_id} -- "
                  f"treating as end of history")
            break

        season = int(league["season"]) if league.get("season") else None

        def _sort_key(t):
            standings = t.get("team_standings") or {}
            outcome = standings.get("outcome_totals") or {}
            return (-int(outcome.get("wins") or 0), -float(standings.get("points_for") or 0))

        for rank, team in enumerate(sorted(teams, key=_sort_key), start=1):
            standings = team.get("team_standings") or {}
            outcome = standings.get("outcome_totals") or {}
            roster_id = str(team.get("team_id"))
            manager = _team_manager(team)
            owner_name = manager.get("nickname") or team.get("name")

            conn.execute(
                """INSERT INTO league_season_standings
                       (league_id, season, roster_id, owner_name, wins, losses, ties,
                        points_for, points_against, final_rank)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(league_id, season, roster_id) DO UPDATE SET
                       owner_name=excluded.owner_name, wins=excluded.wins, losses=excluded.losses,
                       ties=excluded.ties, points_for=excluded.points_for,
                       points_against=excluded.points_against, final_rank=excluded.final_rank""",
                (
                    anchor_league_id, season, roster_id, owner_name,
                    outcome.get("wins"), outcome.get("losses"), outcome.get("ties"),
                    standings.get("points_for"), standings.get("points_against"), rank,
                ),
            )
        conn.commit()
        print(f"[load_yahoo] history: loaded {season} standings for league {anchor_league_id} "
              f"(Yahoo league {game_key}.{league_id}, {len(teams)} teams)")

        try:
            picks = get_draft_results(game_key, league_id)
        except requests.RequestException as e:
            print(f"[load_yahoo] history: draft results request failed for "
                  f"{game_key}.{league_id}: {e}")
            picks = []
        n_picks = load_draft_results(conn, anchor_league_id, season, teams, picks)
        if n_picks:
            print(f"[load_yahoo] history: loaded {n_picks} draft picks for {season}")

        seasons_loaded += 1
        renew = league.get("renew")

    return seasons_loaded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--history", action="store_true",
        help="also walk the renew chain back through every past season's final standings",
    )
    args = parser.parse_args()

    if not YAHOO_COOKIE:
        print("YAHOO_COOKIE not set -- see this script's module docstring for how to get it "
              "from a logged-in browser. Nothing to do.")
        sys.exit(1)

    if not os.path.exists(SQLITE_PATH):
        print("app.db not found -- run scripts/build_db.py first.")
        sys.exit(1)

    conn = sqlite3.connect(SQLITE_PATH)

    league = None
    try:
        league = load_league(conn, YAHOO_GAME_KEY, YAHOO_LEAGUE_ID)
    except requests.RequestException as e:
        print(f"[load_yahoo] WARNING: failed to load league {YAHOO_GAME_KEY}.{YAHOO_LEAGUE_ID}: {e}")

    if league and args.history:
        n = load_season_history(conn, league["league_id"], league)
        print(f"[load_yahoo] history: {n} past season(s) found")

    resolve_yahoo_player_ids(conn)

    # Separate sync_log row per platform, same reasoning as load_espn.py/
    # load_sleeper.py -- sync_log's PRIMARY KEY is just table_name.
    conn.execute(
        """INSERT INTO sync_log (table_name, source, last_synced_at, row_count, notes)
           VALUES ('rosters:yahoo', 'yahoo', datetime('now'),
                   (SELECT count(*) FROM rosters r JOIN leagues l ON l.league_id = r.league_id
                    WHERE l.platform = 'yahoo'), '1 league configured')
           ON CONFLICT(table_name) DO UPDATE SET
               last_synced_at=datetime('now'),
               row_count=(SELECT count(*) FROM rosters r JOIN leagues l ON l.league_id = r.league_id
                          WHERE l.platform = 'yahoo'),
               notes=excluded.notes""",
    )
    conn.commit()
    conn.close()
    print("[load_yahoo] done.")


if __name__ == "__main__":
    main()
