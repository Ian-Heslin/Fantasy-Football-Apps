import pandas as pd
import numpy as np

TIER_SCORE = {'Below Replacement Level': 0, 'Mid/replacement': 1, 'Starter': 2,
              'Star': 3, 'Superstar': 4, 'League Winner': 5}

ranks = pd.read_csv('team_offense_ranked.csv')[['season','team','epa_per_play','epa_rank','epa_per_play_pctile']]
ranks = ranks.rename(columns={'epa_per_play':'off_epa','epa_rank':'off_rank','epa_per_play_pctile':'off_pctile'})

pts = pd.read_csv('/tmp/pfr/player_team_season.csv')
rankings = pd.read_csv('/tmp/pfr/all_rankings_tiered.csv')
rankings = rankings[rankings.position.isin(['QB','RB','WR','TE'])].copy()
rankings['tier_base'] = rankings['tier'].apply(lambda t: t[:-1] if isinstance(t,str) and t.endswith('*') else t)
rankings = rankings[rankings.tier_base.isin(TIER_SCORE.keys())]
rankings['tier_score'] = rankings['tier_base'].map(TIER_SCORE)

# join player -> team (that season) -> team's offense rank that season
df = rankings.merge(pts, on=['player_id','season'], how='left')
df = df.merge(ranks, on=['season','team'], how='left')
df = df.dropna(subset=['off_pctile'])

df.to_csv('player_season_with_offense_rank.csv', index=False)
print(df.shape)
print(df[['season','player_id','display_name','position','team','ppg','tier_base','off_rank','off_pctile']].head())
