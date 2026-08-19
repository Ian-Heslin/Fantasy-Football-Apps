"""
Starter script for pulling FantasyPros v2 API data (rankings, injuries, player points).

RUN THIS ON YOUR OWN MACHINE, NOT IN A CLOUD SANDBOX - api.fantasypros.com is not reachable
from this cloud session's network, and it needs a custom "x-api-key" header that this
session's web-fetch tooling can't send anyway.

Setup (one-time):
    1. pip install requests
    2. Set your API key as an environment variable rather than hardcoding it in a script
       you might ever share or commit:
         export FANTASYPROS_API_KEY="your-key-here"
    3. Run this script.

Docs: https://api.fantasypros.com/public/v2/docs
"""

import os
import requests

API_KEY = os.environ["FANTASYPROS_API_KEY"]
BASE = "https://api.fantasypros.com/public/v2/json"
HEADERS = {"x-api-key": API_KEY}


def get(path, **params):
    resp = requests.get(f"{BASE}/{path}", headers=HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


if __name__ == "__main__":
    # 1. Current-week injury report (great for flagging risk on your rostered players)
    injuries = get("nfl/injuries", year=2026, week=1)
    print(f"{injuries['count']} injury entries this week")

    # 2. Consensus dynasty/redraft rankings - includes player_yahoo_id, tier, rank_ecr
    #    (this is the same shape of data we built the buy-low/sell-high signal from,
    #    but straight from FantasyPros' own API instead of scraping their site)
    rankings = get(
        "nfl/2026/consensus-rankings",
        position="RB",
        scoring="PPR",
        experts="show",
    )
    print(f"{rankings['count']} RB rankings, last updated {rankings['last_updated']}")

    # 3. Actual fantasy points scored so far this season, by player - lets us compute
    #    real week-over-week PPG trends instead of relying on ECR movement as a proxy
    points = get("nfl/2026/player-points", position="RB", scoring="PPR")
    print(f"{len(points['players'])} RB player-points rows, season {points['season']}")

    # From here: match player_yahoo_id / player_id against the crosswalk we already built
    # (db_playerids.csv has fantasypros_id, which is the same "player_id"/"fpid" used here)
    # to join this straight onto the Sleeper/ESPN/Yahoo roster data.
