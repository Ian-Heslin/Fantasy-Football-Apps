# Coaching & offense research

Exploratory analysis, not pipeline. Most of what's in here ran once,
produced a CSV or a workbook, and was superseded by the next iteration —
the numbered filenames (`build_analysis2.py`, `build_analysis3.py`,
`build_workbook4.py`, `01_team_ranks.py` … `17_superstar_rate_combined.py`)
record the order they were written in, not an order to run them in.

This note exists because none of that is visible from the filenames, and
a future session shouldn't have to open sixty scripts to find out which
handful still matter.

## What the live site depends on

The web app never runs anything in this directory. It reads DuckDB
tables that `scripts/load_coaching_and_offense.py` loads **from the CSVs
committed here** — so the CSVs are the live dependency, not the scripts
that made them. Regenerating one means re-running its builder and then
re-running that loader.

Six tables, and the script that actually writes each CSV (verified by
following `to_csv` / `open(..., 'w')`, not by which files mention the
name — most of the mentions are reads):

| CSV | Written by | Table | Read by |
| --- | --- | --- | --- |
| `coach_effects/coach_table.csv` | `coach_effects/build_coach_table.py` | `coach_table` | `/coaches`, `/teams` |
| `offense_analysis/team_offense_ranked.csv` | `offense_analysis/01_team_ranks.py` | `team_offense_season` | `/coaches`, `/teams` |
| `offense_analysis/team_primary_qb_id.csv` | `offense_analysis/07_primary_qb_by_id.py` | `team_primary_qb` | `/teams` |
| `offense_analysis/player_season_with_offense_rank.csv` | `offense_analysis/05_player_offense_resilience.py` | `player_offense_rank` | — |
| `offense_analysis/all_coach_tenure_segments.csv` | `offense_analysis/08_all_coach_segments.py` | `coach_tenure_segments` | — |
| `offense_analysis/vegas_vs_offense.csv` | **nothing in this repo** | `vegas_odds` | `/teams` |

Two things worth knowing about that table:

- **`vegas_vs_offense.csv` has no producer here.** Every script that
  names it reads it (`add_data_sheets.py:123`). It arrived from outside
  the repo and can't currently be regenerated — if it's ever lost or
  needs extending, that's a script to write, not to find.
- `build_coach_table.py` writes to a hardcoded `/tmp/pfr/...` path
  rather than to this directory, so its output has to be copied into
  place by hand after a run.

## Everything else

The numbered `build_analysis*.py` series, the rest of the numbered
`offense_analysis/NN_*.py` series, the `add_data_sheets*.py` and
`build_workbook[2-4].py` variants, and the one-off inspection scripts
(`inspect_top.py`, `shanahan_detail.py`, `fix_ryan.py`, `toplists.py`)
are all superseded.

They're kept because `docs/breakout-falloff-methodology.md` cites their
findings by version number and the workbooks they produced are still in
`data/`. They are not expected to run against the current schema and
shouldn't be treated as maintained code. If one turns out to be worth
keeping, promote it into `scripts/`, where the maintained loaders live.
