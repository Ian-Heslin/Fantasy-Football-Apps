import pandas as pd
import numpy as np

players = pd.read_csv('/tmp/pfr/players.csv')[['gsis_id','rookie_season','birth_date']]
qbdat = pd.read_csv('team_primary_qb_id.csv')
ranked = pd.read_csv('team_offense_ranked.csv')[['season','team','epa_per_play_pctile']]
qbdat = qbdat.merge(ranked, on=['season','team'], how='left').dropna(subset=['epa_per_play_pctile'])
qbdat = qbdat.merge(players, left_on='primary_qb_id', right_on='gsis_id', how='left')
qbdat['experience_year'] = qbdat['season'] - qbdat['rookie_season']
qbdat = qbdat.dropna(subset=['experience_year'])
qbdat['experience_year'] = qbdat['experience_year'].astype(int)
qbdat.loc[qbdat.experience_year<0, 'experience_year'] = 0  # data quirks (rookie_season slightly off for a few)
qbdat.loc[qbdat.experience_year>18, 'experience_year'] = 18  # cap tail, thin samples

curve = qbdat.groupby('experience_year').agg(n=('epa_per_play_pctile','size'), avg_pctile=('epa_per_play_pctile','mean')).reset_index()
print(curve.to_string(index=False))
curve.to_csv('qb_experience_curve.csv', index=False)

qbdat['expected_pctile'] = qbdat['experience_year'].map(curve.set_index('experience_year')['avg_pctile'])
qbdat['residual_pctile'] = qbdat['epa_per_play_pctile'] - qbdat['expected_pctile']
qbdat.to_csv('qb_panel_with_residual.csv', index=False)
print(qbdat[['season','team','primary_qb_name','experience_year','epa_per_play_pctile','expected_pctile','residual_pctile']].head())
