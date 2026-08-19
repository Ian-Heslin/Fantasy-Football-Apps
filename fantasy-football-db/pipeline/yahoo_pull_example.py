"""
Starter script for pulling Yahoo Fantasy Football league data with yfpy.

RUN THIS ON YOUR OWN MACHINE, NOT IN A CLOUD SANDBOX - the OAuth token exchange
requires outbound network access to Yahoo's servers plus an interactive browser
login the first time you run it.

Setup (one-time):
    1. pip install yfpy
    2. Register an app at https://developer.yahoo.com/apps/create/
       - Application Type: "Installed Application"
       - API Permissions: Fantasy Sports (Read)
       - Redirect URI: https://localhost:8080
       - Copy the Client ID (Consumer Key) and Client Secret (Consumer Secret) Yahoo gives you.
    3. Fill in YAHOO_CONSUMER_KEY / YAHOO_CONSUMER_SECRET / LEAGUE_ID below (or better,
       set them as environment variables and read them with os.environ instead of hardcoding).
    4. Run this script. The first run will open a browser tab asking you to log into
       Yahoo and approve access - after that, yfpy caches a token file locally (in the
       folder you point env_file_location at) so future runs don't need the browser step.

Note: yfpy's exact method names have shifted a bit across versions - if something below
errors, check `pip show yfpy` for your installed version and cross-reference against
https://github.com/uberfastman/yfpy for the current query method names. The overall shape
(construct a YahooFantasySportsQuery with your league_id/game_code/keys, then call query
methods for teams/rosters/players/transactions) has been stable.
"""

import os
from pathlib import Path
from yfpy.query import YahooFantasySportsQuery

# --- fill these in, or better, read from environment variables ---
YAHOO_CONSUMER_KEY = os.environ.get("YAHOO_CONSUMER_KEY", "YOUR_CLIENT_ID_HERE")
YAHOO_CONSUMER_SECRET = os.environ.get("YAHOO_CONSUMER_SECRET", "YOUR_CLIENT_SECRET_HERE")
LEAGUE_ID = "123456"  # from the league's URL: football.fantasysports.yahoo.com/f1/<league_id>
GAME_CODE = "nfl"

query = YahooFantasySportsQuery(
    league_id=LEAGUE_ID,
    game_code=GAME_CODE,
    yahoo_consumer_key=YAHOO_CONSUMER_KEY,
    yahoo_consumer_secret=YAHOO_CONSUMER_SECRET,
    env_file_location=Path("."),          # where yfpy will cache the OAuth token after first login
    save_token_data_to_env_file=True,
)

# --- example pulls, mirroring what we already have from Sleeper ---
league_info = query.get_league_info()
print("League:", league_info)

teams = query.get_league_teams()
print(f"\n{len(teams)} teams:")
for t in teams:
    print(" -", t)

# roster for a specific team_id (find your own team_id from the teams list above)
# roster = query.get_team_roster_by_week(team_id=1, chosen_week="current")
# print(roster)
