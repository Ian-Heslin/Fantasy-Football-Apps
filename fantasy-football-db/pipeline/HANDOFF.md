# Fantasy Football Data Pipeline — Handoff Notes

Compiled 2026-08-19 from a Cowork/Claude session, for continuation in Claude Code (or any other
session). This covers everything built and learned across the conversation: four fantasy
platform integrations (Sleeper, ESPN, Yahoo, FantasyPros), a player-ID crosswalk, a dynasty
valuation pipeline, and a lightweight buy-low/sell-high signal.

**This project also has a Claude.ai Project** ("Fantasy Football") with three docs that are the
primary source of truth and should be read first if accessible:
- `claude/sleeper-and-trade-value-pipeline.md` — the fuller version of everything in this handoff
- `claude/breakout-falloff-methodology.md` — a separate, much deeper statistical project (25
  years of NFL data, trained breakout/bounce-back prediction models) whose *methodology* is
  documented but whose *output data files* no longer exist anywhere (see below)
- `claude/sleeper-and-trade-value-pipeline.md` also covers the ESPN/Yahoo/FantasyPros sections

This handoff file + the attached scripts/data are a portable snapshot in case that Project isn't
reachable from wherever this lands.

## The goal
Ian plays fantasy football across multiple platforms (5 Sleeper leagues, 2 ESPN leagues, at least
1 Yahoo league) and wants Claude to pull league-specific data (rosters, standings, values) and
eventually generate trade advice — specifically, comparing dynasty market value against some
notion of "who's actually good" to find buy-low/sell-high trade targets.

## Critical environment fact, learned the hard way
**None of the fantasy platforms' API domains (`api.sleeper.app`, `fantasysports.yahooapis.com`,
`api.login.yahoo.com`, `fantasy.espn.com`, `api.fantasypros.com`) are reachable via direct
outbound HTTP requests (curl/Python requests/etc.) from a standard cloud sandbox** — this was
confirmed repeatedly, including bypassing proxy env vars, so it's a real network-level block, not
a proxy config quirk. If you're running this in a similarly sandboxed environment, expect the
same wall. If you're running locally on a real machine (which is the plan for Yahoo/FantasyPros
below), this isn't an issue at all.

**Two workarounds were found for the sandboxed case:**
1. `lm-api-reads.fantasy.espn.com` (a specific ESPN subdomain, NOT `fantasy.espn.com` itself,
   which is blocked by robots.txt for fetch-style tools) is reachable via a generic web-fetch
   tool for public leagues. `api.sleeper.app` was also reachable that way.
2. Yahoo and FantasyPros were NOT fetchable this way — Yahoo's OAuth needs a POST request (fetch
   tools are typically GET-only), and FantasyPros needs a custom `x-api-key` header that fetch
   tools can't attach. Both need a real script run in a real environment (local machine, or here
   in Claude Code if it has genuine outbound network access — worth testing first).

## Platform-by-platform status

### 1. Sleeper — fully working, data pulled
- Public, read-only, **no auth at all**. Base: `https://api.sleeper.app/v1/...`
- Ian's Sleeper username: `authorzed`, user_id `412300641516400640`.
- His 5 leagues (league_id / name / season / format / his roster_id):
  - `1389389302827339776` — Alumni Committee, 2026, pre-draft, 1QB, roster #9
  - `1313508869787389952` — Quarantine Dynasty, 2026, in season, Superflex, roster #5
  - `1313201033589035008` — (unnamed, shows "TBD"), 2026, in season, Superflex, roster #6
  - `1312127342742614016` — Wisco Dynasty, 2026, in season, 1QB, roster #3
  - `1180207743981412352` — D - 1, 2025 season, complete, Superflex, roster #2
- Full data cached in `data/leagues_summary.json` (league info, all owners, Ian's roster player
  IDs per league).
- **⚠️ Data-integrity lesson, important**: when a batch fetch had to relay a big multi-team roster
  table AND a separate player list in one response, it silently cross-contaminated data between
  two different leagues (wrong owner↔roster_id mapping in one case, an entirely wrong player list
  in another). Both bad pulls looked completely normal — nothing signaled they were wrong. It was
  only caught because Ian spot-checked and said "I don't have [that player]." **Lesson: always
  spot-check roster pulls against something the user can verify, and prefer one targeted
  fetch-per-roster over parsing a big multi-team table out of one response.** This is fixed in
  the current `leagues_summary.json`, but if you re-pull, fetch one roster at a time.

### 2. ESPN — fully working (both leagues are public, no cookies needed)
- No official API; using the well-known unofficial endpoints. Since both of Ian's leagues are
  public, no `SWID`/`espn_s2` cookies are required.
- `lm-api-reads.fantasy.espn.com` works; plain `fantasy.espn.com` API paths get blocked by
  robots.txt for fetch-style tools (may not matter if you have real curl access instead).
- URL pattern: `https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{YEAR}/segments/0/leagues/{LEAGUE_ID}?view=mTeam`
  (swap `view=mRoster` for roster/player data; same league ID works across seasons, e.g. 2025 vs
  2026 — confirmed).
- Ian's ESPN leagues (he's always `teamId=1`):
  - `1532978` — "The Deep's Dolphins" league, 8 teams. 2025 final record: 8-5 (3rd of 8).
  - `1062658` — "'72 Dolphins" league, 8 teams. 2025 final record: 3-10 (last).
  - **Both drafted 2026-08-30** — as of this handoff both were still pre-draft/empty rosters.
    A reminder was scheduled in the original session to check post-draft rosters; if that didn't
    fire wherever you are, you'll need to just re-pull `view=mRoster` for both league IDs above
    once the draft has happened.

### 3. Yahoo Fantasy Sports API — access requested, awaiting approval, NOT yet usable
- Wanted wrapper: `yfpy` (Python).
- **Registration changed recently** — the old "Installed Application" option is gone from
  `developer.yahoo.com/apps/create/`; it's now "OAuth Client Type": pick **Confidential Client**
  (needed for the Client Secret yfpy requires). Fantasy Sports access is **no longer a checkbox**
  on that page — it's a separate gated application at `sports.yahoo.com/developer/access/`,
  reviewed by Yahoo's Fantasy team with no published turnaround time.
- **Status**: Ian created the OAuth app ("Ian's Fantasy Tool") and submitted the access
  application. Waiting on Yahoo's approval — check with Ian on where this stands.
- Starter script: `yahoo_pull_example.py` (uses `yfpy`, needs `pip install yfpy`, needs to run
  wherever Ian has real network access — his own machine, or here if this environment has real
  outbound access). Needs his actual Yahoo league ID (from the league URL,
  `football.fantasysports.yahoo.com/f1/<league_id>`) filled in once he has it.
- His Yahoo player IDs will resolve through the same crosswalk (see below) once real data comes
  back — no extra join work needed.

### 4. FantasyPros v2 API — key issued, NOT yet run/verified
- Ian has an API key (do not ask him to paste it in chat again — treat it like a password; if you
  need it, have him set it as an env var, e.g. `FANTASYPROS_API_KEY`, and reference that rather
  than writing the key value anywhere in code/docs/chat).
- Docs: `https://api.fantasypros.com/public/v2/docs`. Auth: header `x-api-key: <key>`. Base:
  `https://api.fantasypros.com/public/v2/json/{sport}/...`.
- Most relevant endpoints:
  - `/nfl/injuries?year=YYYY&week=N` — injury status + practice reports + `probability_of_playing`
  - `/nfl/{season}/consensus-rankings?position=X&scoring=STD|PPR|HALF` — expert consensus
    rankings, tier, `rank_ecr`, and embedded `player_yahoo_id`/`cbs_player_id`
  - `/nfl/{season}/player-points?position=X&scoring=Y&start=W&end=W` — actual fantasy points
    scored per player per week (useful for computing real PPG trend data)
  - `/nfl/players?ecr=included&external_ids=yahoo:espn:cbs` — player metadata with cross-platform
    IDs
- Starter script: `fantasypros_pull_example.py` — reads key from env var, hits injuries +
  consensus-rankings + player-points as a smoke test. **Never actually run/verified against live
  data** — that's the first thing to do with this one.

## Player ID crosswalk + dynasty trade values (the core reusable asset)
`github.com/dynastyprocess/data` is a public GitHub repo (plain `git clone` works fine even where
the platform APIs themselves are blocked) that ships:
- `files/db_playerids.csv` — crosswalk of `sleeper_id`, `espn_id`, `yahoo_id`, `fantasypros_id`,
  `mfl_id`, `ktc_id`, etc. all pointing to the same player name/position/team. **This one file
  solves player-ID resolution across Sleeper, ESPN, and Yahoo simultaneously.**
- `files/values.csv` — consolidated dynasty trade values (FantasyPros ECR-derived), with both
  `value_1qb` and `value_2qb` (superflex) columns — this is the market-consensus trade-value
  substitute Ian wanted, joined to the crosswalk via `fantasypros_id == fp_id`.
- `files/db_fpecr_latest.csv` — current FantasyPros ECR snapshot across many ranking pages
  (dynasty vs. redraft, by format) — this is what the buy-low/sell-high signal below is built on.
  Should probably be replaced by the real FantasyPros API (see above) once that's wired up.
- Re-clone (`git clone --depth 1 https://github.com/dynastyprocess/data.git`) any time you need
  fresh data — it updates regularly.

Built from this: `data/player_crosswalk.json` (sleeper_id → name/position/team/dynasty values,
6,358 players, 685 with a matched trade value). Rebuild script: `build_crosswalk.py`.

`data/my_rosters_valued.csv` — Ian's own roster in every Sleeper league, resolved to real names
and valued with the correct 1QB/superflex column per league. Rebuild script: `value_rosters.py`.

## Buy-low / sell-high signal (lightweight, not the "real" model)
Ian originally wanted to combine dynasty value with a much deeper breakout/fall-off statistical
model that's documented in this project (`claude/breakout-falloff-methodology.md` — trained
logistic regression models, validated backtests, 25 years of nflverse data). **That model's
actual output files (scored predictions, tier cutoffs) no longer exist anywhere — they lived in
an earlier, now-gone ephemeral session.** Rebuilding it for real means re-pulling 25 years of
nflverse play-by-play and re-deriving tier cutoffs from scratch — a genuinely big undertaking, not
something to casually redo. Ian explicitly chose a lightweight substitute instead for now.

**Method**: for each rostered player, compare dynasty ECR percentile vs. redraft ECR percentile
(both from `db_fpecr_latest.csv`, correct 1QB/superflex format per league).
`gap = dynasty_percentile - redraft_percentile`.
- gap ≥ +0.15 → **BUY-LOW/HOLD** (dynasty market believes in him more than his current-season
  ranking does)
- gap ≤ -0.15 → **SELL-HIGH** (current production is outrunning his long-term dynasty price)
- else → fairly priced

Scripts: `build_comparison_model.py` (builds `data/arbitrage_signal.json`) and
`trade_signals.py` (joins onto Ian's rosters, outputs `data/trade_signals.csv`).

**Known limitation**: this was run in the preseason (2026-08-14, before any 2026 games), so
dynasty and redraft rankings track closely for established players — almost every signal that
fired was a rookie/prospect (real dynasty-vs-redraft uncertainty) or a deep-bench/droppable player
(not a real trade asset), not a genuine performance-vs-price gap yet. **This should get much more
useful once the season is underway and redraft rankings start moving on actual results** — worth
re-running every few weeks in-season. The FantasyPros API's `player-points` endpoint (once wired
up) would be a real upgrade over this ECR-based proxy.

## Immediate next steps, roughly in priority order
1. **Check whether Ian's ESPN drafts (2026-08-30) have happened** — if so, pull post-draft
   rosters (`view=mRoster`, teamId=1, both league IDs above) and run through
   `build_comparison_model.py`/valuation the same way as Sleeper.
2. **Check on Yahoo's API approval status** with Ian — if approved, get his league ID and run
   `yahoo_pull_example.py` (needs `pip install yfpy`; needs real network access).
3. **Run `fantasypros_pull_example.py`** (needs `pip install requests`, `FANTASYPROS_API_KEY` env
   var, real network access) and confirm the data shape, then wire its output into the crosswalk/
   valuation pipeline in place of the scraped `db_fpecr_latest.csv`.
4. **Longer-term**: combine the buy-low/sell-high signal with the breakout/fall-off model
   (if/when that gets rebuilt) — cheap-by-market AND flagged as high-probability by a real
   predictive model is a much stronger buy-low case than either signal alone.

## Files in this handoff bundle
- `HANDOFF.md` — this file
- `build_crosswalk.py`, `value_rosters.py` — Sleeper → crosswalk → valued roster pipeline
- `build_comparison_model.py`, `trade_signals.py` — buy-low/sell-high signal pipeline
- `yahoo_pull_example.py` — Yahoo starter script (yfpy), not yet run
- `fantasypros_pull_example.py` — FantasyPros starter script, not yet run
- `data/leagues_summary.json` — all 5 Sleeper leagues, owners, Ian's roster IDs per league
- `data/player_crosswalk.json` — sleeper_id → name/position/team/dynasty value crosswalk
- `data/arbitrage_signal.json` — dynasty-vs-redraft percentile gap per player, by format
- `data/my_rosters_valued.csv` — Ian's Sleeper rosters, named and valued
- `data/trade_signals.csv` — buy-low/sell-high labels for every rostered player

None of these scripts re-fetch dynastyprocess/data automatically — re-clone
`https://github.com/dynastyprocess/data.git` fresh before rerunning `build_crosswalk.py` or
`build_comparison_model.py` if the cached data here feels stale.
