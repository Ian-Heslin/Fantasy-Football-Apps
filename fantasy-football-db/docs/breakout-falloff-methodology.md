# Fantasy Football Breakout/Fall-off Analysis — Methodology (v18: Top-Offense Consistency & Superstars)

(v1-v5 history: rank-based -> PPG tiers -> tier-transition breakout/falloff events -> health score
with IR -> first weak bounce-back model (2021-2023 only, AUC 0.60). See below for full v1-v5 notes.)

## v6: Sample expansion, feature search, and first final model

### Sample expansion: 2001-2025 (not 2000)
Extended the fall-off dataset from 2020-2025 back to 2001-2025 (25 seasons instead of 6).
Season 2000 was tested and **excluded**: validating our hand-computed PPR fantasy points against
nflverse's own trusted `player_stats_season.csv` showed a 25.9% mismatch rate for 2000 vs. a
1.3-5.4% baseline for every year 2001+ (spot-checked on Marshall Faulk's 2000 line — extra
receptions/yards and phantom rushing 2-point conversions). This is a genuine nflverse data-quality
issue specific to that earliest reconstructed season, not a bug in our pipeline.

### Features tested and their fate
A wide range of candidate features were tested one at a time (each added to the running best
model, compared on the same sample via LOOCV AUC/accuracy and statistical significance):

- **Head coach turnover** (nflverse `nfldata/games.csv` home_coach/away_coach, aggregated to a
  team-season coach and compared year over year): **no predictive value, wrong-signed if
  anything**. Teams that fired their coach within 2 years of a player's fall-off actually
  bounced back *less* often (27.3% vs 36.4%, p=0.037 univariate) — plausibly because a coaching
  change usually signals a team already in disarray, not a fresh-start boost. Not significant
  once age/ppg_drop are controlled for (p=0.15). Dropped.
- **Team change** (player's team next season vs. fall-off season, from play-by-play
  posteam majority per player-season): real univariate signal (39.1% bounce-back if same team
  vs. 25.4% if changed teams, p=0.006; players who left the league entirely bounced back only
  3.75% of the time — a good sanity check). But collinear with ppg_drop (players who change teams
  already fell further, r=0.20) and added negligible marginal AUC once ppg_drop is in the model
  (0.578 -> 0.584 same-sample comparison). Dropped as a formal feature; kept as a documented
  finding.
- **Draft pedigree** (`players.csv` draft_round/draft_pick): the effect is **position-specific**,
  not universal. Pooled, a top-10-pick flag looked significant (odds ratio ~2.0, p=0.004,
  AUC 0.612->0.632) — but that was almost entirely a QB confound (53% of QB fall-off players
  were top-10 picks vs. 14-18% for RB/WR/TE, and QBs bounce back most regardless of pedigree).
  Split by position: top-10 pedigree is not significant for QB (p=0.83) or WR (p=0.82), but IS
  significant for RB (34.6% vs 19.9% bounce-back, p=0.047, holds even at n=26) — running backs
  are the one position where draft investment clearly buys a team's patience. A pooled
  RB-specific interaction term didn't survive re-pooling with the full sample (p=0.18,
  AUC flat), likely diluted by forcing shared age/ppg_drop slopes across positions at this
  sample size. Documented as a real secondary finding; not in the final model.
- **Games missed to injury** (fall-off-season games missed, from injury reports + IR/Reserve
  status via `weekly_rosters`): univariate significant (33.8% bounce-back if missed <=4 games vs.
  21.2% if >4, p=0.007; stays significant alongside age, p=0.001 in a 2-feature model) but not
  significant once position and ppg_drop are in the full model (p=0.20) — redundant with what
  position/ppg_drop already capture (RBs get hurt more AND bounce back less, for reasons beyond
  just games missed). Not in the final model, but now available as a column for reference.
- **Injury type (e.g. Achilles)**: **could not be tested — a real methodology gap, not just a
  data gap.** Zero Achilles tears appear anywhere in the fall-off/bounce-back data. Investigated
  why: Achilles tears are severe enough that they almost always drop a player under 4 games
  played, and the tier system labels any <4-game season "Uncategorized," which the original
  fall-off/bounce-back definition explicitly excludes from both sides of a transition. Every
  skill-position Achilles tear in the data (25 across 2000-2025) happened to a player who had
  *already* declined below Star tier the year before, so none could even qualify as a
  "Star player got hurt" case. This asymmetry is now partially fixed — see "Injury seasons as
  fall-offs" below — but injury-report data only exists from 2009 on and known-injury-type
  coverage even within that window is too thin (11 of 35 severe-injury cases) to break out
  bounce-back rate by specific injury type with any statistical confidence.
- **Offensive line quality proxy**: PFF-style O-line grades are paywalled with no free historical
  export, and every free O-line "ranking" source found (PlayerProfiler, FTN, FantasyPoints, PFF's
  own site) is current-year subjective commentary, not a machine-readable time series back to
  2000 — same dead end as the coaching-staff search. Built a real proxy instead, entirely from
  play-by-play, covering all 32 teams every season 2000-2025: **pass-block grade** = inverse
  percentile rank of sack rate allowed per dropback; **run-block grade** = inverse percentile
  rank of run-stuff-rate allowed (runs for <=0 yards); combined into an overall 0-100 O-line
  grade per team-season. Sanity-checked against 2024 public perception (correctly ranks
  Packers/Cardinals/Ravens at the top, Browns/Chargers/Texans at the bottom). Directionally
  correct in the model (better O-line -> more likely to bounce back) with run-block grade closer
  to significance (p=0.088-0.11) than pass-block (p=0.56), but neither reaches significance, and
  an RB-specific interaction (parallel to the draft-pedigree pattern) was flat (p=0.74). Kept as
  a documented secondary signal, not in the final model. Available as columns
  (`pass_block_grade`, `run_block_grade`, `oline_grade`) for future work.
- **Tier-split vs. continuous "how big a star" (the key breakthrough)**: user's hypothesis that
  the fixed point-total cutoffs were adding noise by treating "barely cleared Star" and "League
  Winner" as the same population turned out to be correct. Splitting fall-offs into two separate
  models (Star-tier-only vs. Superstar+/League-Winner-only) improved fit on both halves
  (pseudo R² 0.085 pooled -> 0.103 Star-only / 0.129 Superstar+-only; AUC 0.674 -> 0.685-0.694).
  But the fully continuous version won outright: replacing the categorical prior tier with
  **`prior_ppg_above_star`** — the player's prior-season PPG minus their position's Star cutoff,
  a single continuous number instead of a Star/Superstar/League-Winner label — outperformed even
  the tier-split approach while using the FULL sample (no splitting needed). Highly significant
  (p<0.0001) with no interaction effect against ppg_drop (p=0.97, dropped) — the two effects
  (how big a star you were, how far you fell) are additive, not multiplicative.
- **Injury seasons as fall-offs (definitional fix)**: found 35 cases of "Star+ tier, then <4 games
  played the very next season" — a pattern the original definition couldn't see at all, since
  <4-game seasons are "Uncategorized" and excluded from both sides of a tier transition. Cross-
  checked each against IR/injury-report data (`weekly_rosters` status + injury reports) and
  required at least 40% of that season's missed games be injury/IR-attributed before counting it
  as a genuine injury fall-off — this correctly excluded non-injury cases like Adrian Peterson's
  2014 suspension and Antonio Brown's 2019 release (both had 0% injury-attributed missed games).
  20 of the 35 passed the threshold and are now included as fall-off events (bounce-back rate
  among them: 30%, close to the standard population's 30.2%). Total fall-off events: 567
  (547 standard + 20 injury), stored in `falloffs_v3_enriched.csv`.

## v7: Career track record and repeat-bounce-back history

Two more candidate features, prompted by a specific question: does it matter how long a player
had been a star before falling off, and does having already bounced back once make a repeat more
predictable?

- **`years_star_streak`** (consecutive seasons immediately before the fall-off where the player
  was Star-or-higher): **real, kept in the model.** Not significant alone (p=0.16 univariate,
  point-biserial correlation only 0.06) — it's confounded with `prior_ppg_above_star`, since a
  long streak usually also means a bigger star. But once age/ppg_drop/prior_ppg_above_star/
  position are already controlled for, it comes through clearly (p=0.005, odds ratio 1.22 per
  additional consecutive year at Star+). Added to the model, LOOCV AUC improved 0.736 -> 0.747
  and pseudo R² 0.141 -> 0.153.
- **`prior_bounce_backs`** (count of times this player has already fallen off and returned to
  Star+ before the current event): **directionally right, not statistically confirmed.**
  Coefficient is positive (odds ratio ~1.27, more prior bounce-backs -> somewhat higher odds of
  doing it again) but not significant in any tested combination (p=0.25-0.73) — only 31 of 567
  fall-off events involve a player with 1+ prior bounce-back, and just 8 with 2+, too thin a
  sample to say anything with confidence. Not in the final model; available as a column.
- **Worked example (the question that prompted this)**: does Christian McCaffrey having already
  bounced back before make his next one "safer" to predict, and does Lamar Jackson's long run as
  a star do the same? CMC genuinely fits: he has two real fall-off events in this data (a 2020
  confirmed-injury season, a 2024 standard fall-off) and returned to Star+ from both, so his 2024
  event correctly carries `prior_bounce_backs=1`. Lamar Jackson does **not** fit the same
  pattern, despite looking like he should: year-by-year he was League Winner/Superstar/Star
  continuously from 2019 through 2024 (dipping only to Star, never below, even in his
  injury-shortened 2021-2022 seasons) — so his 2025 season is his **first-ever fall-off** in this
  dataset (`prior_bounce_backs=0`). What actually raises his predicted probability is
  `years_star_streak=6`, the longest active streak among any 2025 fall-off — a career-durability
  signal, not a repeat-recovery signal. The two ideas are related but distinct, and only the
  track-record one held up statistically at this sample size.

### Final model (v7)
**Features**: age (fall-off season), `ppg_drop` (prior-season PPG minus fall-off-season PPG),
`prior_ppg_above_star` (prior-season PPG minus the player's position-specific Star cutoff),
`years_star_streak` (consecutive years Star-or-higher immediately before falling off), and
position dummies (RB/TE/WR vs. QB as reference).

Trained on 509 fall-off events, season <= 2023 (clean/mostly-resolved labels):

| Feature | Coefficient | p-value | Odds ratio |
|---|---|---|---|
| age | -0.160 | <0.001 | 0.852 (each added year of age cuts bounce-back odds ~15%) |
| ppg_drop | -0.277 | <0.001 | 0.758 (each additional PPG of drop cuts odds ~24%) |
| prior_ppg_above_star | +0.356 | <0.001 | 1.427 (each PPG above the Star cutoff raises odds ~43%) |
| years_star_streak | +0.199 | 0.005 | 1.220 (each consecutive year at Star+ raises odds ~22%) |
| position: RB (vs. QB) | -2.107 | <0.001 | 0.122 |
| position: TE (vs. QB) | -1.837 | <0.001 | 0.159 |
| position: WR (vs. QB) | -1.154 | 0.001 | 0.315 |

**Performance**: Pseudo R² 0.153, LOOCV AUC **0.747**, LOOCV accuracy 73.3% vs. 67.4% baseline
(always guess majority class). Progression across the whole project: age+EPA+ppg_drop only
(AUC 0.60) -> + position (0.674-0.675) -> + continuous star-distance (0.736) -> + career streak
(0.747).

**Note on EPA/touch**: tested throughout the session as a candidate feature; never reached
significance (p ranged 0.12-0.68 across every model version) despite being theoretically
appealing (a "true talent" signal independent of role/opportunity). Dropped from the final model.

### Backtest: 2023 and 2024 fall-offs, predicted walk-forward (no data leakage)
To honestly test real-world performance, two separate models (v7 feature set) were trained using
ONLY data available before the season being predicted (season <= 2022 to predict 2023;
season <= 2023 to predict 2024), then scored against what actually happened.

**2023 fall-offs (n=24, actual bounce-back rate 41.7%)**: accuracy 50.0%, AUC 0.607.

**2024 fall-offs (n=25, actual bounce-back rate 20.0%)**: accuracy 60.0%, AUC 0.500.

**Honest read**: on these two small (24-25 player) real held-out seasons, the model performs
close to a coin flip despite the strong 0.747 pooled LOOCV AUC on the full 25-year sample. This
is a meaningful caveat, not a contradiction — LOOCV AUC reflects average ranking ability pooled
across ~500 events; any single season is a small, noisy draw (the actual bounce-back rate itself
swung from 41.7% in 2023 to 20.0% in 2024, a sign of how much single-year variance exists in the
target itself). The model should be read as a genuine but modest edge over guessing, most
trustworthy in aggregate/relative ranking across many players and seasons, not as a confident
single-season forecasting tool. Full player-by-player predicted-vs-actual detail (including which
specific players the model got right and wrong) is in the delivered workbook's Bounce-back Model
sheet.

**2025 fall-offs (n=33)**: pure forward-looking predictions (model trained on season <= 2024;
outcome not yet knowable — would need the 2026 season to resolve). Highest predicted bounce-back
probability: Lamar Jackson (84.5%), Jayden Daniels (75.1%), Malik Nabers (69.4%), Joe Burrow
(68.4%), Jared Goff (60.5%).

Full scored table (all fall-off events, features, predicted probability, and actual outcome where
known): `falloffs_scored_final_v3.csv` and `falloff_predictions_2023_2025_v2.csv` in the working
session — available in the delivered workbook's Fall-offs and Bounce-back Model sheets.

## v8: Breakout model (Starter-or-lower -> Star-or-higher)

Same overall approach as the bounce-back model, applied to the mirror-image event: a player at
Starter tier or below (or a rookie / not yet in the league) moving up into Star tier or higher,
counted once per career (`breakout_used`). Candidate pool: player-seasons below Star tier with
>=8 games played and meaningful volume (QB: >=100 dropbacks; RB/WR/TE: >=30 touches), season
2001-2024 (needs a following season to score), 3798 total rows across positions (QB 512, RB 1099,
WR 1677, TE 510). Overall breakout-next-year rates: QB 7.4%, RB 7.9%, WR 6.1%, TE 10.8%.

### Features tested and their fate

- **EPA/touch (or EPA/play for QB)**: the starting hypothesis — does elite per-play efficiency
  below Star tier predict a breakout? Real signal on its own, but weaker than PPG-based features
  once combined; strongest for RB (synergizes with opportunity, see below).
- **PPG before breakout**: players who eventually broke out to Star+ were not typically miles
  below the cutoff the year before — most breakouts come from players already producing close to
  Starter-tier ceiling, not out of nowhere. This motivated the same continuous "distance from
  cutoff" trick used in the bounce-back model: **`ppg_above_starter`** = current-season PPG minus
  the player's position-specific Starter cutoff, replacing categorical tier as a continuous
  breakout predictor. Highly significant for every position (p<0.0001 for WR/TE, p<0.001 for QB;
  the one exception is RB, where it loses significance once `position_share` and `epa_per_touch`
  are also in the model — see below).
- **Coaching change**: tested whether a change in head coach helps a player who hasn't broken out
  yet finally do so in a later season. **No effect** (p=0.998) — matches the identical null result
  found for the bounce-back model. Not used.
- **Team change**: tested whether changing teams predicts breaking out to Star+ or Superstar+,
  motivated by the idea that a change of scenery could mean a change of opportunity (especially
  for RBs). **Reversed from the hypothesis**: team-changers break out at *lower* rates than
  players who stayed, at every position (e.g. RB: 8.4% same-team vs. 4.1% changed-team for Star+,
  p=0.019). Plausible read: leaving a team is more often a signal of falling out of a good
  situation than finding a better one. Not used as a positive predictor.
- **`touches_increased`** (a player's touches going up the following season): strongly correlated
  with breaking out, but explicitly **rejected as a feature** because it isn't knowable in
  advance — it's contemporaneous with the very outcome being predicted (the same information
  problem as trying to predict a stock's return using next year's price). This correction from
  the user redirected the search toward genuinely pre-season-knowable opportunity signals.
- **`leading_back_departed`** (whether an RB's team's leading returning back, by touches, left the
  roster by the following season): a real, pre-season-knowable signal — predicts touches
  increasing (51.1% vs. 39.9%, p=0.001) but does **not** predict actual breakout (identical 7.5%
  rates, p=1.0). Important nuance: getting more volume from a vacancy is not the same as becoming
  a Star-tier producer. Not used in the final model, but a useful finding on its own — teams don't
  hand a breakout to whoever inherits the touches.
- **`position_share`** (a generalized opportunity/role metric — volume divided by team's total
  volume at that position that season; volume = touches for RB/WR/TE, dropbacks for QB): **the
  key finding of the breakout phase.** Strong univariate RB signal (corr 0.25, p<0.0001), roughly
  monotonic breakout rate by share (about 3% in the lowest bucket up to 27% in the highest).
  Collinear with `ppg_above_starter` (0.46 correlation pooled — expected, since PPG and touch
  share both track overall role — but the collinearity is strongest for RB specifically, 0.78).
  This collinearity meant `position_share` did **not** survive being forced into a single pooled
  cross-position model, even with an RB-specific interaction term (p=0.64-0.82 across variants,
  no AIC improvement) — the same "dilution when pooled" pattern already seen twice in the
  bounce-back model (RB draft pedigree, RB O-line run-block grade). Tested per position instead:
  significant for RB (p<0.001) and marginally for QB (p=0.09, inconsistent sign across model
  variants — flagged as unresolved below), not significant for WR or TE.

### Decision: separate per-position models, not one pooled model
Because `position_share`'s real effect is RB-specific (and marginal for QB) rather than universal,
and because this mirrors the earlier bounce-back-model lesson that position-specific effects get
diluted by shared coefficients in a pooled model, the breakout model uses **four independent
per-position logistic regressions** rather than one pooled model with position dummies. Feature
sets were chosen per position via systematic comparison (LOOCV AUC + AIC) across four candidate
combinations (age+ppg; +epa; +share; +epa+share). See v9 below for the updated final feature sets
(the QB and TE sets changed; RB and WR are unchanged from this original v8 pass).

## v9: Candidate history — repeat appearances and tier-climbing

Prompted by a specific observation: some players show up on the breakout-candidate list for
multiple years running before finally breaking out (or never do). Two questions were tested
against the full candidate pool: does simply being a repeat candidate raise or lower breakout
odds, and does a player's *trajectory* through the tiers (specifically, just climbing up into
Starter tier from Mid/Below-Replacement) predict a jump all the way to Star the following year.

### Repeat candidacy: mostly doesn't help, except for QB
Built `candidate_streak` (consecutive prior seasons a player was also a below-Star candidate,
walking backward from the current season) for every row in the pool. Pooled, raw breakout rate
actually **drifts down** the longer someone has been a candidate: 8.1% in a player's first year on
the list, 7.0% in year two, 6.6% at three-plus years. Controlling for age and
`ppg_above_starter`, `candidate_streak` is not significant pooled (coef +0.036, p not significant).

Split by position, this splits cleanly in two directions:
- **RB and WR**: coefficient trends negative (RB -0.050, WR -0.121) but neither reaches
  significance (p=0.67, p=0.26) — too much noise to call this a real penalty, but there is no
  supporting evidence for repeat RB/WR candidates being *more* likely to break out either.
- **QB**: coefficient is positive and **significant** (p=0.006) — a longer streak of showing up as
  a below-Star QB candidate genuinely raises the odds of eventually breaking out, even controlling
  for age and current PPG level. A plausible read: game-manager-tier QBs who keep getting
  reps season after season are quietly building toward a QB1 breakout in a way box-score PPG alone
  doesn't capture (extra reps, a stabilizing situation, etc.).
- **TE**: coefficient is positive but not significant (p=0.27, likely too correlated with the
  tier-climbing effect below to say anything independently at this sample size).

**Decision**: added `candidate_streak` to the QB model only. Not added to RB, WR, or TE — the
evidence doesn't support either a bonus or a penalty for repeat candidacy at those positions, and
adding a feature that isn't really there just adds noise to the model.

### Tier trajectory: does climbing into Starter predict jumping to Star the next year?
Tested the user's specific hypothesis — a player who just climbed from Mid/replacement or Below
Replacement Level *into* Starter tier this season (`reached_starter_by_climbing`) vs. everyone
else in the candidate pool. Broken out first by "any tier improvement at all" (moved up one or
more tier levels from the prior season, regardless of where they landed): univariately strong
(12.3% breakout rate for anyone who moved up a tier vs. 5.1% for anyone who didn't, chi-square
p<0.0001) but **this does not survive controlling for `ppg_above_starter` and age** (p=0.56 in
the controlled model) — moving up a tier is highly correlated with simply having a higher PPG
this year, which the model already captures.

The specific "just reached Starter tier by climbing" version is a different story entirely, and
splits sharply by position:

| Position | Breakout rate if just climbed into Starter | Breakout rate otherwise | p-value (univariate) |
|---|---|---|---|
| QB | 10.6% (n=47) | 6.3% (n=222) | 0.46 (not significant) |
| RB | 11.8% (n=49) | 6.1% (n=481) | 0.22 (not significant) |
| WR | 13.5% (n=126) | 4.6% (n=744) | **0.0002** |
| TE | **42.5%** (n=40) | 6.1% (n=180) | **<0.0001** |

TE is the standout: a tight end who just climbed into Starter tier from below broke out to Star+
the very next season **42.5% of the time**, seven times the base rate, and this isn't a fluke of
one or two seasons — it shows up steadily across two decades (Randy McMichael '03, Greg Olsen '08,
Zach Ertz '14, Austin Hooper '18, Tucker Kraft '24, and many more in between). Crucially, this
**survives controlling for age and `ppg_above_starter`** (coef +1.265, p=0.037) — it's adding real
independent signal, not just standing in for "already had a good PPG year," and it improves the
TE model's LOOCV AUC from 0.767 to 0.777 on the same subset.

WR shows the same direction and a highly significant univariate difference (13.5% vs. 4.6%,
p=0.0002), but **does not survive controlling for `ppg_above_starter`** (p=0.55 in the controlled
model, AUC actually ticks down slightly, 0.808 -> 0.804) — for wide receivers, climbing into
Starter tier isn't telling the model anything its PPG level doesn't already say. QB and RB show
the same positive direction but with far fewer climbers (47 and 49 respectively) and no
significance at either the univariate or controlled level — worth another look if the sample
grows, but not enough evidence to add today.

**Decision**: added `reached_starter_by_climbing` to the TE model only.

### Final model (v9)

| Position | Final features | Change from v8 |
|---|---|---|
| QB | age, ppg_above_starter, position_share, **candidate_streak** | added candidate_streak |
| RB | age, ppg_above_starter, epa_per_touch, position_share | unchanged |
| WR | age, ppg_above_starter | unchanged |
| TE | age, ppg_above_starter, **reached_starter_by_climbing** | added reached_starter_by_climbing (sample restricted to players with a prior-season row, n=232 vs. 510) |

**Full-sample coefficients (v9):**

| Position | age | ppg_above_starter | epa_per_touch | position_share | candidate_streak | reached_starter_by_climbing | pseudo R² |
|---|---|---|---|---|---|---|---|
| QB | -0.297 (p<0.001) | +0.350 (p<0.0001) | — | -2.400 (p=0.021) | +0.374 (p=0.002) | — | 0.163 |
| RB | -0.219 (p<0001) | +0.076 (p=0.27, n.s.) | +3.347 (p=0.004) | +4.185 (p<0.001) | — | — | 0.129 |
| WR | -0.299 (p<0.0001) | +0.438 (p<0.0001) | — | — | — | — | 0.216 |
| TE | -0.145 (p=0.17, n.s.) | +0.329 (p=0.062) | — | — | — | +1.265 (p=0.037) | 0.200 |

Adding `candidate_streak` also incidentally resolved part of the QB `position_share` sign
inconsistency flagged in v8 — it's now significant (p=0.021) at least, though still negative-signed,
which remains a bit counterintuitive and worth watching as more QB data accumulates.

### Backtest: 2023 and 2024 breakouts, re-run with v9 features
Same walk-forward methodology (train on seasons before the one being predicted, score the actual
outcome). **2023 breakouts**: AUC 0.768 (up slightly from v8's 0.759). **2024 breakouts**: AUC
0.830 (up slightly from v8's 0.822). Per position, the picture is mixed rather than uniformly
better — this is expected, since these are small position-season samples and single-season
noise cuts both ways:

| Position | 2023 AUC (v8 -> v9) | 2024 AUC (v8 -> v9) |
|---|---|---|
| QB | 0.692 -> 0.846 | 0.944 -> 0.944 (tied) |
| RB | 0.700 -> 0.700 (unchanged, no new features) | 0.677 -> 0.677 (unchanged) |
| WR | 0.858 -> 0.858 (unchanged, no new features) | 0.803 -> 0.803 (unchanged) |
| TE | 0.475 -> 0.542 | 0.870 -> 0.778 |

QB's 2023 result improved substantially with `candidate_streak` added. TE is genuinely mixed
single-season to single-season (small samples — 21-22 TE candidates per season — mean this is
expected noise, not a reason to doubt the pooled/controlled finding above). Coverage note: adding
`reached_starter_by_climbing` to the TE model means TE candidates in their very first season (no
prior-season row to compare against) can't be scored by that feature and drop out of the backtest
pool — 8 fewer candidates in 2023, 9 fewer in 2024, all across positions but concentrated in TE.

2025 forward-looking top predictions now feature several TEs near the top (Brenton Strange 50.5%,
AJ Barner 46.7%, Theo Johnson 40.9%, Colby Parkinson 38.4%) alongside Jaxson Dart (49.0%) — a
direct consequence of the new TE climbing feature, several of whom climbed into Starter tier in
2024 and are TE candidates worth watching into 2026.

Full scored table (all breakout candidates 2023-2025, v9 features, predicted probability, actual
outcome where known): `breakout_backtest_scored_v2.csv` in the working session. Candidate-history
features (streak, tier trajectory) for the full 2001-2025 pool: `breakout_candidate_history.csv`.

## v10: Teammate and roster context

Prompted by three related questions: does having a Star-or-higher teammate at the SAME position
hurt a candidate's breakout odds (roster competition for touches/targets), does having a Star+
player ANYWHERE on the team help or hurt (team quality/scheme proxy), and do breakouts cluster --
do some teams see multiple players break out in the same year more than you'd expect by chance?

### Same-position Star+ teammate: real univariately, doesn't survive controlling for PPG
Built `teammate_star_same_position` (is there a Star-or-higher player at the same position, same
team, same season, excluding the candidate themselves). Pooled univariate effect is real: 5.5%
breakout rate with a same-position Star+ teammate vs. 8.3% without (chi-square p=0.0023). RB shows
the clearest position-level version (9.9% vs. 5.6%, p=0.012); WR is marginal (7.0% vs. 4.6%,
p=0.063); TE and QB show no meaningful signal (QB has only 6 candidates with a same-position
Star+ teammate -- backup QBs behind a Star+ starter rarely qualify as "candidates" at all under
the volume threshold). **Does not survive controlling for `ppg_above_starter`** at any position
(RB p=0.40, WR p=0.43) -- makes sense in hindsight, since a player stuck behind a star at their
own position already shows up with a lower PPG relative to the cutoff, which the model already
captures. Not added as a feature anywhere; the roster-competition effect is real but redundant
with what PPG-above-Starter already tells the model.

### Star+ player anywhere else on the team: no effect except a real, sizeable one for QB
Built `teammate_star_anywhere` (any Star-or-higher player anywhere on the roster, any position).
Pooled, no effect (p=0.45 univariate, not significant controlled). Per position, RB/WR/TE show
nothing (p=0.85, 0.98, 0.69 controlled). **QB is the exception, and the effect runs opposite to
the naive expectation**: QB candidates on a team with NO other Star+ talent anywhere broke out
12.0% of the time, vs. just 5.9% when the team already had a star elsewhere (p=0.0012 univariate,
p=0.0025 controlling for age/ppg_above_starter/position_share/candidate_streak). Read: this isn't
"weapons don't matter" so much as an opportunity story -- a QB stuck on a talent-poor, star-less
roster (often a rebuilding team) is more likely to be handed full control and forced into heavy
pass volume out of necessity, which is exactly the situation that produces a QB breakout (e.g. a
young or bad-team QB compiling volume stats because the offense runs through him by default,
rather than by merit alone). Added `no_other_star_on_team` to the QB model: LOOCV AUC improved
0.772 (v9 QB) -> 0.794 (v10 QB), a meaningful jump, and it remains significant (p=0.0025) even
with 4 other features already in the model.

### Do breakouts cluster by team?
Resolved each actual breakout event to the player's team in the season they broke out (not the
prior candidate season, since some players change teams in between) and counted breakouts per
team-season. Real, memorable examples exist: 2007 Patriots (Tom Brady + Wes Welker), 2015 Jaguars
(Blake Bortles + Allen Robinson + Allen Hurns), 2018 Rams (Jared Goff + Cooper Kupp + Robert
Woods), 2019 Ravens (Lamar Jackson + Mark Andrews), 2022 Cowboys (CeeDee Lamb + Tony Pollard).
46 team-seasons out of 234 that had at least one breakout actually had two or more (three
team-seasons -- 2002 Bills, 2015 Jaguars, 2018 Rams -- had three).

**Tested against a null model**: simulated 2000 seasons under the assumption that each candidate
breaks out independently at their own position's base rate (respecting how many candidates each
real team-season actually fielded). Under pure independence, the expected number of team-seasons
with 2+ breakouts is about 38 (95th percentile ~48); the observed 46 falls inside that range
(empirical p=0.10). **Verdict: breakouts do NOT statistically cluster by team beyond what each
position's individual base rate already predicts.** It's a fun pattern to point out in specific
seasons, but not something to build a "riding shotgun with a breakout" feature on -- the anecdotes
that stand out (Rams '18, Jaguars '15) are within the range chance alone produces once you have
enough team-seasons and candidates to look across. Not added as a feature.

### Final model (v10)

| Position | Final features | Change from v9 |
|---|---|---|
| QB | age, ppg_above_starter, position_share, candidate_streak, **no_other_star_on_team** | added no_other_star_on_team |
| RB | age, ppg_above_starter, epa_per_touch, position_share | unchanged |
| WR | age, ppg_above_starter | unchanged |
| TE | age, ppg_above_starter, reached_starter_by_climbing | unchanged |

**QB full-sample coefficients (v10):** age -0.263 (p=0.001), ppg_above_starter +0.413 (p<0.0001),
position_share -2.296 (p=0.031, still negative-signed -- same carryover flag as v8/v9), candidate_streak
+0.347 (p=0.002), no_other_star_on_team +1.257 (p=0.0025). Pseudo R² improved 0.163 -> 0.197. RB,
WR, and TE coefficients are unchanged from v9.

### Backtest: 2023 and 2024 breakouts, re-run with v10 QB feature
Pooled: 2023 AUC held at 0.768 (unchanged overall, but QB-specific AUC dipped from 0.846 to 0.769
on just 14 QB candidates -- noise at this sample size). 2024 AUC improved 0.830 -> **0.846**, and
QB-specific AUC hit a perfect 1.000 on the 9 QB candidates that season (Trevor Lawrence and Drake
Maye, the two 2024 QB breakouts, were correctly the two highest-ranked QB candidates). Full scored
table: `breakout_backtest_scored_v3.csv`. Roster-context features for the full pool:
`breakout_full_features.csv`. Team-clustering event list and simulation detail:
`breakout_team_clustering_events.csv`.

## v11: Draft pedigree

In the bounce-back model, draft pedigree (`players.csv` draft_round/draft_pick) only mattered for
RB and got diluted everywhere else when pooled (see v6 notes). Tested the same idea for the
breakout model, and it turns out to matter much more broadly here.

### Univariate: draft pedigree predicts breakout at every position
Merged `players.csv` draft_round/draft_pick onto the candidate pool by `gsis_id` (80.1% overall
coverage; undrafted players are filled to round 8 / pick 300 rather than dropped, since going
undrafted is itself a meaningful signal, not missing data). Two binary cuts were tested:
`top10_pick` (drafted in the top 10 overall) and `day3_or_undrafted` (drafted in rounds 4-7, or
not drafted at all).

Both are significant **univariately at every single position** -- a first for this model, since
almost every other feature tested throughout this project turned out to be position-specific:

| Position | Top-10 pick breakout rate | Not top-10 | p-value | Day 3/UDFA breakout rate | Day 1-2 | p-value |
|---|---|---|---|---|---|---|
| QB | 14.3% (n=154) | 4.5% (n=358) | 0.0002 | 3.5% (n=173) | 9.4% (n=339) | 0.024 |
| RB | 26.3% (n=19) | 7.6% (n=1080) | 0.010 | 5.6% (n=719) | 12.4% (n=380) | 0.0001 |
| WR | 18.9% (n=106) | 5.3% (n=1571) | <0.0001 | 2.1% (n=818) | 10.0% (n=859) | <0.0001 |
| TE | 42.9% (n=7) | 10.3% (n=503) | 0.032 | 6.2% (n=257) | 15.4% (n=253) | 0.0014 |

### Controlled: real for RB, TE, and especially WR; marginal for QB
Tested `top10_pick` and `day3_or_undrafted` (and a continuous `log(draft_pick)` version) added to
each position's existing final feature set, comparing LOOCV AUC and AIC:

| Position | Best draft addition | Base AUC -> +draft AUC | p-value |
|---|---|---|---|
| QB | top10_pick | 0.794 -> 0.795 (negligible) | 0.080 (marginal, not significant) |
| RB | log(draft_pick) | 0.755 -> 0.761 | 0.013 |
| WR | top10_pick + day3_or_undrafted (both) | 0.839 -> 0.856 | 0.051 / 0.0008 |
| TE | log(draft_pick) | 0.777 -> 0.800 | 0.018 |

QB's improvement is too small and the p-value too marginal to justify adding a feature -- kept the
QB model as-is (v10 feature set). RB, WR, and TE all cleared a real, meaningful bar: WR is the
standout, where draft pedigree turns out to be the single biggest AUC improvement of any feature
tested since the original age+ppg baseline (WR pseudo R² jumped from 0.216 to 0.242) -- prospect
pedigree is telling the model something PPG-above-Starter and age don't, even though earlier
attempts to add EPA/touch or position_share to the WR model had failed to move the needle at all.
This is a genuinely different lesson from the bounce-back model, where draft pedigree was RB-only;
for breakouts, it generalizes to WR and TE too, just not QB.

### Final model (v11)

| Position | Final features | Change from v10 |
|---|---|---|
| QB | age, ppg_above_starter, position_share, candidate_streak, no_other_star_on_team | unchanged (draft pedigree tested, not added -- p=0.08, negligible AUC gain) |
| RB | age, ppg_above_starter, epa_per_touch, position_share, **log(draft_pick)** | added log(draft_pick) |
| WR | age, ppg_above_starter, **top10_pick**, **day3_or_undrafted** | added both draft flags |
| TE | age, ppg_above_starter, reached_starter_by_climbing, **log(draft_pick)** | added log(draft_pick) |

**Full-sample coefficients (v11 additions only):** RB `log(draft_pick)` -0.292 (p=0.013, higher
pick number = later/worse draft slot = lower breakout odds, as expected). WR `top10_pick` +0.604
(p=0.051, borderline) and `day3_or_undrafted` -0.982 (p=0.0008, strong). TE `log(draft_pick)`
-0.690 (p=0.018).

### Backtest: 2023 and 2024 breakouts, re-run with v11 draft features
Pooled walk-forward AUC improved both years: 2023 **0.768 -> 0.776**, 2024 **0.846 -> 0.858**.
Per position the WR improvement is the clear driver (2023: 0.858 -> 0.896; 2024: 0.803 -> 0.824)
and holds up in real single-season data, not just the pooled LOOCV number. RB is a wash at this
small sample size (2023: 0.700 -> 0.688; 2024: 0.677 -> 0.698) and TE actually dipped slightly in
both real test seasons (2023: 0.542 -> 0.500; 2024: 0.778 -> 0.741) despite the strong pooled/
controlled result -- consistent with the pattern already seen with TE in v9/v10, where the
position's small per-season sample (12-14 candidates) makes single-season backtest numbers noisy
in either direction; the pooled, controlled finding (p=0.018, real AIC improvement) is the more
trustworthy read than any one season's AUC swing.

Full scored table: `breakout_backtest_scored_v4.csv`. Draft-pedigree-merged feature file for the
full pool: `breakout_with_draft.csv`.

## v12: Average Draft Position (2012-2026, footballguys.com + FantasyPros)

### Getting the data
Scraped footballguys.com/adp for consensus preseason ADP, 2022-2026. The page is a JS-rendered
SPA; static fetches only ever returned the default/current-year table regardless of URL query
params. Used Claude in Chrome to drive the live page's year selector and inspect network traffic
during the resulting re-render, which revealed the actual reload endpoint:
`https://www.footballguys.com/adp?componentIdNum=1&pos=<POS>&season=<YEAR>&reload=1` — a plain
public GET that returns an HTML fragment and is directly fetchable (no browser needed) once
known. Fetching all positions in one page (`pos=all`) truncated around ~267 of ~350-530 rows in
the fetch tool's summarization step; fetching each of QB/RB/WR/TE separately per season (20
fetches total) returned complete, un-truncated tables every time. Validated against known real
ADP #1 overall picks each season (2022 Jonathan Taylor, 2023 Justin Jefferson, 2024 Christian
McCaffrey, 2025 Ja'Marr Chase, 2026 Jahmyr Gibbs) — all matched.

**Extending further back:** footballguys' archive only goes to 2022. Checked draftsharks.com/adp
(fully paywalled, no historical archive at all) and fantasydata.com (free tier caps at the top 100
players per season — not useful here, since breakout candidates are specifically the below-Star
players who rank well outside the top 100). FantasyPros' ADP page (`fantasypros.com/nfl/adp/
ppr-overall.php?year=YYYY`) turned out to be the best option: the year param genuinely serves each
season's historical data, but the page shows only the top 5 rows until logged in, even with a free
account. You created a free FantasyPros account, which unlocked the full table (300-570 rows per
year). Years 2012-2021 have real data (2010-2011 are empty — FantasyPros' ADP archive starts in
2012). Extracted via the browser's accessibility tree rather than raw HTML/JS scraping, parsed
with a regex over `Open player card for NAME ... POS+RANK ... AVG` triples — a ~90-97% row capture
rate per year (the few misses are mostly K/DST rows with extra team-bye formatting that the regex
skips; harmless since kickers and defenses aren't part of this model).

Combined with the footballguys 2022-2026 data: **15 ADP seasons (2012-2026)** total. Matched to
the candidate pool by normalized player name (lowercased, punctuation/suffixes like Jr./Sr./II/III
stripped) — a 70-73% match rate per position; the misses are almost entirely deep bench/journeyman
candidates the market doesn't rank at all. Joined so ADP for season S+1 (published before that
season starts) lines up with the pool row for season S — the same pre-season-knowable-feature
discipline used everywhere else in this project. This extends usable pool coverage back to season
2011 (**2,350** pool rows now have a season in the ADP-eligible window, versus 776 with just the
2022-2026 footballguys data — a 3x increase).

### Univariate and controlled results: real signal at every position, now much more solid
| Position | n (ADP-matched) | Breakouts | Univariate p (log ADP) | Controlled p (added to v11 features) | Controlled AUC (base -> +ADP) |
|---|---|---|---|---|---|
| QB | 160 | 29 | 0.0002 | 0.032 | 0.757 -> 0.790 |
| RB | 514 | 46 | <0.0001 | <0.0001 | 0.717 -> 0.821 |
| WR | 774 | 56 | <0.0001 | 0.0008 | 0.858 -> 0.879 |
| TE | 105 (220 univariate) | 15 (28 univariate) | <0.0001 | 0.048 | 0.796 -> 0.817 |

Coefficient on `log(ADP rank)` is negative at every position (a lower/better ADP number raises
breakout odds), as expected. With the 15-year window, WR's controlled effect firmed up from
marginal (p=0.074 on the 5-year window) to solid (p=0.0008) — exactly the kind of thing more data
was expected to resolve. `log_adp` added to all four position models.

### Backtest: a real multi-season walk-forward test, not just pooled/controlled evidence
With 15 ADP seasons instead of 5, a genuine walk-forward re-test became possible: train on all
seasons before the one being predicted, score the held-out season, repeat for every season 2018
through 2025 (2018-2024 have known outcomes; 2025 is forward-looking, resolves with the 2026
season). Pooled AUC by test season:

| Test season | n | Actual breakout rate | AUC |
|---|---|---|---|
| 2018 | 83 | 16.9% | 0.862 |
| 2019 | 105 | 9.5% | 0.947 |
| 2020 | 106 | 8.5% | 0.656 |
| 2021 | 92 | 9.8% | 0.859 |
| 2022 | 97 | 11.3% | 0.799 |
| 2023 | 134 | 6.7% | 0.775 |
| 2024 | 88 | 11.4% | 0.858 |

Average ≈0.82 across seven real, out-of-sample test years. Where it overlaps the v11 (no-ADP)
backtest: pooled AUC is essentially a wash in 2023 (0.776 -> 0.775) and identical in 2024 (0.858 ->
0.858) — but that's the full pool average; per position, RB improved both years (2023: 0.688 ->
0.779; 2024: 0.698 -> 0.796) and WR improved both years too (2023: 0.896 -> 0.920; 2024: 0.824 ->
0.833). QB and TE are noisier at their smaller per-season sample sizes — TE's 2018 slice couldn't
even be fit (too few TE candidates had ADP that far back, still a small position sample even in
the extended window) and TE 2020 dipped to 0.167 on just 7 candidates — but the pooled, controlled
finding above (p=0.048, real n=105) is the more trustworthy read than any one small-sample season
swing, the same pattern seen with TE throughout this project.

**Bottom line:** this is now a properly validated feature, not just a promising-but-small-sample
result. `log_adp` is part of the production model for all four positions. The workbook's "Breakout
Model" sheet reflects this with three tables: the original v11 walk-forward backtest (2023-2024,
full pool, no ADP — kept as the baseline/full-coverage view since ~30% of candidates have no ADP
match), a new v12 walk-forward backtest (2018-2024, ADP-matched candidates only, the properly
validated multi-season test), and 2025 forward-looking predictions shown both ways (v11 full pool,
v12 ADP-augmented).

Scraped ADP data: `adp_scraped_raw.csv` (footballguys 2022-2026), `adp_fp/*.csv` and
`adp_scraped_raw_historical.csv` (FantasyPros 2012-2021), combined into `adp_scraped_raw_all.csv`.
Pool merged with ADP: `breakout_with_adp.csv`. Backtest script and scored output:
`breakout_backtest_v5.py` / `breakout_backtest_scored_v5.csv`.

## Expert breakout picks: real correlation, but fully redundant with existing features
Tested whether being named a "breakout candidate" in a preseason fantasy-analyst article predicts
actual breakouts — the idea being that analysts synthesize situation, opportunity, and talent
signals qualitatively, and might be picking up on something the model's features don't.

### Getting the data
FantasyPros publishes at least one "breakout candidates" article every year, freely readable (no
paywall), going back to at least 2015 and continuing through 2026. Pulled one comprehensive article
per year for 2015-2025 (11 years) via `WebFetch`, supplementing 2021 (whose main article was thin,
only 3 names) with a footballguys.com WR-specific breakout article. This gave 200 total named
picks across 11 years (5-52 per year, with coverage growing substantially in recent years — 2023
alone had 27 comprehensive-article names). Matched to the candidate pool by normalized name, with
the article for season S+1 (e.g. the "2023 breakout candidates" article, published in 2023) joining
to the pool's season-S row (e.g. season 2022) — the same alignment logic as ADP, since these
articles are published before the season they're predicting and are therefore pre-season-knowable
for that pool row. 112 of the 200 named picks matched to the pool (56%); the rest were mostly
rookies/first-year players who can't appear in the candidate pool yet (same pattern seen with ADP
and expert picks in general — a new player has no prior season to be "a candidate" from).

Data: `breakout_articles_raw.py` (source article text per year), `breakout_with_expert_picks.csv`
(joined to pool, `expert_breakout_pick` boolean column).

### Result: strong raw signal, but it evaporates once you control for what the model already knows
Position-agnostic, named picks broke out at 20.5% vs. 7.1% for everyone else (n=112 vs. 3,687) —
a Fisher's exact test gives odds ratio 3.41, p<0.0001. That's a real, highly significant univariate
correlation, and by far the strongest raw signal of any feature tested in this project.

But controlling for each position's existing v12 features (age, PPG-above-starter, draft pedigree,
ADP, etc. — see the v12 section above) erases it completely:

| Position | n (controlled) | Named breakout rate | Not-named rate | Base AUC | +expert pick AUC | pick coef p-value |
|---|---|---|---|---|---|---|
| QB | 160 | 28.6% (n=7) | 7.1% | 0.790 | 0.787 | 0.808 |
| RB | 514 | 22.9% (n=35) | 7.4% | 0.820 | 0.821 | 0.496 |
| WR | 774 | 17.3% (n=52) | 5.8% | 0.879 | 0.880 | 0.414 |
| TE | 105 | 22.2% (n=18) | 10.4% | 0.821 | 0.819 | 0.957 |

Every position: AUC moves by a thousandth or two (one position even ticks down slightly), and the
expert-pick coefficient is nowhere near significant. Re-ran restricted to just the richest-coverage
years (2021-2024 seasons, where expert-pick sample sizes are largest) to make sure this wasn't an
artifact of thin early-year coverage diluting the signal — same result: QB p=0.734, RB p=0.684,
WR p=0.271 (TE too small to test in this window, n=2 named).

**Interpretation**: analysts really are picking players who go on to break out at a much higher
rate than average — but they're doing it using the same underlying signals this model already
captures (market ADP, draft pedigree, age, situational opportunity), not some independent insight.
Once those features are in the model, knowing that FantasyPros also picked the player adds nothing
incremental. This is a cleaner, more decisive null result than the Vegas-odds tests: the raw
correlation here is much stronger, but the controlled test is equally clear that it's redundant
rather than complementary. **Not added to the model.**

## Vegas team win totals: tested, no signal for individual breakouts
Investigated whether a team's preseason Vegas win-total line (and Super Bowl odds, as a second
proxy for team quality) predicts which of that team's candidates break out the next season. The
idea: a team Vegas expects to be good should generate more offensive scoring opportunities,
raising the odds that any given skill-position candidate on it breaks out.

### Getting the data
Pro-Football-Reference publishes a preseason odds page per season
(`pro-football-reference.com/years/{YEAR}/preseason_odds.htm`), sourced from sportsoddshistory.com,
going back to at least 1994 — free, static HTML, no login wall. Scraped 2001-2025 (matching the
candidate pool's full season range) via `WebFetch`, one year at a time after a batch of 4 parallel
requests drew one transient 403 (retried individually with no further issues). Columns: team, Super
Bowl odds (American moneyline), win-total line, and actual record with the bet's over/under/push
result noted. Team full names were mapped to nflverse's standard abbreviations, handling
relocations/renames across the window (St. Louis→Los Angeles Rams, San Diego→Los Angeles Chargers,
Oakland→Las Vegas Raiders, Washington Redskins→Football Team→Commanders). Unlike ADP (a per-player,
name-matched join with real-world match gaps), this is a clean (season, team) join — 100% of the
3,799-row candidate pool matched.

Script chain: `build_vegas_dataset.py` (raw text → `vegas_odds.csv`, 799 team-seasons, 2001-2025)
→ `join_vegas.py` (→ `breakout_with_vegas.csv`) → `vegas_analysis.py` (stats).

### Season alignment (different from ADP, and worth noting why)
ADP for season S+1 joins to the pool's season-S row, because ADP is about the player's own
draft-market value being set heading into the *next* season — mirroring the "pre-season-knowable
feature" discipline used everywhere else in this model. Vegas win totals work differently: the
win-total line for season S is set before season S starts and describes the offensive environment
the candidate is playing in *during* season S itself — the same season whose outcome
(`broke_out_next_year`) is being predicted. So this join is NOT lagged; win_total_line for season S
joins directly to the pool's season-S row.

### Result: no signal at any position
Both the win-total line and the Super Bowl implied probability were tested, univariately and
controlling for each position's existing v11/v12 features. Neither showed anything:

| Position | n | Win total t-test p | Win total univariate AUC | Controlled AUC (base → +win total) | SB odds univariate AUC |
|---|---|---|---|---|---|
| QB | 512 | 0.778 | 0.517 | 0.829 → 0.831 | 0.503 |
| RB | 1099 | 0.324 | 0.533 | 0.775 → 0.781 | 0.549 |
| WR | 1678 | 0.489 | 0.522 | 0.863 → 0.865 | 0.535 |
| TE | 510 | 0.261 | 0.555 | 0.837 → 0.843 | 0.571 |

Every p-value is well above 0.05, every univariate AUC is within noise of a coin flip (0.50-0.57),
and controlling for existing features moves AUC by a thousandth or two at most — the coefficient on
win total is never close to significant once the existing feature set is in the model. This is a
clean, confident null result across both team-quality proxies, all four positions, and both simple
and controlled tests. **Not added to the model.** Team-level offensive environment, at least as
priced by Vegas before the season, does not distinguish which specific players on a team break out —
consistent with breakouts being driven by individual opportunity/role changes (which the existing
features already capture) more than by which team happens to be good.

Data preserved for reference: `vegas_odds_raw.py` (source text per year), `vegas_odds.csv` (clean
per-team-season dataset), `breakout_with_vegas.csv` (joined to pool), `vegas_analysis.py` (test
script). Revisit only if a compelling theoretical reason emerges to test a different formulation
(e.g., pass-rate implied by the total, rather than the total itself).

## Individual player prop bets: no structured historical database, but a manual pilot is possible
Investigated as a second, more granular alternative to team win totals — the idea being that a
player's own preseason receiving/rushing/passing yardage or TD prop line might carry information
current model features don't. No structured historical archive of season-long player prop lines
exists anywhere accessible: The Odds API's historical endpoint only goes back to 2026-05-13 and
explicitly excludes NFL futures/props from historical coverage even from that date forward (free
tier blocks historical entirely); SportsData.io has player props only from 2020 with sales-contact
pricing and no free tier; current-year-only prop pages (BettingPros, FantasyTeamAdvice, CBS Sports)
have no historical archive mode at all — live sportsbook player-odds pages (e.g. Rotowire's
`betting/nfl/player/*-odds-*` pages) get overwritten with the next season's lines once it starts, so
there is no way to pull last year's number back off them, and the Wayback Machine is blocked at this
environment's fetch proxy. Per the user's decision, parked as a database-building effort — building
a real historical archive is not feasible with free sources today.

**However**, a narrower, manually-scoped pilot IS possible for a small named list of players: preseason
"season prop bet" articles from sites like lasvegassportsbetting.com (per-position hub pages listing
~10-30 star-tier players' season yardage/TD lines each year, e.g.
`lasvegassportsbetting.com/nfl-football/2025-26-nfl-season-wide-receivers-odds-props/`), and
one-off "best NFL player prop bets" picks articles (CBS Sports, PFF, Sharp Football Analysis) that
quote a specific player's season-long line as part of their analysis, stay live and searchable/
web-fetchable indefinitely as ordinary articles — unlike live odds tables, they're static published
content. This only works for players prominent enough to get a published season prop in the first
place (mostly established starters/stars); the same backup/role-player names that were unmatchable
in the team-win-total investigation are equally invisible here, for the same underlying reason (no
outlet publishes a season-long prop for a committee-role RB or WR4).

### Pilot: 2025 season props vs. actual 2024-pool breakout outcomes
Tested this against the model's 42 top-scored "2025 breakout candidates" (the pool's season=2024
row, v12 model's top-15-per-position predictions, shown in the workbook's forward-looking table) —
now that the 2025 season is complete and both the props and the actual outcomes are known. Found a
season-long prop for 17 of the 42 (40%, and only for the more prominent names, as expected) via the
sources above. Comparing each player's actual 2025 stat to their preseason prop line:

| Beat/missed prop | Broke out (v12) | Did not break out |
|---|---|---|
| Beat the prop | 5 | 4 |
| Missed the prop | 1 | 7 |

83% of players who broke out (5 of 6) beat their preseason prop line, versus 36% of those who didn't
(4 of 11) — directionally in the expected direction, but Fisher's exact test on this 2x2 gives
p=0.131, not significant, and n=17 (with only 6 breakouts) is far too small to draw a real conclusion.
There's also a selection-bias concern baked into the sample itself: only players notable enough to
get a published prop are included, and that same notability likely already correlates with breakout
odds through the model's existing features (age, draft pedigree, ADP) — so this pilot can't cleanly
separate "the prop adds information" from "the prop and the outcome share the same underlying cause."
One instructive edge case: Tucker Kraft missed his receiving-yards prop (489 actual vs. 699.5 line)
but still broke out, because he did it efficiently via touchdowns (6 receiving TDs, beating his 5.5
TD prop) rather than yardage volume — a reminder that a single-stat comparison is lossy for TEs
and other high-efficiency, lower-volume breakouts.

**Verdict**: not something to build into the model — the underlying data problem (no structured
historical archive, and coverage limited to star-tier players even for one-off pilots) hasn't
changed. This pilot is preserved as a proof-of-concept in case a future need calls for scaling it up
manually across more seasons of candidates, with the caveats above kept in mind.

Pilot data: `vegas_props_2024_candidates.csv` (17 matched players, prop line, actual stat, and
breakout outcome). Scripts: none beyond ad-hoc lookups — see the CSV for the underlying comparison.

## v13: Coaching staff data — obtained, and player-development effects tested
The "on hold" status below was resolved once it was discovered that `claude-in-chrome` can reach
the Wikipedia MediaWiki API directly in this environment (`action=parse`), even though direct
`WebFetch`/REST/Wikidata access to Wikipedia is blocked as "cache-only." Full coaching staffs
(front office, head coach, every position coach, coordinators, strength & conditioning) were
scraped for all 799 team-seasons, 2001-2025 (32 teams x 25 seasons, one team-season fewer than
32x25 because Houston Texans didn't exist before 2002).

**Method**: two-step fetch per page (fetch the article's section-index list via
`prop=sections`, then fetch only the "Staff" section's wikitext via `prop=wikitext&section=N`) —
this two-step approach was adopted after the original single-fetch-whole-page approach developed
an escalating truncation problem in later, more heavily-documented seasons (missed 53-70% of
2007-2009 pages before the pivot). Parsed the `{{NFL final staff}}` template (most years) and an
older raw-wikitable format (pre-~2011) into structured rows. **Final coverage: 771 of 799
team-seasons (96.5%) have a usable Staff section; 28 team-seasons (mostly short pre-2010
articles) genuinely have no Staff section in their Wikipedia article at all** — a real content
gap, not a scraping failure (verified by direct inspection). 23,391 individual coach-role rows
total. Normalized into a `(season, team, role)` -> coach-name table covering Head Coach (HC),
Offensive/Defensive Coordinator (OC/DC), and primary position coaches (QB/RB/WR/TE/OL) — 694-752
team-seasons resolved per role (assistant/quality-control/intern titles excluded so only the
primary coach of record counts).

### Head-coach continuity (re-test with full staff data)
This confirms, rather than changes, the original nflverse-based finding: head-coach turnover has
no predictive value for bounce-back or breakout outcomes (see v6/v8 above). The newly-scraped
staff data adds coordinator- and position-coach-level granularity that wasn't available before.

### Player-development question: do specific coaches consistently produce breakouts or superstars?
Prompted by the user's question: does a specific position coach, offensive coordinator, or head
coach have a track record of coaching players to breakout seasons, or to Superstar-or-better
seasons, more consistently than other coaches?

**Two outcome metrics tested**, each joined to the coach-of-record for the player's team in the
relevant season:
1. **Breakout rate** — using the existing breakout-candidate pool (below-Star player-seasons,
   2001-2024): did the candidate reach Star-or-higher the very next season, attributed to the
   coach(es) of the player's *actual* team in the breakout season (which can differ from the
   team in the candidate season, if the player changed teams).
2. **Superstar-player rate** — across every qualifying player-season (>=4 games) at a skill
   position, did the player *ever* reach Superstar or League Winner tier while playing under a
   given coach, across all their seasons together.

**Critical methodological correction made mid-analysis**: an initial pass tested each
*player-season* as an independent trial. This produced several apparently-significant results,
even surviving Bonferroni correction (e.g. Kyle Shanahan/George Kittle at TE, p=4.3e-05; Sean
McDermott/Josh Allen at QB, p=1.1e-04; Tom Melvin/Travis Kelce at TE). Manual inspection showed
every one of these was driven by a **single generational player who stayed with one coach for
8-10 consecutive seasons** — repeated observations of one person, not independent evidence of a
coaching pattern across different players. This is a real pseudo-replication trap: a "player-season"
unit of analysis silently assumes each season is an independent trial, which breaks down badly
when the same coach-player pair persists for a decade.

**Corrected method**: re-ran both metrics using **distinct players** as the unit of analysis — did
this specific player ever reach the outcome under this coach, counted once per player, regardless
of how many seasons that took. League base rates were recomputed the same way (fraction of all
distinct players at a position who ever reached the outcome, league-wide).

### Result: no statistically robust "star-maker" effect, at either metric
At the player level:

| Metric | Position coaches tested (min 8 players) | OCs tested | HCs tested | Any survive Bonferroni? |
|---|---|---|---|---|
| Superstar-player rate | 245 | 305 | 246 | **0 of 796** |
| Breakout-player rate | 73 | 66 | 71 | **0 of 210** |

Across just over 1,000 coach/position combinations tested, **zero survive correction for multiple
comparisons** in either metric. A handful of raw p<0.05 hits appear in both directions (some
coaches' players *underperform* base rates as often as others overperform) — exactly the pattern
expected from chance alone at this many tests, not a real effect. This is a clean null result,
consistent with the existing finding that head-coach turnover has no bearing on breakout or
bounce-back outcomes.

**Descriptive top lists** (not statistically significant, all p > 0.10, provided for interest
only): among position coaches with a reasonable sample (15+ distinct players), the closest thing
to a genuine multi-player pattern is **James Saxon** (RB coach) — 5 different backs reached
Superstar tier under him across different teams/careers (Priest Holmes, Larry Johnson, Le'Veon
Bell, Adrian Peterson, James Conner), a 16.7% rate vs. a 13.0% league base (p=0.58, not
significant) — genuinely a fun résumé, but statistically indistinguishable from chance at this
sample size. Similarly, OCs **Norv Turner** and **Al Saunders** show breadth across multiple
different Superstar-tier running backs, not just one player, but again without statistical
significance (p=0.18 and p=0.11 respectively).

**Bottom line**: this project's fantasy-points-based tier framework finds no evidence that any
specific position coach, coordinator, or head coach systematically "makes" superstars or
breakouts more than the league average, once the analysis is done at the correct (player-level,
not player-season-level) unit of observation. Not added as a model feature. Full scored tables
(all coaches tested, both metrics, both units of analysis) are in the delivered
`Coaching_Staff_Player_Development_Analysis.xlsx` workbook, and the raw normalized coach-role
table (season/team/role/coach-name, 5,962 rows) is included as a reference sheet.

Data: `staff_rows.jsonl` (raw scraped rows, in the coaching working directory), `coach_table.csv`
(normalized season/team/role table), `position_coach_superstar_playerlevel.csv` /
`oc_superstar_playerlevel.csv` / `hc_superstar_playerlevel.csv` (superstar-rate results, all three
coach types), `position_coach_breakout_playerlevel.csv` / `oc_breakout_playerlevel.csv` /
`hc_breakout_playerlevel.csv` (breakout-rate results). Player-season-level versions (before the
pseudo-replication correction) are preserved for reference as
`*_superstar_stats.csv`/`*_breakout_stats.csv` but should not be used for inference.

## v14: "Does a coach really have zero effect?" — draft-pedigree-adjusted and combined OC+HC identity tests
The user pushed back on the v13 null result directly: "I don't think it makes sense that a coach
has essentially zero effect on how good a player is." Two further, more targeted analyses were
built to stress-test that gut feel, using Kyle Shanahan as an explicit worked example per the
user's request that his OC seasons (Washington, Cleveland, Atlanta) and HC seasons (San Francisco)
be evaluated as ONE continuous coaching track record, not two separate ones.

### Analysis A: draft-pedigree-adjusted coaching effect
Question: are some coaches better at getting more out of players drafted later, relative to how
players drafted in that range normally perform? Players were bucketed into three draft-pedigree
tiers per the user's specified breakdown: **Day1** = Round 1, **Day2** = Rounds 2-3, **Day3+UDFA**
= Rounds 4-7 or undrafted. A league baseline was built as the average career tier-score (on this
project's existing 0-5 tier scale: Below Replacement=0, Mid/replacement=1, Starter=2, Star=3,
Superstar=4, League Winner=5) for distinct players in each (position, draft tier) cell — see the
workbook's "Draft Tier Baseline" sheet.

Each coach's distinct players in a (position, draft tier) cell (minimum 15 distinct players) were
compared against the REST of the league's players in that same cell using Welch's two-sample
t-test, excluding the coach's own players from the comparison group.

**Method revision, self-caught**: a first pass (minimum 5 players, one-sample t-test against the
baseline mean) produced several p=0.0000 results driven by tiny, zero-variance samples (e.g. 5
players who all happened to bust, producing a degenerate artifact, not a real finding) — the same
kind of statistical trap as the v13 pseudo-replication issue, just a different flavor. Discarded in
favor of the larger-sample, two-sample-t-test version described above.

**Result: no positive "develops late picks better" effect survives correction.** Across 44
position-coach, 29 OC, and 28 HC (position x draft-tier) combinations tested, exactly ONE survives
Bonferroni correction in each table — and all three are NEGATIVE (underperformance), all at WR
Day3+UDFA: Zach Azzanni as position coach (p=1.0e-07), Greg Roman as OC (p=9.8e-09), and Ron Rivera
as HC (p=6.7e-25). In other words, the data shows more statistically robust evidence of specific
coaches getting LESS out of late-round/UDFA receivers than league average, than of any coach
getting MORE out of them. No coach clears the bar for a genuine "late-round developer" effect at
any position once corrected for the ~100 tests run across the three tables.

### Analysis B: combined OC+HC coaching-identity effect (Kyle Shanahan worked example)
Per the user's explicit instruction — "I think when we are analyzing coaches we should analyze
Kyle Shanahan the OC and his impact the same as we analyze Kyle Shanahan the HC" — each coach's
OC-role seasons and HC-role seasons were merged into ONE continuous track record (the union of all
team-seasons in either role), rather than scored as separate coaching identities. For every distinct
skill-position player (QB/RB/WR/TE) who played under that combined tenure, the player's own
overperformance vs. draft-tier expectation (actual career tier-score under this coach minus the
position+draft-tier league baseline) was computed, then averaged across the coach's distinct
players and tested with a one-sample t-test against zero. Coaches needed >=15 distinct skill
players across their combined tenure to be included — 332 qualifying coaching identities.

**Result, scanning all coaches**: 0 of 332 combined coaching identities survive Bonferroni
correction (threshold p<0.00015). As with the v13 superstar/breakout analysis, this reinforces
that no coach's whole-career track record is statistically distinguishable from luck once compared
simultaneously against ~330 other coaches. Min raw p-value in the whole scan was 0.0017 (Aaron
Kromer) — nowhere close to the corrected bar.

**Result, as a single named hypothesis (Kyle Shanahan specifically)**: this is a materially
different statistical question from the scan above — testing ONE pre-specified coach the user
named ahead of time, not scanning for the best of many, so no correction for hundreds of
simultaneous comparisons is required. Kyle Shanahan's combined 9 seasons as OC (Houston 2008-09,
Washington 2010-13, Cleveland 2014, Atlanta 2015-16) plus 9 seasons as HC (San Francisco
2017-2025) shows a real, standalone-significant result: **+0.262 average overperformance vs.
draft-tier expectation across 120 distinct skill-position players (p=0.0119)**.

The player-level detail (workbook's "Shanahan Worked Example" sheet) directly corroborates the
specific examples the user raised: Robert Griffin III (+1.68 overperformance, consistent with his
Offensive Rookie of the Year season), Matt Ryan (+1.18, consistent with his lone MVP season under
Shanahan), Brock Purdy (a Day3+UDFA-tier QB pick who overperforms his draft slot, supporting the
"gets more out of mid/late-round QBs" claim), Devonta Freeman (+4.19), George Kittle (+3.83),
Christian McCaffrey (+2.35), Deebo Samuel (+2.04), Brandon Aiyuk (+0.70, reflecting a strong
partial season before a serious injury, as the user described), and Arian Foster (+2.69, a UDFA
who became a star). This is genuine, specific supporting evidence for the user's gut feel about
this particular coach — it does not, however, generalize into evidence that coaching effects are
detectable league-wide (see the 0/332 scan-all-coaches result above). The honest synthesis: one
well-chosen, well-supported hypothesis about a specific coach can be real and demonstrable even
while the broader claim ("coaches in general have a detectable, rankable effect on player
outcomes") remains unsupported once you look at all of them at once and correct for that.

**Caveat**: the "HC" role was credited broadly, including to defensive-minded head coaches who do
not call their own offense. Several names near the bottom of the "Combined OC+HC Rank" sheet (e.g.
Rod Marinelli, Dick LeBeau, Steve Wilks) are defensive specialists whose apparent "underperformance"
likely reflects that they were not the actual offensive play-caller on their team, rather than a
real negative effect on player development. This limitation should be kept in mind before reading
too much into any specific head coach's rank on that sheet, positive or negative.

Data: `player_seasons_with_draft.json` / `draft_tier_baseline.json` (draft-tier classification and
league baselines), `draft_tier_position_coach_v2.csv` / `draft_tier_oc_v2.csv` /
`draft_tier_hc_v2.csv` (Analysis A results), `combined_oc_hc_overperformance.csv` (Analysis B,
all 332 coaches), `shanahan_worked_example.csv` (full 120-player detail for the worked example).
All included as sheets in the updated `Coaching_Staff_Player_Development_Analysis.xlsx` workbook
(14 sheets total).

## v15: Best NFL offenses by year, named-coach reputation check, position-resilience, and Vegas-era correlation
Prompted by a follow-up question tying the coaching work back into the broader breakout/fall-off
project: does analyst reputation for "elite offensive mind" coaches actually show up in the data,
how does that interact with player-level fantasy performance (do some positions resist a bad
offense better than others), and how well do preseason Vegas win totals predict actual offensive
quality, in different eras?

### Best NFL offense by year (2000-2025), three objective metrics
Built directly from nflverse play-by-play and schedule data already cached in this project
(`play_by_play_{season}.csv`, `games.csv`), regular season only. Three metrics: PPG (from actual
final scores), YPG (yards gained on every offensive scrimmage play), and EPA/play (mean Expected
Points Added per offensive scrimmage play — the standard advanced efficiency metric, preferred
over raw yards since it accounts for down/distance/situation). All three agree on the same #1
team in about half of seasons and diverge in the rest (PPG rewards short-field/red-zone
efficiency, YPG can be inflated by garbage-time volume, EPA/play is the most "pure" per-play
quality measure). Results check out against well-known history: 2000-01 Rams, 2007 Patriots
(16-0 season), 2013 Broncos (Manning's record year), 2011/2020 Packers (Rodgers MVP years), 2018
Chiefs (Mahomes' first MVP), 2019/2024 Ravens (Lamar Jackson MVP years) all top their respective
metrics in the expected years.

**DVOA could not be included**: Football Outsiders shut down in 2023; the DVOA brand and its
1977-present historical archive moved to FTN Fantasy, but that archive is subscriber-only and not
bulk-downloadable for free. Free year-end recap articles exist for individual seasons (e.g. the
2023 49ers as FTN's #1 offense by DVOA) but there's no free, complete, machine-readable series to
build a reliable table from. Parked; revisit if FTN subscription access becomes available.

Data: `team_offense_master.csv` (points/yards/EPA per team-season, 2000-2025, team abbreviations
normalized for relocated franchises — OAK→LV, SD→LAC, STL→LA), `team_offense_ranked.csv` (adds
rank and percentile within each season). Delivered as `NFL_Best_Offense_By_Year_2000-2025.xlsx`.

### Named-coach reputation check: do Shanahan/LaFleur/McVay/Ben Johnson/Reid/Payton actually produce top offenses?
Tested six coaches with strong analyst reputations as elite offensive minds. Per this project's
existing v14 combined-identity methodology, each coach's OC-role and HC-role seasons are merged
into one continuous track record. "Offense quality" = team offensive EPA/play, percentiled against
all NFL teams that same season (1.0 = league's best offense that year, 0.5 = average). One
data-cleaning catch worth noting: Sean Payton's 2012 season carried a stray "†" character in the
raw scraped coaching-staff data — investigating why revealed he was suspended for the entire 2012
season (Bounty Scandal) and did not actually coach that year, so that season is excluded from his
credit (New Orleans' 2012 offense, coached in practice by others, is correctly NOT counted as a
Payton season).

**Result 1 — yes, real and statistically solid.** Average offensive percentile while each coach
held OC/HC (weighted by seasons): Ben Johnson 83.6%ile, Matt LaFleur 79.2%ile, Sean Payton
75.4%ile, Andy Reid 73.1%ile, Kyle Shanahan 63.7%ile, Sean McVay 62.8%ile. Because this tests six
specific, pre-named coaches rather than scanning the whole league, it doesn't need the same
multiple-testing correction used in the v13/v14 all-coach scans. Coach-level one-sample t-test
(n=6, one observation per coach to avoid the pseudo-replication trap already learned earlier in
this project): mean=72.9%ile vs. a 50% null, t=6.75, **p=0.0011**. Analyst consensus on these six
names is genuinely borne out.

**Result 2 — arrival is associated with a real jump from the year before.** Segment-level (each
coach-team stop = one segment, n=18 with a valid "before" year): during-tenure avg 66.0%ile vs.
37.1%ile the year immediately before that coach arrived at that team (paired t-test, t=3.75,
**p=0.0016**). Segments aren't fully independent (some coaches contribute several stops), so this
is directionally strong rather than a single clean test.

**Result 3 — controlling for the starting QB shrinks, but doesn't erase, the effect.** Part of
the jump above is entangled with these coaches also often importing a better QB in the same move
(Andy Reid + Alex Smith at KC; Sean McVay leaving Washington for a clean QB slate in LA).
Restricting to team-stops where the SAME primary starting QB (from `games.csv` home/away_qb_name,
mode per team-season) carried over from the prior season — holding QB talent roughly fixed —
shrinks the sample to n=11: during 66.1%ile vs. before 50.4%ile, still directionally positive but
only marginally significant (t=1.94, **p=0.081**). Honest read: some of "these coaches make
offenses great" is really "these coaches also land better QB situations," but a real scheme
effect still appears even holding QB constant — just smaller and less certain than the headline
number implies.

**Result 4 — offenses don't reliably collapse the moment these coaches leave.** During-tenure avg
(62.9%ile) vs. the very next season after departure (61.5%ile, n=12): no significant difference
(t=0.18, **p=0.86**). Two notable counter-examples keep this honest: Philadelphia's offense
actually *improved* the year after Andy Reid left (2013, Chip Kelly's up-tempo debut, 90.6%ile),
and Houston's improved after Shanahan left too (96.9%ile). Roster talent and scheme continuity
often carry a team for at least one more year regardless of who's calling plays.

### Do some fantasy positions resist a bad offense better than others? Yes, clearly.
For every player who stayed on the SAME team across two consecutive seasons (isolating the
offense-quality effect from the confound of a player also changing situations by changing teams),
correlated the change in team offensive EPA/play percentile with the change in that player's own
PPG and tier score (n=5,440 same-team year-pairs, 2001-2025). Correlation with tier change,
strongest to weakest: **QB r=0.440 (p<0.0001)** — by far the most tied to overall offense quality,
which makes sense since QB stats essentially ARE the passing offense — **RB r=0.195 (p<0.0001)**,
**WR r=0.161 (p<0.0001)**, **TE r=0.053 (p=0.071, not significant)** — tight end fantasy output is
the LEAST tied to whether the team offense as a whole gets better or worse.

This shows up just as clearly in levels, not just year-over-year change: of all Star-or-better
player-seasons, the share that happened on a below-average offense: QB 12.1%, WR 29.0%, TE 34.0%,
RB 34.1% — and on a bottom-third offense specifically: QB 5.8%, WR 13.6%, TE 19.6%, RB 21.5%.
Elite QB seasons on truly bad offenses are rare and generally cut short (e.g. Dak Prescott 2020,
injury-shortened, on a 25th-ranked offense — the worst offense to still produce an elite-tier QB
season in this dataset). RB and TE, by contrast, regularly produce elite fantasy seasons on
bottom-5 offenses: Christian McCaffrey (2019/2021 CAR, 28th/30th), Breece Hall (2022/2023 NYJ,
30th/32nd), Fred Taylor (2002 JAX, 32nd), David Njoku (2023/2024 CLE, 28th/32nd), Brock Bowers
(2024/2025 LV, 31st/32nd). **Bottom line: RB and TE fantasy value is meaningfully more independent
of overall offensive quality than QB or WR** — a running back or tight end can be a league-winning
fantasy asset even on one of the league's worst offenses; a QB essentially cannot.

Data: `player_yoy_offense_change.csv` (the year-over-year same-team join), `player_season_with_
offense_rank.csv` (every qualifying player-season joined to that team's offensive rank/percentile).

### Preseason Vegas win totals vs. actual end-of-season offensive rank, by era
Correlated each team's preseason Vegas win-total line (already scraped for this project, see the
Vegas team win totals section above) against that SAME season's offensive EPA/play (799
team-seasons, 2001-2025, 100% match rate): full sample r=0.462 (p<0.0001); 2001-2014 r=0.483
(p<0.0001); 2015-2024 r=0.409 (p<0.0001); 2025 only r=0.559 (n=32, one season — noisy). Read:
Vegas win totals have always had a moderate, far-from-perfect relationship with actual offensive
quality (roughly r=0.4-0.5 across the whole 25-year period) — expected, since a win total prices
in defense and special teams too, not offense alone. The 2015-2024 correlation is modestly lower
than 2001-2014, but the gap is small, not a dramatic era shift, and 2025's single-season r=0.56 is
well within normal one-year sampling noise rather than clear evidence of a new trend. No strong
evidence Vegas has gotten meaningfully better or worse at pricing in offensive quality specifically
across this period.

Data: `vegas_vs_offense.csv` (merged team-season table with win totals, actual wins, and all three
offensive metrics). Delivered as `Coaching_and_Offense_Quality_Analysis.xlsx` (7 sheets: Summary,
Coach Season Detail, Coach Before-During-After, Coach Summary, Player YoY Offense-Change Corr,
Player Examples, Vegas vs Offense by Era).

## v16: A stricter, QB-controlled test — does a coach elevate whichever QB he has?
The v15 before/during/after design can't fully separate "the coach is great" from "the coach also
got a better QB in the same move." Prompted by the user noting that Shanahan, McVay, Reid, and
LaFleur have each succeeded across multiple different starting QBs at their current team, this
builds a stricter, within-player test: for the SAME quarterback, does he perform better (team
offensive EPA/play percentile) under Coach X than in the rest of his own career, under every OTHER
coach he ever played for? This holds the player's talent fixed and isolates the coach as the only
thing that changed. Built from `games.csv` home/away_qb_id (career-persistent player IDs, more
robust than name matching) to find each team-season's primary starter, matched against every other
season of that QB's career under a different coach.

**A real attribution bug was caught and fixed during this analysis**: an early version tried to
label each team-season with "the" credited coach by taking the first alphabetical match among
that team-season's OC and HC rows in `coach_table.csv` — which silently misattributed offenses to
whichever assistant/OC happened to sort first (e.g. briefly crediting Kyle Shanahan's 2025 49ers
offense to Klay Kubiak, an OC in title only, rather than Shanahan, who remained the actual
play-caller as HC). Fixed by restructuring the design so no single "team-season coach" label is
ever needed — each candidate coach's own OC/HC tenure segments (independently built per person,
already correct) are matched directly against the QB-primary-per-team-season data, so the
ambiguity of "who gets credit when both an OC and HC exist" never has to be resolved.

**Critical baseline check, before trusting any single coach's number**: pooling all 687 coach-QB
pairs leaguewide with real comparison data, the average QB does NOT perform better under a given
coach than in the rest of his career — mean delta = **-0.036** (slightly worse), only 45.7% of
pairs positive. A coach retaining a second or third different multi-year starter is not, by
itself, evidence of anything; the leaguewide baseline leans slightly negative (plausibly because
journeyman/backup QBs are often acquired cheaply during a decline phase). Any coach beating this
-3.6% baseline by a wide margin is doing something distinguishable from average.

**Result: the original four named coaches don't all hold up equally well once QB is properly
controlled.** Per-coach average delta across every distinct starting QB with real comparison data:
Andy Reid **+0.222** (n=3 QBs — McNabb +0.18, Vick +0.07, Alex Smith +0.41, ALL THREE positive;
the single cleanest "elevates whoever he has" case in the dataset; Mahomes is excluded since he
has no career outside Reid to compare to, which if anything understates Reid's real effect). Matt
LaFleur **+0.059** (n=3 — Rodgers +0.08, Goff +0.18, Mariota -0.09; mildly positive, not a strong
signal alone). Kyle Shanahan **+0.053** (n=6 — Grossman/Schaub/Ryan/Hoyer/RG3 all positive, but
Donovan McNabb's rough lone 2010 season under him is a large -0.40 outlier; net barely above the
leaguewide baseline). Sean McVay **-0.004** (n=4 — Stafford +0.19 and Cousins +0.24 positive, but
Goff -0.09 and RG3's brief rookie-OC-year -0.36 pull it to essentially dead even). Sean Payton
**-0.097** (n=4 — Brees is spectacular at +0.123 across a 14-season sample, but Russell Wilson
-0.27 and Jameis Winston -0.23 pull the coach-level average negative; Payton's "makes anyone good"
reputation looks more like "was outstanding with one franchise QB" once you look past Brees).
None of these individual coach-level t-tests reach conventional significance (all p>0.10) — a
structural sample-size ceiling, since it's rare for any coach to keep his job through 3+ genuinely
different competent starters.

**Other coaches the data supports adding to the list**, scanning every coach in the league (min 2
distinct QBs with real comparison data): **Josh McDaniels +0.217** (n=8 QBs across NE/DEN/LV
stops — the largest sample of any coach tested and still solidly positive; the strongest
data-backed addition), **Greg Roman +0.161** (n=6, matches his real-world reputation for building
schemes around unconventional QBs — Kaepernick, Lamar Jackson), Bill Belichick +0.124 (n=3, but
very likely mostly a Brady-era artifact, not a general pattern — flagged as low-confidence), Mike
Vrabel +0.327 (n=3, largest raw delta but Vrabel is defense-oriented — likely reflects his OC
hires' work more than his own scheme), Jim Harbaugh and Chip Kelly both +0.23 (n=3 each,
promising but too small to lean on). Cross-referencing against whole-career average offensive
percentile (min 6 total seasons as OC/HC, any team, OC+HC combined per the v14 identity method)
reinforces Josh McDaniels as the strongest additional name: 17 seasons, 75.0th percentile average —
right between Sean Payton (75.4) and Andy Reid (73.1) — with a much larger positive QB-elevation
sample behind it than either.

**Can we "prove" this ability exists? Partially.** What the data supports: this is a real,
testable question, and the leaguewide baseline shows that simply having multiple long-tenured
starters is not automatically meaningful — so coaches who clear that -3.6% bar by a wide margin
(Reid, McDaniels, Roman, and to a lesser extent Shanahan/LaFleur) are doing something
distinguishable from average. Andy Reid has the cleanest, most complete case: three unrelated QBs
(a mobile athlete in McNabb, a run-first athlete in Vick, a game-manager in Alex Smith) all
performed above their own career norms under him. What the data does NOT support: statistical
proof at the individual-coach level — every coach-level t-test here has p>0.10, a structural
ceiling given how rarely a coach gets 3+ truly different competent starters, not a flaw in method.
There's also a real right-censoring problem: QBs who never leave a coach (Mahomes/Reid, largely
Purdy/Shanahan) can't be used as evidence in this design at all, likely understating the true
effect for the very best pairings. And McVay's and Payton's reputations specifically look less
like "succeeds with any QB" and more like "had one all-time-great QB" once this control is
applied — a genuinely different and more honest read than the popular narrative.

Data: `team_primary_qb_id.csv` (ID-based primary starter per team-season), `all_coach_tenure_
segments.csv` (every coach's OC/HC tenure per team, all coaches league-wide), `qb_coach_paired_
deltas_v2.csv` (every coach-QB pair with real comparison data, 687 rows), `coach_qb_elevation_
leaderboard_v2.csv` (coach-level aggregation), `coach_career_avg_pctile.csv` (whole-career average
offensive percentile, all coaches, min 6 seasons), `coach_combined_leaderboard.csv` (the two
leaderboards merged). Delivered as `QB_Controlled_Coach_Analysis.xlsx` (6 sheets: Summary,
Named-6 QB Variety, Named-6 QB Elevation Detail, All-Coach QB Elevation Leaderboard, Career Avg
Off Pctile (All Coaches), Combined Leaderboard).

## v17: Decline-adjusting the QB comparison, and what happens after a QB leaves a coach
Two follow-up refinements to v16, prompted directly by the user: (1) the "elsewhere" comparison
should account for where in a QB's career arc a season falls — Russell Wilson's Denver decline
started with a downtick in Seattle, so comparing his Denver years to his flat career average
unfairly blames Payton for a trend that predates him; (2) look at how QBs perform AFTER leaving a
coach, not just during — specifically, Sam Darnold's best two seasons (2024-2025) came only after
a 2023 season with Kyle Shanahan in San Francisco.

### Decline-adjusted comparison (fixes the Wilson problem)
Built an experience-curve baseline: league-wide average team offensive percentile by "years since
a QB's first primary-starter season" (using `players.csv` rookie_season), from `qb_experience_curve.csv`.
Rookies average the 32nd percentile, rising to a 55-59th percentile plateau by year 6-8, noisy
after that (only elite QBs still start 15+ years in). Each QB-season's **residual** = actual
percentile minus the expected percentile for that experience-year — this nets out "declining or
improving anyway" before comparing a QB's time with one coach against the rest of his career.

**Russell Wilson specifically**: residuals fall from +0.29 to +0.59 in his 2012-2015 peak (SEA),
down to just +0.04 to +0.27 by 2016-2021 — already trending toward merely average-for-his-
experience-level well before Denver, exactly matching the user's read. But 2022 (his first Payton
year) still posts a residual of -0.367 — meaningfully worse than even his already-declining trend
predicted — before partially recovering to -0.076 in 2023. Verdict: Wilson's decline did start in
Seattle, but 2022 under Payton was still a real, additional shock beyond that trend, not fully
explained by career-stage alone.

**Redone leaderboard**: the leaguewide baseline barely moves with this adjustment (mean delta
-0.039 vs. the original -0.036 raw version) — the correction mostly matters for individual cases
like Wilson's, not the aggregate. Named-6 coaches largely hold their earlier ranking (Andy Reid
+0.189 residual vs. +0.222 raw, still cleanest; Ben Johnson +0.312 vs +0.411, still strong n=2;
Josh McDaniels +0.200, still the strongest large-sample addition). Payton's Wilson shortfall
shrinks somewhat (-0.235 residual vs. -0.273 raw) but remains real.

### After-leaving-a-coach test (the Darnold question)
Built a second, independent design using team ROSTER membership (`player_team_season.csv`), not
just primary-starter status — necessary because Darnold barely played in 2023 at San Francisco
and would be invisible to the v16 primary-starter-only test entirely. For every QB who spent any
time (starter or bench) under a coach, compared his primary-starter residual performance in
seasons BEFORE joining that coach vs. seasons AFTER leaving.

**Sam Darnold's full trajectory**: residuals of -0.20 to -0.47 through 2018-2021 (NYJ, then CAR) —
well below expectation the whole time, not just bad in absolute terms. 2023: on San Francisco's
roster under Shanahan, but didn't start enough games to register as a primary-starter season at
all. 2024 (MIN, Kevin O'Connell) and 2025 (SEA): residuals +0.02 and +0.07 — modest but a genuine,
real reversal from deeply negative to slightly positive. **This turnaround is real and does follow
his year with Shanahan, exactly as described — but the design cannot cleanly credit Shanahan
alone**: the turnaround also directly coincides with landing at Minnesota under Kevin O'Connell,
himself a well-regarded QB developer (Justin Herbert's rookie surge as his OC, now this). Both
explanations are equally supported by the data with only one case to look at — an important, honest
limitation, not a gap that can be closed with the data on hand.

**Correction, caught by the user**: the original comparison for Matt Ryan (Shanahan's other
qualifying alumnus) incorrectly averaged his post-Shanahan seasons together with his eventual
departure from Atlanta entirely — but Shanahan left Atlanta after 2016, while Ryan stayed in
Atlanta through 2021, not leaving for Indianapolis until 2022. Lumping "Shanahan left" and "Ryan
left" into one "after" bucket erased a real 5-season gap. Broken out properly, by regime: before
Shanahan (2008-2014) avg residual +0.205; during Shanahan (2015-2016) +0.191; after Shanahan left
but Ryan still in Atlanta, under Steve Sarkisian then Dirk Koetter (2017-2020) +0.138 — still
solidly positive; his final Atlanta season under a brand-new Arthur Smith/Dave Ragone regime
(2021, age 36) -0.323; after actually leaving Atlanta for Indianapolis (2022, age 37) -0.492. Read:
Ryan did NOT collapse the moment Shanahan left — he kept performing close to his career norm for 4
more years under two different OCs while still with the team, and only declined sharply in his
final Atlanta season and after the trade, a standard late-30s age-decline story rather than
evidence of Shanahan-specific magic wearing off. This means Ryan should NOT be read as a clean
counter-example to Darnold's turnaround the way the original (erroneous) framing implied — his
data doesn't cleanly argue against a lasting Shanahan effect one way or the other. Sean Payton's
four qualifying alumni (Kerry Collins, Russell Wilson, Teddy Bridgewater, Jameis Winston) ALL show
negative swings after leaving him — no evidence of a lasting positive Payton effect in this test,
for what small samples are worth.

**Coach-level alumni leaderboard** (min 3 qualifying QBs with both before and after data): no
coach's average post-departure swing reaches significance (all p>0.09, n=3-6 QBs per coach) — an
even noisier test than the contemporaneous one, since a QB's next stop brings an entirely new
coach, system, and supporting cast that could just as easily explain any change. Treat every
number here as a suggestive data point, not proof of any specific coach's lasting influence.

**Bottom line**: decline-adjustment confirms the Wilson read (already fading in Seattle) while
still showing his first Denver year was a real added shock beyond that trend. The after-leaving
test can genuinely show Darnold's specific turnaround — real in the data — but can't isolate
whether Shanahan's year or Minnesota's system deserves the credit. Across the alumni leaderboard
broadly, no coach shows a statistically real, general "his players keep improving even after they
leave" effect — the strongest, most repeatable evidence in this whole coaching arc remains the
CONTEMPORANEOUS finding from v16 (Reid, Ben Johnson, McDaniels).

Data: `qb_experience_curve.csv` (baseline expectation by experience-year), `qb_panel_with_residual.csv`
(every primary-starter season with its residual), `coach_qb_elevation_leaderboard_residual.csv`
(v16 leaderboard redone with decline-adjustment), `qb_alumni_before_after_filtered.csv` (every
qualifying coach-QB roster relationship's before/after swing), `coach_alumni_leaderboard.csv`
(coach-level rollup, min 3 QBs). Delivered as `Decline_Adjusted_and_Alumni_Analysis.xlsx` (6
sheets: Summary, QB Experience Curve, Wilson & Darnold Detail, Residual-Adjusted Elevation
Leaderboard, QB Alumni Before-After, Coach Alumni Leaderboard). Note: the delivered workbook was
later corrected in place (Matt Ryan's before/after split fixed, see the correction note above) —
its "Wilson & Darnold Detail" sheet was renamed "Wilson, Darnold & Ryan Detail" and now includes
Ryan's full season-by-season breakdown; sheet count is still 6.

## v18: Do coaches who consistently run top-5/top-10 offenses produce more Superstar-tier players?
A related but distinct question from v13-v17: rather than testing named individuals or a specific
QB-elevation mechanism, this asks whether OVERALL TEAM CONSISTENCY at running a top-tier offense
(any coach, any era) predicts a higher rate of individually Superstar-tier fantasy seasons among
that coach's players — a single, well-specified, well-powered hypothesis test rather than another
round of small-sample individual-coach comparisons.

### Part 1: identifying consistently top-5/top-10 offenses
For every coach who ever held an OC or HC role (combined career identity across all teams, same
method as v14/v16), computed the share of his OC/HC seasons finishing top-5 and top-10 league-wide
in offensive EPA/play. Restricted to coaches with >=6 total OC/HC seasons for reliability (97
coaches qualify). Two Wikipedia-scrape name-duplicate artifacts were caught and merged during this
step: "Pete Carmichael" / "Pete Carmichael, Jr." and "Kevin Gilbride" / "Kevin Gilbride, Jr." were
the same person, inconsistently suffixed across different years' pages.

Most consistent top-10 offenses (min 6 seasons): Eric Bieniemy, Al Saunders, and Tom Moore all at
83.3% (6-season samples); Pete Carmichael 78.6% (14 seasons); Matt LaFleur 77.6% (9); Josh
McDaniels 70.6% (17); Sean Payton 70.0% (20); Bill Belichick 69.6% (23); Sean McDermott 66.7% (9);
Andy Reid 64.0% (25). Full ranked list of 97 coaches on the "Top Offense Consistency" sheet.

### Part 2: yes, their players do reach Superstar tier more often — and this result is well-powered
Rebuilt the v13 player-level superstar-rate metric (distinct skill-position players who ever
reached Superstar or League Winner tier under a coach) using the combined career OC+HC identity.
League-wide baseline: 8.0% of all distinct skill players ever reach Superstar+ under any coach in
their career.

Rather than testing each of the 97 coaches individually (which would recreate v13's multiple-
testing and small-sample problems), split them into "consistently top-10" (top10_rate >= 60%, 14
coaches) vs. everyone else (83 coaches) and pooled ALL their distinct players together into one
2x2 comparison — a single, well-specified test with real statistical power:
- Consistently-top-10 coaches: 95 of 1,252 distinct players reached Superstar+ = **7.6%**
- Everyone else (still >=6 seasons, just not top-10-consistent): 389 of 7,532 = **5.2%**
- Fisher's exact test: odds ratio = **1.51, p = 0.0008**

This holds up across every threshold tested (40%/50%/60%/70% top-10 rate, and repeated with top-5
rate): odds ratios consistently 1.4-1.6x, p always <0.02, usually <0.001. This is the most
statistically robust coaching-related finding across the whole v13-v18 arc — the sample sizes here
(thousands of players, not dozens) give it real power that the individual-coach tests in
v13/v14/v16 structurally couldn't reach.

### The critical caveat: this is likely partly mechanical, not proof of coaching causation
Team offensive EPA/play and individual player fantasy tier are not independent measurements — both
are driven substantially by the same underlying thing: how well the QB and skill players on the
field actually performed that season. A team can't post a top-5 EPA/play offense without someone
playing at a genuinely elite level, and that same performance is exactly what fantasy tiers
measure. So "top-10 offenses produce more Superstar-tier players" partly restates the same
underlying fact two different ways rather than confirming coaching skill independently. It also
can't rule out reverse causation or organizational quality — a coach might look "consistent" simply
because ownership keeps stacking him with elite talent (e.g. inheriting a generational QB), not
because his scheme creates stars. Honest read: sustained top-10 offenses and Superstar-tier fantasy
production genuinely overlap more than chance predicts (robust across thresholds) — but this
analysis alone cannot separate "the coach makes players better" from "good players make the coach
look consistent" from "organizations that get one right tend to get both right."

Data: `coach_top_offense_consistency.csv` (97 qualified coaches, top-5/top-10 rates),
`coach_superstar_rate_combined.csv` (superstar rate by combined coach identity, all coaches with
>=15 distinct players), `coach_consistency_and_superstar.csv` (merged, used for correlation and
threshold tests). Delivered as `Top_Offense_Consistency_and_Superstars.xlsx` (4 sheets: Summary,
Top Offense Consistency, Superstar Rate (Combined), Consistency + Superstar Merged).

## Deliverable
`Fantasy_Football_PPG_Tiers_2001-2025.xlsx` (or latest filename) — Tier Cutoffs, Breakouts,
Fall-offs (now includes confirmed injury fall-offs and years_star_streak), Bounce-back Profile,
Health Scores, Bounce-back Model (v7 final model + 2023-2025 walk-forward predictions/backtest),
Breakout Model (v12 final per-position models: v11 features + draft pedigree + market ADP,
validated with a 7-season walk-forward backtest on top of the original 2023-2025 one; forward-
looking predictions for the 2025 pool season / 2026 outcome shown both with and without ADP),
per-year PPG Tier sheets (2001-2025), Tier Counts by Year.

`Coaching_Staff_Player_Development_Analysis.xlsx` (v14, 14 sheets) — full coaching-staff scrape
results plus three player-development analyses: (1) the v13 breakout/superstar-rate-by-coach
analysis with the player-level pseudo-replication correction, a clean null result; (2) the v14
draft-pedigree-adjusted coaching effect, finding no positive "late-round developer" signal but
three significant negative (underperformance) findings at WR Day3+UDFA; (3) the v14 combined
OC+HC coaching-identity analysis, null when scanning all 332 coaches but with a real, specifically
validated positive result for Kyle Shanahan as a single named hypothesis, backed by detailed
player-level evidence matching the user's own narrative about him.

`NFL_Best_Offense_By_Year_2000-2025.xlsx` (v15, 3 sheets) — best NFL offense by season (2000-2025)
by PPG, YPG, and EPA/play, with a note on why DVOA couldn't be included (paywalled).

`Coaching_and_Offense_Quality_Analysis.xlsx` (v15, 7 sheets) — named-coach reputation check
(Shanahan/LaFleur/McVay/Ben Johnson/Reid/Payton all significantly outperform league-average
offensive percentile while coaching, p=0.0011; effect shrinks but survives controlling for QB
continuity; offenses don't collapse the season after they leave), player position-resilience to
offense-quality changes (QB most tied to offense quality, TE least), and Vegas win-total vs.
offensive-rank correlation stability across eras (r≈0.4-0.5 throughout 2001-2025, no dramatic
shift).

`QB_Controlled_Coach_Analysis.xlsx` (v16, 6 sheets) — stricter within-QB test of whether a coach
elevates whichever quarterback he has: Andy Reid is the cleanest positive case (3/3 QBs above
their own career norms, +0.222 avg); Shanahan/LaFleur mildly positive; McVay/Payton wash out to
roughly neutral/negative once Brees/one-great-QB is factored out; Josh McDaniels (+0.217, n=8) and
Greg Roman (+0.161, n=6) are the strongest data-backed additions to the "elite offensive mind"
list. No individual coach reaches statistical significance (structural small-sample ceiling).

`Decline_Adjusted_and_Alumni_Analysis.xlsx` (v17, 6 sheets) — decline-adjusted version of the v16
test (Wilson's Denver decline mostly pre-existing from Seattle, but 2022 was still a real added
shock beyond that trend) and a before/after-leaving-a-coach test using roster data (Darnold's real
2024-2025 turnaround followed his Shanahan year but can't be cleanly separated from Kevin
O'Connell's Minnesota system — only one case exists to examine). No coach shows a statistically
significant general "alumni effect" (all p>0.09). Corrected mid-analysis (user caught it): Matt
Ryan's "after Shanahan" number originally conflated his 4 still-productive seasons in Atlanta under
different OCs with his real decline only after actually leaving for Indianapolis at 37 — properly
separated, Ryan is not a clean counter-example to Darnold either way.

`Top_Offense_Consistency_and_Superstars.xlsx` (v18, 4 sheets) — identifies 97 coaches with >=6
career OC/HC seasons and ranks them by consistency at running top-5/top-10 offenses (Bieniemy,
Saunders, T. Moore, Carmichael, LaFleur, McDaniels, Payton, Belichick lead); finds a real,
well-powered link to producing Superstar-tier fantasy players (consistently-top-10 coaches: 7.6%
of players reach Superstar+ vs. 5.2% for others, OR=1.51, p=0.0008, robust across thresholds) —
the most statistically solid coaching finding in the whole v13-v18 arc, but flagged as likely
partly mechanical (team EPA and player fantasy tier share the same underlying driver) rather than
proof of causation.

## Open next steps
- v18's top-10-consistency-vs-superstar-rate link is well-powered but purely correlational and
  flagged as likely partly mechanical. If revisited, worth trying to at least partially separate
  "coach effect" from "team EPA and player tier share a driver" by re-running the same pooled
  Fisher's-exact design using DEFENSE-adjusted or DRAFT-TIER-adjusted player outcomes (v14's
  baseline) instead of raw Superstar-tier status, which would at least control for some of the
  "the player was just good anyway" confound. Also worth checking whether the effect is driven
  more by QB superstar-rate specifically (almost definitional, since QB EPA is most of team EPA)
  vs. RB/WR/TE superstar-rate (less definitional, would be more informative if it holds up).
- v17's alumni test is the noisiest design in the project so far (a QB's next stop confounds coach
  and system/supporting-cast changes at once) — revisit only if a much larger sample of qualifying
  before/after QBs accumulates, or if a way to control for the destination team's own offensive
  quality/coach reputation is found (e.g. weight by the destination coach's own v16 elevation
  score, to at least flag cases like Darnold→O'Connell where both origin and destination coach
  have real developer reputations). Also worth extending the decline-adjustment (experience-year
  residual) to RB/WR/TE for the position-resilience analysis in v15, since aging curves likely
  differ meaningfully by position too.
- v16's QB-elevation test is sample-size-limited by design (2-8 distinct QBs per coach, no
  individual test significant). Revisit as Ben Johnson (n=2), LaFleur, McVay, and Shanahan
  accumulate more QB changes at their current teams. Also worth formally testing Josh McDaniels
  and Greg Roman as named hypotheses (like Shanahan in v14) now that the scan has flagged them as
  the strongest data-backed additions. The QB right-censoring issue (Mahomes/Reid, Purdy/Shanahan
  have no "elsewhere" data) means the very best pairings are structurally excluded from evidence —
  no clean fix without a different design (e.g. comparing to draft-slot expectation, per v14,
  rather than the QB's own other seasons).
- v15's named-coach reputation check used only 6 coaches (Shanahan, LaFleur, McVay, Ben Johnson,
  Reid, Payton). Could extend to other analyst-consensus "offensive minds" (e.g. Josh McDaniels,
  Zac Taylor, Mike McDaniel) the same way if useful, and the QB-continuity-controlled subsample
  (n=11) is thin — revisit as these coaches accumulate more seasons, especially Ben Johnson at
  Chicago. DVOA remains parked pending FTN subscription access — would let v15's "best offense by
  year" and the named-coach check cross-validate against a second advanced metric.
- Revisit the QB `position_share` sign (still negative, p=0.031 in the v10 model) once more QB
  breakout events accumulate.
- Revisit RB and QB tier-climbing (`reached_starter_by_climbing`) once more candidates accumulate
  at those positions — both show the same positive direction as TE/WR but with too few climbers
  (47-49) to say anything with confidence yet.
- If revisited: RB-specific draft pedigree, run-block O-line quality, and repeat-bounce-back
  history (`prior_bounce_backs`) remain the most promising untested secondary signals for the
  bounce-back model specifically; `leading_back_departed` and team-change are documented findings
  for the breakout model that didn't make the final feature set but could be worth another look
  with more data.
- Team-clustering (multiple breakouts on the same roster in the same year) was tested and found to
  be statistically indistinguishable from chance (p=0.10) — not a feature, but worth remembering
  before reading too much into "the whole receiving corps broke out together" narratives.
- QB draft pedigree (`top10_pick`) was marginal (p=0.08) and barely moved AUC — worth another look
  if the QB candidate sample grows (currently the smallest position sample at 512).
- ADP (v12) is now validated with a real 7-season walk-forward backtest (2018-2024, avg AUC ~0.82)
  using 15 years of ADP data (2012-2026, footballguys + FantasyPros). TE's per-season backtest is
  still noisy at its small sample (105 ADP-matched candidates total) — the 2018 slice couldn't even
  be fit — so keep watching whether TE's pooled/controlled finding (p=0.048) holds up as more
  seasons resolve. Could also try pushing the FantasyPros archive further back if a future need
  calls for it (2011 and earlier returned no data when checked).
- Coaching staff data (v13) is now obtained and tested for a player-development "star-maker" effect (breakout rate and superstar rate by position coach/OC/HC) — a clean null result at the correct player-level unit of analysis (0 of ~1,000 coach/position combinations survive Bonferroni correction). Not added as a model feature. Revisit only if a much larger sample or a different outcome metric (e.g. per-play efficiency rather than fantasy tier) suggests otherwise.
- v14 draft-pedigree-adjusted and combined OC+HC coaching-identity analyses are complete: no
  positive "coach develops late picks/players better than league average" effect survives
  Bonferroni correction when scanning all coaches, but Kyle Shanahan holds up as a specific,
  well-supported single-named-hypothesis finding (+0.262 overperformance vs. draft-tier
  expectation, p=0.0119, 120 distinct players). If revisited: consider narrowing the "HC" role
  credit to offense-calling head coaches only (excluding defensive-minded HCs like Marinelli/
  LeBeau/Wilks) to remove the caveat noted above, and consider testing other specific
  user-nameable coaches (e.g. other long-tenured OC/HC combos) as single named hypotheses the same
  way Shanahan was tested here.
- Vegas team win totals and Super Bowl odds were tested (2001-2025, 100% pool match rate) and found
  to have no predictive relationship with individual player breakouts at any position — a clean
  null result, not added to the model. See "Vegas team win totals" section above.
- Individual player prop bet history remains a parked future idea — no free/accessible historical
  source exists today; would need a paid data source to revisit. A 2026 preseason props snapshot
  (QB/RB/WR/TE season-long O/U lines) was archived in `NFL_2026_Season_Player_Props.xlsx` for
  future reference regardless, in case it's worth revisiting once more seasons of outcomes exist.
- Expert breakout picks (FantasyPros preseason articles, 2015-2025) were tested and found to have a
  strong raw correlation with breaking out (20.5% vs 7.1%, p<0.0001) that fully disappears once
  controlling for existing v12 features — a clean "redundant, not complementary" null result, not
  added to the model. See "Expert breakout picks" section above.
