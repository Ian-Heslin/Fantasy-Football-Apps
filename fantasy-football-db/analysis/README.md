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

Follow-up to the above, three refinements: (1) a tighter 250-299 vs. 300+
comparison (narrower than the original 200-249 vs. 300+); (2) run twice --
once across all RB seasons, once restricted to seasons where the back was
already Superstar-tier or better (`tier_score >= 4`) that year; (3) run
under BOTH rushing **carries** only (isolates leg-wear from receiving
work) and total **touches** (carries + receptions, the original report's
definition), side by side.

**Finding: same direction under carries, no longer significant; touches
gets noisier still, and flips sign in the smallest cut.** Carries, all RBs
(n=115 vs 147): 300+ still declines less (PPG -14.5% vs -16.4%, p=0.64).
Carries, Superstar+ only (n=80 vs 52): same direction (-17.1% vs -20.6%,
p=0.50). Touches, all RBs (n=217 vs 195): same direction again but flatter
(-15.2% vs -16.9%, p=0.62). Touches, Superstar+ only (n=133 vs 55): flips
-- 300+ touches declines *slightly more* than 250-299 (-19.1% vs -17.2%,
p=0.73) -- though at that p-value it's indistinguishable from no
difference either way, not a real reversal.

Read: none of these narrower cuts reach significance in either direction.
The original 200-249-vs-300+ gap was real (p=0.012/0.001) because it
contrasted a genuinely different, noisier population (committee/timeshare
backs) against true workhorses. Once both buckets are already heavy
workloads -- or, further, already elite production -- there's little real
contrast left to detect at these sample sizes, and which way the point
estimate leans stops meaning much.

Run `python3 analysis/rb_carries_superstar_falloff.py` to reproduce --
runs both metrics automatically, writes `rb_carries_superstar_falloff_rows.csv`
and `rb_touches_superstar_falloff_rows.csv`, and prints every Superstar+/
League-Winner RB season at 250+ carries or touches with its next-season
outcome.
