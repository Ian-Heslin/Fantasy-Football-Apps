import pandas as pd
import numpy as np
from scipy import stats

df = pd.read_csv('player_season_with_offense_rank.csv')
df = df.sort_values(['player_id','season'])

# self-join season s to season s+1, requiring SAME team both years (isolates offense-quality change
# from the confound of the player also changing situations by changing teams)
a = df[['player_id','display_name','position','season','team','ppg','tier_score','off_pctile','off_rank']].copy()
b = a.copy()
b['season'] = b['season'] - 1  # shift so b.season aligns with a.season as "next year" when merged
merged = a.merge(b, on=['player_id','season'], suffixes=('_y0','_y1'))
merged = merged[merged.team_y0 == merged.team_y1]  # same team both seasons

merged['off_pctile_change'] = merged['off_pctile_y1'] - merged['off_pctile_y0']
merged['player_ppg_change'] = merged['ppg_y1'] - merged['ppg_y0']
merged['player_tier_change'] = merged['tier_score_y1'] - merged['tier_score_y0']

merged.to_csv('player_yoy_offense_change.csv', index=False)
print('total same-team year-pairs:', len(merged))

print()
print('Correlation: team offense pctile change (year N-1 -> N) vs player PPG change, by position')
for pos, g in merged.groupby('position_y0'):
    r, p = stats.pearsonr(g['off_pctile_change'], g['player_ppg_change'])
    r2, p2 = stats.pearsonr(g['off_pctile_change'], g['player_tier_change'])
    print(f'  {pos}: n={len(g)}, PPG-change corr r={r:.3f} (p={p:.4f}); tier-change corr r={r2:.3f} (p={p2:.4f})')
