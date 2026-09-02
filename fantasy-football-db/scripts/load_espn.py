#!/usr/bin/env python3
"""
load_espn.py -- pulls Ian's ESPN leagues, rosters, and roster/player
membership from ESPN's public (unofficial, no-auth) fantasy API and loads
them into app.db, the same way load_sleeper.py does for Sleeper.

Both of Ian's ESPN leagues are public, so no SWID/espn_s2 login cookies are
needed for the CURRENT season -- see docs/sleeper-and-trade-value-pipeline.md's
ESPN section. The working API host is `lm-api-reads.fantasy.espn.com`, NOT
`fantasy.espn.com` itself (which blocks fetch-style tools via robots.txt) --
a plain `requests` GET against lm-api-reads works fine.

--history is a different story: ESPN 401s on seasons more than a few years
back even for a currently-public league -- confirmed live 2026-09, both of
Ian's leagues 401'd on 2019 and 2018 while 2020-2025 worked with no auth at
all. ESPN appears to enforce THAT season's own privacy setting rather than
the league's current one, so older seasons need real login cookies even
though nothing else in this script does. Set SWID and ESPN_S2 as env vars
(pulled from a logged-in browser: DevTools -> Application/Storage ->
Cookies -> fantasy.espn.com) to authenticate those requests -- never
hardcode them here, they're full login credentials for Ian's ESPN account.
Without them, --history just stops at whatever season first 401s (which is
NOT the same thing as "the league didn't exist before this season" -- see
the per-season failure reason this script prints).

NOTE: like load_sleeper.py, this can't reach ESPN's API from this sandbox
(egress to lm-api-reads.fantasy.espn.com is blocked here). Run this on your
own machine, or from wherever the web app actually runs.

Usage:
    python3 scripts/load_espn.py            # current season only
    python3 scripts/load_espn.py --history  # also walk back through every
                                             # past season's final standings
                                             # into league_season_standings
                                             # (set SWID/ESPN_S2 to get past
                                             # seasons that 401 without auth)
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
# Optional -- only needed for --history seasons old enough to 401 without
# auth (see the module docstring). None/None means "no cookies sent", which
# is exactly today's no-auth behavior for everything that doesn't need them.
ESPN_COOKIES = None
if os.environ.get("SWID") and os.environ.get("ESPN_S2"):
    ESPN_COOKIES = {"swid": os.environ["SWID"], "espn_s2": os.environ["ESPN_S2"]}
# Sent on every request just to look like ordinary browser traffic -- not
# strictly proven necessary once HISTORY_BASE below got corrected, but
# matches what a real browser hitting these URLs sends, so left in place.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}
BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons"
# BASE's /seasons/{year}/... pattern (same one get_league() uses for the
# current season) works fine for any season back through 2018 -- confirmed
# live 2026-09, it pulled 2020-2025 for both of Ian's leagues in one run.
# Seasons before 2018 need leagueHistory instead (same cutoff the community
# espn-api library uses) -- confirmed by capturing the ACTUAL request
# fantasy.espn.com's own frontend makes when Ian loads a pre-2018 season in
# his browser: it's leagueHistory on this SAME lm-api-reads host, with a
# longer view= list than BASE needs. Earlier attempts pointed leagueHistory
# at fantasy.espn.com instead (a guess, based on how a different community
# library used to build in this URL) and chased 403s/empty bodies that were
# just symptoms of hitting the wrong host -- not a real block on this one.
LEAGUE_HISTORY_CUTOFF = 2018
HISTORY_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/leagueHistory"
HISTORY_VIEWS = [
    ("view", v) for v in
    ("mTeam", "mStandings", "mSettings", "mRoster", "mMatchupScore",
     "mLiveScoring", "mStatus", "modular", "mNav")
]

# Ian's ESPN leagues, from the project's pipeline notes -- both public, no
# login cookies needed for the current season (see ESPN_COOKIES above for
# --history on older seasons). Ian is always teamId=1 in both. Edit as
# leagues (or the season) change; the names below are just a fallback if
# settings.name doesn't come back for some reason.
SEASON = 2026
MY_TEAM_ID = "1"
LEAGUE_IDS = {
    "1532978": "The Deep's Dolphins",
    "1062658": "'72 Dolphins",
}

# --history walks backward season by season starting at SEASON - 1 (this
# season's own standings aren't final yet). It stops once this many
# consecutive seasons in a row come back with no data -- that's the signal
# ESPN has nothing that far back for this particular league, rather than
# guessing a specific founding year. FLOOR_SEASON is just a hard backstop so
# a data hiccup can't turn into an unbounded loop.
HISTORY_CONSECUTIVE_FAILURE_LIMIT = 2
FLOOR_SEASON = 2005


def get_league(league_id):
    resp = requests.get(
        f"{BASE}/{SEASON}/segments/0/leagues/{league_id}",
        params=[("view", "mTeam"), ("view", "mRoster"), ("view", "mSettings"), ("view", "mDraftDetail")],
        cookies=ESPN_COOKIES,
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def load_league(conn, league_id, fallback_name):
    info = get_league(league_id)
    if not info:
        print(f"[load_espn] WARNING: no data for league {league_id}, skipping")
        return

    settings = info.get("settings", {}) or {}
    name = settings.get("name") or fallback_name
    lineup_slot_counts = (settings.get("rosterSettings") or {}).get("lineupSlotCounts") or {}
    is_superflex = int(lineup_slot_counts.get("7", 0)) > 0  # ESPN slot 7 = "OP" (superflex)
    drafted = bool((info.get("draftDetail") or {}).get("drafted"))
    status = "in_season" if drafted else "pre_draft"

    conn.execute(
        """INSERT INTO leagues (league_id, platform, name, season, format, status, my_roster_id, updated_at)
           VALUES (?, 'espn', ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(league_id) DO UPDATE SET
               name=excluded.name, season=excluded.season, format=excluded.format,
               status=excluded.status, my_roster_id=excluded.my_roster_id, updated_at=datetime('now')""",
        (league_id, name, SEASON, "SF" if is_superflex else "1QB", status, MY_TEAM_ID),
    )

    # mTeam's `members` array maps owner GUIDs to real display names -- fall
    # back to the team's own name (location + nickname) when a member isn't
    # resolvable, same idea as Sleeper's owner_name.
    members = {m["id"]: m.get("displayName") for m in (info.get("members") or [])}
    teams = info.get("teams") or []

    for team in teams:
        roster_id = str(team["id"])
        owner_ids = team.get("owners") or []
        owner_id = owner_ids[0] if owner_ids else None
        team_name = " ".join(filter(None, [team.get("location"), team.get("nickname")])).strip()
        owner_name = members.get(owner_id) or team_name or None
        is_mine = 1 if roster_id == MY_TEAM_ID else 0

        conn.execute(
            """INSERT INTO rosters (league_id, roster_id, owner_id, owner_name, is_mine, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(league_id, roster_id) DO UPDATE SET
                   owner_id=excluded.owner_id, owner_name=excluded.owner_name,
                   is_mine=excluded.is_mine, updated_at=datetime('now')""",
            (league_id, roster_id, owner_id, owner_name, is_mine),
        )

        for entry in (team.get("roster") or {}).get("entries", []):
            player = (entry.get("playerPoolEntry") or {}).get("player") or {}
            espn_player_id = player.get("id")
            if espn_player_id is None:
                continue
            conn.execute(
                """INSERT INTO roster_players (league_id, roster_id, player_id, as_of_date)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT DO NOTHING""",
                (league_id, roster_id, f"espn:{espn_player_id}", TODAY),
            )

    conn.commit()
    print(f"[load_espn] loaded league '{name}' ({league_id}): {len(teams)} teams")


def resolve_espn_player_ids(conn):
    """roster_players stores raw espn ids as 'espn:<id>' -- if a player also
    has a fantasypros_id in the players table (loaded by build_db.py),
    repoint roster_players at that canonical id so it joins cleanly against
    trade_values/arbitrage_signals/model_predictions, which are keyed by
    fantasypros_id. Players with no fantasypros match keep the espn: id."""
    rows = conn.execute(
        "SELECT player_id, espn_id FROM players WHERE espn_id IS NOT NULL"
    ).fetchall()
    remap = {f"espn:{espn_id}": canonical_id for canonical_id, espn_id in rows}

    updated = 0
    for raw_id, canonical_id in remap.items():
        if raw_id == canonical_id:
            continue
        cur = conn.execute(
            "UPDATE OR IGNORE roster_players SET player_id = ? WHERE player_id = ?",
            (canonical_id, raw_id),
        )
        updated += cur.rowcount
    conn.commit()
    print(f"[load_espn] remapped {updated} roster_players rows to canonical player_id")


def get_season_teams(league_id, season):
    """Returns (teams, members) for one PAST league-season (mTeam view), or
    None if that season doesn't exist for this league -- observed both as
    an HTTP error and as a response with no 'teams' key for seasons before
    a league existed. Prints the actual reason on failure so a real error
    (rate limit, auth) doesn't look identical to "this league genuinely has
    no more history" in the log."""
    if season >= LEAGUE_HISTORY_CUTOFF:
        url = f"{BASE}/{season}/segments/0/leagues/{league_id}"
        params = [("view", "mTeam")]
    else:
        url = f"{HISTORY_BASE}/{league_id}"
        params = [("seasonId", season)] + HISTORY_VIEWS

    try:
        resp = requests.get(url, params=params, cookies=ESPN_COOKIES, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        # A 200 with a completely empty body shows up for seasons this legacy
        # endpoint has nothing for at all (observed 2026-09 on 2017 for both
        # of Ian's leagues, right after 2018 loaded real data) -- ESPN's way
        # of saying "no data" here, not a real request failure.
        data = resp.json() if resp.text.strip() else None
    except (requests.RequestException, ValueError) as e:
        print(f"[load_espn] history: {season} request failed for league {league_id}: {e}")
        return None

    if data is None:
        print(f"[load_espn] history: {season} returned an empty response for league "
              f"{league_id} -- treating as end of history")
        return None
    # leagueHistory replies with a list containing one league-season object;
    # BASE replies with that object directly.
    info = (data[0] if data else {}) if isinstance(data, list) else (data or {})
    teams = info.get("teams")
    if not teams:
        print(f"[load_espn] history: {season} has no teams for league {league_id} -- "
              f"treating as end of history")
        return None
    members = {m["id"]: m.get("displayName") for m in (info.get("members") or [])}
    return teams, members


def load_season_history(conn, league_id):
    """Walks backward from SEASON - 1 loading each past season's final
    standings into league_season_standings, until
    HISTORY_CONSECUTIVE_FAILURE_LIMIT seasons in a row come back empty (or
    FLOOR_SEASON is reached). Returns how many seasons were found."""
    season = SEASON - 1
    consecutive_failures = 0
    seasons_loaded = 0

    while season >= FLOOR_SEASON and consecutive_failures < HISTORY_CONSECUTIVE_FAILURE_LIMIT:
        result = get_season_teams(league_id, season)
        if result is None:
            consecutive_failures += 1
            season -= 1
            continue
        consecutive_failures = 0
        teams, members = result

        # final_rank is a best-effort ranking by (wins, points_for) -- see
        # the caveat on league_season_standings in schema/sqlite_schema.sql.
        def _sort_key(t):
            record = (t.get("record") or {}).get("overall") or {}
            return (-(record.get("wins") or 0), -(record.get("pointsFor") or 0))

        for rank, team in enumerate(sorted(teams, key=_sort_key), start=1):
            roster_id = str(team["id"])
            record = (team.get("record") or {}).get("overall") or {}
            owner_ids = team.get("owners") or []
            owner_id = owner_ids[0] if owner_ids else None
            team_name = " ".join(filter(None, [team.get("location"), team.get("nickname")])).strip()
            owner_name = members.get(owner_id) or team_name or None

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
                    league_id, season, roster_id, owner_name,
                    record.get("wins"), record.get("losses"), record.get("ties"),
                    record.get("pointsFor"), record.get("pointsAgainst"), rank,
                ),
            )
        conn.commit()
        print(f"[load_espn] history: loaded {season} standings for league {league_id} ({len(teams)} teams)")
        seasons_loaded += 1
        season -= 1

    return seasons_loaded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--history", action="store_true",
        help="also walk back through every past season's final standings",
    )
    args = parser.parse_args()

    if not os.path.exists(SQLITE_PATH):
        print("app.db not found -- run scripts/build_db.py first.")
        sys.exit(1)

    conn = sqlite3.connect(SQLITE_PATH)
    for league_id, fallback_name in LEAGUE_IDS.items():
        try:
            load_league(conn, league_id, fallback_name)
        except requests.RequestException as e:
            print(f"[load_espn] WARNING: failed to load league {league_id}: {e}")

        if args.history:
            try:
                n = load_season_history(conn, league_id)
                print(f"[load_espn] history: {n} past season(s) found for league {league_id}")
            except requests.RequestException as e:
                print(f"[load_espn] WARNING: failed to load history for league {league_id}: {e}")

    resolve_espn_player_ids(conn)

    # Separate sync_log row from Sleeper's ('rosters:espn' vs. 'rosters') --
    # sync_log's PRIMARY KEY is just table_name, so sharing 'rosters' between
    # both loaders would have each one silently overwrite the other's
    # freshness record instead of tracking them independently.
    conn.execute(
        """INSERT INTO sync_log (table_name, source, last_synced_at, row_count, notes)
           VALUES ('rosters:espn', 'espn', datetime('now'),
                   (SELECT count(*) FROM rosters r JOIN leagues l ON l.league_id = r.league_id
                    WHERE l.platform = 'espn'), ?)
           ON CONFLICT(table_name) DO UPDATE SET
               last_synced_at=datetime('now'),
               row_count=(SELECT count(*) FROM rosters r JOIN leagues l ON l.league_id = r.league_id
                          WHERE l.platform = 'espn'),
               notes=excluded.notes""",
        (f"{len(LEAGUE_IDS)} leagues configured",),
    )
    conn.commit()
    conn.close()
    print("[load_espn] done.")


if __name__ == "__main__":
    main()
