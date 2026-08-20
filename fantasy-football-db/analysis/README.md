# Ad-hoc research

One-off analysis questions run against the existing databases -- not part
of the regular data-load/model pipeline in `scripts/`, but kept here (with
their row-level output) so a finding can be checked or re-run later rather
than living only in a chat transcript.

## `rb_touches_falloff.py`

Question: do RBs with a ~300-touch season (rushing attempts + receptions)
decline more the following year than backs with a lighter 200-249 touch
season? Are they more likely to miss significant time?

**Finding: no -- the opposite.** Across 2,558 RB seasons since 2001, RBs
coming off 300+ touches saw PPG fall 15.2% on average the next season vs.
24.3% for the 200-249 touch group (p = 0.012, Welch's t-test), and missed
significant time (<=9 games) far less often: 14.3% vs. 26.8% (p = 0.001).
Likely explanation: reaching 300 touches is itself a filter for
health/role security/offensive stability, all of which also predict a
decent following season -- not evidence that heavy usage is harmless in
general. Full write-up, charts, and caveats (no real injury data, touches
correlate with talent/offense quality, the total-points version of this
comparison is directional but not conclusive at p=0.176) in the published
report.

Run `python3 analysis/rb_touches_falloff.py` to reproduce -- reads
`player_stats_season`/`player_offense_rank`/`player_bio` from
`analytics.duckdb`, writes `rb_touches_falloff_rows.csv` (row-level
dataset, one row per RB-season with its bucket, current/next-season
PPG/points/games, and whether it "vanished" from the data the next season).
