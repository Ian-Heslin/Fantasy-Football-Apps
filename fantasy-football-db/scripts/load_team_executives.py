#!/usr/bin/env python3
"""
load_team_executives.py -- loads owner + GM per team-season into
analytics.duckdb's team_executives_season table, for GM-level attribution
in analysis/analyze_draft_reaches.py (HC-level attribution, via
coach_table, is already done).

NOT reachable from this project's sandbox -- en.wikipedia.org is blocked
by the same egress policy that blocks api.sleeper.app and ordinary
websites. This script is written to be run on a normal machine (or fed to
the Claude-in-Chrome extension, which can read rendered Wikipedia pages
directly instead of hitting the API below).

Source: each team's per-season Wikipedia article, e.g.
https://en.wikipedia.org/wiki/2023_Arizona_Cardinals_season -- the
infobox on these pages carries "Owner" and "General manager" fields.
Pulled via the MediaWiki API (action=query, prop=revisions) rather than
scraping rendered HTML, so this only needs `requests`, no browser --
Wikipedia's API requires a descriptive User-Agent or it 403s, so one is
set below (edit WIKI_USER_AGENT with a real contact if you fork this).

Franchise relocations/renames are handled via TEAM_FULL_NAMES below,
covering the article-title changes within the 2006-2025 window this
project's draft-grade data spans (Rams STL->LA, Chargers SD->LA,
Raiders Oakland->Las Vegas, Washington Redskins->Football Team->
Commanders). If a page title doesn't resolve (redirect naming differs
from what's guessed here), the row is skipped and logged rather than
guessed at.

Usage:
    python3 scripts/load_team_executives.py                 # 2006-2025
    python3 scripts/load_team_executives.py --start 2020 --end 2024
"""
import argparse
import os
import re
import sys
import time

import duckdb
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUCKDB_PATH = os.path.join(ROOT, "data", "analytics.duckdb")
WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKI_USER_AGENT = (
    "FantasyFootballAppsResearchBot/1.0 "
    "(personal project, non-commercial; contact: repo owner)"
)

# Standard team code -> full franchise name, keyed by the season range it
# applies to (inclusive). Teams with no relocation/rename in this window
# use a single (None, None, name) entry.
TEAM_FULL_NAMES = {
    "ARI": [(None, None, "Arizona Cardinals")],
    "ATL": [(None, None, "Atlanta Falcons")],
    "BAL": [(None, None, "Baltimore Ravens")],
    "BUF": [(None, None, "Buffalo Bills")],
    "CAR": [(None, None, "Carolina Panthers")],
    "CHI": [(None, None, "Chicago Bears")],
    "CIN": [(None, None, "Cincinnati Bengals")],
    "CLE": [(None, None, "Cleveland Browns")],
    "DAL": [(None, None, "Dallas Cowboys")],
    "DEN": [(None, None, "Denver Broncos")],
    "DET": [(None, None, "Detroit Lions")],
    "GB": [(None, None, "Green Bay Packers")],
    "HOU": [(None, None, "Houston Texans")],
    "IND": [(None, None, "Indianapolis Colts")],
    "JAX": [(None, None, "Jacksonville Jaguars")],
    "KC": [(None, None, "Kansas City Chiefs")],
    "LA": [
        (None, 2015, "St. Louis Rams"),
        (2016, None, "Los Angeles Rams"),
    ],
    "LAC": [
        (None, 2016, "San Diego Chargers"),
        (2017, None, "Los Angeles Chargers"),
    ],
    "LV": [
        (None, 2019, "Oakland Raiders"),
        (2020, None, "Las Vegas Raiders"),
    ],
    "MIA": [(None, None, "Miami Dolphins")],
    "MIN": [(None, None, "Minnesota Vikings")],
    "NE": [(None, None, "New England Patriots")],
    "NO": [(None, None, "New Orleans Saints")],
    "NYG": [(None, None, "New York Giants")],
    "NYJ": [(None, None, "New York Jets")],
    "PHI": [(None, None, "Philadelphia Eagles")],
    "PIT": [(None, None, "Pittsburgh Steelers")],
    "SEA": [(None, None, "Seattle Seahawks")],
    "SF": [(None, None, "San Francisco 49ers")],
    "TB": [(None, None, "Tampa Bay Buccaneers")],
    "TEN": [(None, None, "Tennessee Titans")],
    "WAS": [
        (None, 2019, "Washington Redskins"),
        (2020, 2021, "Washington Football Team"),
        (2022, None, "Washington Commanders"),
    ],
}

INFOBOX_FIELD_RE = re.compile(
    r"^\|\s*(owner|general_?manager|gm)\s*=\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def log(msg):
    print(f"[load_team_executives] {msg}")


def full_name_for(team, season):
    for start, end, name in TEAM_FULL_NAMES[team]:
        if (start is None or season >= start) and (end is None or season <= end):
            return name
    raise ValueError(f"no full name mapping for {team} {season}")


def clean_wiki_value(raw):
    """Strip wikilinks/refs/markup down to plain text, e.g.
    "[[Michael Bidwill]]<ref>...</ref>" -> "Michael Bidwill"."""
    v = re.sub(r"<ref[^>]*>.*?</ref>", "", raw, flags=re.DOTALL)
    v = re.sub(r"<ref[^>]*/>", "", v)
    v = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", v)  # [[link|display]]
    v = re.sub(r"\[\[([^\]]+)\]\]", r"\1", v)  # [[link]]
    v = re.sub(r"'''?", "", v)  # bold/italics
    v = re.sub(r"<[^>]+>", "", v)  # any remaining HTML tags
    v = re.sub(r"\{\{[^}]*\}\}", "", v)  # inline templates
    return v.strip()


def fetch_wikitext(title, session):
    resp = session.get(
        WIKI_API,
        params={
            "action": "query",
            "prop": "revisions",
            "rvslots": "main",
            "rvprop": "content",
            "format": "json",
            "titles": title,
        },
        timeout=30,
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    for page in pages.values():
        if "missing" in page:
            return None
        revisions = page.get("revisions")
        if revisions:
            return revisions[0]["slots"]["main"]["*"]
    return None


def parse_owner_and_gm(wikitext):
    owner, gm = None, None
    for field, value in INFOBOX_FIELD_RE.findall(wikitext):
        cleaned = clean_wiki_value(value)
        if not cleaned:
            continue
        field_norm = field.lower().replace("_", "")
        if field_norm == "owner" and owner is None:
            owner = cleaned
        elif field_norm in ("generalmanager", "gm") and gm is None:
            gm = cleaned
    return owner, gm


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=2006)
    parser.add_argument("--end", type=int, default=2025)
    parser.add_argument("--sleep", type=float, default=1.0,
                         help="seconds between requests (be polite to Wikipedia)")
    args = parser.parse_args()

    if not os.path.exists(DUCKDB_PATH):
        log("analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    session = requests.Session()
    session.headers["User-Agent"] = WIKI_USER_AGENT

    rows = []
    skipped = []
    for season in range(args.start, args.end + 1):
        for team in sorted(TEAM_FULL_NAMES):
            name = full_name_for(team, season)
            title = f"{season} {name} season"
            try:
                wikitext = fetch_wikitext(title, session)
            except requests.RequestException as e:
                skipped.append((season, team, title, str(e)))
                continue
            time.sleep(args.sleep)

            if wikitext is None:
                skipped.append((season, team, title, "page not found"))
                continue

            owner, gm = parse_owner_and_gm(wikitext)
            if owner is None and gm is None:
                skipped.append((season, team, title, "no owner/GM field found in infobox"))
                continue

            source_url = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")
            rows.append((season, team, owner, gm, source_url))
            log(f"{season} {team}: owner={owner!r} gm={gm!r}")

    conn = duckdb.connect(DUCKDB_PATH)
    for season, team, owner, gm, source_url in rows:
        conn.execute(
            """INSERT INTO team_executives_season (season, team, owner, general_manager, source_url)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (season, team) DO UPDATE SET
                   owner = excluded.owner,
                   general_manager = excluded.general_manager,
                   source_url = excluded.source_url""",
            (season, team, owner, gm, source_url),
        )
    conn.close()

    log(f"loaded {len(rows)} team-seasons, skipped {len(skipped)}")
    if skipped:
        log("skipped (page/field not found -- check title mapping or infobox field names):")
        for season, team, title, reason in skipped:
            log(f"  {season} {team} ({title!r}): {reason}")
    log("done.")


if __name__ == "__main__":
    main()
