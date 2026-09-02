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

## `analyze_draft_reaches.py`

Question: do players drafted well above their pre-draft grade ("reaches")
underperform relative to realistic peers (others drafted in the same slot
range that year), and are some teams/coaches better at making reaches work
anyway -- specifically, does Kyle Shanahan's reputation for reaching at WR
and having it pan out hold up?

Method: rank every graded prospect by NGS draft grade within their year,
match to actual `draft_picks` by normalized name + position, re-rank by
actual pick number, `reach_score = grade_rank - actual_rank`. Outcome
(weighted career AV) is compared against same-year peers within +/-32
picks, not the whole league, so the comparison isn't just "early picks are
better." Full method in the script's docstring.

**Finding: reaches underperform on average, and Shanahan is a real, modest
exception.** Across 2,739 matched players (2006-2025), `correlation(reach_score,
AV vs. same-slot peers) = -0.094` -- weak but real, and consistent in the
group comparison: big reaches (reach_score >= 32, n=337) averaged -1.81 AV
vs. peers; players who matched-or-fell (reach_score <= 0, n=1,374) averaged
+2.13. League-wide, Kyle Shanahan is a genuinely aggressive drafter overall
(45 picks, avg reach_score +8.8, one of the largest in the league) whose
reaches come out close to break-even (-0.69 AV vs. peers on his 27 reaches
-- much better than most equally-aggressive reachers, e.g. Bill Belichick
at -6.66 or Jack Del Rio at -12.16). Restricted to just his WR picks
(n=12), the reach is actually mild (avg reach_score +2.9, not a large jump)
and the outcome is slightly below peers (-0.73 AV vs. peers) -- not the
"reaches that consistently pan out" story, but not a bad outcome either;
the more defensible version of the reputation is "reaches aggressively
overall and it costs him less than it costs most equally aggressive GMs/
coaches," not "reaches specifically at WR and it works."

**GM-level attribution** (via `team_executives_season`, Wikipedia-sourced
through Claude/Cowork -- this sandbox can't reach Wikipedia directly)
tells a consistent story with the HC finding above: John Lynch (the
49ers' GM throughout Shanahan's tenure) is similarly aggressive (48
picks, avg reach_score +9.6) with a near-break-even outcome on his
reaches (-0.65 AV vs. peers) -- the same "reaches a lot, costs him less
than most" pattern, which is a reasonable cross-check that the HC and GM
attribution are joining correctly (same era, same franchise, same
signal). Elsewhere: Trent Baalke (48 picks, avg reach_score +11.9) is
both aggressive and costly on his reaches (-5.89 AV vs. peers) --
matching his reputation as one of the more criticized GMs of that era;
Thomas Dimitroff (44 picks) is on the other end, muted reaching
(avg reach_score +1.6) with reaches that outperformed peers (+8.98 AV).

**Known caveat**: `draft_picks`' team codes are PFR-style (`SFO`, `GNB`,
`KAN`, ...); this script normalizes them (`TEAM_CODE_MAP`) to this
project's standard codes before joining against `coach_table`/
`team_executives_season` -- without that, every relocated/renamed
franchise (including SF/Shanahan/Lynch) silently drops out of both the
HC- and GM-level results.

Run `python3 analysis/analyze_draft_reaches.py` to reproduce -- reads
`draft_prospect_grades`/`draft_picks`/`coach_table`/`team_executives_season`
from `analytics.duckdb` (needs `scripts/load_draft_grades.py`,
`scripts/load_draft_picks.py`, and `scripts/load_team_executives.py` run
first), writes `draft_reach_player_level.csv` (every matched player, one
row each), `draft_reach_by_team.csv`, `draft_reach_by_coach.csv`, and
`draft_reach_by_gm.csv`.
