import pandas as pd

g = pd.read_csv('/tmp/pfr/games.csv', low_memory=False)
g = g[(g.season>=2000)&(g.season<=2025)&(g.game_type=='REG')]
remap = {'OAK':'LV','SD':'LAC','STL':'LA'}

rows = []
for _, r in g.iterrows():
    rows.append({'season': r['season'], 'team': remap.get(r['home_team'], r['home_team']), 'qb_id': r['home_qb_id'], 'qb_name': r['home_qb_name']})
    rows.append({'season': r['season'], 'team': remap.get(r['away_team'], r['away_team']), 'qb_id': r['away_qb_id'], 'qb_name': r['away_qb_name']})
df = pd.DataFrame(rows).dropna(subset=['qb_id'])

counts = df.groupby(['season','team','qb_id','qb_name']).size().reset_index(name='starts')
idx = counts.groupby(['season','team'])['starts'].idxmax()
primary = counts.loc[idx].rename(columns={'qb_id':'primary_qb_id','qb_name':'primary_qb_name'})
primary.to_csv('team_primary_qb_id.csv', index=False)
print(primary.shape)
print(primary.head())
