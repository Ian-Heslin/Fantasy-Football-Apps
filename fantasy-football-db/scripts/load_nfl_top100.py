#!/usr/bin/env python3
"""
load_nfl_top100.py -- loads the NFL Network's fan-voted annual "Top 100
Players" list into analytics.duckdb's nfl_top_100 table, for a separate
"guess a player's rank" trivia game (distinct from the Award Winners
guessing game already built -- see webapp/app/trivia.py).

NOT reachable from this project's sandbox -- there's no ready-made CSV/
dataset for this anywhere (confirmed by search: no GitHub-hosted mirror
exists, unlike nflverse's stat releases), and the only real source is
Wikipedia's "NFL Top 100 Players of <year>" articles, one per year since
2011 -- en.wikipedia.org is blocked by this sandbox's egress policy, same
wall as load_team_executives.py hit for owner/GM data. Written to be run
on a normal machine (or fed to the Claude-in-Chrome extension, which can
read the rendered page directly instead of hitting the API below).

UNVERIFIED, unlike this project's other loaders: I could not fetch a real
"NFL Top 100 Players of <year>" page from here to confirm its exact
wikitext structure, so the parser below tries three plausible formats
(a wikitable with rank/player/team columns; a MediaWiki ordered list of
wikilinks, one per rank; numbered section headers, one per player) rather
than one confirmed pattern. Run this for one recent year first and
spot-check the output before trusting the full 2011-present range --
if all three parsing strategies come up empty for a real page, paste a
sample of that page's wikitext (Wikipedia's own "Edit source" view) back
so the parser can be corrected against the real format.

Usage:
    python3 scripts/load_nfl_top100.py --start 2011 --end 2025
    python3 scripts/load_nfl_top100.py --start 2024 --end 2024  # spot-check one year first
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

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def log(msg):
    print(f"[load_nfl_top100] {msg}")


def clean_wiki_value(raw):
    v = re.sub(r"<ref[^>]*>.*?</ref>", "", raw, flags=re.DOTALL)
    v = re.sub(r"<ref[^>]*/>", "", v)
    v = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", v)
    v = re.sub(r"\[\[([^\]]+)\]\]", r"\1", v)
    v = re.sub(r"'''?", "", v)
    v = re.sub(r"<[^>]+>", "", v)
    return v.strip()


def fetch_wikitext(title, session):
    resp = session.get(
        WIKI_API,
        params={
            "action": "query", "prop": "revisions", "rvslots": "main",
            "rvprop": "content", "format": "json", "titles": title,
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


def parse_wikitable(wikitext):
    """Rows like '| 1 || [[Player]] || [[Team]]' or '|1||Player||Team',
    inside any {| ... |} table block. Returns [] if nothing matches."""
    rows = []
    in_table = False
    current = []
    for line in wikitext.splitlines():
        stripped = line.strip()
        if stripped.startswith("{|"):
            in_table = True
            continue
        if stripped.startswith("|}"):
            in_table = False
            continue
        if not in_table:
            continue
        if stripped.startswith("|-"):
            if current:
                rows.append(current)
                current = []
            continue
        if stripped.startswith("|") and not stripped.startswith("|+"):
            cell = clean_wiki_value(stripped.lstrip("|").strip())
            if "||" in stripped:
                # single-line "| a || b || c" row
                cells = [clean_wiki_value(c.strip()) for c in stripped.lstrip("|").split("||")]
                rows.append(cells)
            else:
                current.append(cell)
    if current:
        rows.append(current)

    results = []
    for cells in rows:
        if len(cells) < 2:
            continue
        rank_match = re.match(r"^(\d+)", cells[0])
        if not rank_match:
            continue
        rank = int(rank_match.group(1))
        player = cells[1]
        team = cells[2] if len(cells) > 2 else None
        if player:
            results.append((rank, player, team))
    return results


def parse_ordered_list(wikitext):
    """A MediaWiki ordered list ('# ...'), one line per rank -- assumed to
    count down from 100 (rank 1 = best) unless the line itself states a
    number. Player = the line's first wikilink; team = a later wikilink
    on the same line, if any."""
    results = []
    lines = [l for l in wikitext.splitlines() if l.strip().startswith("#") and not l.strip().startswith("#REDIRECT")]
    n = len(lines)
    if n < 50:  # too few to plausibly be the 100-player list
        return []
    for i, line in enumerate(lines):
        links = WIKILINK_RE.findall(line)
        if not links:
            continue
        player = links[0][1] or links[0][0]
        team = (links[1][1] or links[1][0]) if len(links) > 1 else None
        rank = n - i  # first line = highest rank number (100), counting down to 1
        results.append((rank, clean_wiki_value(player), clean_wiki_value(team) if team else None))
    return results


def parse_section_headers(wikitext):
    """Numbered section headers, one per player, e.g. '==100. Player=='
    or '==No. 100: Player=='."""
    results = []
    for m in re.finditer(r"^==+\s*(?:No\.\s*)?(\d+)[.:]?\s*(.+?)\s*==+\s*$", wikitext, re.MULTILINE):
        rank = int(m.group(1))
        player = clean_wiki_value(m.group(2))
        if player:
            results.append((rank, player, None))
    return results


def parse_top_100(wikitext):
    for parser in (parse_wikitable, parse_ordered_list, parse_section_headers):
        rows = parser(wikitext)
        if len(rows) >= 50:  # a real hit should cover most/all of the list
            return rows, parser.__name__
    return [], None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=2011)
    parser.add_argument("--end", type=int, default=2025)
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()

    if not os.path.exists(DUCKDB_PATH):
        log("analytics.duckdb not found -- run scripts/build_db.py first.")
        sys.exit(1)

    session = requests.Session()
    session.headers["User-Agent"] = WIKI_USER_AGENT

    all_rows = []
    for year in range(args.start, args.end + 1):
        title = f"NFL Top 100 Players of {year}"
        try:
            wikitext = fetch_wikitext(title, session)
        except requests.RequestException as e:
            log(f"{year}: request failed -- {e}")
            continue
        time.sleep(args.sleep)

        if wikitext is None:
            log(f"{year}: page {title!r} not found")
            continue

        rows, method = parse_top_100(wikitext)
        if not rows:
            log(f"{year}: no parser matched -- page structure differs from what this script "
                f"expects. Paste a sample of {title!r}'s wikitext (Wikipedia's 'Edit source' "
                f"view) back so the parser can be fixed.")
            continue

        source_url = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")
        log(f"{year}: parsed {len(rows)} rows via {method}")
        for rank, player, team in rows:
            all_rows.append((year, rank, player, team, source_url))

    if not all_rows:
        log("nothing parsed -- see notes above. Not touching nfl_top_100.")
        return

    conn = duckdb.connect(DUCKDB_PATH)
    conn.execute("DELETE FROM nfl_top_100 WHERE year >= ? AND year <= ?", (args.start, args.end))
    conn.executemany(
        "INSERT INTO nfl_top_100 (year, rank, player, team, source_url) VALUES (?, ?, ?, ?, ?)",
        all_rows,
    )
    conn.close()
    log(f"loaded {len(all_rows)} rows across {args.end - args.start + 1} requested years")
    log("Spot-check a couple of years against the real Wikipedia page before trusting this --"
        " this script's parsing was never verified against a live page from this sandbox.")
    log("done.")


if __name__ == "__main__":
    main()
