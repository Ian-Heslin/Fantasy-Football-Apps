# Sleeper league data + dynasty trade-value pipeline

Working notes on how we're pulling Ian's league-specific data for trade/roster advice, so a
future session can pick this up without re-discovering it.

## Sleeper (league/roster/owner data)
- Public, read-only, no auth. Base: `https://api.sleeper.app/v1/...`
- **This sandbox's Bash/curl network cannot reach `api.sleeper.app`** (blocked at the network
  level, confirmed even bypassing proxy env vars) — but the `WebFetch` tool reaches it fine. Use
  WebFetch for any live Sleeper pull in this environment.
- Ian's Sleeper username: `authorzed`, user_id `412300641516400640`.
- Ian's leagues (league_id, name, season, format):
  - `1389389302827339776` — Alumni Committee, 2026, pre-draft, 1QB, roster #9
  - `1313508869787389952` — Quarantine Dynasty, 2026, in season, Superflex, roster #5
  - `1313201033589035008` — (name not set in Sleeper, shows "TBD"), 2026, in season, Superflex, roster #6
  - `1312127342742614016` — Wisco Dynasty, 2026, in season, 1QB, roster #3
  - `1180207743981412352` — D - 1, 2025, complete, Superflex, roster #2
- Full league/roster/owner detail cached this session at `/home/claude/sleeper/leagues_summary.json`
  (session-local, not persistent — re-pull via WebFetch if a new session needs it).

### ⚠️ WebFetch data-integrity caveat — confirmed, don't skip verification
When several `/rosters` endpoints were fetched in one batch and WebFetch had to relay a
multi-team table AND a separate "Complete Player Rosters" list in the same response, it silently
returned wrong/cross-contaminated data twice: once mislabeling which owner went with which
roster_id, and separately once returning a player list for "Wisco Dynasty roster 3" that didn't
actually belong to that roster at all (confirmed by re-fetching — no overlap with the real list,
and the real list didn't contain a player the user confirmed he doesn't own). Both bad pulls
looked completely well-formatted and plausible; nothing about the output signaled it was wrong.
**Lesson: never trust a WebFetch roster pull that hasn't been spot-checked against something the
user can verify (e.g. "do you actually own this specific player?").** The reliable pattern is one
targeted fetch per roster — asking for "the ONE roster where owner_id equals X, full players
array, verbatim" — rather than fetching the whole multi-team endpoint and asking WebFetch to pick
a row out of a big table. All 5 of Ian's rosters were re-pulled this way and cross-checked
(Alumni Committee and Quarantine Dynasty matched the original batch pull exactly; the TBD league
and Wisco Dynasty had been wrong and are now corrected in `leagues_summary.json`).

## Player ID resolution + dynasty trade values (dynastyprocess/data)
- Sleeper only exposes player names via a ~5MB `/v1/players/nfl` file, which truncates at
  ~60-70% when pulled through WebFetch — not reliable for full roster name resolution.
- **Fix found this session**: `github.com/dynastyprocess/data` (git clone works fine in this
  sandbox — regular GitHub git/https access is not blocked, unlike api.sleeper.app) ships:
  - `files/db_playerids.csv` — a full crosswalk of `sleeper_id`, `espn_id`, `yahoo_id`,
    `fantasypros_id`, `mfl_id`, `ktc_id`, etc. all pointing to the same `name`/`position`/`team`.
    This solves player-ID resolution for **Sleeper, ESPN, and Yahoo all at once** — the same
    file works no matter which platform's league data we're joining.
  - `files/values.csv` — consolidated dynasty trade values (FantasyPros ECR-derived), one row
    per player + draft pick, with both `value_1qb` and `value_2qb` (superflex) columns and
    `ecr_1qb`/`ecr_2qb`/`ecr_pos` ranks. This is our market-consensus substitute for a trade
    calculator (KeepTradeCut-style). Joins to `db_playerids.csv` via `fantasypros_id` == `fp_id`.
  - `files/db_fpecr_latest.csv` — current FantasyPros ECR snapshot across many ranking pages
    (dynasty-overall, dynasty-superflex, ppr-cheatsheets [redraft 1QB], ppr-superflex-cheatsheets
    [redraft SF], plus positional/best-ball variants), keyed by the same `id` == `fp_id`. Has a
    `rank_delta` column for week-over-week movement, but it's NA everywhere in the 2026-08-14
    snapshot since the season hadn't started yet — useless as a momentum signal in the preseason,
    should become usable once real weekly snapshots accumulate in-season.
  - `files/db_fpecr.csv.gz` — full historical ECR archive (2021-2026, 1.5M rows) if a longer
    trend line is ever needed instead of the single latest snapshot.
  - Repo updates its `values.csv`/`db_fpecr_latest.csv` regularly (scrape_date was 2026-08-14 as
    of this session) — re-clone (`git clone --depth 1 https://github.com/dynastyprocess/data.git`)
    to refresh rather than reusing a stale copy.
- Built this session: `/home/claude/sleeper/player_crosswalk.json` (sleeper_id -> name/position/
  team/dynasty values, 6,358 players, 685 with a matched trade value) and
  `/home/claude/sleeper/my_rosters_valued.csv` (Ian's own roster in each league, resolved to
  names and valued using the correct value column per league's 1QB/superflex format, corrected
  version after the WebFetch data-integrity fix above). Both are session-local — rebuild from
  the repo clone if needed later (script logic: join rosters' Sleeper player_ids ->
  db_playerids.csv on sleeper_id -> values.csv on fantasypros_id).

## Buy-low / sell-high comparison model (lightweight version, built this session)
The project's breakout/fall-off methodology doc (`claude/breakout-falloff-methodology.md`, v16)
describes a real, validated statistical model (trained coefficients, tier cutoffs, scored
predictions) — but none of that model's actual output files were ever saved anywhere persistent;
they lived in a prior session's ephemeral workspace and are gone. Rebuilding it for real would
mean re-pulling 25 years of nflverse play-by-play and re-deriving position tier cutoffs from
scratch — a multi-session undertaking. Ian chose a lightweight substitute for now instead of that
full rebuild.

**Method**: for each rostered player, compare two FantasyPros ECR percentiles pulled from
`db_fpecr_latest.csv` — dynasty rank (long-term market value, `dynasty-overall.php` for 1QB
leagues / `dynasty-superflex.php` for superflex leagues) vs. redraft rank (this-season-only value,
`ppr-cheatsheets.php` / `ppr-superflex-cheatsheets.php`). Both converted to a 0-1 percentile within
their own ranking pool (~500-550 players each), then `gap = dynasty_percentile -
redraft_percentile`.
- **gap >= +0.15** → BUY-LOW / HOLD: the dynasty market values him more than his current-season
  redraft ranking does (long-term believer, not yet peaking — often a young/rookie profile).
- **gap <= -0.15** → SELL-HIGH: current-season production/ranking is outrunning his long-term
  dynasty price (age-cliff or one-year-wonder risk — the classic "sell while he's hot" case).
- in between → fairly priced.

Script: `/home/claude/build_comparison_model.py` (builds `/home/claude/sleeper/
arbitrage_signal.json`, the per-player gap by format) and `/home/claude/trade_signals.py` (joins
that onto each of Ian's 5 rosters, outputs `/home/claude/sleeper/trade_signals.csv`). Both
session-local — rebuild from the repo clone + existing crosswalk/leagues_summary.json if needed.

**Known limitation, important to flag on re-use**: this was run in the preseason (2026-08-14,
before any 2026 games), so dynasty and redraft rankings track each other very closely for
established players — there's been no real-world performance yet to create a gap. Almost every
flagged BUY-LOW hit this run was a rookie/prospect (wide redraft-ranking uncertainty, not a true
performance-vs-price gap) and most flagged SELL-HIGH hits were deep-bench/near-droppable
players, not real trade assets. This signal should get much more useful and discriminating once
the season is underway and redraft rankings start moving on actual weekly results while dynasty
value stays comparatively sticky — worth re-running every few weeks in-season rather than treating
this preseason run as the final word. At that point `rank_delta` (currently all NA) will also
become usable as a real momentum feature to add alongside the gap. **The FantasyPros v2 API below
is a much better long-term source for this than the scraped `db_fpecr_latest.csv` snapshot** —
worth migrating this script to pull from `consensus-rankings` + `player-points` directly once the
API is wired into a local runner.

## Yahoo Fantasy Sports API — access requested, awaiting approval
Ian wants to pull his Yahoo league(s) the same way, using the `yfpy` Python wrapper. Confirmed
this session that **Yahoo's OAuth/API domains (`fantasysports.yahooapis.com`,
`api.login.yahoo.com`) are blocked from this sandbox's Bash/curl the same way api.sleeper.app is
— and unlike Sleeper, there's no WebFetch workaround, because the OAuth token exchange needs a
POST request and WebFetch only does GETs.** Any actual Yahoo API pull has to happen on Ian's own
machine, not in this cloud session — I can write/maintain the script, but he runs it locally.

**Yahoo's registration flow has changed since yfpy's own docs were written** (confirmed live via
Claude in Chrome, 2026-08-19):
1. `developer.yahoo.com/apps/create/` — the old "Installed Application" radio button is gone;
   it's now **OAuth Client Type**: "Confidential Client" (traditional web apps) vs. "Public
   Client" (mobile/native/SPA). Pick **Confidential Client** — yfpy needs a Client ID *and*
   Client Secret, which only a confidential client gets. The API Permissions checkboxes on this
   page are now just "OpenID Connect Permissions" and "TW Auction" — **no Fantasy Sports
   checkbox here anymore.**
2. Fantasy Sports access is now a **separate gated application** at
   `sports.yahoo.com/developer/access/`, reviewed by Yahoo's Fantasy Sports team (no published
   turnaround time). Read-only by default; write access needs justification in notes. Fields are
   clearly written for commercial products (Business Name & Address, Consumer-Facing Product
   Name, Company Description, Website URL/App Store listing, Intended Use Case, Expected Users
   Small/Medium/Large) but the page explicitly allows "personal or single league use" as a valid
   answer if stated plainly in the description fields. Optional Client ID field links it to the
   app created in step 1.

**Status as of 2026-08-19**: Ian created the OAuth app ("Ian's Fantasy Tool",
`developer.yahoo.com/apps/aQHMRdqu/` — Client ID/Secret live in his own YDN account, not recorded
here) and submitted the Fantasy Sports API access application referencing it. Now waiting on
Yahoo's review/approval before the Fantasy scopes will actually work. Starter pull script (to run
on his own machine once approved) delivered to him as `yahoo_pull_example.py` — uses `yfpy`,
follows the same league/roster shape as the Sleeper pipeline above, and his `yahoo_id` is already
in the crosswalk so once real data comes back it slots into the same valuation/arbitrage scripts
with no extra join work needed.

**Next step once approved**: get Ian's actual Yahoo league ID(s) (visible in the league URL,
`football.fantasysports.yahoo.com/f1/<league_id>`), run/adapt the starter script, and feed the
resulting roster data through the same crosswalk + `build_comparison_model.py` /
`trade_signals.py` pipeline already built for Sleeper.

## ESPN (public leagues — working, no auth needed)
Both of Ian's ESPN leagues are public, so no `SWID`/`espn_s2` cookies are needed at all. Unlike
`fantasy.espn.com` itself (blocked for WebFetch by robots.txt) and unlike the Bash-blocked domains
used elsewhere in this doc, **`lm-api-reads.fantasy.espn.com` works fine through WebFetch** for
these public leagues — confirmed this session pulling both current-season team lists and prior-
season (2025) final standings.

- Ian's ESPN leagues (Ian is always `teamId=1` in both):
  - `1532978` — "The Deep's Dolphins" league, 8 teams. 2026: pre-draft. **2025 final record:
    8-5** (3rd of 8; Cousins Tucker/Richard Hansen won at 9-4).
  - `1062658` — "'72 Dolphins" league, 8 teams. 2026: pre-draft. **2025 final record: 3-10**
    (last of 8).
- URL pattern (swap `{YEAR}` for any past season — same league ID persists year over year, at
  least back to 2025; not yet tested further back):
  `https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{YEAR}/segments/0/leagues/{LEAGUE_ID}?view=mTeam`
  (`view=mRoster` for roster/player data instead of team/standings info).
- **Both leagues drafted on 2026-08-30.** A reminder is scheduled (via `send_later`,
  trigger_id `trig_01D32Bp8wAH831auxR7oFs1x`, fires 2026-08-31 02:00 UTC / ~9pm CT on the 30th)
  to check whether the drafts happened and, if so, pull both post-draft rosters
  (`view=mRoster`, team id=1) and run them through the crosswalk/valuation pipeline the same way
  as the Sleeper rosters above (ESPN IDs already resolve via `db_playerids.csv`'s `espn_id`
  column — no extra join work needed).

## FantasyPros v2 API (added 2026-08-19, key issued to Ian — needs local runner like Yahoo)
Ian has a FantasyPros v2 public API key (issued directly to his account — **not recorded in this
doc**, since project docs are org-visible; he's holding it locally and it should be treated like a
password/credential, same guidance given for the Sleeper password mix-up and the Yahoo client
secret earlier in this project). Full docs: `https://api.fantasypros.com/public/v2/docs`.

**Auth**: header `x-api-key: <key>`. **Base URL**: `https://api.fantasypros.com/public/v2/json/
{sport}/...`.

**Same network wall as Yahoo, confirmed this session**: `api.fantasypros.com` is unreachable from
this sandbox's Bash (blocked at the network level, same as the other fantasy-platform domains),
and — unlike Sleeper — WebFetch can't work around it here either, because the API requires a
custom `x-api-key` header and WebFetch has no way to attach custom headers (confirmed: an
unauthenticated WebFetch hit returned a plain 403). **This one has to run on Ian's own machine
too**, same pattern as Yahoo.

**Endpoints most relevant to this project** (all under `/nfl/...`, full parameter list in the
live docs):
- `/nfl/injuries?year=YYYY&week=N` — injury status, practice-report detail, and a numeric
  `probability_of_playing` per player. Nothing else in this pipeline has real injury data yet —
  this fills a real gap for weekly lineup/trade advice.
- `/nfl/{season}/consensus-rankings?position=X&scoring=STD|PPR|HALF` — expert-level consensus
  rankings with tier, `rank_ecr`, and (usefully) `player_yahoo_id`/`cbs_player_id` embedded per
  player, so it cross-references cleanly against the `dynastyprocess` crosswalk already in place.
  This is a cleaner, official, non-scraped equivalent of the `db_fpecr_latest.csv` snapshot the
  buy-low/sell-high model currently runs on.
- `/nfl/{season}/player-points?position=X&scoring=Y&start=W&end=W` — actual fantasy points scored
  per player, by week range. This is the piece that's been missing to compute real PPG trend data
  (rather than proxying momentum through ECR movement) — directly useful if the breakout/fall-off
  methodology's PPG-based features ever get rebuilt (see that section above).
- `/nfl/players?ecr=included&external_ids=yahoo:espn:cbs` — player metadata with cross-platform
  IDs bundled in one call, another possible crosswalk source.

Starter script delivered to Ian as `fantasypros_pull_example.py` — reads the key from an
`FANTASYPROS_API_KEY` env var (not hardcoded), hits injuries + consensus-rankings + player-points
as a smoke test. **Not yet run or verified against live data** (can't be, from this session) —
next step is Ian running it locally and confirming the shape of what comes back, then wiring the
output into the existing crosswalk/valuation pipeline the same way the Yahoo/ESPN data will be.

## Still-open next step
Combining the lightweight arbitrage signal with the real breakout/fall-off model (once/if that
gets rebuilt) would be the strongest version of this: cheap-by-market AND flagged as a
high-probability breakout/bounce-back by the validated model is a much stronger buy-low case than
either signal alone. Not built; flagged for whoever picks this up next. The FantasyPros API's
`player-points` endpoint (see above) is a promising building block for that rebuild, since it
provides real per-week fantasy points without needing to re-derive them from nflverse play-by-play.
