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

## `rb_carries_superstar_falloff.py`

Follow-up to the above, two refinements: (1) rushing **carries** only, not
touches -- isolates leg-wear specifically from receiving work; (2) a
tighter 250-299 vs. 300+ carries comparison, run twice -- once across all
RB seasons, once restricted to seasons where the back was already
Superstar-tier or better (`tier_score >= 4`) that year.

**Finding: same direction, no longer significant.** All RB seasons:
300+ carries still declines less than 250-299 (PPG -14.5% vs -16.4%; <=9
games missed 13.0% vs 16.3%) but p=0.64/0.46 -- narrowing from 200-249 to
250-299 shrinks the true gap along with the sample, since 250-299-carry
backs are already a fairly established, bell-cow-ish population
themselves, not the more mixed committee/timeshare group that sat in
200-249. Superstar+-only (n=80 vs n=52): same direction again (PPG -17.1%
vs -20.6%) but same story, p=0.50. Read: the original 200-249-vs-300+ gap
was real and driven by contrasting a stable-workhorse population against a
noisier one; once both buckets already are workhorses (or already are
elite producers), there's less contrast left to detect at this sample
size -- consistent with, not a contradiction of, the original finding.

Run `python3 analysis/rb_carries_superstar_falloff.py` to reproduce --
writes `rb_carries_superstar_falloff_rows.csv` and prints every
Superstar+/League-Winner RB season at 250+ carries with its next-season
outcome.
