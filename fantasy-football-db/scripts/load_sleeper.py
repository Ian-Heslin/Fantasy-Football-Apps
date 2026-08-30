#!/usr/bin/env python3
"""
load_sleeper.py -- pulls Ian's Sleeper leagues, rosters, and roster/player
membership straight from the public Sleeper API (no auth needed) and loads
them into app.db.

NOTE: this sandbox's network cannot reach api.sleeper.app (confirmed in this
project's own pipeline notes -- see the project doc). That's a restriction of
THIS cloud sandbox specifically, not a real limitation -- plain `requests`
calls to api.sleeper.app work fine from an ordinary machine (which is why
this script uses `requests` rather than anything sandbox-specific). Run this
on your own machine, or from wherever the web app actually runs.

Usage:
    python3 scripts/load_sleeper.py
"""
import os
import sqlite3
import sys
from datetime import date

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQLITE_PATH = os.path.join(ROOT, "data", "app.db")
TODAY = date.today().isoformat()
BASE = "https://api.sleeper.app/v1"

# Ian's leagues, from the project's pipeline notes. Edit this list (or load it
# from a config file) as leagues are added/dropped season to season.
MY_USER_ID = "412300641516400640"  # authorzed
LEAGUE_IDS = [
    "1389389302827339776",  # Alumni Committee
    "1313508869787389952",  # Quarantine Dynasty
    "1313201033589035008",  # (TBD name), Superflex
    "1312127342742614016",  # Wisco Dynasty
    "1180207743981412352",  # D - 1, 2025 (complete)
]


def get(path):
    resp = requests.get(f"{BASE}{path}", timeout=15)
    resp.raise_for_status()
    return resp.json()


def load_league(conn, league_id):
    info = get(f"/league/{league_id}")
    if not info:
        print(f"[load_sleeper] WARNING: no data for league {league_id}, skipping")
        return

    settings = info.get("settings", {}) or {}
    is_superflex = bool((info.get("roster_positions") or []).count("SUPER_FLEX"))
    my_roster_id = None

    conn.execute(
        """INSERT INTO leagues (league_id, platform, name, season, format, status, updated_at)
           VALUES (?, 'sleeper', ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(league_id) DO UPDATE SET
               name=excluded.name, season=excluded.season, format=excluded.format,
               status=excluded.status, updated_at=datetime('now')""",
        (
            league_id,
            info.get("name"),
            int(info.get("season")) if info.get("season") else None,
            "SF" if is_superflex else "1QB",
            info.get("status"),
        ),
    )

    # rosters (owner mapping) + users (owner display names) together
    rosters = get(f"/league/{league_id}/rosters")
    users = {u["user_id"]: u for u in get(f"/league/{league_id}/users")}

    for roster in rosters:
        roster_id = str(roster["roster_id"])
        owner_id = roster.get("owner_id")
        owner_name = (users.get(owner_id) or {}).get("display_name")
        is_mine = 1 if owner_id == MY_USER_ID else 0
        if is_mine:
            my_roster_id = roster_id

        conn.execute(
            """INSERT INTO rosters (league_id, roster_id, owner_id, owner_name, is_mine, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(league_id, roster_id) DO UPDATE SET
                   owner_id=excluded.owner_id, owner_name=excluded.owner_name,
                   is_mine=excluded.is_mine, updated_at=datetime('now')""",
            (league_id, roster_id, owner_id, owner_name, is_mine),
        )

        for sleeper_player_id in (roster.get("players") or []):
            conn.execute(
                """INSERT INTO roster_players (league_id, roster_id, player_id, as_of_date)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT DO NOTHING""",
                (league_id, roster_id, f"sleeper:{sleeper_player_id}", TODAY),
            )

    if my_roster_id:
        conn.execute(
            "UPDATE leagues SET my_roster_id = ? WHERE league_id = ?",
            (my_roster_id, league_id),
        )

    conn.commit()
    print(f"[load_sleeper] loaded league '{info.get('name')}' ({league_id}): "
          f"{len(rosters)} rosters")


def resolve_sleeper_player_ids(conn):
    """roster_players stores raw sleeper ids as 'sleeper:<id>' -- if a player
    also has a fantasypros_id in the players table (loaded by build_db.py),
    repoint roster_players at that canonical id so it joins cleanly against
    trade_values / arbitrage_signals / model_predictions, which are keyed by
    fantasypros_id. Players with no fantasypros match keep the sleeper: id."""
    rows = conn.execute(
        "SELECT player_id, sleeper_id FROM players WHERE sleeper_id IS NOT NULL"
    ).fetchall()
    remap = {f"sleeper:{sleeper_id}": canonical_id for canonical_id, sleeper_id in rows}

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
    print(f"[load_sleeper] remapped {updated} roster_players rows to canonical player_id")


def main():
    if not os.path.exists(SQLITE_PATH):
        print("app.db not found -- run scripts/build_db.py first.")
        sys.exit(1)

    conn = sqlite3.connect(SQLITE_PATH)
    for league_id in LEAGUE_IDS:
        try:
            load_league(conn, league_id)
        except requests.RequestException as e:
            print(f"[load_sleeper] WARNING: failed to load league {league_id}: {e}")

    resolve_sleeper_player_ids(conn)

    # Separate sync_log row from ESPN's ('rosters:sleeper' vs. 'rosters:espn')
    # -- sync_log's PRIMARY KEY is just table_name, so sharing one row between
    # both loaders would have each one silently overwrite the other's
    # freshness record instead of tracking them independently. Also scope
    # row_count to Sleeper's own rosters rather than every platform's.
    # (One-time cleanup: drop the old shared 'rosters' key from before ESPN
    # support existed, so it doesn't linger on the dashboard forever.)
    conn.execute("DELETE FROM sync_log WHERE table_name = 'rosters'")
    conn.execute(
        """INSERT INTO sync_log (table_name, source, last_synced_at, row_count, notes)
           VALUES ('rosters:sleeper', 'sleeper', datetime('now'),
                   (SELECT count(*) FROM rosters r JOIN leagues l ON l.league_id = r.league_id
                    WHERE l.platform = 'sleeper'), ?)
           ON CONFLICT(table_name) DO UPDATE SET
               last_synced_at=datetime('now'),
               row_count=(SELECT count(*) FROM rosters r JOIN leagues l ON l.league_id = r.league_id
                          WHERE l.platform = 'sleeper'),
               notes=excluded.notes""",
        (f"{len(LEAGUE_IDS)} leagues configured",),
    )
    conn.commit()
    conn.close()
    print("[load_sleeper] done.")


if __name__ == "__main__":
    main()
