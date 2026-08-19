import pandas as pd

m = pd.read_csv('/tmp/pfr/best_offense/team_offense_master.csv')
m = m.sort_values(['season','team']).reset_index(drop=True)

for col, rankcol in [('epa_per_play','epa_rank'), ('ppg','ppg_rank'), ('yards_per_game','ypg_rank')]:
    m[rankcol] = m.groupby('season')[col].rank(ascending=False, method='min').astype(int)
    m[f'{col}_pctile'] = m.groupby('season')[col].rank(pct=True)  # 1.0 = best

m.to_csv('team_offense_ranked.csv', index=False)
print(m.shape)
print(m[m.season==2023].sort_values('epa_rank')[['season','team','epa_per_play','epa_rank','ppg','ppg_rank']].head(10))
